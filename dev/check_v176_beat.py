"""v1.7.6 拍点检测：120/90 BPM、静音、开关与噪声。"""

from __future__ import annotations

import math
import importlib.util
import os
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


def run_click(bpm: float, seconds: float = 10.0) -> tuple[BeatTracker, BeatTracker]:
    tracker = BeatTracker()
    history = [0.0] * 48
    interval_frames = max(1, int(round((60.0 / bpm) / 0.025)))
    state = None
    for frame in range(int(seconds / 0.025)):
        value = 1.0 if frame > 8 and (frame - 8) % interval_frames == 0 else 0.0
        history = history[1:] + [value]
        state = tracker.update(history, frame * 0.025)
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
    expected = 19
    check(
        "120 BPM 起音计数误差 ≤1",
        abs(tracker120._onset_count - expected) <= 1,
        str(tracker120._onset_count),
    )

    tracker90, state90 = run_click(90)
    check("90 BPM 落在 ±4", abs(state90.bpm - 90) <= 4, str(state90))

    silent = BeatTracker()
    history = [0.0] * 48
    state = None
    for frame in range(120):
        state = silent.update(history, frame * 0.025)
    check("静音 3 秒没有起音", silent._onset_count == 0, str(silent._onset_count))
    check("静音脉冲归零", state.pulse < 0.02, str(state.pulse))

    noisy = BeatTracker()
    history = [0.0] * 48
    onsets = 0
    for frame in range(400):
        # 0.12 是持续底噪幅度；叠加 ±1% 的缓慢起伏模拟室内噪声。
        value = 0.12 + 0.01 * (0.5 + 0.5 * math.sin(frame * 0.2))
        history = history[1:] + [value]
        state = noisy.update(history, frame * 0.025)
    onset_count = noisy._onset_count
    check("噪声误报 ≤2 次/10 秒", onset_count <= 2, str(onset_count))
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
