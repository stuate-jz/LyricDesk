"""v1.7.0 开机置顶自检。必须在真实 Windows 平台运行。"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lyricdesk import config  # noqa: E402

config.SETTINGS_PATH = Path(tempfile.mkdtemp(prefix="lyricdesk-v170-top-")) / "settings.json"

from lyricdesk.config import Settings  # noqa: E402
from lyricdesk.win_util import is_topmost, set_native_topmost  # noqa: E402
from lyricdesk.window import LyricWindow  # noqa: E402


class Engine:
    lyrics = None

    def snapshot(self):
        return None

    def players(self):
        return []


def wait(app, milliseconds: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()
    app.processEvents()


def main() -> int:
    app = QApplication(sys.argv)
    failures = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  {'OK  ' if ok else 'FAIL'} {name}" + (f"  —— {detail}" if detail else ""))
        if not ok:
            failures.append(name)

    settings = Settings()
    settings.always_on_top = True
    window = LyricWindow(settings, Engine())
    window.show()
    app.processEvents()
    check("显示后原生置顶", is_topmost(window))

    # 启动 3 秒断点会自检；这里先手动摘掉，再验证定时断点能恢复。
    set_native_topmost(window, False)
    wait(app, 3200)
    check("启动 3 秒断点恢复置顶", is_topmost(window))

    set_native_topmost(window, False)
    wait(app, 10500)
    check("10 秒静默重断言恢复置顶", is_topmost(window))

    window.set_topmost_suspended(True)
    set_native_topmost(window, False)
    window._assert_topmost()
    check("设置窗口打开时不抢回置顶", not is_topmost(window))
    window.set_topmost_suspended(False)
    check("设置窗口关闭后恢复置顶", is_topmost(window))

    window.close()
    app.processEvents()
    if failures:
        print("失败：", ", ".join(failures))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
