r"""自检：width 语义（歌词可用宽）+ 老配置迁移 + 播放器独立宽度（任务 2）。

用法： python dev\check_width_semantics.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from PySide6.QtWidgets import QApplication  # noqa: E402

from lyricdesk import config  # noqa: E402
from lyricdesk.config import (  # noqa: E402
    LEGACY_WIDTH_SHIFT,
    PLAYER_WIDTH_MAX,
    WIDTH_MAX,
    WIDTH_MIN,
    Settings,
)
from lyricdesk.window import MARGIN, PAD, LyricWindow  # noqa: E402

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


def load_from(raw: dict) -> Settings:
    """用临时 settings.json 走一遍真正的 Settings.load()。"""
    original = config.SETTINGS_PATH
    tmp = Path(tempfile.mkdtemp(prefix="ld-width-")) / "settings.json"
    tmp.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    config.SETTINGS_PATH = tmp
    try:
        return Settings.load()
    finally:
        config.SETTINGS_PATH = original
        tmp.unlink(missing_ok=True)
        tmp.parent.rmdir()


def drawable(window: LyricWindow) -> float:
    """歌词实际能画文字的宽度 = 窗口宽 − 左右 MARGIN/余量 − 左右 PAD。"""
    return window.width() - 2 * (MARGIN + window._overscan) - 2 * PAD


def main() -> int:
    app = QApplication(sys.argv)

    print("1) 常量")
    check("WIDTH_MAX = 1440", WIDTH_MAX == 1440, str(WIDTH_MAX))
    check("PLAYER_WIDTH_MAX = 1440", PLAYER_WIDTH_MAX == 1440, str(PLAYER_WIDTH_MAX))
    check("迁移偏移 = 2×PAD", LEGACY_WIDTH_SHIFT == 2 * PAD, f"{LEGACY_WIDTH_SHIFT} vs {2 * PAD}")

    print()
    print("2) 老配置迁移（settings_version 2 → 3）")
    old = load_from({"settings_version": 2, "width": 880, "mode": "lyrics"})
    check("880 → 840", old.width == 840, str(old.width))
    check("版本号升到 3", old.settings_version == 3, str(old.settings_version))
    check("老配置 player_width = 0（自动）", old.player_width == 0, str(old.player_width))
    check("太小的老宽度回落到下限", load_from({"settings_version": 2, "width": 260}).width == WIDTH_MIN)
    new = load_from({"settings_version": 3, "width": 380})
    check("已经是 v3 的不再迁移", new.width == 380, str(new.width))

    print()
    print("3) 纯歌词面板：drawable == width")
    for width in (240, 380, 1000, 1440):
        settings = Settings()
        settings.width = width
        settings.mode = "lyrics"
        settings.clamp()
        window = LyricWindow(settings, FakeEngine())
        got = drawable(window)
        check(
            f"width={width} → 歌词可用宽 {got:.0f}，窗口总宽 {window.width()}",
            abs(got - width) < 1.5,
        )

    print()
    print("4) 立体卡片：drawable == width")
    settings = Settings()
    settings.width = 420
    settings.mode = "depth3d"
    settings.clamp()
    window = LyricWindow(settings, FakeEngine())
    check(f"drawable = {drawable(window):.0f}", abs(drawable(window) - 420) < 1.5)

    print()
    print("5) 唱片面板：自动 / 手动两套宽度")
    settings = Settings()
    settings.mode = "album"
    settings.player_width = 0
    settings.clamp()
    auto_window = LyricWindow(settings, FakeEngine())
    auto_drawable = drawable(auto_window)
    check(
        f"自动：窗口 {auto_window.width()}，内容 {auto_drawable:.0f}（≈封面+220 或 280）",
        280 <= auto_drawable <= 700,
    )
    settings.player_width = 600
    settings.clamp()
    manual_window = LyricWindow(settings, FakeEngine())
    check(f"手动 600：内容 {drawable(manual_window):.0f}", abs(drawable(manual_window) - 600) < 1.5)
    check("手动宽度不影响歌词 width", settings.width == 380, str(settings.width))

    print()
    print("6) clamp 行为")
    settings = Settings()
    settings.player_width = 5000
    settings.clamp()
    check("player_width 超上限被夹到 1440", settings.player_width == 1440, str(settings.player_width))
    settings.player_width = -30
    settings.clamp()
    check("负值当 0（自动）", settings.player_width == 0, str(settings.player_width))
    settings.player_width = 100
    settings.clamp()
    check("1~239 抬到 240", settings.player_width == 240, str(settings.player_width))

    print()
    print("全部通过" if FAILS == 0 else f"{FAILS} 项没通过")
    return 0 if FAILS == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
