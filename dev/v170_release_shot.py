"""生成 v1.7.0 圆盘歌词与播放器发布图。"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QColor,
    QLinearGradient,
    QPainter,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import QApplication  # noqa: E402

from lyricdesk import config  # noqa: E402

config.SETTINGS_PATH = Path(tempfile.mkdtemp(prefix="lyricdesk-shot-")) / "settings.json"

from lyricdesk.config import Settings  # noqa: E402
from lyricdesk.fonts import register_all  # noqa: E402
from lyricdesk.lyricdoc import LyricWord  # noqa: E402
from lyricdesk.lyrics import LyricLine, Lyrics  # noqa: E402
from lyricdesk.smtc import Snapshot, Track  # noqa: E402
from lyricdesk.window import LyricWindow  # noqa: E402

OUTS = (
    ROOT / "assets" / "screenshots",
    ROOT / "release-page" / "screenshots",
    ROOT / "docs" / "screenshots",
)


class Engine:
    def __init__(self) -> None:
        texts = [
            "风越过城市安静的屋檐",
            "把没有说完的话轻轻吹远",
            "此刻让歌词沿着唱片发光",
            "每一个字都跟着节拍向前",
            "下一句仍然清楚停在你身边",
            "夜色落在透明的桌面上",
            "让旋律慢慢地绕过时间",
        ]
        lines = []
        cursor = 0.0
        for text in texts:
            words = [
                LyricWord(cursor + index * 0.22, 0.18, char)
                for index, char in enumerate(text)
            ]
            lines.append(LyricLine(cursor, text, cursor + 3.8, words=words))
            cursor += 4.0
        self.lyrics = Lyrics(
            lines=lines,
            source="酷狗KRC",
            title="让歌词沿着唱片发光",
            artist="LyricDesk",
            album="桌面歌词 v1.7.0",
            albummid="v170-showcase",
            provider="kugou",
        )
        self.lyrics.to_doc()
        self.snapshot_value = Snapshot(
            track=Track(
                "让歌词沿着唱片发光",
                "LyricDesk",
                "桌面歌词 v1.7.0",
                238.0,
            ),
            position=15.4,
            is_playing=True,
            status=4,
            source="QQMusic.exe",
        )

    def snapshot(self):
        return self.snapshot_value

    def players(self):
        return []

    def send_control(self, _command):
        return None


def cover_pixmap() -> QPixmap:
    cache = Path(os.environ.get("APPDATA", "")) / "LyricDesk" / "covers"
    if cache.is_dir():
        for path in sorted(cache.glob("*.jpg"), key=lambda item: -item.stat().st_size):
            pixmap = QPixmap(str(path))
            if not pixmap.isNull() and pixmap.width() >= 200:
                return pixmap
    pixmap = QPixmap(500, 500)
    painter = QPainter(pixmap)
    gradient = QLinearGradient(0, 0, 500, 500)
    gradient.setColorAt(0.0, QColor("#7dd3fc"))
    gradient.setColorAt(0.5, QColor("#a78bfa"))
    gradient.setColorAt(1.0, QColor("#f0abfc"))
    painter.fillRect(pixmap.rect(), gradient)
    painter.setPen(QColor(255, 255, 255, 90))
    painter.drawEllipse(QPointF(250, 250), 150, 150)
    painter.end()
    return pixmap


def wallpaper(width: int, height: int) -> QPixmap:
    pixmap = QPixmap(width, height)
    painter = QPainter(pixmap)
    gradient = QLinearGradient(0, 0, width, height)
    gradient.setColorAt(0.0, QColor("#111827"))
    gradient.setColorAt(0.48, QColor("#17243a"))
    gradient.setColorAt(1.0, QColor("#2a1e3d"))
    painter.fillRect(pixmap.rect(), gradient)
    glow = QRadialGradient(QPointF(width * 0.38, height * 0.38), width * 0.55)
    glow.setColorAt(0.0, QColor(63, 167, 214, 52))
    glow.setColorAt(1.0, QColor(20, 25, 45, 0))
    painter.fillRect(pixmap.rect(), glow)
    painter.end()
    return pixmap


def render(window: LyricWindow) -> QPixmap:
    layer = QPixmap(window.size())
    layer.fill(QColor(0, 0, 0, 0))
    window.render(layer)
    return layer


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    register_all()
    cover = cover_pixmap()

    settings = Settings()
    settings.font_family = "Smiley Sans"
    settings.font_size = 38
    settings.theme = "aurora"
    settings.show_song_info = True
    settings.background = False
    settings.cover_size = 150
    settings.lyric_lines = 7
    settings.lyric_layout = "disc"
    settings.lyric_align = "right"
    settings.disc_angle = 10
    settings.disc_spread = 42
    settings.lyric_effect = "word"

    disc = LyricWindow(settings, Engine())
    disc._covers["v170-showcase"] = cover
    disc.recalculate()

    player_settings = Settings()
    player_settings.font_family = "Smiley Sans"
    player_settings.font_size = 34
    player_settings.theme = "aurora"
    player_settings.background = False
    player_settings.cover_size = 96
    player_settings.player_width = 420
    player_settings.lyric_layout = "disc"
    player = LyricWindow(player_settings, Engine(), role="player")

    # 单张圆盘场景
    width = max(1040, disc.width() + 140)
    height = max(620, disc.height() + 120)
    canvas = wallpaper(width, height)
    disc_layer = render(disc)
    painter = QPainter(canvas)
    painter.drawPixmap(
        (width - disc.width()) // 2,
        (height - disc.height()) // 2,
        disc_layer,
    )
    painter.end()
    canvas.save(str(ROOT / "assets" / "screenshots" / "screenshot-v170-disc.png"))

    # 发布页/文档用图：圆盘 + 不再重复封面的播放器面板
    show_width = max(1320, disc.width() + player.width() + 120)
    show_height = max(720, disc.height() + 160)
    show = wallpaper(show_width, show_height)
    painter = QPainter(show)
    disc_x = 54
    disc_y = show_height - disc.height() - 54
    painter.drawPixmap(disc_x, disc_y, disc_layer)
    player_layer = render(player)
    painter.drawPixmap(
        show_width - player.width() - 58,
        62,
        player_layer,
    )
    painter.end()
    show.save(str(ROOT / "assets" / "screenshots" / "screenshot-v170-show.png"))

    for folder in OUTS[1:]:
        folder.mkdir(parents=True, exist_ok=True)
        canvas.save(str(folder / "disc.png"))
        show.save(str(folder / "show.png"))
    print("已生成 v1.7.0 圆盘 / 组合发布图")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
