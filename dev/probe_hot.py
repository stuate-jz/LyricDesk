r"""找一个能拿到「播放热度」的接口。"""

from __future__ import annotations

import json

import requests

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Referer": "https://music.163.com/"}


def main() -> int:
    # 先用搜索拿到 id
    r = requests.post(
        "https://music.163.com/api/search/get/web",
        data={"s": "海屿你 马也_Crabbit", "type": 1, "offset": 0, "limit": 3},
        timeout=(6, 12),
        headers=H,
    )
    songs = r.json().get("result", {}).get("songs", [])
    print("搜索到", len(songs), "首")
    if not songs:
        return 1
    song_id = songs[0]["id"]
    print("第一首:", songs[0].get("name"), song_id)

    r2 = requests.get(
        "https://music.163.com/api/song/detail",
        params={"ids": json.dumps([song_id])},
        timeout=(6, 12),
        headers=H,
    )
    payload = r2.json()
    detail = (payload.get("songs") or [{}])[0]
    keys = sorted(detail.keys())
    print("详情字段:", keys)
    for key in ("pop", "score", "hot", "playCount", "popularity", "commentCount"):
        if key in detail:
            print(f"   {key} = {detail[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
