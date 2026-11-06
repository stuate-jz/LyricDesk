"""统一的歌词文档模型：行级 LRC 与逐字歌词共用同一结构。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LyricWord:
    time: float
    dur: float
    text: str


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


@dataclass
class LyricDoc:
    lines: list[LyricLine]
    source: str
    provider: str
    track_key: str
    has_words: bool = False

    def __post_init__(self) -> None:
        self.has_words = any(line.words for line in self.lines)

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
