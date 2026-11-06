"""酷狗 KRC 逐字歌词：公开搜索、下载、解密与解析。"""

from __future__ import annotations

import base64
import difflib
import json
import re
import unicodedata
import zlib

import requests

from ..lyricdoc import LyricDoc, LyricLine, LyricWord

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/124 Safari/537.36"
    )
}
CATALOG_URL = "http://mobilecdn.kugou.com/api/v3/search/song"
SEARCH_URL = "https://krcs.kugou.com/search"
DOWNLOAD_URL = "https://lyrics.kugou.com/download"
TIMEOUT = 10

XOR_KEY = bytes(
    [
        0x40, 0x47, 0x61, 0x77, 0x5E, 0x32, 0x74, 0x47,
        0x51, 0x36, 0x31, 0x2D, 0xCE, 0xD2, 0x6E, 0x69,
    ]
)
LINE_RE = re.compile(r"^\[(\d+),(\d+)\](.*)$")
WORD_RE = re.compile(r"<(\d+),(\d+),\d+>")
LANG_RE = re.compile(r"\[language:([^\]]+)\]")


def _normalize(text: str) -> str:
    value = unicodedata.normalize("NFKC", text or "").lower()
    return re.sub(r"[\s\-_·、,，.。!！?？'\"“”‘’()（）\[\]【】]", "", value)


def _similar(a: str, b: str) -> float:
    left, right = _normalize(a), _normalize(b)
    if not left or not right:
        return 0.0
    return difflib.SequenceMatcher(None, left, right).ratio()


def _artist_matches(candidate: str, wanted: str) -> bool:
    target = _normalize(wanted)
    if not target:
        return True
    parts = re.split(r"[/、,，&]|feat\.?|ft\.?", candidate or "", flags=re.I)
    return any(_normalize(part) == target for part in parts) or _similar(candidate, wanted) >= 0.75


