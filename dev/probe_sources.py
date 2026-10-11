"""探测：SMTC 里都有哪些播放器；网易云 / 酷狗的歌词接口是否可用。"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from winrt.windows.media.control import (  # noqa: E402
    GlobalSystemMediaTransportControlsSessionManager as SessionManager,
)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
STATUS = {0: "CLOSED", 1: "OPENED", 2: "CHANGING", 3: "STOPPED", 4: "PLAYING", 5: "PAUSED"}


async def list_sessions() -> None:
    manager = await SessionManager.request_async()
    sessions = list(manager.get_sessions() or [])
    print(f"=== SMTC 会话数: {len(sessions)}")
    for session in sessions:
        app_id = session.source_app_user_model_id or ""
        try:
            info = await session.try_get_media_properties_async()
            title, artist = info.title, info.artist
        except Exception as exc:  # noqa: BLE001
            title = artist = f"<读取失败 {exc}>"
        playback = session.get_playback_info()
        timeline = session.get_timeline_properties()
        print(
            f"  [{STATUS.get(int(playback.playback_status), '?')}] {app_id}\n"
            f"      {title} - {artist}  "
            f"({timeline.position.total_seconds():.0f}/"
            f"{timeline.end_time.total_seconds():.0f}s)"
        )


def probe_netease(title: str, artist: str) -> None:
    print("=" * 20, "网易云")
    headers = {"User-Agent": UA, "Referer": "https://music.163.com/"}
    try:
        response = requests.post(
            "https://music.163.com/api/search/get/web",
            data={"s": f"{title} {artist}", "type": 1, "offset": 0, "limit": 5},
            headers=headers,
            timeout=10,
        )
        payload = response.json()
    except Exception as exc:  # noqa: BLE001
        print("  搜索失败:", exc)
        return
    songs = (payload.get("result") or {}).get("songs") or []
    print(f"  搜索结果: {len(songs)} 条")
    for song in songs[:3]:
        singers = "/".join(a.get("name", "") for a in song.get("artists", []))
        print(f"    {song.get('name')} - {singers}  id={song.get('id')} dur={song.get('duration')}")
    if not songs:
        return
    song_id = songs[0]["id"]
    try:
        response = requests.get(
            "https://music.163.com/api/song/lyric",
            params={"id": song_id, "lv": -1, "kv": -1, "tv": -1},
            headers=headers,
            timeout=10,
        )
        data = response.json()
    except Exception as exc:  # noqa: BLE001
        print("  歌词请求失败:", exc)
        return
    lrc = (data.get("lrc") or {}).get("lyric") or ""
    print(f"  歌词长度: {len(lrc)}")
    for line in lrc.splitlines()[:4]:
        print("    ", line)


def probe_kugou(title: str, artist: str) -> None:
    print("=" * 20, "酷狗")
    headers = {"User-Agent": UA, "Referer": "https://www.kugou.com/"}
    try:
        response = requests.get(
            "https://mobilecdn.kugou.com/api/v3/search/song",
            params={"format": "json", "keyword": f"{title} {artist}", "page": 1, "pagesize": 5},
            headers=headers,
            timeout=10,
        )
        payload = response.json()
    except Exception as exc:  # noqa: BLE001
        print("  搜索失败:", exc)
        return
    items = ((payload.get("data") or {}).get("info")) or []
    print(f"  搜索结果: {len(items)} 条")
    for item in items[:3]:
        print(
            f"    {item.get('songname')} - {item.get('singername')}  "
            f"hash={item.get('hash')} dur={item.get('duration')}"
        )
    if not items:
        return
    song = items[0]
    try:
        response = requests.get(
            "https://krcs.kugou.com/search",
            params={
                "ver": 1,
                "man": "yes",
                "client": "mobi",
                "hash": song.get("hash"),
                "album_id": song.get("album_id", 0),
                "duration": song.get("duration"),
            },
            headers=headers,
            timeout=10,
        )
        cand = response.json()
    except Exception as exc:  # noqa: BLE001
        print("  krcs 搜索失败:", exc)
        return
    candidates = cand.get("candidates") or []
    print(f"  歌词候选: {len(candidates)}")
    if not candidates:
        return
    first = candidates[0]
    print(f"    id={first.get('id')} accesskey={first.get('accesskey')}")
    try:
        response = requests.get(
            "https://lyrics.kugou.com/download",
            params={
                "ver": 1,
                "client": "pc",
                "id": first.get("id"),
                "accesskey": first.get("accesskey"),
                "fmt": "lrc",
                "charset": "utf8",
            },
            headers=headers,
            timeout=10,
        )
        data = response.json()
    except Exception as exc:  # noqa: BLE001
        print("  下载失败:", exc)
        return
    content = data.get("content")
    if content:
        text = base64.b64decode(content).decode("utf-8", "replace")
        print(f"  歌词长度: {len(text)}")
        for line in text.splitlines()[:4]:
            print("    ", line)
    else:
        print("  返回里没有 content:", json.dumps(data, ensure_ascii=False)[:200])


if __name__ == "__main__":
    asyncio.run(list_sessions())
    for t, a in (("山茶花", "忧郁男孩"), ("失忆 (温柔版)", "正在进行石女士")):
        print()
        probe_netease(t, a)
        probe_kugou(t, a)
