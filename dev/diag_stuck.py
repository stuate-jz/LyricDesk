r"""歌词卡住时跑一下：看播放进度到底有没有在走。"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lyricdesk.config import Settings  # noqa: E402
from lyricdesk.engine import Engine  # noqa: E402


def main() -> int:
    settings = Settings.load()
    engine = Engine(settings)
    time.sleep(2.5)

    print(f"设置里的模式：{settings.mode}")
    print(f"引擎在跑吗：{engine.is_running()}")
    players = getattr(engine, "players", None)
    if players is not None:
        try:
            print("看到的播放器：")
            for item in players() or []:
                print(f"   {item}")
        except Exception as exc:  # noqa: BLE001
            print("   players() 出错:", type(exc).__name__)

    print("\n连续采样播放进度（每 1 秒一次，共 6 次）：")
    last = None
    samples = []
    for index in range(6):
        snap = engine.snapshot()
        if snap is None:
            print(f"  [{index}] 没有播放会话（snapshot = None）")
        else:
            track = snap.track
            title = f"{track.title} - {track.artist}" if track else "（无歌曲）"
            print(
                f"  [{index}] 位置={snap.position:7.2f}  播放中={snap.is_playing}"
                f"  状态={getattr(snap, 'status', '?')}  来源={snap.source}  {title}"
            )
            samples.append(snap.position)
        time.sleep(1.0)

    print("\n歌词对象：")
    lyrics = engine.lyrics
    if lyrics is None:
        print("  lyrics = None")
    else:
        print(f"  来源={getattr(lyrics, 'source', '?')}  行数={len(lyrics.lines)}")
        snap = engine.snapshot()
        if snap and lyrics.lines:
            position = snap.position + settings.offset_ms / 1000.0
            index = lyrics.index_at(position)
            print(f"  当前时间点 {position:.2f}s 对应第 {index} 行")

    if len(samples) >= 2:
        moved = samples[-1] - samples[0]
        print(f"\n结论：{samples[0]:.2f} → {samples[-1]:.2f}，位移 {moved:+.2f} 秒")
        if abs(moved) < 0.5:
            print("  → 进度根本没动：问题出在读取层（SMTC），不是画面")
        else:
            print("  → 进度在走：问题出在绘制或歌词匹配")

    engine.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
