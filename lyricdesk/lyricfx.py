"""歌词动效基础：字素切分、字级时间轴和动画预算。"""

from __future__ import annotations

import unicodedata
import math
from collections import OrderedDict
from collections import Counter
from dataclasses import dataclass

from PySide6.QtGui import QFont, QFontMetricsF

MICRO_LINE = 0.10
SHORT_LINE = 0.18

_TIMELINE_CACHE: "OrderedDict[tuple, tuple[CharTiming, ...]]" = OrderedDict()
_TIMELINE_CACHE_LIMIT = 192
_CHORUS_CACHE: "OrderedDict[tuple, tuple[float, ...]]" = OrderedDict()
_CHORUS_CACHE_LIMIT = 4


@dataclass(frozen=True)
class CharTiming:
    char: str
    start: float
    end: float
    width: float = 0.0
    x: float = 0.0


@dataclass(frozen=True)
class Budget:
    klass: str
    enter: float
    exit: float
    reveal: str
    lookahead: float


@dataclass
class SpringState:
    value: float = 1.0
    velocity: float = 0.0
    target: float = 1.0
    alpha: float = 1.0
    alpha_target: float = 1.0
    mode: str = "waiting"


def _is_regional_indicator(char: str) -> bool:
    return "\U0001f1e6" <= char <= "\U0001f1ff"


def _joins_previous(char: str) -> bool:
    code = ord(char)
    return (
        unicodedata.combining(char) != 0
        or code in (0xFE0E, 0xFE0F, 0x20E3)
        or 0x1F3FB <= code <= 0x1F3FF
    )


def graphemes(text: str) -> list[str]:
    """按组合字符、ZWJ 序列和区域指示符对切分 Unicode 字素。"""
    result: list[str] = []
    join_next = False
    regional_open = False
    for char in text or "":
        if not result:
            result.append(char)
            regional_open = _is_regional_indicator(char)
            continue
        if char == "\u200d":
            result[-1] += char
            join_next = True
            regional_open = False
            continue
        if join_next or _joins_previous(char):
            result[-1] += char
            join_next = False
            continue
        if _is_regional_indicator(char) and regional_open:
            result[-1] += char
            regional_open = False
            continue
        result.append(char)
        regional_open = _is_regional_indicator(char)
        join_next = False
    return result


def _font(family: str, size: int, weight) -> QFont:
    from .render import letter_spacing

    font = QFont(family)
    font.setPixelSize(max(1, int(size)))
    if isinstance(weight, int):
        font.setWeight(QFont.Weight(weight))
    else:
        font.setWeight(weight)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, letter_spacing())
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return font


def _is_timing_punctuation(text: str) -> bool:
    return bool(text) and (
        text.isspace() or unicodedata.category(text[0]).startswith("P")
    )


def _make_timings(
    values: list[tuple[str, float, float, float]],
) -> tuple[CharTiming, ...]:
    """把 (字素, 起点, 终点, 宽度) 合成可见字素时间轴。

    标点和空格仍然占据宽度和时长，但并入前一个可见字素；行首标点并入
    第一个可见字素，避免出现没有文字的“空一拍”。
    """
    result: list[CharTiming] = []
    pending_prefix: list[tuple[str, float, float, float]] = []
    cursor_x = 0.0
    for char, start, end, width in values:
        if not char:
            continue
        if _is_timing_punctuation(char):
            if result:
                previous = result[-1]
                result[-1] = CharTiming(
                    previous.char,
                    previous.start,
                    max(previous.end, end),
                    previous.width + width,
                    previous.x,
                )
            else:
                pending_prefix.append((char, start, end, width))
            cursor_x += width
            continue
        if pending_prefix:
            first_start = pending_prefix[0][1]
            start = min(start, first_start)
            pending_prefix.clear()
        result.append(CharTiming(char, start, end, width, cursor_x))
        cursor_x += width
    return tuple(result)


