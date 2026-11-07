"""网易云官方歌词：songId、LRC/富文本 LRC、YRC、翻译与音译。"""

from __future__ import annotations

import difflib
import json
import re
import unicodedata

import requests

from ..lyricdoc import LyricDoc, LyricLine, LyricWord

LYRIC_URL = "https://music.163.com/api/song/lyric/v1"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/124 Safari/537.36"
    ),
    "Referer": "https://music.163.com/",
}
TIMEOUT = 10
_TIME_RE = re.compile(r"\[(\d+):(\d+(?:[.:]\d+)?)\]")
_YRC_LINE = re.compile(r"^\[(\d+),(\d+)\](.*)$")
_YRC_WORD = re.compile(r"[\(<](\d+),(\d+),\d+[\)>]")
_CREDIT_RE = re.compile(
    r"^\s*(?:"
    r"作词|作曲|编曲|演唱|原唱|制作人|制作|监制|出品人?|统筹|视觉|封面|策划|发行|词曲|词|曲|"
    r"录音(?:师|棚|室)?|混音(?:师|室)?|母带(?:师|室)?|和声|吉他|贝斯|鼓|键盘|弦乐|"
    r"lyrics?\s*(?:by|edit\w*)?|music\s*by|written\s*by|composed\s*by|arranged\s*by|"
    r"produced\s*by|mixed\s*by|mastered\s*by|vocal\s*(?:edit\w*|by)?|"
    r"lyricist|composer|arranger|producer|mixing|mastering|recording|label"
    r")\s*[:：]",
    re.IGNORECASE,
)
_BRACKET_ONLY = re.compile(r"^[\[【(（].*[\]】)）]$")
_COLON_LABEL = re.compile(r"^.{0,20}?[:：]")
_CREDIT_HEAD_RE = re.compile(
    r"^\s*(?:版权|录音制品|音乐制作|制作公司|发行公司|出品公司|"
    r"OP|SP|©|℗)",
    re.IGNORECASE,
)
_CREDIT_WINDOW = 30.0


def _normalize(text: str) -> str:
    value = unicodedata.normalize("NFKC", text or "").lower()
    return re.sub(r"[\s\-_·、,，.。!！?？'\"“”‘’()（）\[\]【】]", "", value)


def _parse_json_lrc(text: str) -> list[LyricLine]:
    values: list[LyricLine] = []
    for raw in text.splitlines():
        try:
            item = json.loads(raw)
        except Exception:
            continue
        if not isinstance(item, dict):
            continue
        timestamp = max(0.0, float(item.get("t") or 0.0) / 1000.0)
        content = "".join(
            str(part.get("tx") or "")
            for part in item.get("c") or []
            if isinstance(part, dict)
        ).strip()
        if content:
            values.append(LyricLine(timestamp, 0.0, content))
    return values


def _parse_text_lrc(text: str) -> list[LyricLine]:
    values: list[LyricLine] = []
    for raw in text.replace("\r", "\n").splitlines():
        stamps = list(_TIME_RE.finditer(raw))
        if not stamps:
            continue
        content = raw[stamps[-1].end():].strip()
        for stamp in stamps:
            minute = int(stamp.group(1))
            second = float(stamp.group(2).replace(":", "."))
            values.append(LyricLine(minute * 60 + second, 0.0, content))
    return values


def _clean_lrc_lines(values: list[LyricLine]) -> list[LyricLine]:
    cleaned: list[LyricLine] = []
    seen: set[tuple[int, str]] = set()
    for line in sorted(values, key=lambda item: item.time):
        text = line.text.strip()
        if not text:
            continue
        key = (round(line.time * 1000), _normalize(text))
        if key in seen:
            continue
        if line.time < _CREDIT_WINDOW and (
            _CREDIT_RE.match(text)
            or _CREDIT_HEAD_RE.match(text)
            or _BRACKET_ONLY.match(text)
            or (len(text) <= 48 and _COLON_LABEL.match(text))
        ):
            continue
        seen.add(key)
        cleaned.append(
            LyricLine(
                time=line.time,
                end=line.end,
                text=text,
                words=list(line.words),
                trans=line.trans,
                roma=line.roma,
            )
        )
    return cleaned


def parse_lrc(text: str) -> list[LyricLine]:
    if not text:
        return []
    # 网易云部分曲目把 JSON 制作信息和普通 [mm:ss] 歌词混在同一个字段里。
    # 两种格式必须一起解析，不能因为首字符是 "{" 就把后面的正文全部丢掉。
    values = _parse_json_lrc(text) + _parse_text_lrc(text)
    return _clean_lrc_lines(values)


