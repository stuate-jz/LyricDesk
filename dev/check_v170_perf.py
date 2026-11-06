"""v1.7.0 绘制成本：列表 / 圆盘 × 四种歌词动效的离屏基准。"""

from __future__ import annotations

import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lyricdesk import config  # noqa: E402

config.SETTINGS_PATH = Path(tempfile.mkdtemp(prefix="lyricdesk-v170-perf-")) / "settings.json"

from lyricdesk.config import Settings  # noqa: E402
from lyricdesk.lyricdoc import LyricWord  # noqa: E402
from lyricdesk.lyrics import LyricLine, Lyrics  # noqa: E402
from lyricdesk.smtc import Snapshot, Track  # noqa: E402
from lyricdesk.window import LyricWindow  # noqa: E402


class Engine:
    def __init__(self) -> None:
        lines = []
        for index in range(20):
            text = f"第{index + 1}句测试歌词正在沿着时间轴发光"
            words = [
                LyricWord(index * 4.0 + offset * 0.22, 0.18, char)
                for offset, char in enumerate(text)
            ]
            lines.append(
                LyricLine(
                    index * 4.0,
                    text,
                    index * 4.0 + 3.8,
                    words=words,
                )
            )
        self.lyrics = Lyrics(lines=lines, source="test", title="性能", artist="测试")
        self.snapshot_value = Snapshot(
            track=Track("性能", "测试", "专辑", 90.0),
            position=41.1,
            is_playing=True,
            status=4,
            source="QQMusic.exe",
        )

    def snapshot(self):
        return self.snapshot_value

    def players(self):
        return []


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    settings = Settings()
    settings.show_song_info = False
    settings.background = False
    settings.always_on_top = False
    window = LyricWindow(settings, Engine())
    window.show()
    app.processEvents()
    failures = []
    for layout in ("list", "disc"):
        settings.lyric_layout = layout
        for effect in ("off", "word", "bounce", "sweep"):
            settings.lyric_effect = effect
            window._commit(resize=True)
            layer = QPixmap(window.size())
            for _ in range(5):
                window.render(layer)
            samples = []
            for _ in range(40):
                started = time.perf_counter()
                window.render(layer)
                samples.append((time.perf_counter() - started) * 1000.0)
            average = statistics.mean(samples)
            maximum = max(samples)
            limit_avg = 8.0 if layout == "disc" else 5.0
            limit_max = 10.0
            ok = average <= limit_avg and maximum <= limit_max
            print(
                f"  {'OK  ' if ok else 'FAIL'} {layout:4s} / {effect:6s}"
                f" avg={average:.2f}ms max={maximum:.2f}ms"
            )
            if not ok:
                failures.append(f"{layout}/{effect}")
    window.deleteLater()
    app.processEvents()
    if failures:
        print("失败：", ", ".join(failures))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
