"""AMLL TTML DB 歌词源：严格匹配、索引缓存与多镜像回退。"""

from __future__ import annotations

import json
import re
import threading
import time
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

from .config import cache_dir
from .lyricdoc import LyricDoc, LyricLine, LyricWord

TIMEOUT = 12.0
INDEX_TTL = 7 * 24 * 3600.0
INDEX_URLS = {
    "ncm": (
        "https://raw.githubusercontent.com/amll-dev/amll-ttml-db/"
        "refs/heads/main/ncm-lyrics/index.jsonl",
        "https://raw.gitmirror.com/amll-dev/amll-ttml-db/"
        "refs/heads/main/ncm-lyrics/index.jsonl",
    ),
    "qq": (
        "https://raw.githubusercontent.com/amll-dev/amll-ttml-db/"
        "refs/heads/main/qq-lyrics/index.jsonl",
        "https://raw.gitmirror.com/amll-dev/amll-ttml-db/"
        "refs/heads/main/qq-lyrics/index.jsonl",
    ),
}
_RAW_BASE = {
    "ncm": (
        "https://raw.githubusercontent.com/amll-dev/amll-ttml-db/"
        "refs/heads/main/ncm-lyrics/{id}.{suffix}"
    ),
    "qq": (
        "https://raw.githubusercontent.com/amll-dev/amll-ttml-db/"
        "refs/heads/main/qq-lyrics/{id}.{suffix}"
    ),
}
_GITMIRROR_BASE = {
    "ncm": (
        "https://raw.gitmirror.com/amll-dev/amll-ttml-db/"
        "refs/heads/main/ncm-lyrics/{id}.{suffix}"
    ),
    "qq": (
        "https://raw.gitmirror.com/amll-dev/amll-ttml-db/"
        "refs/heads/main/qq-lyrics/{id}.{suffix}"
    ),
}
_MIRROR_URLS = {
    "ncm": (
        "https://amll-ttml-db.stevexmh.net/ncm/{id}",
        "https://amlldb.bikonoo.com/ncm-lyrics/{id}.ttml",
        "https://amll.mirror.dimeta.top/api/db/ncm-lyrics/{id}.ttml",
    ),
    "qq": (
        "https://amll-ttml-db.stevexmh.net/qq/{id}",
        "https://amlldb.bikonoo.com/qq-lyrics/{id}.ttml",
        "https://amll.mirror.dimeta.top/api/db/qq-lyrics/{id}.ttml",
    ),
}
_INDEX_LOCK = threading.Lock()
_MATCH_LOCK = threading.Lock()
_TITLE_BRACKETS = re.compile(
    r"\([^)]*\)|（[^）]*）|\[[^\]]*\]|【[^】]*】"
)
_TTML_TIME = re.compile(
    r"(?:(\d+):)?(\d{1,2}):(\d{1,2}(?:\.\d+)?)"
)
_LYRIC_SUFFIXES = ("yrc", "qrc", "ttml", "lys")


def normalize_title(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").lower()
    text = _TITLE_BRACKETS.sub("", text)
    return re.sub(
        r"[\s\-_·、,，.。!！?？'\"“”‘’()（）\[\]【】]",
        "",
        text,
    )


def normalize_artist(value: str) -> set[str]:
    text = unicodedata.normalize("NFKC", value or "").lower()
    # 索引里有「郭采洁(Amber Kuo)」「周杰伦 / Jay Chou」等别名写法；
    # 去掉括号别名后仍要求至少一个主艺名完全相等。
    text = _TITLE_BRACKETS.sub("", text)
    parts = re.split(r"[/、,，&]|\bfeat\.?\b|\bft\.?\b", text)
    return {
        re.sub(r"[\s.。·_\-'\"“”‘’]+", "", part)
        for part in parts
        if re.sub(r"[\s.。·_\-'\"“”‘’]+", "", part)
    }


def _index_path(platform: str) -> Path:
    return cache_dir() / f"amll-{platform}-index.jsonl"


def _match_cache_path(platform: str) -> Path:
    return cache_dir() / f"amll-{platform}-matches.json"


def _download(urls, target: Path) -> bool:
    headers = {"User-Agent": "LyricDesk/1.7.10"}
    for url in urls:
        try:
            response = requests.get(url, headers=headers, timeout=TIMEOUT)
            if response.status_code == 200 and response.content:
                if target.name.endswith(".jsonl") and b"{" not in response.content:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                temp = target.with_suffix(target.suffix + ".part")
                temp.write_bytes(response.content)
                temp.replace(target)
                return True
        except Exception:
            continue
    return False


def ensure_index(platform: str) -> Path | None:
    platform = platform if platform in INDEX_URLS else "ncm"
    path = _index_path(platform)
    with _INDEX_LOCK:
        if path.exists() and time.time() - path.stat().st_mtime < INDEX_TTL:
            return path
        if _download(INDEX_URLS[platform], path):
            return path
    # 下载失败时，过期缓存仍比“完全没有索引”可靠。
    return path if path.exists() else None


def _load_match_cache(platform: str) -> dict[str, str]:
    path = _match_cache_path(platform)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in data.items()}
    except Exception:
        return {}