def parse_yrc(text: str) -> list[LyricLine]:
    values: list[LyricLine] = []
    for raw in text.splitlines():
        match = _YRC_LINE.match(raw.strip())
        if not match:
            continue
        start_ms, duration_ms = int(match.group(1)), int(match.group(2))
        body = match.group(3)
        markers = list(_YRC_WORD.finditer(body))
        words: list[LyricWord] = []
        relative_offsets = bool(
            markers and int(markers[0].group(1)) < max(1, start_ms // 2)
        )
        for index, marker in enumerate(markers):
            text_end = markers[index + 1].start() if index + 1 < len(markers) else len(body)
            content = body[marker.end():text_end]
            if content:
                offset_ms = int(marker.group(1))
                word_time = offset_ms if not relative_offsets else start_ms + offset_ms
                words.append(
                    LyricWord(
                        time=word_time / 1000.0,
                        dur=int(marker.group(2)) / 1000.0,
                        text=content,
                    )
                )
        if words:
            values.append(
                LyricLine(
                    time=start_ms / 1000.0,
                    end=(start_ms + max(duration_ms, 1)) / 1000.0,
                    text="".join(word.text for word in words),
                    words=words,
                )
            )
    return values


def parse_krc(text: str) -> list[LyricLine]:
    """解析网易云 KRC 家族的 klyric；字偏移相对行首。"""
    return parse_yrc(text)


def _merge_timed_track(lines: list[LyricLine], raw: str, field: str) -> None:
    track = parse_lrc(raw)
    if not track:
        return
    by_ms = {round(line.time * 1000): line.text for line in track}
    for line in lines:
        value = by_ms.get(round(line.time * 1000))
        if value:
            setattr(line, field, value)


def _merge_yrc(lines: list[LyricLine], yrc: list[LyricLine]) -> None:
    if not yrc:
        return
    used: set[int] = set()
    for line in lines:
        best_index = -1
        best_score = 0.0
        for index, detail in enumerate(yrc):
            if index in used:
                continue
            if abs(line.time - detail.time) > 0.3:
                continue
            text_score = difflib.SequenceMatcher(
                None, _normalize(line.text), _normalize(detail.text)
            ).ratio()
            time_score = max(0.0, 1.0 - abs(line.time - detail.time) / 3.0)
            score = text_score * 0.75 + time_score * 0.25
            if score > best_score:
                best_score, best_index = score, index
        if best_index >= 0 and best_score >= 0.58:
            used.add(best_index)
            line.words = yrc[best_index].words
            if line.words:
                line.words[0].time = line.time
def parse_payload(payload: dict, track_key: str = "") -> LyricDoc | None:
    lrc = str((payload.get("lrc") or {}).get("lyric") or "")
    yrc = str((payload.get("yrc") or {}).get("lyric") or "")
    klyric = str((payload.get("klyric") or {}).get("lyric") or "")
    lines = parse_lrc(lrc)
    detailed = _clean_lrc_lines(parse_yrc(yrc) or parse_krc(klyric))
    if not lines and detailed:
        lines = detailed
    if not lines:
        return None
    _merge_yrc(lines, detailed)
    _merge_timed_track(lines, str((payload.get("tlyric") or {}).get("lyric") or ""), "trans")
    _merge_timed_track(lines, str((payload.get("romalrc") or {}).get("lyric") or ""), "roma")
    tail = lines[-1].time + 6.0
    for index, line in enumerate(lines):
        if line.end <= line.time:
            line.end = lines[index + 1].time if index + 1 < len(lines) else tail
    return LyricDoc(
        lines=lines,
        source="网易云官方",
        provider="netease",
        track_key=track_key,
        has_words=any(line.words for line in lines),
    )


def fetch_doc(
    song_id: int | str,
    track_key: str = "",
) -> LyricDoc | None:
    if not song_id:
        return None
    try:
        response = requests.get(
            LYRIC_URL,
            params={
                "id": song_id,
                "cp": "false",
                "tv": 0,
                "lv": 0,
                "rv": 0,
                "kv": 0,
                "yv": 1,
                "ytv": 0,
                "yrv": 0,
            },
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        return parse_payload(response.json(), track_key)
    except Exception:
        return None