def build_char_timeline(
    line,
    family: str,
    size: int,
    weight,
    max_width: float,
) -> list[CharTiming]:
    """把真实词时间展开成字素时间；没有逐字时按字宽占比分配。"""
    from .render import letter_spacing

    text = str(getattr(line, "text", "") or "")
    start = float(getattr(line, "time", 0.0) or 0.0)
    end = float(getattr(line, "end", 0.0) or 0.0)
    if end <= start:
        end = start + max(0.9, 0.185 * max(1, len(text)) + 0.4)
    words = list(getattr(line, "words", None) or [])
    word_key = tuple(
        (
            round(float(getattr(word, "time", 0.0) or 0.0), 3),
            round(float(getattr(word, "dur", 0.0) or 0.0), 3),
            str(getattr(word, "text", "") or ""),
        )
        for word in words
    )
    key = (
        round(start, 3),
        round(end, 3),
        text,
        family,
        int(size),
        int(weight),
        round(float(max_width), 2),
        round(letter_spacing(), 2),
        word_key,
    )
    cached = _TIMELINE_CACHE.get(key)
    if cached is not None:
        _TIMELINE_CACHE.move_to_end(key)
        return list(cached)

    font = _font(family, size, weight)
    metrics = QFontMetricsF(font)
    values: list[tuple[str, float, float, float]] = []
    if words:
        for word in words:
            chars = graphemes(str(getattr(word, "text", "") or ""))
            if not chars:
                continue
            word_start = float(getattr(word, "time", start))
            word_end = max(
                word_start + 0.001,
                word_start + float(getattr(word, "dur", 0.0) or 0.0),
            )
            span = (word_end - word_start) / len(chars)
            values.extend(
                (
                    char,
                    word_start + index * span,
                    word_start + (index + 1) * span,
                    max(0.01, metrics.horizontalAdvance(char)),
                )
                for index, char in enumerate(chars)
            )
    else:
        chars = graphemes(text)
        if chars:
            widths = [max(0.01, metrics.horizontalAdvance(char)) for char in chars]
            total = sum(widths)
            span = max(0.001, end - start)
            cursor = start
            for char, width in zip(chars, widths):
                duration = span * width / total
                values.append((char, cursor, cursor + duration, width))
                cursor += duration

    timings = _make_timings(values)
    _TIMELINE_CACHE[key] = timings
    if len(_TIMELINE_CACHE) > _TIMELINE_CACHE_LIMIT:
        _TIMELINE_CACHE.popitem(last=False)
    return list(timings)


def render_budget(duration: float) -> Budget:
    """根据行时长给出动画预算。"""
    duration = max(0.0, float(duration or 0.0))
    if duration < MICRO_LINE:
        return Budget("micro", 0.0, 0.0, "instant", 0.03)
    if duration < SHORT_LINE:
        return Budget("short", 0.055, 0.035, "fast", 0.08)
    return Budget(
        "normal",
        max(0.22, min(0.42, duration * 0.18)),
        max(0.18, min(0.32, duration * 0.15)),
        "normal",
        0.15,
    )


def spring_step(
    state: SpringState,
    dt: float,
    target: float,
    *,
    stiffness: float = 260.0,
    damping: float = 22.0,
) -> SpringState:
    """8ms 子步进的二阶弹簧积分，数值夹紧防止极端帧间隔爆炸。"""
    dt = max(0.0, min(0.08, float(dt)))
    state.target = target
    if dt <= 0.0:
        return state
    steps = max(1, int(math.ceil(dt / 0.008)))
    step = dt / steps
    for _ in range(steps):
        acceleration = stiffness * (target - state.value) - damping * state.velocity
        state.velocity += acceleration * step
        state.value += state.velocity * step
        state.value = max(1.0, min(1.35, state.value))
    state.alpha += (state.alpha_target - state.alpha) * min(1.0, dt * 18.0)
    return state