def _save_match_cache(platform: str, values: dict[str, str]) -> None:
    try:
        path = _match_cache_path(platform)
        temp = path.with_suffix(path.suffix + ".part")
        temp.write_text(
            json.dumps(values, ensure_ascii=False),
            encoding="utf-8",
        )
        temp.replace(path)
    except Exception:
        pass


def _metadata(item: dict, key: str) -> list[str]:
    for pair in item.get("metadata") or []:
        if (
            isinstance(pair, (list, tuple))
            and len(pair) == 2
            and str(pair[0]) == key
        ):
            values = pair[1]
            if isinstance(values, str):
                return [values]
            if isinstance(values, (list, tuple)):
                return [str(value) for value in values]
    return []


def find_song(
    title: str,
    artist: str,
    platform: str = "ncm",
) -> tuple[str, float] | None:
    """标题必须完全相等，且至少一位歌手相等；否则拒绝匹配。"""
    platform = platform if platform in INDEX_URLS else "ncm"
    wanted_title = normalize_title(title)
    wanted_artists = normalize_artist(artist)
    if not wanted_title or not wanted_artists:
        return None
    key = f"{wanted_title}|{'/'.join(sorted(wanted_artists))}"
    with _MATCH_LOCK:
        cached = _load_match_cache(platform)
        if key in cached:
            return cached[key], 1.0
        index = ensure_index(platform)
        if index is None:
            return None
        best: tuple[float, str] | None = None
        try:
            with index.open("r", encoding="utf-8-sig", errors="replace") as handle:
                for raw in handle:
                    try:
                        item = json.loads(raw)
                    except Exception:
                        continue
                    names = _metadata(item, "musicName")
                    if not any(
                        normalize_title(name) == wanted_title
                        for name in names
                    ):
                        continue
                    candidate_artists = set()
                    for name in _metadata(item, "artists"):
                        candidate_artists.update(normalize_artist(name))
                    overlap = len(wanted_artists.intersection(candidate_artists))
                    song_id = str(item.get("id") or "").strip()
                    if not song_id or overlap <= 0:
                        continue
                    score = 1.0 + min(0.5, overlap * 0.1)
                    if best is None or score > best[0]:
                        best = (score, song_id)
        except Exception:
            return None
        if best is not None:
            cached[key] = best[1]
            _save_match_cache(platform, cached)
            return best[1], best[0]
    return None


def _cached_lyric(platform: str, song_id: str) -> Path | None:
    for suffix in _LYRIC_SUFFIXES:
        path = cache_dir() / f"amll-{platform}-{song_id}.{suffix}"
        if path.exists() and path.stat().st_size > 0:
            return path
    return None


def _decode(response: requests.Response) -> str:
    # GitHub raw 的 text/plain 常常没有 charset；requests.text 会按 latin-1
    # 解码，导致中文 TTML 变成乱码。歌词库固定是 UTF-8。
    return response.content.decode("utf-8-sig", errors="replace").strip()


def _sniff_kind(text: str) -> str:
    lowered = text.lstrip("\ufeff \t\r\n").lower()
    if lowered.startswith("<tt") or "<tt " in lowered[:600]:
        return "ttml"
    if re.match(r"^\[\d+(?:\.\d+)?\]", lowered):
        return "lys"
    if re.match(r"^\[\d+,\d+\]", lowered):
        return "yrc" if re.search(r"[\(<]\d+,\d+,\d+[\)>]", text) else "qrc"
    if re.match(r"^\[\d{1,3}:\d{1,2}", lowered):
        return "lrc"
    return ""


def _candidate_urls(platform: str, song_id: str):
    for writable in (
        _RAW_BASE.get(platform),
        _GITMIRROR_BASE.get(platform),
    ):
        if not writable:
            continue
        for suffix in ("yrc", "qrc", "ttml"):
            yield writable.format(id=song_id, suffix=suffix)
    for template in _MIRROR_URLS.get(platform, ()):
        yield template.format(id=song_id)


def _fetch_raw(platform: str, song_id: str) -> tuple[str, str] | None:
    cached = _cached_lyric(platform, song_id)
    if cached is not None:
        return (
            cached.read_text(encoding="utf-8-sig", errors="replace"),
            cached.suffix[1:],
        )
    seen: set[str] = set()
    for url in _candidate_urls(platform, song_id):
        if url in seen:
            continue
        seen.add(url)
        try:
            response = requests.get(
                url,
                headers={"User-Agent": "LyricDesk/1.7.10"},
                timeout=TIMEOUT,
            )
            if response.status_code != 200 or not response.content:
                continue
            text = _decode(response)
            kind = _sniff_kind(text)
            if kind not in _LYRIC_SUFFIXES:
                continue
            target = cache_dir() / f"amll-{platform}-{song_id}.{kind}"
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_suffix(target.suffix + ".part")
            temp.write_text(text, encoding="utf-8")
            temp.replace(target)
            return text, kind
        except Exception:
            continue
    return None


