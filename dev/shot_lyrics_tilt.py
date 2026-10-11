r"""检查纯歌词面板的倾斜 / 旋转（和立体卡片同一套效果）。

    python dev\shot_lyrics_tilt.py <输出目录>
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lyricdesk.config import Settings  # noqa: E402
from lyricdesk.lyrics import LyricLine, Lyrics  # noqa: E402
from lyricdesk.smtc import Snapshot, Track  # noqa: E402
from lyricdesk.window import LyricWindow  # noqa: E402


class FakeEngine:
    def __init__(self) -> None:
        self._snapshot = Snapshot(
            track=Track(
                title="海屿你",
                artist="马也_Crabbit",
                album="海屿你",
                duration=219.0,
            ),
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


def wallpaper(width: int, height: int) -> QPixmap:
    pixmap = QPixmap(width, height)
    painter = QPainter(pixmap)
    gradient = QLinearGradient(0, 0, width, height)
    gradient.setColorAt(0.0, QColor("#1b2430"))
    gradient.setColorAt(1.0, QColor("#2b2233"))
    painter.fillRect(pixmap.rect(), gradient)
    painter.end()
    return pixmap


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "dev")
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication([])

    cases = [
        ("plain", 0.0, 0.0, 0.0, "right"),
        ("h_only", 0.0, 0.32, 0.0, "right"),
        ("v_and_h", 0.20, 0.32, 0.0, "right"),
        ("all", 0.20, 0.32, -6.0, "right"),
        ("reverse_h", 0.0, -0.32, 0.0, "right"),
        ("reverse_v", -0.20, 0.0, 0.0, "right"),
        ("align_left", 0.0, 0.32, 0.0, "left"),
        ("align_center", 0.0, 0.32, 0.0, "center"),
    ]
    for tag, depth_v, depth_h, tilt, align in cases:
        settings = Settings()
        settings.mode = "lyrics"
        settings.text_depth_v = depth_v
        settings.text_depth_h = depth_h
        settings.text_tilt = tilt
        settings.lyric_align = align
        window = LyricWindow(settings, FakeEngine())
        # 头部（歌名 / 作者 / 热度）单独渲染一张，热度用假数据
        if tag in ("all", "reverse_h", "align_left", "align_center"):
            from lyricdesk import heat as heat_lookup

            window._heat_key = heat_lookup.key_for("海屿你", "马也_Crabbit")
            window._heat_value = 88.0
        window.recalculate()
        canvas = wallpaper(window.width(), window.height())
        layer = QPixmap(window.size())
        layer.fill(QColor(0, 0, 0, 0))
        window.render(layer)
        painter = QPainter(canvas)
        painter.drawPixmap(0, 0, layer)
        painter.end()
        path = out / f"24_lyrics_{tag}.png"
        canvas.save(str(path))
        print(
            f"{path.name}  上倾={depth_v} 左右倾={depth_h} 旋转={tilt} 对齐={align}  "
            f"窗口 {window.width()}x{window.height()}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
