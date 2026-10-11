r"""回归检查：倾斜 / 旋转拉到新上限时，歌词不会被窗口边缘切掉。

做法很直接：把窗口画到一张透明图上，然后看最外面 2 像素有没有被涂到。
涂到了就说明内容顶到了窗口边界 —— 也就是被裁了。

    python dev\check_tilt_clip.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lyricdesk import config  # noqa: E402

config.SETTINGS_PATH = Path(tempfile.mkdtemp(prefix="lyricdesk-clip-")) / "settings.json"

from lyricdesk.config import Settings  # noqa: E402
from lyricdesk.lyrics import LyricLine, Lyrics  # noqa: E402
from lyricdesk.smtc import Snapshot, Track  # noqa: E402
from lyricdesk.window import LyricWindow  # noqa: E402

MARGIN = 2


class FakeEngine:
    def __init__(self) -> None:
        self._snapshot = Snapshot(
            track=Track(title="海屿你", artist="马也_Crabbit", album="海屿你", duration=219.0),
            position=10.0,
            is_playing=True,
            status=4,
            source="QQMusic.exe",
        )
        self._lyrics = Lyrics(
            lines=[
                LyricLine(time=0.0, text="他们说爱过就可以伤和别离", end=4.0),
                LyricLine(time=4.0, text="像放在手心就能够发光美丽", end=8.0),
                LyricLine(time=8.0, text="像放在脑海就能够翻云覆雨", end=12.0),
                LyricLine(time=12.0, text="从陌生到熟悉爱你到恨你", end=16.0),
                LyricLine(time=16.0, text="爱让每个人都有秘密", end=20.0),
            ],
            source="QQ音乐",
            title="海屿你",
            artist="马也_Crabbit",
            albummid="",
            album="海屿你",
        )

    @property
    def lyrics(self):
        return self._lyrics

    def snapshot(self):
        return self._snapshot

    def players(self):
        return []


def edge_hits(window) -> tuple[int, QPixmap]:
    """最外圈被涂到的像素个数（0 就是没顶到边）。"""
    layer = QPixmap(window.size())
    layer.fill(QColor(0, 0, 0, 0))
    window.render(layer)
    image = layer.toImage()
    width, height = image.width(), image.height()
    hits = 0
    for x in range(width):
        for y in list(range(MARGIN)) + list(range(height - MARGIN, height)):
            if image.pixelColor(x, y).alpha() > 24:
                hits += 1
    for y in range(height):
        for x in list(range(MARGIN)) + list(range(width - MARGIN, width)):
            if image.pixelColor(x, y).alpha() > 24:
                hits += 1
    return hits, layer


def main() -> int:
    app = QApplication(sys.argv)
    failures: list[str] = []

    # (说明, 模式, 上倾, 左右倾, 旋转, 宽度, 字号)
    cases = [
        ("默认（仅左右倾斜强）", "depth3d", 0.0, 0.32, 0.0, 880, 38),
        ("上下+左右都拉满", "depth3d", 0.80, 0.80, 0.0, 880, 38),
        ("两方向拉满 + 旋转 45°", "depth3d", 0.80, 0.80, 45.0, 880, 38),
        ("两方向拉满 + 旋转 90°", "depth3d", 0.80, 0.80, 90.0, 880, 38),
        ("纯歌词面板拉满 + 旋转 80°", "lyrics", 0.80, 0.80, 80.0, 880, 38),
        ("宽窗口 1600 拉满", "depth3d", 0.80, 0.80, 0.0, 1600, 38),
        ("大字号 120 拉满", "depth3d", 0.80, 0.80, 0.0, 880, 120),
        ("极端：宽 2560 + 字号 200", "depth3d", 0.80, 0.80, 0.0, 2560, 200),
    ]

    out = Path(__file__).resolve().parent
    for name, mode, depth_v, depth_h, tilt, width, font_size in cases:
        settings = Settings()
        settings.mode = mode
        settings.text_depth_v = depth_v
        settings.text_depth_h = depth_h
        settings.text_tilt = tilt
        settings.width = width
        settings.font_size = font_size
        settings.clamp()
        window = LyricWindow(settings, FakeEngine())
        window.recalculate()
        hits, layer = edge_hits(window)
        ok = hits == 0
        print(
            f"  {'OK  ' if ok else 'CLIP'} {name}: 窗口 {window.width()}x{window.height()}"
            f" 余量 {window._overscan}/{window._overscan_v} 边缘像素 {hits}"
        )
        if not ok:
            failures.append(name)
        layer.save(str(out / "_clip_check.png"))

    if failures:
        print("\n被裁切的情况：", ", ".join(failures))
        return 1
    print("\n全部通过：以上组合都没有顶到窗口边缘")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
