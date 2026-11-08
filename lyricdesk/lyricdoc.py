"""统一的歌词文档模型：行级 LRC 与逐字歌词共用同一结构。"""

from __future__ import annotations

import re
import statistics
import unicodedata
from dataclasses import dataclass, field


@dataclass
class LyricWord:
    time: float
    dur: float
    text: str
    estimated: bool = False


@dataclass
class LyricLine:
    time: float
    end: float
    text: str
    words: list[LyricWord] = field(default_factory=list)
    trans: str = ""
    roma: str = ""

    @property
    def is_gap(self) -> bool:
        return not self.text.strip()

    @property
    def has_real_words(self) -> bool:
        return any(word.text and not word.estimated for word in self.words)


@dataclass
class LyricDoc:
    lines: list[LyricLine]
    source: str
    provider: str
    track_key: str
    has_words: bool = False

    def __post_init__(self) -> None:
        self.has_words = any(line.words for line in self.lines)

    @property
    def real_word_lines(self) -> int:
        return sum(1 for line in self.lines if line.has_real_words)

    @property
    def has_real_words(self) -> bool:
        return self.real_word_lines > 0

    def index_at(self, position: float) -> int:
        if not self.lines:
            return -1
        if position < self.lines[0].time:
            return -1
        low, high = 0, len(self.lines) - 1
        while low < high:
            middle = (low + high + 1) // 2
            if self.lines[middle].time <= position:
                low = middle
            else:
                high = middle - 1
        return low


_INLINE_TIME = re.compile(r"<(\d{1,3}):(\d{1,2}(?:[.:]\d{1,3})?)>")
_PUNCTUATION = set("，。！？、,.!?;:：；…")


def parse_inline_words(
    content: str,
    fallback_start: float,
) -> tuple[str, list[LyricWord]]:
    """解析增强 LRC 的 <mm:ss.xx> 行内标签。"""
    markers = list(_INLINE_TIME.finditer(content or ""))
    display = _INLINE_TIME.sub("", content or "").strip()
    if not markers:
        return display, []
    values: list[LyricWord] = []
    prefix = content[: markers[0].start()]
    if prefix.strip():
        values.append(
            LyricWord(
                time=float(fallback_start),
                dur=max(0.01, _inline_seconds(markers[0]) - fallback_start),
                text=prefix,
            )
        )
    for index, marker in enumerate(markers):
        end_pos = markers[index + 1].start() if index + 1 < len(markers) else len(content)
        text = content[marker.end():end_pos]
        if not text:
            continue
        start = _inline_seconds(marker)
        end = _inline_seconds(markers[index + 1]) if index + 1 < len(markers) else start
        values.append(
            LyricWord(
                time=start,
                dur=max(0.0, end - start),
                text=text,
            )
        )
    return display, values


def _inline_seconds(match: re.Match[str]) -> float:
    return int(match.group(1)) * 60.0 + float(match.group(2).replace(":", "."))


def estimate_lrc_words(lines: list[LyricLine]) -> None:
    """为纯 LRC 行补字级时间；已有字级的行保持原样。"""
    from .lyricfx import graphemes

    timed_units: list[float] = []
    for line in lines:
        for word in line.words:
            if not word.text or word.dur <= 0:
                continue
            weight = sum(
                1.8 if char in _PUNCTUATION else 1.0
                for char in graphemes(word.text)
            )
            if weight > 0:
                timed_units.append(word.dur / weight)
    unit = statistics.median(timed_units) if timed_units else 0.20
    unit = max(0.05, min(1.0, float(unit)))

    for line in lines:
        if line.words or not line.text.strip():
            continue
        chars = graphemes(line.text)
        if not chars:
            continue
        weights = [
            1.8 if char in _PUNCTUATION else 1.0
            for char in chars
        ]
        total_weight = sum(weights)
        line_duration = max(0.35, float(line.end) - float(line.time))
        sung = min(line_duration, max(0.35, total_weight * unit))
        cursor = float(line.time)
        for char, weight in zip(chars, weights):
            duration = sung * weight / max(0.01, total_weight)
            line.words.append(
                LyricWord(
                    time=cursor,
                    dur=duration,
                    text=char,
                    estimated=True,
                )
            )
            cursor += duration


def validate(doc: LyricDoc, duration: float) -> tuple[bool, list[str]]:
    """按 v1.7.0 的五条规则校验；返回 (是否通过, 失败原因)。"""
    errors: list[str] = []
    lines = doc.lines
    if len([line for line in lines if line.text.strip()]) < 8:
        errors.append("出现歌词的行数少于 8")

    if duration > 15.0 and lines:
        coverage = lines[-1].time / duration
        if coverage < 0.6:
            errors.append(f"歌词覆盖率过低：{coverage:.0%}")
        if coverage > 1.25:
            errors.append(f"歌词比整首歌长出 {coverage:.0%}")

    previous = -1.0
    for line in lines:
        if line.time + 0.001 < previous:
            errors.append("时间轴不是递增的")
            break
        previous = line.time

    for line in lines:
        if line.words and abs(line.words[0].time - line.time) > 0.031:
            errors.append(f"行 {line.time:.2f}s 的首字时间与行首不一致")
            break

    if duration > 0:
        for line in lines:
            if line.end - line.time > duration + 0.05:
                errors.append(f"行 {line.time:.2f}s 的时长超过整曲")
                break
            if line.words:
                word_end = max((word.time + word.dur for word in line.words), default=line.time)
                if word_end - line.time > duration + 0.05:
                    errors.append(f"行 {line.time:.2f}s 的逐字时间超过整曲")
                    break
    return not errors, errors
