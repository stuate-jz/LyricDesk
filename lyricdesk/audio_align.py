"""实验性音频起音对齐：只校正估算字级，置信度低时保持 B2 时间轴。"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

from .lyricfx import CharTiming

FRAME_SECONDS = 0.025
MIN_FLUX = 0.018
REFRACTORY = 0.10


def detect_onsets(low: list[float], position: float) -> list[float]:
    """从 25ms 低频能量历史取局部极大值，并映射到歌曲播放时间。"""
    values = [max(0.0, float(value)) for value in low[-48:]]
    if len(values) < 4:
        return []
    flux = [
        max(0.0, values[index] - values[index - 1])
        for index in range(1, len(values))
    ]
    ordered = sorted(flux)
    median = statistics.median(ordered)
    mad = statistics.median(abs(value - median) for value in ordered)
    threshold = max(MIN_FLUX, median + 1.4 * mad, max(flux) * 0.42)
    onsets: list[float] = []
    for index, value in enumerate(flux):
        if value < threshold:
            continue
        if index > 0 and flux[index - 1] > value:
            continue
        if index + 1 < len(flux) and flux[index + 1] > value:
            continue
        frame_from_end = len(values) - 2 - index
        onset = float(position) - frame_from_end * FRAME_SECONDS
        if onsets and onset - onsets[-1] < REFRACTORY:
            continue
        onsets.append(max(0.0, onset))
    return onsets


def align_timings(
    timings: list[CharTiming],
    onsets: list[float],
    line_start: float,
    line_end: float,
) -> tuple[list[CharTiming], float]:
    """单调 DP 把起音点匹配到最可能的字头，返回新时间轴与置信度。"""
    if len(timings) < 2 or not onsets:
        return list(timings), 0.0
    usable = sorted(
        onset
        for onset in onsets
        if line_start - 0.12 <= onset <= line_end + 0.12
    )
    if not usable:
        return list(timings), 0.0
    spacing = statistics.median(
        max(0.02, timing.end - timing.start)
        for timing in timings
    )
    sigma = max(0.12, min(0.55, spacing * 1.80))
    scores = [
        [
            max(
                0.0,
                1.0 - abs(onset - timing.start) / sigma,
            )
            for onset in usable
        ]
        for timing in timings
    ]
    rows, cols = len(timings), len(usable)
    dp = [[0.0] * (cols + 1) for _ in range(rows + 1)]
    take = [[False] * (cols + 1) for _ in range(rows + 1)]
    for row in range(1, rows + 1):
        for col in range(1, cols + 1):
            best = max(dp[row - 1][col], dp[row][col - 1])
            # 每个正相关配对一个固定奖励，避免累计漂移时只匹配前半句。
            candidate = (
                dp[row - 1][col - 1]
                + 0.65
                + scores[row - 1][col - 1]
            )
            if scores[row - 1][col - 1] >= 0.05 and candidate > best:
                best = candidate
                take[row][col] = True
            dp[row][col] = best
    matched: list[tuple[int, float, float]] = []
    row, col = rows, cols
    while row > 0 and col > 0:
        if take[row][col]:
            matched.append((row - 1, usable[col - 1], scores[row - 1][col - 1]))
            row -= 1
            col -= 1
        elif dp[row - 1][col] >= dp[row][col - 1]:
            row -= 1
        else:
            col -= 1
    matched.reverse()
    if len(matched) < min(3, len(timings)):
        return list(timings), 0.0
    mean_score = sum(item[2] for item in matched) / len(matched)
    coverage = len(matched) / max(1, min(len(timings), len(usable)))
    confidence = mean_score * (0.55 + 0.45 * coverage)
    if confidence < 0.48:
        return list(timings), confidence

    anchors: list[tuple[int, float, bool]] = [(0, line_start, False)]
    anchors.extend((index, onset, True) for index, onset, _score in matched)
    anchors.append((len(timings), line_end, False))
    anchors.sort(key=lambda item: item[0])
    starts = [line_start] * len(timings)
    for (left_index, left_time, _), (right_index, right_time, _) in zip(
        anchors, anchors[1:]
    ):
        if right_index <= left_index:
            continue
        original = [
            timing.start for timing in timings[left_index:right_index]
        ]
        if not original:
            continue
        weight_total = max(
            0.001,
            (original[-1] - original[0]) if len(original) > 1 else right_time - left_time,
        )
        for offset, index in enumerate(range(left_index, right_index)):
            if index == left_index and left_time != line_start:
                starts[index] = left_time
                continue
            ratio = (
                0.0
                if len(original) == 1
                else (original[offset] - original[0]) / weight_total
            )
            starts[index] = left_time + (right_time - left_time) * ratio
    ends = starts[1:] + [line_end]
    adjusted = [
        CharTiming(
            timing.char,
            start,
            max(start + 0.001, end),
            timing.width,
            timing.x,
        )
        for timing, start, end in zip(timings, starts, ends)
    ]
    return adjusted, confidence


@dataclass
class _LineState:
    onsets: list[float]
    timings: list[CharTiming]
    confidence: float


class AudioOnsetAligner:
    """按行累积起音，不修改歌词文档本身，也不会污染时间轴缓存。"""

    def __init__(self) -> None:
        self._states: dict[tuple, _LineState] = {}

    def observe(
        self,
        line,
        timings: list[CharTiming],
        position: float,
        low: list[float],
    ) -> list[CharTiming]:
        if len(timings) < 2:
            return timings
        key = (
            round(float(line.time), 3),
            round(float(line.end), 3),
            str(line.text),
        )
        state = self._states.get(key)
        if state is None:
            state = _LineState([], list(timings), 0.0)
            self._states[key] = state
            if len(self._states) > 12:
                self._states.pop(next(iter(self._states)))
        for onset in detect_onsets(low, position):
            if float(line.time) - 0.12 <= onset <= float(line.end) + 0.12:
                if not any(abs(onset - old) < 0.07 for old in state.onsets):
                    state.onsets.append(onset)
        state.onsets.sort()
        adjusted, confidence = align_timings(
            timings,
            state.onsets,
            float(line.time),
            float(line.end),
        )
        if confidence >= 0.48:
            state.timings = adjusted
            state.confidence = confidence
        return list(state.timings)

