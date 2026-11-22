"""比较子进程预烘与同步预烘的整窗截图，支持 layout / spacing / DPR。"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_SCALE_FACTOR", "1.5")
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "dev" / "line_art_worker_check"
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lyricdesk import config, heat, render  # noqa: E402

config.SETTINGS_PATH = Path(tempfile.mkdtemp(prefix="lyricdesk-worker-")) / "settings.json"

from lyricdesk.config import Settings  # noqa: E402
from lyricdesk.fonts import register_all  # noqa: E402
from lyricdesk.lyrics import LyricLine, Lyrics  # noqa: E402
from lyricdesk.smtc import Snapshot, Track  # noqa: E402
from lyricdesk.window import LyricWindow  # noqa: E402

heat.lookup = lambda *args, **kwargs: None  # type: ignore[assignment]
heat.cached = lambda key: None  # type: ignore[assignment]

TEXTS = [
    "我把车窗摇下来让晚风灌进来",
    "城市灯火一盏一盏往后退",
    "那些说不出口的话都留在风里",
    "我们走过的那条街还在下雪",
    "时间它从来不回答任何问题",
    "可是我想说的其实只有一句",
    "你听啊这首歌里都是你的名字",
    "等天亮之前我们再唱一遍",
]


class FakeScreen:
    def availableGeometry(self) -> QRect:
        return QRect(0, 0, 1707, 1067)


class Engine:
    def __init__(self) -> None:
        self.lyrics = Lyrics(
            lines=[
                LyricLine(10.0 + index * 4.0, text, 10.0 + index * 4.0 + 3.6)
                for index, text in enumerate(TEXTS)
            ],
            source="test",
            title="测试歌曲",
            artist="测试歌手",
            provider="test",
        )
        self.snapshot_value = Snapshot(
            track=Track("测试歌曲", "测试歌手", "测试专辑", 240.0),
            position=18.4,
            is_playing=True,
            status=4,
            source="QQMusic.exe",
        )

    def snapshot(self):
        return self.snapshot_value

    def players(self):
        return []

    def send_control(self, _action):
        return None

    def reload(self):
        return None


def settings_for(glow: float) -> Settings:
    settings = Settings()
    raw = json.loads(
        (Path(os.environ["APPDATA"]) / "LyricDesk" / "settings.json").read_text(
            encoding="utf-8"
        )
    )
    for key, value in raw.items():
        if hasattr(settings, key):
            setattr(settings, key, value)
    settings.show_wave = False
    settings.real_wave = False
    settings.beat_boost = False
    settings.chorus_boost = False
    settings.lyric_arc = 0.0
    settings.lyric_breath = 0.0
    settings.lyric_jitter = 0.0
    settings.lyric_audio_align = False
    settings.lyric_scatter = False
    settings.auto_show_on_music = False
    settings.lyric_effect = "off"
    settings.lyric_glow = glow
    settings.width = 1020
    settings.lyric_layout = os.environ.get("CHECK_LAYOUT", "list")
    spacing = os.environ.get("CHECK_SPACING")
    settings.letter_spacing = float(spacing) if spacing is not None else 4.5
    return settings


def spin(seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.005)


def capture(glow: float, name: str) -> dict:
    render.clear_line_cache()
    window = LyricWindow(settings_for(glow), Engine())
    window.screen = lambda: FakeScreen()
    window._topmost_timer.stop()
    window.show()
    QApplication.processEvents()
    spin(4.0)
    window._anim_t0 = 0.0
    QApplication.processEvents()
    pixmap = window.grab()
    path = OUT / f"{name}.png"
    pixmap.save(str(path))
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    raw = bytes(image.bits())
    record = {
        "sha256": hashlib.sha256(raw).hexdigest().upper(),
        "alpha_sum": sum(raw[3::4]),
        "size": [image.width(), image.height()],
    }
    window._timer.stop()
    window.close()
    window.deleteLater()
    QApplication.processEvents()
    return record


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    register_all()
    from lyricdesk import line_art_worker

    records: dict[str, dict] = {}
    for glow in (0.0, 1.0, 5.0):
        name = f"sync_glow{int(glow * 100):03d}"
        records[name] = capture(glow, name)
        print(f"{name}: alpha={records[name]['alpha_sum']} sha={records[name]['sha256']}")

    os.environ["LYRICDESK_FORCE_LINE_WORKER"] = "1"
    print(f"worker.enabled() = {line_art_worker.enabled()}")
    for glow in (0.0, 1.0, 5.0):
        name = f"worker_glow{int(glow * 100):03d}"
        records[name] = capture(glow, name)
        print(f"{name}: alpha={records[name]['alpha_sum']} sha={records[name]['sha256']}")

    failed = 0
    for glow in (0.0, 1.0, 5.0):
        sync = records[f"sync_glow{int(glow * 100):03d}"]
        worker = records[f"worker_glow{int(glow * 100):03d}"]
        equal = sync["sha256"] == worker["sha256"]
        print(f"glow={glow:.2f}: {'OK' if equal else 'FAIL'}")
        failed += 0 if equal else 1
    print(f"\n结果：{'全部通过' if failed == 0 else f'{failed} 项失败'}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
