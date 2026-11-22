"""30 帧逐字绘制追踪：整行底图与逐字层中心差必须 ≤0.5px。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_SCALE_FACTOR", "1.5")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lyricdesk import config, heat, render  # noqa: E402

config.SETTINGS_PATH = Path(tempfile.mkdtemp(prefix="lyricdesk-word-ghost-")) / "settings.json"

from lyricdesk.config import Settings  # noqa: E402
from lyricdesk.fonts import register_all  # noqa: E402
from lyricdesk.lyricdoc import LyricWord  # noqa: E402
from lyricdesk.lyrics import LyricLine, Lyrics  # noqa: E402
from lyricdesk.smtc import Snapshot, Track  # noqa: E402
from lyricdesk.window import LyricWindow  # noqa: E402

heat.lookup = lambda *args, **kwargs: None  # type: ignore[assignment]
heat.cached = lambda key: None  # type: ignore[assignment]

TEXT = "未唱到的部分不能留下错位暗字"


class FakeScreen:
    def availableGeometry(self) -> QRect:
        return QRect(0, 0, 1707, 1067)


class Engine:
    def __init__(self) -> None:
        words = [
            LyricWord(10.0 + index * 0.36, 0.32, char)
            for index, char in enumerate(TEXT)
        ]
        self.lyrics = Lyrics(
            lines=[LyricLine(10.0, TEXT, 10.0 + len(TEXT) * 0.36, words=words)],
            source="test",
            title="逐字重影测试",
            artist="LyricDesk",
            provider="test",
        )
        self.snapshot_value = Snapshot(
            track=Track("逐字重影测试", "LyricDesk", "", 60.0),
            position=10.0,
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
    settings = Settings()
    raw = json.loads(
        (Path(os.environ["APPDATA"]) / "LyricDesk" / "settings.json").read_text(
            encoding="utf-8"
        )
    )
    for key, value in raw.items():
        if hasattr(settings, key):
            setattr(settings, key, value)
    settings.lyric_effect = "word"
    settings.lyric_glow = 2.4
    settings.lyric_arc = 0.0
    settings.lyric_breath = 0.0
    settings.lyric_jitter = 0.35
    settings.show_wave = False
    settings.real_wave = False
    settings.auto_show_on_music = False

    engine = Engine()
    window = LyricWindow(settings, engine)
    window.screen = lambda: FakeScreen()
    window._timer.stop()
    window._topmost_timer.stop()
    window.show()
    QApplication.processEvents()

    max_layer_offset = 0.0
    max_advance_delta = 0.0
    max_spacing_error = 0.0
    for frame_index in range(30):
        engine.snapshot_value.position = 10.0 + (frame_index + 1) * 0.12
        window._anim_t0 = -1000.0
        render.start_draw_trace()
        window.grab()
        trace = render.stop_draw_trace()
        line_draws = [
            item
            for item in trace
            if item.get("context", {}).get("line_text") == TEXT
            and item["text"] == TEXT
        ]
        char_draws = [
            item
            for item in trace
            if item.get("context", {}).get("line_text") == TEXT
            and len(item["text"]) == 1
        ]
        if line_draws:
            context = line_draws[0]["context"]
            max_advance_delta = max(
                max_advance_delta,
                float(context["line_advance_delta"]),
            )
            if char_draws:
                left = min(item["center_x"] - item["advance"] / 2.0 for item in char_draws)
                right = max(item["center_x"] + item["advance"] / 2.0 for item in char_draws)
                char_center = (left + right) / 2.0
                max_layer_offset = max(
                    max_layer_offset,
                    abs(line_draws[0]["center_x"] - char_center),
                )
            timed = [
                item
                for item in char_draws
                if "timing_width" in item.get("context", {})
            ]
            timed.sort(key=lambda item: item["context"]["timing_x"])
            for left, right in zip(timed, timed[1:]):
                expected = (
                    float(left["context"]["timing_width"])
                    + float(right["context"]["timing_width"])
                ) / 2.0
                actual = right["center_x"] - left["center_x"]
                max_spacing_error = max(
                    max_spacing_error,
                    abs(actual - expected),
                )

    print(f"max_advance_delta={max_advance_delta:.3f}px")
    print(f"max_layer_offset={max_layer_offset:.3f}px")
    print(f"max_spacing_error={max_spacing_error:.3f}px")
    ok = (
        max_advance_delta <= 0.5
        and max_layer_offset <= 0.5
        and max_spacing_error <= 1.0
    )
    print(f"\n结果：{'通过' if ok else '失败'}")
    window.close()
    window.deleteLater()
    QApplication.processEvents()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
