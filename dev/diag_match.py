r"""诊断「歌词和播放对不上」：看选中的候选和正在播的那首是不是同一个版本。

    python dev\diag_match.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lyricdesk.config import Settings  # noqa: E402
from lyricdesk.engine import Engine  # noqa: E402
from lyricdesk.lyrics import (  # noqa: E402
    _PROVIDERS,
    _coverage,
    load_cached,
    parse_lrc,
    score_candidate,
)


def main() -> int:
    settings = Settings.load()
    engine = Engine(settings)
    deadline = time.monotonic() + 12
    snap = None
    while time.monotonic() < deadline:
        snap = engine.snapshot()
        if snap is not None and snap.track is not None:
            break
        time.sleep(0.5)
    if snap is None or snap.track is None:
        print("现在没有在播放的歌曲")
        engine.stop()
        return 1

    track = snap.track
    print(f"正在播放：{track.title} - {track.artist}")
    print(f"  专辑={track.album!r}  时长={track.duration:.1f}s  来源={snap.source}")
    print(f"  当前偏移设置 = {settings.offset_ms:+d} ms")

    cached = load_cached(track.title, track.artist)
    if cached is not None:
        lines = cached.lines
        print(
            f"\n缓存里的歌词：来源={cached.source!r} 行数={len(lines)}"
            f" 最后一行={lines[-1].time if lines else -1:.1f}s"
            f" 覆盖={_coverage(lines, track.duration) * 100:.0f}%"
        )
        if lines:
            print(f"  前 3 行时间: {[round(item.time, 1) for item in lines[:3]]}")
            print(f"  后 3 行时间: {[round(item.time, 1) for item in lines[-3:]]}")
    else:
        print("\n缓存里没有这首歌")

    print("\n各曲库的候选（时长差越多越可能不是同一个版本）：")
    query = f"{track.title} {track.artist}".strip()
    for key, label, search, resolver in _PROVIDERS:
        try:
            candidates = search(query)
        except Exception as exc:  # noqa: BLE001
            print(f"  {label}: 搜索失败 {type(exc).__name__}")
            continue
        for candidate in candidates[:4]:
            score = score_candidate(candidate, track.title, track.artist, track.duration)
            duration = candidate.get("duration") or 0
            delta = duration - track.duration if duration else 0
            flag = "" if not duration else ("  ← 时长不符" if abs(delta) > 3 else "  ✓ 时长接近")
            print(
                f"  {label:5s} {str(candidate.get('title'))[:18]:20s}"
                f" 候选时长={duration:6.1f}s (差 {delta:+6.1f}s)  匹配分={score:.2f}{flag}"
            )
    engine.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
