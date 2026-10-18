r"""任务 1 的验收截图：左右倾斜 0.2 / 0.5 / 0.8 各一张，外加一张横向拼图。

用法： python dev\shot_perspective.py
输出： dev\_persp_0.2.png / _0.5.png / _0.8.png / _persp_all.png
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPixmap
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
    app = QApplication([])
    shots: list[tuple[float, QPixmap]] = []
    for depth in (0.2, 0.5, 0.8):
        settings = Settings()
        settings.mode = "lyrics"
        settings.text_depth_h = depth
        settings.text_depth_v = 0.0
        settings.text_tilt = 0.0
        settings.lyric_align = "right"
        window = LyricWindow(settings, FakeEngine())
        window._anim_t0 = -1000.0
        window.recalculate()
        canvas = wallpaper(window.width(), window.height())
        layer = QPixmap(window.size())
        layer.fill(QColor(0, 0, 0, 0))
        window.render(layer)
        painter = QPainter(canvas)
        painter.drawPixmap(0, 0, layer)
        painter.end()
        path = ROOT / "dev" / f"_persp_{depth:.1f}.png"
        canvas.save(str(path))
        print(f"{path.name}  窗口 {window.width()}x{window.height()}  倾斜 {depth}")
        shots.append((depth, canvas))

    # 横向拼图（每张上面写一行标签）
    gap = 18
    total_w = sum(p.width() for _d, p in shots) + gap * (len(shots) - 1)
    total_h = max(p.height() for _d, p in shots) + 34
    montage = QPixmap(total_w, total_h)
    montage.fill(QColor("#0b1020"))
    painter = QPainter(montage)
    font = QFont("Microsoft YaHei UI", 11)
    painter.setFont(font)
    painter.setPen(QColor("#9ecbff"))
    x = 0
    for depth, pic in shots:
        painter.drawText(x + 8, 22, f"左右倾斜 {depth:.1f}")
        painter.drawPixmap(x, 34, pic)
        x += pic.width() + gap
    painter.end()
    out = ROOT / "dev" / "_persp_all.png"
    montage.save(str(out))
    print(f"{out.name}  拼图 {total_w}x{total_h}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
