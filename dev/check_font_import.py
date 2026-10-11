r"""验证「导入自己的字体」：导入 → 加载 → 出现在菜单里 → 重启后还在。

用临时 APPDATA，不会往你真正的字体目录里塞东西：
    python dev\check_font_import.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEMP_APPDATA = Path(tempfile.mkdtemp(prefix="lyricdesk-fonts-"))
os.environ["APPDATA"] = str(TEMP_APPDATA)

from PySide6.QtWidgets import QApplication  # noqa: E402

from lyricdesk.fonts import (  # noqa: E402
    import_font_file,
    imported_fonts,
    register_all,
    user_font_dir,
)


def main() -> int:
    app = QApplication([])  # noqa: F841
    failures = 0

    print(f"临时配置目录：{TEMP_APPDATA}")
    print("字体目录：", user_font_dir())

    print("\n[1] 还没导入时")
    print("   imported_fonts() ->", imported_fonts())

    print("\n[2] 导入一个真实字体（用内置的得意黑当素材）")
    source = ROOT / "assets" / "fonts" / "SmileySans-Oblique.otf"
    ok, message = import_font_file(source)
    print(f"   结果={ok} 字体名={message!r}")
    if not ok:
        failures += 1

    print("\n[3] 再导入一个（内置的霞鹜漫黑）")
    source2 = ROOT / "assets" / "fonts" / "LXGWMarkerGothic-Regular.ttf"
    ok2, message2 = import_font_file(source2)
    print(f"   结果={ok2} 字体名={message2!r}")
    if not ok2:
        failures += 1

    print("\n[4] 导入非字体文件（应该被拒绝）")
    junk = TEMP_APPDATA / "not-a-font.txt"
    junk.write_text("hello", encoding="utf-8")
    ok3, message3 = import_font_file(junk)
    print(f"   结果={ok3} 说明={message3!r}")
    if ok3:
        failures += 1

    print("\n[5] 现在的自备字体列表")
    mine = imported_fonts()
    for family, filename in mine:
        print(f"   {family}  <-  {filename}")
    if len(mine) < 2:
        failures += 1

    print("\n[6] 重新注册一遍（模拟程序重启后自动加载）")
    loaded = register_all()
    print("   启动时加载到的字体数：", len(loaded))
    if not loaded:
        failures += 1

    print("\n[7] 歌词字体菜单里长什么样")
    from dataclasses import replace

    from lyricdesk.config import Settings
    from lyricdesk.window import LyricWindow

    settings = Settings()
    settings.font_family = mine[0][0] if mine else "Microsoft YaHei UI"
    window = LyricWindow(settings, _FakeEngine())
    menu = window.build_menu()
    for action in menu.actions():
        submenu = action.menu()
        if submenu and action.text() == "歌词字体":
            for item in submenu.actions():
                mark = "✓" if item.isChecked() else " "
                print(f"   [{mark}] {item.text() or '―――'}")
    menu.deleteLater()

    print("\n" + ("有失败项" if failures else "全部通过"))
    return 1 if failures else 0


class _FakeEngine:
    lyrics = None

    def snapshot(self):
        return None

    def players(self):
        return []


if __name__ == "__main__":
    raise SystemExit(main())