def _catalog(title: str, artist: str, duration: float) -> dict | None:
    query = f"{title} {artist}".strip()
    response = requests.get(
        CATALOG_URL,
        params={"format": "json", "keyword": query, "page": 1, "pagesize": 10},
        headers=UA,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    items = ((response.json().get("data") or {}).get("info")) or []
    ranked: list[tuple[float, dict]] = []
    for item in items:
        name = str(item.get("songname") or "")
        singer = str(item.get("singername") or "")
        item_duration = float(item.get("duration") or 0.0)
        if not item.get("hash"):
            continue
        name_score = _similar(name, title)
        if name_score < 0.88 or not _artist_matches(singer, artist):
            continue
        delta = abs(item_duration - duration) if duration > 0 and item_duration > 0 else 0.0
        if duration > 0 and item_duration > 0 and delta > 8.0:
            continue
        score = name_score * 0.7 + max(0.0, 1.0 - delta / 15.0) * 0.3
        ranked.append((score, item))
    ranked.sort(key=lambda item: -item[0])
    return ranked[0][1] if ranked else None


def _krc_candidate(hash_value: str, duration_ms: int, keyword: str) -> dict | None:
    response = requests.get(
        SEARCH_URL,
        params={
            "ver": 1,
            "man": "yes",
            "client": "mobi",
            "keyword": keyword,
            "duration": max(0, int(duration_ms)),
            "hash": hash_value,
        },
        headers=UA,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    candidates = payload.get("candidates") or []
    if not candidates:
        return None
    proposal = str(payload.get("proposal") or "")
    if proposal:
        for item in candidates:
            if str(item.get("id") or "") == proposal:
                return item
    return candidates[0]


def _download(candidate: dict) -> str | None:
    response = requests.get(
        DOWNLOAD_URL,
        params={
            "ver": 1,
            "client": "pc",
            "id": candidate.get("id"),
            "accesskey": candidate.get("accesskey"),
            "fmt": "krc",
            "charset": "utf8",
        },
        headers=UA,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    content = response.json().get("content") or ""
    if not content:
        return None
    raw = base64.b64decode(content)
    if not raw.startswith(b"krc1"):
        return None
    body = bytes(value ^ XOR_KEY[index % 16] for index, value in enumerate(raw[4:]))
    return zlib.decompress(body).decode("utf-8", "replace")


def _language_tracks(text: str) -> tuple[list[str], list[str]]:
    translated: list[str] = []
    romanized: list[str] = []
    match = LANG_RE.search(text)
    if not match:
        return translated, romanized
    try:
        payload = json.loads(base64.b64decode(match.group(1)).decode("utf-8", "replace"))
    except Exception:
        return translated, romanized
    for track in payload.get("content") or []:
        if not isinstance(track, dict):
            continue
        rows = track.get("lyricContent") or []
        values = [
            "".join(str(part) for part in row).strip()
            if isinstance(row, list)
            else ""
            for row in rows
        ]
        if track.get("type") == 1:
            translated = values
        elif track.get("type") == 0:
            romanized = values
    return translated, romanized


def parse_krc(text: str, track_key: str = "") -> LyricDoc | None:
    if not text:
        return None
    translated, romanized = _language_tracks(text)
    parsed: list[tuple[int, int, list[tuple[int, int, str]]]] = []
    for raw in text.splitlines():
        match = LINE_RE.match(raw.strip())
        if not match:
            continue
        start_ms, duration_ms = int(match.group(1)), int(match.group(2))
        body = match.group(3)
        markers = list(WORD_RE.finditer(body))
        words: list[tuple[int, int, str]] = []
        for index, marker in enumerate(markers):
            text_end = markers[index + 1].start() if index + 1 < len(markers) else len(body)
            word_text = body[marker.end():text_end]
            if word_text:
                words.append(
                    (
                        int(marker.group(1)),
                        int(marker.group(2)),
                        word_text,
                    )
                )
        if words:
            parsed.append((start_ms, duration_ms, words))
    if not parsed:
        return None
    parsed.sort(key=lambda item: item[0])

    lines: list[LyricLine] = []
    for index, (start_ms, duration_ms, raw_words) in enumerate(parsed):
        end_ms = (
            parsed[index + 1][0]
            if index + 1 < len(parsed)
            else start_ms + max(duration_ms, 1)
        )
        if end_ms <= start_ms:
            end_ms = start_ms + max(duration_ms, 1000)
        words = [
            LyricWord(
                time=(start_ms + offset_ms) / 1000.0,
                dur=max(0.01, dur_ms / 1000.0),
                text=text_value,
            )
            for offset_ms, dur_ms, text_value in raw_words
        ]
        full_text = "".join(word.text for word in words).strip()
        if not full_text:
            continue
        lines.append(
            LyricLine(
                time=start_ms / 1000.0,
                end=end_ms / 1000.0,
                text=full_text,
                words=words,
                trans=translated[index] if index < len(translated) else "",
                roma=romanized[index] if index < len(romanized) else "",
            )
        )
    return LyricDoc(
        lines=lines,
        source="酷狗KRC",
        provider="kugou",
        track_key=track_key,
        has_words=True,
    )


def fetch_doc(
    title: str,
    artist: str,
    duration: float,
    track_key: str = "",
) -> LyricDoc | None:
    """按严格歌名/歌手/时长匹配酷狗 KRC。失败静默返回 None。"""
    try:
        catalog = _catalog(title, artist, duration)
        if catalog is None:
            return None
        keyword = f"{catalog.get('songname') or title} - {catalog.get('singername') or artist}"
        candidate = _krc_candidate(
            str(catalog.get("hash") or ""),
            int(float(catalog.get("duration") or duration) * 1000),
            keyword,
        )
        if candidate is None:
            return None
        text = _download(candidate)
        return parse_krc(text or "", track_key=track_key)
    except Exception:
        return None
