r"""看看某一首歌在各个曲库抓到的歌词是不是完整的。

    python dev\diag_lyrics.py "我们俩" "Yihuik苡慧" [时长秒数]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lyricdesk.lyrics import (  # noqa: E402
    fetch,
    parse_lrc,
    search_kugou,
    search_netease,
    search_qq,
)


def main() -> int:
    title = sys.argv[1] if len(sys.argv) > 1 else "我们俩"
    artist = sys.argv[2] if len(sys.argv) > 2 else "Yihuik苡慧"
    duration = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0

    for name, search in (("QQ", search_qq), ("酷狗", search_kugou), ("网易云", search_netease)):
        results = search(f"{title} {artist}", limit=3)
        for candidate in results[:2]:
            raw = candidate.get("lyric") or ""
            if not raw:
                print(f"{name:5s} {str(candidate.get('title'))[:16]:18s} 这个候选没有歌词")
                continue
            lines = parse_lrc(raw)
            last = lines[-1].time if lines else -1.0
            print(
                f"{name:5s} {str(candidate.get('title'))[:16]:18s}"
                f" 行数={len(lines):3d}  最后一行={last:7.1f}s"
                f"  候选时长={candidate.get('duration') or 0:6.1f}s"
                f"  原文={len(raw)} 字"
            )
            if lines:
                print(
                    "        开头:",
                    [round(item.time, 1) for item in lines[:3]],
                    " 结尾:",
                    [round(item.time, 1) for item in lines[-3:]],
                )

    print()
    result = fetch(title, artist, duration)
    lines = result.lines
    print(
        f"fetch() 选中的来源={result.source!r} 行数={len(lines)}"
        f" 最后一行={lines[-1].time if lines else -1:.1f}s"
        f" 歌曲时长={duration:.1f}s"
    )
    if lines and duration and lines[-1].time < duration * 0.75:
        print(
            f"  ⚠ 歌词只覆盖到 {lines[-1].time / duration * 100:.0f}% 的时长，"
            "后半段会一直停在最后一行"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
