r"""自检：更新下载进度条的文字/百分比/速度显示（离屏，不弹真窗口）。

用法： python dev\check_update_progress_ui.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from PySide6.QtWidgets import QApplication, QProgressDialog  # noqa: E402

from lyricdesk.config import Settings  # noqa: E402
from lyricdesk.window import LyricWindow  # noqa: E402

FAILS = 0


class FakeEngine:
    def snapshot(self):
        return None

    def stop(self) -> None:
        pass

    def reload(self) -> None:
        pass

    def track(self):
        return None


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILS
    if not ok:
        FAILS += 1
    print(f"  {'OK  ' if ok else 'FAIL'} {name}" + (f"  —— {detail}" if detail else ""))


def main() -> int:
    app = QApplication(sys.argv)
    window = LyricWindow(Settings(), FakeEngine())
    box = QProgressDialog("…", "取消", 0, 100, window)
    window._update_progress = box

    print("1) 知道总大小时：百分比 + 已下/总量 + 速度 + 剩余时间")
    window._on_update_progress(12 * 1048576, 44 * 1048576, 1.5 * 1048576)
    text = box.labelText()
    print(f"      {text!r}")
    check("有百分比", "27%" in text, text)
    check("有已下/总量", "12.0 / 44.0 MB" in text, text)
    check("有速度", "1.50 MB/s" in text, text)
    check("有预计剩余", "预计还剩" in text, text)
    check("进度条值跟着走", box.value() == 12 * 1048576 and box.maximum() == 44 * 1048576)

    print()
    print("2) 服务器没给总大小：忙碌指示 + 已下载量")
    window._on_update_progress(3 * 1048576, 0, 512 * 1024)
    text = box.labelText()
    print(f"      {text!r}")
    check("切成忙碌指示", box.maximum() == 0)
    check("显示已下载量", "3.0 MB" in text, text)
    check("显示速度", "0.50 MB/s" in text, text)

    print()
    print("3) 下载结束（取消）时进度条会被收掉")
    window._on_update_downloaded(False, "已取消", object())
    app.processEvents()
    check("进度条引用已清空", getattr(window, "_update_progress", None) is None)
    check("取消不弹错误框（没有 modal）", app.activeModalWidget() is None)

    print()
    print("全部通过" if FAILS == 0 else f"{FAILS} 项没通过")
    return 0 if FAILS == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
