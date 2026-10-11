r"""检查「前奏中 · 还剩几秒」这行提示画得对不对。

    python dev\shot_intro.py <输出目录>
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import dev.split_shot as shot  # noqa: E402
from lyricdesk.config import Settings  # noqa: E402
from lyricdesk.lyrics import LyricLine, Lyrics  # noqa: E402
from lyricdesk.window import LyricWindow  # noqa: E402


class IntroEngine(shot.FakeEngine):
    """一首前奏 30 秒的歌，当前才播到第 5 秒。"""

    def __init__(self) -> None:
        super().__init__()
        self._snapshot.position = 5.0
        self._lyrics = Lyrics(
            lines=[
                LyricLine(time=30.0, text="第一句歌词从这里开始", end=34.0),
                LyricLine(time=34.0, text="第二句歌词", end=38.0),
            ],
            source="QQ音乐",
            title="海屿你",
            artist="马也_Crabbit",
            albummid="",
            album="海屿你",
        )


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "dev")
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication([])  # noqa: F841

    settings = Settings()
    settings.mode = "lyrics"
    window = LyricWindow(settings, IntroEngine())
    window.recalculate()
    canvas = shot.wallpaper(window.width(), window.height())
    layer = QPixmap(window.size())
    layer.fill(QColor(0, 0, 0, 0))
    window.render(layer)
    painter = QPainter(canvas)
    painter.drawPixmap(0, 0, layer)
    painter.end()
    path = out / "27_intro_hint.png"
    canvas.save(str(path))
    print(f"已保存 {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
