"""把内置字体 + 已下载的在线字体各渲染一遍，拼成一张对比图。"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lyricdesk.config import Settings  # noqa: E402
from lyricdesk.fonts import ONLINE_FONTS, register_all  # noqa: E402
from lyricdesk.lyrics import LyricLine, Lyrics  # noqa: E402
from lyricdesk.window import LyricWindow  # noqa: E402

LYRICS = (
    "如果当初没有遇见你",
    "也许不会写满了回忆",
    "多少温柔藏在心底",
    "多少思念无人提起",
    "曾经说好一起到老去",
    "如今只剩孤单的自己",
)

ROW_H = 250
LABEL_W = 300


class Track:
    title = "如果当初没有遇见你"
    artist = "演唱者"
    album = "专辑"
    duration = 220.0
    key = "k"
    display = "x"


class Snap:
    track = Track()
    position = 92.0
    is_playing = True
    status = 4
    source = "x"
    can_next = True
    can_prev = True
    can_seek = False


class FakeEngine:
    lyrics = Lyrics(
        lines=[
            LyricLine(time=i * 4.0, text=text, end=i * 4.0 + 4.0)
            for i, text in enumerate(LYRICS)
        ],
        source="QQ音乐",
        title=Track.title,
        artist=Track.artist,
        albummid="local",
    )

    def snapshot(self):
        return Snap()

    def thumbnail(self):
        return None


def load_cover() -> QPixmap | None:
    cover_dir = Path.home() / "AppData" / "Roaming" / "LyricDesk" / "covers"
    if not cover_dir.is_dir():
        return None
    for item in sorted(cover_dir.glob("*.jpg")):
        pixmap = QPixmap(str(item))
        if not pixmap.isNull():
            return pixmap
    return None


def render(family: str, cover: QPixmap | None) -> QPixmap:
    settings = Settings()
    settings.mode = "depth3d"
    settings.depth_album_style = "classic"
    settings.font_family = family
    settings.font_size = 46
    window = LyricWindow(settings, FakeEngine())
    if cover is not None:
        window._covers["local"] = cover
    window.recalculate()
    pixmap = QPixmap(window.width(), window.height())
    pixmap.fill(QColor("#232733"))
    window.render(pixmap)
    return pixmap


def main() -> int:
    app = QApplication(sys.argv)
    register_all()

    entries = [("微软雅黑（系统默认）", "Microsoft YaHei UI"), ("得意黑（内置）", "Smiley Sans")]
    entries += [(f"{item.label}（在线）", item.family) for item in ONLINE_FONTS]

    cover = load_cover()
    canvas = QPixmap(1180, ROW_H * len(entries) + 20)
    canvas.fill(QColor("#161a22"))
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    label_font = QFont("Microsoft YaHei UI")
    label_font.setPixelSize(17)

    for index, (label, family) in enumerate(entries):
        top = 10 + index * ROW_H
        painter.setFont(label_font)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(
            QRectF(16, top + 95, LABEL_W - 30, 50),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            label,
        )
        shot = render(family, cover)
        # 只截右侧歌词区，歌词更清楚
        painter.drawPixmap(
            LABEL_W, int(top), 880, int(ROW_H - 10),
            shot,
            int(shot.width() * 0.32), int(shot.height() * 0.17),
            int(shot.width() * 0.68), int(shot.height() * 0.68),
        )
        painter.setPen(QColor(255, 255, 255, 16))
        painter.drawLine(0, top + ROW_H - 4, canvas.width(), top + ROW_H - 4)

    painter.end()
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("font_montage_all.png")
    canvas.save(str(out))
    print("saved", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
