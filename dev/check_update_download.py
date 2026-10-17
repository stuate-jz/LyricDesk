r"""自检：更新包下载这条链（进度回调 / 完整性校验 / 取消 / 失败标记 / 不删安装包）。

用法：
    python dev\check_update_download.py

起一个本机 HTTP 服务，分别模拟「正常安装包」「被代理换成 HTML」「传到一半断开」，
全部走 lyricdesk.update.download() 的真实代码。
"""

from __future__ import annotations

import http.server
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from lyricdesk import update as U  # noqa: E402
from lyricdesk.window import LyricWindow  # noqa: E402

FAILS = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILS
    if not ok:
        FAILS += 1
    print(f"  {'OK  ' if ok else 'FAIL'} {name}" + (f"  —— {detail}" if detail else ""))


class Handler(http.server.BaseHTTPRequestHandler):
    """/ok 正常 2.5 MB（MZ 头）、/html 网页、/short 只发一半就断。"""

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/ok":
            body = b"MZ" + b"\0" * (2_500_000 - 2)
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/html":
            body = b"<html>" + b"x" * 2_000_000 + b"</html>"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/short":
            self.send_response(200)
            self.send_header("Content-Length", "3000000")
            self.end_headers()
            self.wfile.write(b"MZ" + b"\0" * 1_200_000)
            self.wfile.flush()
            self.close_connection = True
        else:
            self.send_error(404)

    def log_message(self, *_args) -> None:  # 安静点
        pass


def run_download(url: str, target: Path, cancel_on_first_progress: bool = False, **kwargs):
    """同步跑一次 download()，返回 (ok, message, 进度样本)。

    cancel_on_first_progress=True 时，第一个进度回调就把「取消」按下去 ——
    比按时间取消确定得多（本机回环太快，2.5 MB 不到 0.1 秒就传完了）。
    """
    samples: list[tuple[int, int, float]] = []
    box: list = []
    done = threading.Event()
    stop = threading.Event()

    def on_progress(downloaded: int, total: int, speed: float) -> None:
        samples.append((downloaded, total, speed))
        if cancel_on_first_progress:
            stop.set()

    def on_done(ok: bool, message: str) -> None:
        box.append((ok, message))
        done.set()

    U.download(
        url,
        target,
        on_done,
        on_progress=on_progress,
        should_stop=stop.is_set,
        **kwargs,
    )
    if not done.wait(120):
        raise TimeoutError("下载回调超时")
    return box[0][0], box[0][1], samples


def main() -> int:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    tmp = Path(tempfile.mkdtemp(prefix="ld-dl-check-"))

    print("1) 正常下载：进度回调 + 文件保留")
    target = tmp / "ok.exe"
    ok, message, samples = run_download(base + "/ok", target)
    check("下载成功", ok, message)
    check("文件保留且大小正确", target.exists() and target.stat().st_size == 2_500_000,
          f"{target.stat().st_size if target.exists() else '不存在'}")
    check("进度样本 > 0 条", len(samples) > 0, f"{len(samples)} 条")
    check("进度单调不减", all(a[0] <= b[0] for a, b in zip(samples, samples[1:])))
    check("最后一条是 100%", bool(samples) and samples[-1][0] == samples[-1][1] == 2_500_000,
          str(samples[-1] if samples else None))
    check("速度为正数", bool(samples) and samples[-1][2] > 0,
          f"{samples[-1][2]:.0f} B/s" if samples else "")

    print()
    print("2) 下到的是网页（不是 exe）：报错并删掉")
    target = tmp / "html.exe"
    ok, message, _ = run_download(base + "/html", target)
    check("判定失败", not ok)
    check("提示不是安装程序", "不是安装程序" in message, message)
    check("坏文件已删除", not target.exists())

    print()
    print("3) 传到一半断开：报错并删掉半截文件")
    target = tmp / "short.exe"
    ok, message, _ = run_download(base + "/short", target)
    check("判定失败", not ok)
    check("没有留下半截文件", not target.exists())
    print(f"      （提示：{message}）")

    print()
    print("4) 点取消：立刻停下、删掉半截文件")
    target = tmp / "cancel.exe"
    ok, message, _ = run_download(base + "/ok", target, cancel_on_first_progress=True)
    check("返回已取消", not ok and message == "已取消", message)
    check("没有留下半截文件", not target.exists())

    print()
    print("5) 安装失败标记：能读回安装包路径，读完即删")
    marker = Path(tempfile.gettempdir()) / U.FAILED_MARKER
    backup = marker.with_suffix(".bak")
    had_marker = marker.exists()
    if had_marker:
        marker.replace(backup)
    fake = Path(tempfile.gettempdir()) / "LyricDesk-Setup-v9.9.9.exe"
    fake.write_bytes(b"MZ")
    marker.write_text(fake.name, encoding="mbcs")
    got = U.failed_installer()
    check("读回路径", got == fake, str(got))
    check("标记已清除", not marker.exists())
    fake.unlink(missing_ok=True)
    if had_marker:
        backup.replace(marker)

    print()
    print("6) 安装脚本：装失败时保留安装包 + 写失败标记")
    if had_marker:
        marker.replace(backup)
    # 跟真实更新一样放在 %TEMP% 根目录（脚本会走 %TEMP% 那条分支）
    fake_setup = Path(tempfile.gettempdir()) / "LyricDesk-Setup-v9.9.9.exe"
    # 拿 where.exe 冒充一个「装不上」的安装程序：带这些参数运行时它返回 2
    shutil.copy2(Path(os.environ["SystemRoot"]) / "System32" / "where.exe", fake_setup)
    script = LyricWindow._write_update_script(None, fake_setup, None)
    check("脚本写出来了", script is not None)
    text = script.read_text(encoding="mbcs", errors="replace")
    check("脚本会检查退出码", "if errorlevel 1 goto failed" in text)
    check("成功分支才删安装包", 'del /q "%TEMP%\\' in text)
    check("等待不依赖控制台（ping 而不是 timeout）", "ping -n 4" in text and "timeout" not in text)
    started = time.time()
    subprocess.run(["cmd", "/c", str(script)], timeout=120)
    print(f"      脚本跑完用了 {time.time() - started:.1f}s")
    check("装失败后安装包还在", fake_setup.exists())
    check("写了失败标记", marker.exists())
    got = U.failed_installer()
    check("标记能定位到安装包", got == fake_setup, str(got))
    check("读完之后标记清掉", not marker.exists())
    fake_setup.unlink(missing_ok=True)
    if had_marker:
        backup.replace(marker)

    server.shutdown()
    shutil.rmtree(tmp, ignore_errors=True)
    print()
    print("全部通过" if FAILS == 0 else f"{FAILS} 项没通过")
    return 0 if FAILS == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
