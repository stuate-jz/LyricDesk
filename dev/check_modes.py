"""回归检查：菜单里能选的每一个界面模式，都必须能原样通过 clamp()。

之前出过一次事故：菜单新增了「纯歌词面板」(lyrics)，
但 Settings.clamp() 的白名单忘了加这个词，结果每次保存设置都把它打回立体卡片，
界面上表现为「点了纯歌词面板没反应」。这个脚本就是盯住这类问题的。
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lyricdesk import config  # noqa: E402
from lyricdesk.config import Settings  # noqa: E402

# 存档往返测试必须写到临时目录，绝不能碰用户真正的 settings.json
config.SETTINGS_PATH = Path(tempfile.mkdtemp(prefix="lyricdesk-modes-")) / "settings.json"


def menu_modes() -> list[str]:
    """从 populate_menu 的源码里抠出界面模式的取值，避免两份清单各写各的。"""
    source = Path(__file__).resolve().parent.parent / "lyricdesk" / "window.py"
    text = source.read_text(encoding="utf-8")
    start = text.index('mode_menu = menu.addMenu("界面模式")')
    block = text[start : text.index("):", start)]
    return [
        line.rsplit('"', 2)[1]
        for line in block.splitlines()
        if line.strip().startswith('("') and '", "' in line
    ]


def main() -> int:
    modes = menu_modes()
    failed = []
    print("菜单里的界面模式：")
    for mode in modes:
        settings = Settings()
        settings.mode = mode
        settings.clamp()
        ok = settings.mode == mode
        print(f"  {'OK  ' if ok else 'FAIL'} {mode:8s} -> {settings.mode}")
        if not ok:
            failed.append(mode)

    print("\n存档往返（写盘再读回来）：")
    for mode in modes:
        settings = Settings()
        settings.mode = mode
        settings.save()
        again = Settings.load()
        ok = again.mode == mode
        print(f"  {'OK  ' if ok else 'FAIL'} {mode:8s} -> {again.mode}")
        if not ok:
            failed.append(mode + "(roundtrip)")

    if failed:
        print("\n失败：", ", ".join(failed))
        return 1
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