def _timestamp(value: str) -> float:
    match = _TTML_TIME.fullmatch((value or "").strip())
    if not match:
        return 0.0
    hours = int(match.group(1) or 0)
    return hours * 3600 + int(match.group(2)) * 60 + float(match.group(3))


def _ttml_role(node: ET.Element) -> str:
    for key, value in node.attrib.items():
        if key.rsplit("}", 1)[-1] == "role":
            return value.lower()
    return ""


def parse_ttml(text: str) -> list[LyricLine]:
    try:
        root = ET.fromstring(text.encode("utf-8"))
    except Exception:
        return []
    lines: list[LyricLine] = []
    for paragraph in root.iter():
        if not paragraph.tag.lower().endswith("p"):
            continue
        begin = paragraph.attrib.get("begin", "00:00.000")
        end = paragraph.attrib.get("end", begin)
        words: list[LyricWord] = []
        translation: list[str] = []
        for span in paragraph.iter():
            if span is paragraph or not span.tag.lower().endswith("span"):
                continue
            role = _ttml_role(span)
            role_name = role.rsplit(":", 1)[-1]
            if role_name in ("x-translation", "translation"):
                content = "".join(span.itertext()).strip()
                if content:
                    translation.append(content)
                continue
            if role_name.startswith("x-") and role_name not in ("x-bg",):
                continue
            # 背景人声的父 span 也有时间，但它包含子 span。只取叶节点，
            # 避免同一个字被父、子各记一次。
            if any(child.tag.lower().endswith("span") for child in list(span)):
                continue
            content = "".join(span.itertext())
            if not content:
                continue
            start = _timestamp(span.attrib.get("begin", begin))
            finish = _timestamp(span.attrib.get("end", end))
            words.append(
                LyricWord(
                    time=start,
                    dur=max(0.01, finish - start),
                    text=content,
                )
            )
        display = "".join(word.text for word in words).strip()
        if not display:
            # 没有逐字 span 时仍保留 TTML 行级文本。
            display = "".join(paragraph.itertext()).strip()
        if not display:
            continue
        start = _timestamp(begin)
        finish = max(start + 0.01, _timestamp(end))
        lines.append(
            LyricLine(
                time=start,
                end=finish,
                text=display,
                words=words,
                trans=" / ".join(translation),
            )
        )
    return sorted(lines, key=lambda item: item.time)


def parse_lys(text: str) -> list[LyricLine]:
    """解析 AMLL / Lyricify Syllable 的最小公共子集。"""
    marker = re.compile(r"\((\d+),(\d+)(?:,\d+)?\)")
    lines: list[LyricLine] = []
    for raw in text.splitlines():
        match = re.match(r"^\[(\d+)\](.*)$", raw.strip())
        if not match:
            continue
        line_ms = int(match.group(1))
        body = match.group(2)
        found = list(marker.finditer(body))
        words: list[LyricWord] = []
        previous = 0
        for item in found:
            content = body[previous:item.start()]
            previous = item.end()
            if content:
                start_ms = int(item.group(1))
                duration_ms = int(item.group(2))
                words.append(
                    LyricWord(
                        time=start_ms / 1000.0,
                        dur=max(0.01, duration_ms / 1000.0),
                        text=content,
                    )
                )
        display = "".join(word.text for word in words).strip()
        if not display:
            display = body.strip()
        if not display:
            continue
        start = line_ms / 1000.0
        word_end = max(
            (word.time + word.dur for word in words),
            default=start + 2.5,
        )
        lines.append(
            LyricLine(
                time=start,
                end=max(start + 0.01, word_end),
                text=display,
                words=words,
            )
        )
    return sorted(lines, key=lambda item: item.time)


def _parse_text(text: str, kind: str) -> list[LyricLine]:
    if kind == "ttml":
        return parse_ttml(text)
    if kind == "lys":
        return parse_lys(text)
    from .sources.netease import parse_yrc

    return parse_yrc(text)


def fetch_doc(
    platform: str,
    title: str,
    artist: str,
    duration: float = 0.0,
    track_key: str = "",
    known_id: str = "",
    trusted_id: bool = False,
) -> LyricDoc | None:
    """取 AMLL 歌词；非播放器原生 ID 必须再经过严格标题/歌手匹配。"""
    platform = platform if platform in INDEX_URLS else "ncm"
    song_id = str(known_id or "").strip()
    if song_id and not trusted_id:
        matched = find_song(title, artist, platform)
        if matched is None or matched[0] != song_id:
            return None
    if not song_id:
        matched = find_song(title, artist, platform)
        if matched is None:
            return None
        song_id = matched[0]
    raw = _fetch_raw(platform, song_id)
    if raw is None:
        return None
    text, kind = raw
    lines = _parse_text(text, kind)
    if not lines:
        return None
    for index, line in enumerate(lines):
        if line.end <= line.time:
            line.end = (
                lines[index + 1].time
                if index + 1 < len(lines)
                else max(duration, line.time + 6.0)
            )
    return LyricDoc(
        lines=lines,
        source=f"AMLL TTML DB ({platform})",
        provider=f"amll-{platform}",
        track_key=track_key or song_id,
        has_words=any(line.words for line in lines),
    )
