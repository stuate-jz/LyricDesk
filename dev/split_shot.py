"""离线渲染「分离面板」模式的两扇面板，检查位置与尺寸是否符合预期。"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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
            position=73.4,
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

    def thumbnail(self):
        return None


def wallpaper(width: int, height: int) -> QPixmap:
    pixmap = QPixmap(width, height)
    painter = QPainter(pixmap)
    gradient = QLinearGradient(0, 0, width, height)
    gradient.setColorAt(0.0, QColor("#1b2430"))
    gradient.setColorAt(1.0, QColor("#3a2d3f"))
    painter.fillRect(pixmap.rect(), gradient)
    painter.end()
    return pixmap


def main() -> int:
    app = QApplication(sys.argv)
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "dev")
    out.mkdir(parents=True, exist_ok=True)

    settings = Settings()
    settings.mode = "split"
    engine = FakeEngine()

    player = LyricWindow(settings, engine, role="player")
    player.recalculate()
    lyrics = LyricWindow(
        settings, engine, role="lyrics", anchor_y=player.height() + 84
    )
    lyrics.recalculate()

    print("player", player.width(), player.height(), "lyrics", lyrics.width(), lyrics.height())

    # 把两扇面板按默认相对位置叠到同一张壁纸上，直观看出间距
    width = max(player.width(), lyrics.width()) + 160
    height = player.height() + lyrics.height() + 240
    canvas = wallpaper(width, height)
    offset_x = width - max(player.width(), lyrics.width()) - 80
    player.move(offset_x, 80)
    lyrics.move(offset_x, 80 + player.height() + 24)
    for win in (player, lyrics):
        layer = QPixmap(win.size())
        layer.fill(QColor(0, 0, 0, 0))
        win.render(layer)
        painter = QPainter(canvas)
        painter.drawPixmap(win.x(), win.y(), layer)
        painter.end()

    path = out / "split_panels.png"
    canvas.save(str(path))
    print("rendered", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
