"""v1.7.4 glow=0 / glow=1 绘制成本对比。"""

from __future__ import annotations

import os
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from lyricdesk import config

config.SETTINGS_PATH = Path(tempfile.mkdtemp(prefix="lyricdesk-v174-perf-")) / "settings.json"

from lyricdesk.config import Settings
from lyricdesk.lyricdoc import LyricWord
from lyricdesk.lyrics import LyricLine, Lyrics
from lyricdesk.smtc import Snapshot, Track
from lyricdesk.window import LyricWindow


class Engine:
    def __init__(self) -> None:
        lines = []
        for index in range(20):
            text = f"第{index + 1}句歌词正在沿着时间轴发光"
            lines.append(
                LyricLine(
                    index * 4.0,
                    text,
                    index * 4.0 + 3.8,
                    words=[
                        LyricWord(index * 4.0 + offset * 0.22, 0.18, char)
                        for offset, char in enumerate(text)
                    ],
                )
            )
        self.lyrics = Lyrics(lines=lines, source="test", title="性能测试", artist="LyricDesk")
        self.snapshot_value = Snapshot(
            track=Track("性能测试", "LyricDesk", "测试", 90.0),
            position=41.1,
            is_playing=True,
            status=4,
            source="QQMusic.exe",
        )

    def snapshot(self):
        return self.snapshot_value

    def players(self):
        return []


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    settings = Settings()
    settings.show_song_info = False
    settings.background = False
    settings.always_on_top = False
    window = LyricWindow(settings, Engine())
    window.show()
    app.processEvents()
    results: dict[tuple[str, str, float], tuple[float, float]] = {}
    failures = 0
    for glow in (0.0, 1.0):
        settings.lyric_glow = glow
        for layout in ("list", "disc"):
            settings.lyric_layout = layout
            for effect in ("off", "word", "bounce"):
                settings.lyric_effect = effect
                window._commit(resize=True)
                layer = QPixmap(window.size())
                for _ in range(6):
                    window.render(layer)
                samples = []
                for _ in range(50):
                    start = time.perf_counter()
                    window.render(layer)
                    samples.append((time.perf_counter() - start) * 1000.0)
                average = statistics.mean(samples)
                maximum = max(samples)
                results[(layout, effect, glow)] = (average, maximum)
                limit_avg = 8.0 if layout == "disc" else 5.0
                ok = average <= limit_avg and maximum <= 10.0
                failures += 0 if ok else 1
                print(
                    f"  {'OK  ' if ok else 'FAIL'} glow={glow:g} {layout:4s} {effect:6s} "
                    f"avg={average:.2f}ms max={maximum:.2f}ms"
                )

    baseline_path = Path(__file__).resolve().parent / "perf_baseline.json"
    raw_baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    baseline = {
        tuple(key.split("/", 1)): float(value)
        for key, value in raw_baseline.items()
    }
    print("  同机同批复测，单次波动 ±8%")
    for layout in ("list", "disc"):
        for effect in ("off", "word", "bounce"):
            disabled = results[(layout, effect, 0.0)][0]
            enabled = results[(layout, effect, 1.0)][0]
            target = baseline[(layout, effect)]
            delta = (disabled - target) / max(
                0.001, target
            )
            ok = delta <= 0.10
            failures += 0 if ok else 1
            print(
                f"  {'OK  ' if ok else 'FAIL'} glow=0 相对同机基线 {layout}/{effect}: "
                f"{target:.2f} -> {disabled:.2f}ms ({delta:+.1%}); "
                f"glow=1 {enabled:.2f}ms"
            )
    print("全部通过" if not failures else f"{failures} 项失败")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
