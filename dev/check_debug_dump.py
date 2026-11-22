"""验证 Ctrl+Alt+Shift+D 对应的转储函数能生成完整压缩包。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lyricdesk import config, heat  # noqa: E402

config.SETTINGS_PATH = Path(tempfile.mkdtemp(prefix="lyricdesk-debug-dump-")) / "settings.json"

from lyricdesk.config import Settings  # noqa: E402
from lyricdesk.fonts import register_all  # noqa: E402
from lyricdesk.lyrics import LyricLine, Lyrics  # noqa: E402
from lyricdesk.smtc import Snapshot, Track  # noqa: E402
from lyricdesk import window as window_module  # noqa: E402
from lyricdesk.window import LyricWindow  # noqa: E402

heat.lookup = lambda *args, **kwargs: None  # type: ignore[assignment]
heat.cached = lambda key: None  # type: ignore[assignment]


class FakeScreen:
    def availableGeometry(self) -> QRect:
        return QRect(0, 0, 1707, 1067)


class Engine:
    def __init__(self) -> None:
        self.lyrics = Lyrics(
            lines=[LyricLine(10.0, "调试转储测试歌词", 14.0)],
            source="test",
            title="调试转储测试",
            artist="LyricDesk",
            provider="test",
        )
        self.snapshot_value = Snapshot(
            track=Track("调试转储测试", "LyricDesk", "", 60.0),
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


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    register_all()
    temp = Path(tempfile.mkdtemp(prefix="lyricdesk-debug-output-"))
    original_app_dir = window_module.app_dir
    window_module.app_dir = lambda: temp
    settings = Settings()
    settings.lyric_effect = "word"
    settings.show_wave = False
    settings.real_wave = False
    settings.auto_show_on_music = False
    window = LyricWindow(settings, Engine())
    window.screen = lambda: FakeScreen()
    window._timer.stop()
    window._topmost_timer.stop()
    window.show()
    QApplication.processEvents()
    window._tick()
    QApplication.processEvents()
    window._dump_debug_bundle()
    QApplication.processEvents()

    archives = list((temp / "debug").glob("*/debug-*.zip"))
    ok = bool(archives)
    names: list[str] = []
    draw_lines = 0
    if archives:
        with zipfile.ZipFile(archives[-1]) as bundle:
            names = sorted(bundle.namelist())
            draw_name = next((name for name in names if name.startswith("draw-")), "")
            if draw_name:
                draw_lines = len(bundle.read(draw_name).decode("utf-8").splitlines())
        ok = (
            len(names) == 3
            and any(name.startswith("frame-") for name in names)
            and any(name.startswith("settings-") for name in names)
            and any(name.startswith("draw-") for name in names)
            and draw_lines > 0
        )
    print(f"archive={archives[-1] if archives else 'none'}")
    print(f"members={names}")
    print(f"draw_lines={draw_lines}")
    print(f"\n结果：{'通过' if ok else '失败'}")
    window.close()
    window.deleteLater()
    QApplication.processEvents()
    window_module.app_dir = original_app_dir
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
