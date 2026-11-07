"""低成本低频起音与节拍估计。"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

FRAME_SECONDS = 0.025
REFRACTORY = 0.12
DECAY = 0.82
MIN_BPM = 60.0
MAX_BPM = 180.0


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


@dataclass
class BeatState:
    pulse: float = 0.0
    bpm: float = 0.0
    confidence: float = 0.0
    onset: bool = False
    onset_count: int = 0


class BeatTracker:
    """在 UI 线程消费 48 帧低频历史，不创建线程。"""

    def __init__(self) -> None:
        self.pulse = 0.0
        self.bpm = 0.0
        self.confidence = 0.0
        self._last_onset = -10.0
        self._onsets: list[float] = []
        self._onset_count = 0
        self._last_bpm_calc = -10.0

    def update(self, low: list[float], now: float) -> BeatState:
        now = float(now)
        values = [max(0.0, float(value)) for value in low[-48:]]
        if len(values) >= 2:
            flux = [
                max(0.0, values[index] - values[index - 1])
                for index in range(1, len(values))
            ]
        else:
            flux = []

        self.pulse *= DECAY
        onset = False
        if flux:
            median = _median(flux)
            mad = _median([abs(value - median) for value in flux])
            peak = max(flux)
            # 稀疏频谱下 median/MAD 会退化成 0，必须再挂一个峰值相对门限。
            threshold = max(0.004, median + 1.5 * mad, 0.40 * peak)
            tail = flux[-3:]
            candidate = max(tail)
            candidate_index = len(tail) - 1 - tail[::-1].index(candidate)
            candidate_time = now - (len(tail) - 1 - candidate_index) * FRAME_SECONDS
            loud = max(values[-12:]) >= 0.15
            if (
                loud
                and candidate > threshold
                and now - self._last_onset >= REFRACTORY
            ):
                strength = min(1.0, max(0.0, candidate / threshold - 1.0))
                self.pulse = max(self.pulse, strength)
                self._last_onset = candidate_time
                self._onsets.append(candidate_time)
                self._onset_count += 1
                onset = True

        if now - self._last_onset > 0.6:
            self.pulse *= 0.9
        if now - self._last_onset > 2.0:
            self.pulse = 0.0
        self.pulse = max(0.0, min(1.0, self.pulse))

        if now - self._last_bpm_calc >= 1.0:
            self._last_bpm_calc = now
            self._recalculate_bpm()
        return BeatState(
            pulse=self.pulse,
            bpm=self.bpm,
            confidence=self.confidence,
            onset=onset,
            onset_count=self._onset_count,
        )

    def _recalculate_bpm(self) -> None:
        cutoff = (self._onsets[-1] if self._onsets else 0.0) - 20.0
        self._onsets = [value for value in self._onsets if value >= cutoff][-128:]
        bins: Counter[int] = Counter()
        for left, right in zip(self._onsets, self._onsets[1:]):
            interval = right - left
            if interval <= 0.001:
                continue
            bpm = 60.0 / interval
            while bpm < MIN_BPM:
                bpm *= 2.0
            while bpm > MAX_BPM:
                bpm /= 2.0
            if MIN_BPM <= bpm <= MAX_BPM:
                bins[int(round(bpm / 10.0)) * 10] += 1
        if not bins:
            self.bpm = 0.0
            self.confidence = 0.0
            return
        bucket, hits = bins.most_common(1)[0]
        total = sum(bins.values())
        confidence = hits / max(1, total)
        self.confidence = max(0.0, min(1.0, confidence))
        self.bpm = float(bucket) if self.confidence >= 0.30 else 0.0
