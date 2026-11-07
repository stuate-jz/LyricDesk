"""v1.7.6 拍点检测：120/90 BPM、静音、开关与噪声。"""

from __future__ import annotations

import importlib.util
import os
import random
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from lyricdesk import config

config.SETTINGS_PATH = Path(tempfile.mkdtemp(prefix="lyricdesk-v176-beat-")) / "settings.json"

from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication

from lyricdesk import audio as audio_mod
from lyricdesk.beat import BeatTracker
from lyricdesk.config import Settings
from lyricdesk.fonts import register_all
from lyricdesk.settings_dialog import SettingsDialog
from lyricdesk.window import LyricWindow


def fake_engine():
    path = ROOT / "dev" / "check_v170_disc.py"
    spec = importlib.util.spec_from_file_location("_v176_beat_engine", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.FakeEngine()


class ProbeBeat(BeatTracker):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def update(self, low, now):
        self.calls += 1
        return super().update(low, now)


def run_click(bpm: float, seconds: float = 20.0) -> tuple[BeatTracker, BeatTracker]:
    tracker = BeatTracker()
    history = [0.0] * 48
    interval_frames = max(1, int(round((60.0 / bpm) / 0.025)))
    state = None
    for frame in range(int(seconds / 0.025)):
        value = 1.0 if frame > 8 and (frame - 8) % interval_frames == 0 else 0.0
        history = history[1:] + [value]
        state = tracker.update(history, frame * 0.025)
    return tracker, state


def run_jitter(
    bpm: float,
    jitter: float,
    seconds: float = 20.0,
    poll: float = 30.0,
    *,
    base: float = 0.32,
    click: bool = True,
) -> tuple[BeatTracker, object]:
    """真实频谱的帧间抖动是随机的，不是平滑正弦。"""
    rng = random.Random(5)
    frames = int(seconds / 0.025)
    period = 60.0 / bpm / 0.025
    low = []
    for index in range(frames):
        value = base + rng.uniform(-jitter, jitter)
        if click:
            for beat in range(int(frames / period) + 1):
                if abs(index - beat * period) < 0.5:
                    value = 0.9
        low.append(max(0.0, value))
    tracker = BeatTracker()
    state = None
    ticks = int(seconds * poll)
    for tick in range(ticks):
        now = tick / poll
        frame = int(now / 0.025)
        history = low[max(0, frame - 47):frame + 1]
        if len(history) < 48:
            history = [0.0] * (48 - len(history)) + history
        state = tracker.update(history, now)
    return tracker, state


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    register_all()
    failures = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        failures += 0 if ok else 1
        print(f"  {'OK  ' if ok else 'FAIL'} {name}" + (f"  —— {detail}" if detail else ""))

    tracker120, state120 = run_click(120)
    check("120 BPM 落在 ±4", abs(state120.bpm - 120) <= 4, str(state120))
    expected = 40
    check(
        "零抖动 120 BPM 起音 40 次",
        abs(tracker120._onset_count - expected) <= 1,
        str(tracker120._onset_count),
    )

    tracker90, state90 = run_click(90)
    check("90 BPM 落在 ±4", abs(state90.bpm - 90) <= 4, str(state90))

    for bpm, jitter, expected_count, tolerance in (
        (100, 0.005, 33, 0.10),
        (100, 0.02, 33, 0.10),
        (120, 0.005, 40, 0.10),
        (120, 0.02, 40, 0.10),
        (60, 0.02, 20, 0.15),
    ):
        tracker, state = run_jitter(bpm, jitter)
        low = expected_count * (1.0 - tolerance)
        high = expected_count * (1.0 + tolerance)
        detail = (
            f"onsets={tracker._onset_count}, bpm={state.bpm:.0f}, "
            f"confidence={state.confidence:.2f}"
        )
        check(
            f"{bpm}BPM 抖动 ±{jitter:g} 起音数在范围内",
            low <= tracker._onset_count <= high,
            detail,
        )
        if bpm in (100, 120):
            check(
                f"{bpm}BPM 抖动 ±{jitter:g} confidence ≥0.5",
                state.confidence >= 0.5,
                f"{state.confidence:.2f}",
            )

    silent = BeatTracker()
    history = [0.0] * 48
    state = None
    for frame in range(120):
        state = silent.update(history, frame * 0.025)
    check("静音 3 秒没有起音", silent._onset_count == 0, str(silent._onset_count))
    check("静音脉冲归零", state.pulse < 0.02, str(state.pulse))

    quiet, _quiet_state = run_jitter(
        120,
        0.01,
        seconds=10.0,
        base=0.05,
        click=False,
    )
    check("安静段抖动不产生起音", quiet._onset_count == 0, str(quiet._onset_count))
    perf_tracker = BeatTracker()
    started = time.perf_counter()
    for index in range(10000):
        perf_tracker.update(history, index * 0.033)
    elapsed = (time.perf_counter() - started) / 10000.0 * 1000.0
    check("节拍 update ≤0.05ms/帧", elapsed <= 0.05, f"{elapsed:.4f}ms")

    settings = Settings()
    settings.font_family = "Smiley Sans"
    settings.background = False
    settings.show_song_info = False
    settings.lyric_effect = "word"
    settings.beat_boost = False
    settings.real_wave = True
    engine = fake_engine()
    window = LyricWindow(settings, engine)
    window.show()
    app.processEvents()
    window._display_idx = 8
    window._scroll_ready = True
    window._scroll_from = window._scroll_target = 8.0
    engine._snapshot.position = engine.lyrics.lines[8].time + 1.0
    old_has_data = audio_mod.MONITOR._has_data
    audio_mod.MONITOR._has_data = True
    try:
        probe = ProbeBeat()
        window._beat = probe
        image = QPixmap(window.size())
        image.fill(QColor(0, 0, 0, 0))
        window.render(image)
        check("beat_boost=False 不调用 update", probe.calls == 0, str(probe.calls))

        settings.beat_boost = True
        settings.real_wave = False
        window._commit()
        probe.calls = 0
        window.render(image)
        check("real_wave=False 不调用 update 且 pulse=0", probe.calls == 0 and probe.pulse == 0.0, str(probe.calls))

        settings.real_wave = True
        window._commit()
        probe.calls = 0
        window.render(image)
        check("三项条件满足后调用 update", probe.calls > 0, str(probe.calls))
    finally:
        audio_mod.MONITOR._has_data = old_has_data

    dialog = SettingsDialog(window)
    dialog.goto_page("lyrics")
    settings.real_wave = False
    dialog._refresh()
    dialog._sync_layout_controls()
    check("未开真实音波时拍点复选框置灰", not dialog._beat_box.isEnabled())
    settings.real_wave = True
    dialog._loopback_available = True
    dialog._sync_layout_controls()
    check("真实音波与回环可用时拍点可勾选", dialog._beat_box.isEnabled())

    window.close()
    window.deleteLater()
    app.processEvents()

    print("全部通过" if not failures else f"{failures} 项失败")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
