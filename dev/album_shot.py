"""把唱片模式渲染到模拟壁纸上，检查无背景板时的可读性。"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lyricdesk.config import Settings  # noqa: E402
from lyricdesk.window import LyricWindow  # noqa: E402


class Track:
    title = "海屿你"
    artist = "马也_Crabbit"
    album = "海屿你"
    duration = 219.0
    key = "k"
    display = "海屿你 - 马也_Crabbit"


class Snap:
    track = Track()
    position = 73.0
    is_playing = True
    status = 4
    source = "QQMusic.exe"
    can_next = True
    can_prev = True
    can_seek = False


class Lyrics:
    albummid = "local"
    source = "QQ音乐"
    lines: list = []


class FakeEngine:
    def snapshot(self):
        return Snap()

    lyrics = Lyrics()

    def thumbnail(self):
        return None


def wallpaper(width: int, height: int, dark: bool) -> QPixmap:
    pixmap = QPixmap(width, height)
    painter = QPainter(pixmap)
    gradient = QLinearGradient(0, 0, width, height)
    if dark:
        gradient.setColorAt(0.0, QColor("#1b2430"))
        gradient.setColorAt(1.0, QColor("#0d1117"))
    else:
        gradient.setColorAt(0.0, QColor("#d8d2c0"))
        gradient.setColorAt(1.0, QColor("#8fa0a8"))
    painter.fillRect(pixmap.rect(), gradient)
    painter.end()
    return pixmap


def main() -> int:
    app = QApplication(sys.argv)
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    out.mkdir(parents=True, exist_ok=True)

    # 用封面缓存里的第一张图，做出带真实封面的效果
    cover: QPixmap | None = None
    cover_dir = Path.home() / "AppData" / "Roaming" / "LyricDesk" / "covers"
    if cover_dir.is_dir():
        for item in sorted(cover_dir.glob("*.jpg")):
            pixmap = QPixmap(str(item))
            if not pixmap.isNull():
                cover = pixmap
                break

    for dark in (False, True):
        settings = Settings()
        settings.mode = "album"
        settings.album_shape = "disc"
        window = LyricWindow(settings, FakeEngine())
        if cover is not None:
            window._covers[Lyrics.albummid] = cover
        window.recalculate()
        pixmap = wallpaper(window.width(), window.height(), dark)
        window.render(pixmap)
        tag = "dark" if dark else "light"
        path = out / f"album_nocard_{tag}.png"
        pixmap.save(str(path))
        print("rendered", path.name, f"{window.width()}x{window.height()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
