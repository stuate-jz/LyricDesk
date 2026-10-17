r"""复现「检查更新 → 下载安装包 → 静默安装」这条链，用来排查用户升级失败。

用法：
    python dev\probe_update_flow.py            只做检查和下载（不安装）
    python dev\probe_update_flow.py --install  下载完再按程序里那套参数静默装一遍

说明：
    · 全程用程序自己的函数（lyricdesk.update），不另写逻辑，所以结果就是用户遇到的结果；
    · 只读不写用户配置；--install 会真的跑安装程序（装的是同一个版本，用来验证静默安装这一步）。
"""

from __future__ import annotations

import hashlib
import os
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
from lyricdesk.fonts import proxy_candidates  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SOURCE = "gitee:pursue-studies/LyricDesk"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def wait_for(call, *args):
    """把 update.check / update.download 这种回调式 API 变成同步调用。"""
    box: list = []
    done = threading.Event()

    def on_done(*values):
        box.append(values[0] if len(values) == 1 else values)
        done.set()

    call(*args, on_done)
    if not done.wait(300):
        raise TimeoutError("等了 300 秒还没回调")
    return box[0]


def main() -> int:
    do_install = "--install" in sys.argv

    print("=" * 68)
    print("1) 更新源与代理候选")
    print("=" * 68)
    print(f"  更新源            {SOURCE}")
    print(f"  程序目录 update.json（bundled_source）: {U.bundled_source() or '(没有，正常)'}")
    print(f"  请求地址          {U._candidate_urls(SOURCE)}")
    print(f"  代理候选顺序      {proxy_candidates()}")
    print(f"  若当前是 1.6.2，这次会认为有新版吗：{U.is_newer('v1.6.5', '1.6.2')}")

    print()
    print("=" * 68)
    print("2) 检查更新（走程序自己的 check()，含代理回退）")
    print("=" * 68)
    started = time.time()
    info = wait_for(U.check, SOURCE)
    print(f"  耗时 {time.time() - started:.1f}s")
    print(f"  ok        = {info.ok}")
    print(f"  latest    = {info.latest!r}")
    print(f"  installer = {info.installer!r}")
    print(f"  portable  = {info.portable!r}")
    print(f"  url       = {info.url!r}")
    print(f"  error     = {info.error!r}")
    if not info.ok or not info.installer:
        print()
        print("  [!] 没拿到安装包直链 —— 界面上不会出现「立即更新」按钮。")
        return 1

    print()
    print("=" * 68)
    print("3) 下载安装包（走程序自己的 download()）")
    print("=" * 68)
    target = Path(tempfile.gettempdir()) / f"probe-update-{info.latest}.exe"
    target.unlink(missing_ok=True)
    started = time.time()
    ok, message = wait_for(U.download, info.installer, target)
    print(f"  耗时 {time.time() - started:.1f}s")
    print(f"  ok      = {ok}")
    print(f"  message = {message!r}")
    if not ok:
        print()
        print("  [!] 下载失败 —— 这正是用户看到的「更新包下载失败」。")
        return 1

    size = target.stat().st_size
    head = target.open("rb").read(2)
    print(f"  落盘文件 {target}")
    print(f"  大小     {size:,} B（{size / 1048576:.2f} MB）")
    print(f"  文件头   {head!r}（应为 b'MZ'）")
    print(f"  SHA256   {sha256(target)}")
    local = ROOT / "dist" / f"LyricDesk-Setup-{info.latest}.exe"
    if local.exists():
        print(f"  与本机 {local.name} 完全一致：{sha256(local) == sha256(target)}")

    if not do_install:
        print()
        print("（没加 --install，安装这一步跳过）")
        return 0

    print()
    print("=" * 68)
    print("4) 静默安装（参数与程序里 _write_update_script 完全一致）")
    print("=" * 68)
    installed = (
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "LyricDesk" / "LyricDesk.exe"
    )
    before = (installed.stat().st_size, installed.stat().st_mtime) if installed.exists() else None
    print(f"  安装前：存在={installed.exists()}  大小/时间={before}")
    log = Path(tempfile.gettempdir()) / "probe-install.log"
    log.unlink(missing_ok=True)
    started = time.time()
    result = subprocess.run(
        [str(target), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", f"/LOG={log}"],
        capture_output=True,
    )
    print(f"  耗时 {time.time() - started:.1f}s   退出码 = {result.returncode}")
    after = (installed.stat().st_size, installed.stat().st_mtime) if installed.exists() else None
    print(f"  安装后：存在={installed.exists()}  大小/时间={after}")
    if log.exists():
        print("  ---- 安装日志里可疑的行 ----")
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            low = line.lower()
            if any(word in low for word in ("error", "fail", "cannot", "warning", "pending", "reboot", "exit code")):
                print("   ", line.strip()[:160])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
