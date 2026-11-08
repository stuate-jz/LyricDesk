"""本机音乐目录里的多格式歌词：LRC / YRC / QRC / TTML / LYS。"""

from __future__ import annotations

import os
import re
import time
import unicodedata
from pathlib import Path

from .lyricdoc import LyricDoc, LyricLine

_SUFFIXES = {".lrc", ".yrc", ".qrc", ".ttml", ".lys"}
_TAG = re.compile(r"^\[([a-zA-Z]+):([^\]]*)\]")
_SEPARATORS = re.compile(r"\s+[-—–·]\s+")
_DISCOVERY_TTL = 60.0
_DISCOVERY_LOCK: dict[str, tuple[float, list[Path]]] = {}


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").lower()
    return re.sub(
        r"[\s\-_·、,，.。!！?？'\"“”‘’()（）\[\]【】]",
        "",
        text,
    )


def default_roots() -> list[Path]:
    roots: list[Path] = []
    configured = os.environ.get("LYRICDESK_MUSIC_DIRS", "")
    for raw in configured.split(os.pathsep):
        if raw.strip():
            roots.append(Path(raw.strip()))
    home = Path.home()
    public = Path(os.environ.get("PUBLIC", r"C:\Users\Public"))
    roots.extend(
        (
            home / "Music",
            home / "Downloads",
            public / "Music",
        )
    )
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        try:
            key = str(root.resolve()).lower()
        except Exception:
            key = str(root).lower()
        if key not in seen and root.is_dir():
            seen.add(key)
            unique.append(root)
    return unique


def _discover(roots: list[Path], limit: int = 20_000) -> list[Path]:
    key = "\0".join(str(root) for root in roots)
    cached = _DISCOVERY_LOCK.get(key)
    now = time.monotonic()
    if cached is not None and now - cached[0] < _DISCOVERY_TTL:
        return cached[1]
    found: list[Path] = []
    for root in roots:
        try:
            for directory, _subdirs, files in os.walk(root):
                for name in files:
                    path = Path(directory) / name
                    if path.suffix.lower() in _SUFFIXES:
                        found.append(path)
                        if len(found) >= limit:
                            break
                if len(found) >= limit:
                    break
        except Exception:
            continue
        if len(found) >= limit:
            break
    found.sort(key=lambda path: str(path).lower())
    _DISCOVERY_LOCK[key] = (now, found)
    return found


def _header(path: Path) -> tuple[str, str]:
    title = ""
    artist = ""
    try:
        with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
            for _ in range(40):
                raw = handle.readline()
                if not raw:
                    break
                match = _TAG.match(raw.strip())
                if not match:
                    continue
                key = match.group(1).lower()
                if key == "ti":
                    title = match.group(2).strip()
                elif key in ("ar", "artist"):
                    artist = match.group(2).strip()
    except Exception:
        return "", ""
    return title, artist


def _identity_match(
    path: Path,
    title: str,
    artist: str,
) -> bool:
    wanted_title = _normalize(title)
    wanted_artist = _normalize(artist)
    if not wanted_title:
        return False
    tag_title, tag_artist = _header(path)
    if tag_title:
        if _normalize(tag_title) != wanted_title:
            return False
        return not wanted_artist or _normalize(tag_artist) == wanted_artist

    parts = [
        _normalize(part)
        for part in _SEPARATORS.split(path.stem)
        if _normalize(part)
    ]
    if wanted_title not in parts:
        return False
    if wanted_artist:
        return wanted_artist in parts
    return len(parts) == 1


def _parse(path: Path, text: str) -> list[LyricLine]:
    suffix = path.suffix.lower()
    if suffix == ".lrc":
        from .lyrics import parse_lrc

        return parse_lrc(text, path.stem)
    if suffix in (".yrc", ".qrc"):
        from .sources.netease import parse_yrc

        return parse_yrc(text)
    if suffix == ".ttml":
        from .amll import parse_ttml

        return parse_ttml(text)
    if suffix == ".lys":
        from .amll import parse_lys

        return parse_lys(text)
    return []


def find_local_doc(
    title: str,
    artist: str,
    duration: float = 0.0,
    track_key: str = "",
    roots: list[Path] | None = None,
) -> LyricDoc | None:
    """按严格标题/歌手匹配本地歌词；找不到或有多个同名文件就放弃。"""
    search_roots = roots if roots is not None else default_roots()
    matches = [
        path
        for path in _discover(search_roots)
        if _identity_match(path, title, artist)
    ]
    if len(matches) != 1:
        return None
    path = matches[0]
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except Exception:
        return None
    lines = _parse(path, text)
    if not lines:
        return None
    for index, line in enumerate(lines):
        if line.end <= line.time:
            line.end = (
                lines[index + 1].time
                if index + 1 < len(lines)
                else max(duration, line.time + 6.0)
            )
    kind = path.suffix[1:].upper()
    return LyricDoc(
        lines=lines,
        source=f"本地 {kind}",
        provider="local",
        track_key=track_key or str(path),
        has_words=any(line.words for line in lines),
    )
