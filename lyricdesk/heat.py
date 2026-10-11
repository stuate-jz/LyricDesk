"""歌曲热度：网易云的 popularity（0~100）。

QQ音乐和酷狗都没有公开的播放量接口，网易云的歌曲详情里有一个
popularity 字段（0~100 的热度值），拿它来显示「播放热度」。
查不到就不显示，不瞎编。
"""

from __future__ import annotations

import threading

import requests

_CACHE: dict[str, float] = {}
_PENDING: set[str] = set()
_LOCK = threading.Lock()

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://music.163.com/",
}


def cached(key: str) -> float | None:
    return _CACHE.get(key)


def key_for(title: str, artist: str) -> str:
    return f"{title}\u241f{artist}"


def _search_id(title: str, artist: str) -> int | None:
    query = f"{title} {artist}".strip()
    response = requests.post(
        "https://music.163.com/api/search/get/web",
        data={"s": query, "type": 1, "offset": 0, "limit": 5},
        timeout=(5, 8),
        headers=_HEADERS,
    )
    songs = (response.json().get("result") or {}).get("songs") or []
    if not songs:
        return None
    # 标题要对得上，别把翻唱/伴奏的热度算进来
    wanted = title.strip().lower()
    for song in songs:
        name = str(song.get("name") or "").strip().lower()
        if name == wanted:
            return int(song["id"])
    for song in songs:
        name = str(song.get("name") or "").strip().lower()
        if wanted and (wanted in name or name in wanted):
            return int(song["id"])
    return None


def _popularity(song_id: int) -> float | None:
    import json

    response = requests.get(
        "https://music.163.com/api/song/detail",
        params={"ids": json.dumps([song_id])},
        timeout=(5, 8),
        headers=_HEADERS,
    )
    songs = response.json().get("songs") or []
    if not songs:
        return None
    value = songs[0].get("popularity")
    if value is None:
        value = songs[0].get("score")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def lookup(key: str, title: str, artist: str, on_done) -> None:
    """后台查热度，完成后回调 on_done(key, 热度或 None)。

    同一个 key 只会查一次，结果缓存在内存里。
    """
    if not title:
        return
    with _LOCK:
        if key in _CACHE:
            return
        if key in _PENDING:
            return
        _PENDING.add(key)

    def worker() -> None:
        value: float | None = None
        try:
            song_id = _search_id(title, artist)
            if song_id is not None:
                value = _popularity(song_id)
        except Exception:  # noqa: BLE001
            value = None
        with _LOCK:
            _PENDING.discard(key)
            if value is not None:
                _CACHE[key] = value
        on_done(key, value)

    threading.Thread(target=worker, name="heat-lookup", daemon=True).start()
