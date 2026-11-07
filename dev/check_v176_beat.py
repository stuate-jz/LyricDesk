"""v1.7.6 拍点检测：120/90 BPM、静音、开关与噪声。"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lyricdesk.beat import BeatTracker


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

    print("全部通过" if not failures else f"{failures} 项失败")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
