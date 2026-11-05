"""v1.6.11 回归：四种网易云状态下歌词菜单和托盘菜单都必须可构建。"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="ld-v1611-menus-")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

from lyricdesk import config  # noqa: E402
from lyricdesk.config import Settings  # noqa: E402
from lyricdesk.window import LyricWindow, log_error  # noqa: E402

config.SETTINGS_PATH = Path(os.environ["APPDATA"]) / "LyricDesk" / "settings.json"

FAILS = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILS
    if not ok:
        FAILS += 1
    print(f"  {'OK  ' if ok else 'FAIL'} {name}" + (f"  —— {detail}" if detail else ""))


class FakeEngine:
    def __init__(self, connected: bool) -> None:
        self.netease_connected = connected
        self.lyrics = None

    def snapshot(self):
        return None

    def players(self):
        return []

    def thumbnail(self):
        return None

    def send_control(self, _action):
        return None

    def reload(self):
        return None


def action_texts(menu: QMenu) -> list[str]:
    return [action.text() for action in menu.actions()]


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    combinations = [
        (False, False),
        (False, True),
        (True, False),
        (True, True),
    ]
    windows: list[LyricWindow] = []
    for netease_mode, connected in combinations:
        label = f"netease_mode={netease_mode} connected={connected}"
        settings = Settings()
        settings.netease_mode = netease_mode
        window = LyricWindow(settings, FakeEngine(connected))
        windows.append(window)

        right_menu = window.build_menu()
        right_texts = action_texts(right_menu)
        tray_menu = QMenu()
        window.populate_menu(tray_menu)
        tray_texts = action_texts(tray_menu)
        check(f"{label} 歌词右键菜单", len(right_texts) >= 15, str(len(right_texts)))
        check(f"{label} 托盘菜单", len(tray_texts) >= 15, str(len(tray_texts)))
        check(
            f"{label} 文案与连接状态一致",
            any("网易云：未连接" in text for text in right_texts)
            == (netease_mode and not connected),
        )
        right_menu.deleteLater()
        tray_menu.deleteLater()

    print("\n兜底路径：")
    broken = windows[0]

    def broken_build():
        raise RuntimeError("simulated menu failure")

    original_build = broken.build_menu

    broken.build_menu = broken_build  # type: ignore[method-assign]
    created: list = []

    class DummyAction:
        def __init__(self, text: str) -> None:
            self._text = text
            self.enabled = True

        def setEnabled(self, value: bool):
            self.enabled = bool(value)
            return self

        def text(self):
            return self._text

    class DummyMenu:
        def __init__(self) -> None:
            self._actions: list[DummyAction] = []
            self.executed = False
            created.append(self)

        def addAction(self, text, _callback=None):
            action = DummyAction(text)
            self._actions.append(action)
            return action

        def addSeparator(self):
            self._actions.append(DummyAction(""))

        def exec(self, _pos):
            self.executed = True
            return 0

        def deleteLater(self):
            return None

    try:
        with patch("lyricdesk.window.QMenu", DummyMenu):
            broken.contextMenuEvent(type("Event", (), {"globalPos": lambda self: QPoint(0, 0)})())
        check("右键菜单构建异常时不抛到事件循环", True)
        fallback = created[-1] if created else None
        fallback_texts = [item.text() for item in fallback._actions] if fallback else []
        check(
            "异常后仍弹出兜底菜单",
            bool(fallback and fallback.executed and "退出" in fallback_texts),
            str(fallback_texts),
        )
    finally:
        broken.build_menu = original_build

    error_log = config.app_dir() / "error.log"
    log_error("菜单回归测试", RuntimeError("expected test error"))
    check("异常写入 error.log", error_log.exists() and "菜单回归测试" in error_log.read_text(encoding="utf-8"))

    print("\n同类 API 扫描：")
    offenders: list[str] = []
    for source in (ROOT / "lyricdesk").glob("*.py"):
        for line_no, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
            if ".setForeground(" in line or ".setBackground(" in line:
                allowed = source.name == "settings_dialog.py" and "item.setForeground" in line
                if not allowed:
                    offenders.append(f"{source.name}:{line_no}: {line.strip()}")
    check("没有 QAction 误用 setForeground / setBackground", not offenders, "; ".join(offenders))

    print("\n结果：", "全部通过" if FAILS == 0 else f"{FAILS} 项失败")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
