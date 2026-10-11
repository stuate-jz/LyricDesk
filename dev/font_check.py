"""检查字体菜单：在线字体状态 + 菜单结构。"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lyricdesk.config import Settings  # noqa: E402
from lyricdesk.fonts import ONLINE_FONTS, family_for, register_all  # noqa: E402
from lyricdesk.window import LyricWindow  # noqa: E402


class EmptyEngine:
    lyrics = None

    def snapshot(self):
        return None


def main() -> int:
    app = QApplication(sys.argv)
    register_all()
    print(f"在线字体共 {len(ONLINE_FONTS)} 款：")
    for item in ONLINE_FONTS:
        family = family_for(item)
        state = f"已下载 -> {family}" if family else "未下载"
        print(f"   {item.label:<18} {item.size_mb:>5.1f} MB   {item.license:<13} {state}")

    window = LyricWindow(Settings(), EmptyEngine())
    menu = window.build_menu()
    print("\n歌词字体菜单：")
    for action in menu.actions():
        if action.text() != "歌词字体":
            continue
        for sub in action.menu().actions():
            if sub.isSeparator():
                print("   " + "-" * 30)
            else:
                mark = "[x] " if sub.isChecked() else "[ ] "
                print("   " + mark + sub.text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
