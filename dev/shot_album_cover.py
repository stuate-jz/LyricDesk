r"""检查唱片模式：封面大小档位、以及「显示封面」关掉后的效果。

    python dev\shot_album_cover.py <输出目录>
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
            position=73.0,
            is_playing=True,
            status=4,
            source="QQMusic.exe",
        )
        self._lyrics = Lyrics(
            lines=[LyricLine(time=0.0, text="海屿你", end=4.0)],
            source="QQ音乐",
            title="海屿你",
            artist="马也_Crabbit",
            albummid="local",
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
    gradient.setColorAt(1.0, QColor("#0d1117"))
    painter.fillRect(pixmap.rect(), gradient)
    painter.end()
    return pixmap


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "dev")
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication([])

    cover_file = None
    covers = ROOT / "dev"
    for name in ("_album_disc.png",):
        candidate = covers / name
        if candidate.exists():
            cover_file = candidate

    cases = [
        ("cover48", 48, True),
        ("cover88", 88, True),
        ("cover120", 120, True),
        ("nofcov", 88, False),
    ]
    for tag, size, show in cases:
        settings = Settings()
        settings.mode = "album"
        settings.cover_size = size
        settings.show_cover = show
        settings.width = 760
        window = LyricWindow(settings, FakeEngine())
        window.recalculate()
        canvas = wallpaper(window.width(), window.height())
        layer = QPixmap(window.size())
        layer.fill(QColor(0, 0, 0, 0))
        window.render(layer)
        painter = QPainter(canvas)
        painter.drawPixmap(0, 0, layer)
        painter.end()
        path = out / f"23_album_{tag}.png"
        canvas.save(str(path))
        print(
            f"{path.name}  窗口 {window.width()}x{window.height()}  "
            f"封面设置={size} 显示封面={show}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
