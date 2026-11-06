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
_YRC_WORD = re.compile(r"\((\d+),(\d+),\d+\)")


def _normalize(text: str) -> str:
    value = unicodedata.normalize("NFKC", text or "").lower()
    return re.sub(r"[\s\-_·、,，.。!！?？'\"“”‘’()（）\[\]【】]", "", value)


def parse_lrc(text: str) -> list[LyricLine]:
    if not text:
        return []
    values: list[LyricLine] = []
    if text.lstrip().startswith("{"):
        for raw in text.splitlines():
            try:
                item = json.loads(raw)
            except Exception:
                continue
            if not isinstance(item, dict):
                continue
            timestamp = float(item.get("t") or 0.0) / 1000.0
            content = "".join(
                str(part.get("tx") or "")
                for part in item.get("c") or []
                if isinstance(part, dict)
            ).strip()
            if content:
                values.append(LyricLine(timestamp, 0.0, content))
    else:
        for raw in text.replace("\r", "\n").splitlines():
            stamps = list(_TIME_RE.finditer(raw))
            if not stamps:
                continue
            content = raw[stamps[-1].end():].strip()
            for stamp in stamps:
                minute = int(stamp.group(1))
                second = float(stamp.group(2).replace(":", "."))
                values.append(LyricLine(minute * 60 + second, 0.0, content))
    values.sort(key=lambda line: line.time)
    return values


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
        for index, marker in enumerate(markers):
            text_end = markers[index + 1].start() if index + 1 < len(markers) else len(body)
            content = body[marker.end():text_end]
            if content:
                words.append(
                    LyricWord(
                        time=int(marker.group(1)) / 1000.0,
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
    for index, detail in enumerate(yrc):
        if index not in used:
            lines.append(detail)
    lines.sort(key=lambda line: line.time)


def parse_payload(payload: dict, track_key: str = "") -> LyricDoc | None:
    lrc = str((payload.get("lrc") or {}).get("lyric") or "")
    yrc = str((payload.get("yrc") or {}).get("lyric") or "")
    lines = parse_lrc(lrc)
    detailed = parse_yrc(yrc)
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
