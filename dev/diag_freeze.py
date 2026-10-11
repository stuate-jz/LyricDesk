r"""盯着歌词的「当前行 / 显示行」看它有没有卡住。

必须在 Qt 事件循环里采样 —— 引擎的轮询是主线程的 QTimer，
在主线程 sleep 会把引擎一起冻住，测出来的是假象。

    python dev\diag_freeze.py [持续秒数]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lyricdesk.config import Settings  # noqa: E402
from lyricdesk.engine import Engine  # noqa: E402
from lyricdesk.window import LyricWindow  # noqa: E402


def main() -> int:
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 25.0
    app = QApplication([])
    settings = Settings.load()
    engine = Engine(settings)
    window = LyricWindow(settings, engine)
    window.show()

    print(f"模式={settings.mode}  角色={window.role}")
    print("  时间   位置  歌词行 当前行 显示行 滚动就绪  当前行文本")
    state = {"last": None, "stuck": 0, "start": time.monotonic()}

    def sample() -> None:
        elapsed = time.monotonic() - state["start"]
        snap = engine.snapshot()
        lyrics = engine.lyrics
        now = time.monotonic()
        if snap is None or lyrics is None or not lyrics.lines:
            position = "--" if snap is None else f"{snap.position:6.1f}"
            count = "无" if lyrics is None else str(len(lyrics.lines))
            print(f"{elapsed:6.1f}s {position:>6s} {count:>5s}", flush=True)
            return
        _anim, index, current, _next = window._resolve_lyrics(snap, lyrics, now)
        visual = window._visual_index(now)
        text = (current.text if current else "")[:18]
        print(
            f"{elapsed:6.1f}s {snap.position:6.1f} {len(lyrics.lines):5d} "
            f"{index:6d} {visual:6.1f} {str(window._scroll_ready):>8s}  {text}",
            flush=True,
        )
        state["stuck"] = state["stuck"] + 1 if index == state["last"] else 0
        state["last"] = index

    def finish() -> None:
        if state["stuck"] >= 6:
            print(
                f"\n注意：当前行连续 {state['stuck']} 秒没变"
                "（可能正好是长间奏，也可能真卡住了）"
            )
        engine.stop()
        app.quit()

    tick = QTimer()
    tick.setInterval(1000)
    tick.timeout.connect(sample)
    QTimer.singleShot(1200, tick.start)
    QTimer.singleShot(int(seconds * 1000), finish)
    code = app.exec()
    engine.join(1.0)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
