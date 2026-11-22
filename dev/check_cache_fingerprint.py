"""验证透明参数复用位图，字号变化使位图整体失效。"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lyricdesk import config, heat, render  # noqa: E402

config.SETTINGS_PATH = Path(tempfile.mkdtemp(prefix="lyricdesk-cache-")) / "settings.json"

from lyricdesk.config import Settings  # noqa: E402
from lyricdesk.fonts import register_all  # noqa: E402
from lyricdesk.lyrics import LyricLine, Lyrics  # noqa: E402
from lyricdesk.smtc import Snapshot, Track  # noqa: E402
from lyricdesk.window import LyricWindow  # noqa: E402

heat.lookup = lambda *args, **kwargs: None  # type: ignore[assignment]
heat.cached = lambda key: None  # type: ignore[assignment]


class FakeScreen:
    def availableGeometry(self) -> QRect:
        return QRect(0, 0, 1707, 1067)


class Engine:
    def __init__(self) -> None:
        self.lyrics = Lyrics(
            lines=[
                LyricLine(10.0, "缓存指纹测试歌词", 14.0),
                LyricLine(14.0, "第二行用于缓存命中", 18.0),
            ],
            source="test",
            title="缓存测试",
            artist="LyricDesk",
            provider="test",
        )
        self.snapshot_value = Snapshot(
            track=Track("缓存测试", "LyricDesk", "", 60.0),
            position=10.8,
            is_playing=True,
            status=4,
            source="QQMusic.exe",
        )

    def snapshot(self):
        return self.snapshot_value

    def players(self):
        return []

    def send_control(self, _action):
        return None

    def reload(self):
        return None


def paint(window: LyricWindow) -> None:
    window._anim_t0 = -1000.0
    layer = QPixmap(window.size())
    window.render(layer)
    QApplication.processEvents()


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    register_all()
    settings = Settings()
    settings.lyric_effect = "off"
    settings.lyric_glow = 0.0
    settings.lyric_arc = 0.0
    settings.lyric_breath = 0.0
    settings.lyric_jitter = 0.0
    settings.show_wave = False
    settings.real_wave = False
    settings.auto_show_on_music = False
    window = LyricWindow(settings, Engine())
    window.screen = lambda: FakeScreen()
    window._timer.stop()
    window._topmost_timer.stop()
    window.show()
    QApplication.processEvents()
    paint(window)
    paint(window)
    print(f"initial_line_cache={len(render._LINE_CACHE)}")

    render.reset_cache_stats()
    window._set_ui_opacity(0.55)
    paint(window)
    opacity_stats = render.cache_stats()

    render.reset_cache_stats()
    window._set_font_size(52)
    paint(window)
    font_stats = render.cache_stats()

    print(f"opacity hit_rate={opacity_stats['line_hit_rate'] * 100:.1f}%")
    print(f"font_size hit_rate={font_stats['line_hit_rate'] * 100:.1f}%")
    print(f"fallback={render.cache_stats()['line_fallbacks']}")
    ok = (
        opacity_stats["line_hit_rate"] >= 0.999
        and font_stats["line_hit_rate"] <= 0.001
    )
    print(f"结果：{'通过' if ok else '失败'}")
    window.close()
    window.deleteLater()
    QApplication.processEvents()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
