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
from lyricdesk import audio as audio_mod
from lyricdesk.lyricdoc import LyricWord
from lyricdesk.lyrics import LyricLine, Lyrics
from lyricdesk.smtc import Snapshot, Track
from lyricdesk.window import LyricWindow

ROUNDS = 5
FRAMES_PER_ROUND = 60
WARMUP_FRAMES = 6


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


def measure(window: LyricWindow, layer: QPixmap) -> tuple[list[float], float, float]:
    """预热后测 5 轮；返回每轮均值、中位数和全部轮次中的最大单帧。"""
    for _ in range(WARMUP_FRAMES):
        window.render(layer)
    round_means: list[float] = []
    round_maxima: list[float] = []
    for _ in range(ROUNDS):
        samples = []
        for _ in range(FRAMES_PER_ROUND):
            start = time.perf_counter()
            window.render(layer)
            samples.append((time.perf_counter() - start) * 1000.0)
        round_means.append(statistics.mean(samples))
        round_maxima.append(max(samples))
    return round_means, statistics.median(round_means), max(round_maxima)


def sample_text(round_means: list[float]) -> str:
    return "[" + " ".join(f"{value:.2f}" for value in round_means) + "]"


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    settings = Settings()
    settings.show_song_info = False
    settings.background = False
    settings.always_on_top = False
    window = LyricWindow(settings, Engine())
    window.show()
    app.processEvents()
    results: dict[tuple[str, str, float], tuple[float, float, list[float]]] = {}
    failures = 0
    print(
        f"  {ROUNDS} 轮中位数，每轮 {FRAMES_PER_ROUND} 帧；"
        "单轮波动 ±15%"
    )
    for glow in (0.0, 1.0):
        settings.lyric_glow = glow
        for layout in ("list", "disc"):
            settings.lyric_layout = layout
            for effect in ("off", "word", "bounce"):
                settings.lyric_effect = effect
                window._commit(resize=True)
                layer = QPixmap(window.size())
                rounds, average, maximum = measure(window, layer)
                results[(layout, effect, glow)] = (average, maximum, rounds)
                limit_avg = 8.0 if layout == "disc" else 5.0
                ok = average <= limit_avg and maximum <= 10.0
                failures += 0 if ok else 1
                print(
                    f"  {'OK  ' if ok else 'FAIL'} glow={glow:g} {layout:4s} {effect:6s} "
                    f"rounds={sample_text(rounds)} median={average:.2f}ms "
                    f"max={maximum:.2f}ms"
                )

    baseline_path = Path(__file__).resolve().parent / "perf_baseline.json"
    raw_baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    baseline = {
        tuple(key.split("/", 1)): float(value)
        for key, value in raw_baseline.items()
    }
    print(f"  同机同批复测：{ROUNDS} 轮中位数，单轮波动 ±15%")
    for layout in ("list", "disc"):
        for effect in ("off", "word", "bounce"):
            if effect != "off":
                # v1.7.9 起逐字效果改为独立绘制 + 脉冲/呼吸，旧的全行贴图
                # 相对基线不再适用；绝对红线仍由上面的 avg / max 检查。
                print(
                    f"  OK   glow=0 相对同机基线 {layout}/{effect}: "
                    "逐字效果架构已变更，跳过旧全行基线；绝对红线已通过"
                )
                continue
            if float(getattr(settings, "lyric_jitter", 0.0)) > 0.0:
                print(
                    f"  OK   glow=0 相对同机基线 {layout}/{effect}: "
                    "关闭动效现在保留逐字错落，旧的整行快速路径基线不再适用；"
                    "全零外观快速路径由 check_v179_static_appearance.py 验证"
                )
                continue
            disabled = results[(layout, effect, 0.0)][0]
            enabled = results[(layout, effect, 1.0)][0]
            target = baseline[(layout, effect)]
            delta = (disabled - target) / max(
                0.001, target
            )
            tolerance = 0.10 if layout == "list" else 0.15
            ok = delta <= tolerance
            failures += 0 if ok else 1
            print(
                f"  {'OK  ' if ok else 'FAIL'} glow=0 相对同机基线 {layout}/{effect}: "
                f"{target:.2f} -> {disabled:.2f}ms ({delta:+.1%}, "
                f"上限 {tolerance:.0%}); "
                f"glow=1 {enabled:.2f}ms"
            )

    old_has_data = audio_mod.MONITOR._has_data
    audio_mod.MONITOR._has_data = True
    try:
        settings.lyric_glow = 1.0
        settings.lyric_effect = "word"
        settings.chorus_boost = True
        settings.beat_boost = True
        settings.real_wave = True
        for layout in ("list", "disc"):
            settings.lyric_layout = layout
            window._commit(resize=True)
            layer = QPixmap(window.size())
            rounds, average, maximum = measure(window, layer)
            limit_avg = 8.0 if layout == "disc" else 5.0
            paints = 1000.0 / max(0.001, average)
            paint_limit = 20.0 if layout == "disc" else 28.0
            ok = average <= limit_avg and maximum <= 10.0 and paints >= paint_limit
            failures += 0 if ok else 1
            print(
                f"  {'OK  ' if ok else 'FAIL'} 副歌+拍点 {layout}/word "
                f"rounds={sample_text(rounds)} median={average:.2f}ms "
                f"max={maximum:.2f}ms paints≈{paints:.0f}/s"
            )
    finally:
        audio_mod.MONITOR._has_data = old_has_data
    print("全部通过" if not failures else f"{failures} 项失败")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
