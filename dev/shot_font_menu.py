r"""把「歌词字体」子菜单渲染成图片，方便检查菜单内容。

    python dev\shot_font_menu.py <输出图片>
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# 必须强制换成临时目录：用 setdefault 的话 APPDATA 本来就存在，
# 会直接把示例字体写进用户真实的字体文件夹（上次就是这么翻车的）。
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="ld-menu-")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lyricdesk.config import Settings  # noqa: E402
from lyricdesk.fonts import import_font_file, register_all  # noqa: E402
from lyricdesk.window import LyricWindow  # noqa: E402


class FakeEngine:
    lyrics = None

    def snapshot(self):
        return None

    def players(self):
        return []


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "dev/font_menu.png")
    app = QApplication([])

    # 先摆几个「我导入的」字体进去，看看菜单长什么样
    for name in ("LXGWMarkerGothic-Regular.ttf", "SmileySans-Oblique.otf"):
        import_font_file(ROOT / "assets" / "fonts" / name)
    register_all()

    settings = Settings()
    window = LyricWindow(settings, FakeEngine())
    menu = window.build_menu()

    submenu = None
    for action in menu.actions():
        if action.text() == "歌词字体":
            submenu = action.menu()
    if submenu is None:
        print("没找到歌词字体菜单")
        return 1

    submenu.popup(window.pos())

    def grab() -> None:
        pixmap = submenu.grab()
        pixmap.save(str(out))
        print(f"已保存 {out}  ({pixmap.width()}x{pixmap.height()})")
        submenu.close()
        app.quit()

    QTimer.singleShot(600, grab)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