class WordSpring:
    """一行歌词内每个字素的 waiting / active / passed 弹簧状态。"""

    def __init__(self) -> None:
        self.states: dict[int, SpringState] = {}

    def reset(self) -> None:
        self.states.clear()

    def update(
        self,
        timings: list[CharTiming],
        position: float,
        budget: Budget,
        dt: float,
        active_target: float = 1.24,
    ) -> list[SpringState]:
        states: list[SpringState] = []
        for index, timing in enumerate(timings):
            state = self.states.setdefault(index, SpringState())
            if position < timing.start:
                mode = "waiting"
                target = 1.0
                alpha_target = 1.0
            elif position < timing.end:
                mode = "active"
                target = active_target
                alpha_target = 1.0
            else:
                mode = "passed"
                target = 1.0
                alpha_target = 0.84
            if mode != state.mode:
                state.mode = mode
                state.alpha_target = alpha_target
            spring_step(state, dt, target)
            states.append(state)
        return states


def reveal_state(
    timings: list[CharTiming],
    position: float,
    *,
    micro: bool = False,
    exit_duration: float = 0.32,
) -> tuple[float, float, float, float]:
    """返回（实心前沿、拖尾前沿、羽化像素、透明度）。

    位置在行开始前返回全零；行结束后由调用方结合 Budget.exit 淡出。
    """
    if not timings or position < timings[0].start:
        return 0.0, 0.0, 0.0, 0.0
    if micro:
        last = timings[-1]
        width = max(1.0, last.x + last.width)
        return 1.0, 1.0, 0.0, 1.0
    active = len(timings) - 1
    for index, timing in enumerate(timings):
        if position < timing.end:
            active = index
            break
    timing = timings[active]
    local = max(0.0, min(1.0, (position - timing.start) / max(0.001, timing.end - timing.start)))
    solid_x = timing.x + timing.width * local
    tail_index = min(len(timings) - 1, active + 4)
    tail = timings[tail_index]
    tail_x = tail.x + tail.width
    average = sum(item.width for item in timings) / max(1, len(timings))
    feather = max(3.0, average * 0.9)
    line_width = max(1.0, timings[-1].x + timings[-1].width)
    opacity = 1.0
    if position > timings[-1].end:
        opacity = max(
            0.0,
            1.0 - (position - timings[-1].end) / max(0.001, exit_duration),
        )
    return (
        max(0.0, min(1.0, solid_x / line_width)),
        max(0.0, min(1.0, tail_x / line_width)),
        feather,
        opacity,
    )


def clear_timeline_cache() -> None:
    _TIMELINE_CACHE.clear()


def _chorus_text(text: str) -> str:
    remove = set("，。！？、,.!?…～~　 \t\r\n")
    return "".join(char for char in str(text or "") if char not in remove)


def chorus_weights(lines) -> list[float]:
    """重复整句权重 1.0，前四个字相同权重 0.5；无明显副歌时全 0。"""
    values = list(lines or [])
    if not values:
        return []
    first = values[0]
    key = (
        len(values),
        round(float(getattr(first, "time", 0.0) or 0.0), 3),
        round(float(getattr(values[-1], "end", 0.0) or 0.0), 3),
        str(getattr(first, "text", "") or ""),
    )
    cached = _CHORUS_CACHE.get(key)
    if cached is not None:
        _CHORUS_CACHE.move_to_end(key)
        return list(cached)

    normalized = [_chorus_text(getattr(line, "text", "")) for line in values]
    counts = Counter(text for text in normalized if text)
    highest = max(counts.values(), default=0)
    if highest < 2 or highest / max(1, len(normalized)) < 0.05:
        result = [0.0] * len(normalized)
    else:
        prefixes = {
            text[:4]
            for text, count in counts.items()
            if len(text) >= 4 and count >= 2
        }
        result = []
        for text in normalized:
            if text and counts[text] >= 2:
                result.append(1.0)
            elif len(text) >= 4 and text[:4] in prefixes:
                result.append(0.5)
            else:
                result.append(0.0)
    frozen = tuple(result)
    _CHORUS_CACHE[key] = frozen
    if len(_CHORUS_CACHE) > _CHORUS_CACHE_LIMIT:
        _CHORUS_CACHE.popitem(last=False)
    return list(frozen)


def clear_chorus_cache() -> None:
    _CHORUS_CACHE.clear()
