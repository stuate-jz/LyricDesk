"""22 场景视觉 golden：同机要求 0 像素差，跨机按 0.1% / 通道差 2 容差。"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import time
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.pop("QT_SCALE_FACTOR", None)
ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "dev" / "golden"
UPDATE = "--update" in sys.argv
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
import PySide6  # noqa: E402

from lyricdesk import config, heat  # noqa: E402

config.SETTINGS_PATH = Path(tempfile.mkdtemp(prefix="lyricdesk-golden-")) / "settings.json"

from lyricdesk.config import Settings  # noqa: E402
from lyricdesk.fonts import register_all  # noqa: E402
from lyricdesk.lyrics import LyricLine, Lyrics  # noqa: E402
from lyricdesk.smtc import Snapshot, Track  # noqa: E402
from lyricdesk import window as window_module  # noqa: E402
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
    "把所有的遗憾都交给明天",
    "就这样一直唱到没有力气",
]


class FakeScreen:
    def availableGeometry(self) -> QRect:
        return QRect(0, 0, 1707, 1067)


class Clock:
    def __init__(self) -> None:
        self.value = 1000.0

    def advance(self) -> None:
        self.value += 1.0 / 30.0


CLOCK = Clock()


class TimeProxy:
    def __getattr__(self, name):
        import time as real_time

        return getattr(real_time, name)

    def monotonic(self) -> float:
        return CLOCK.value


window_module.time = TimeProxy()


class SettledWindow(LyricWindow):
    def paintEvent(self, event) -> None:  # noqa: N802
        self._spin_angle = 0.0
        CLOCK.advance()
        super().paintEvent(event)


class Engine:
    def __init__(self) -> None:
        self.lyrics = Lyrics(
            lines=[
                LyricLine(10.0 + index * 4.0, text, 13.6 + index * 4.0)
                for index, text in enumerate(TEXTS)
            ],
            source="test",
            title="测试歌曲",
            artist="测试歌手",
            provider="test",
        )
        self.snapshot_value = Snapshot(
            track=Track("测试歌曲", "测试歌手", "测试专辑", 240.0),
            position=22.6,
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


def base_settings() -> Settings:
    settings = Settings()
    settings.font_family = "AaLingSheZhuan"
    settings.font_size = 58
    settings.width = 1020
    settings.lyric_lines = 6
    settings.lyric_effect = "off"
    settings.lyric_glow = 0.0
    settings.lyric_arc = 0.0
    settings.lyric_breath = 0.0
    settings.lyric_jitter = 0.0
    settings.lyric_scatter = False
    settings.show_wave = False
    settings.real_wave = False
    settings.beat_boost = False
    settings.chorus_boost = False
    settings.auto_show_on_music = False
    settings.background = False
    settings.show_song_info = False
    settings.show_cover = False
    settings.show_progress = False
    settings.show_controls = False
    return settings


def scenarios() -> list[tuple[str, Settings]]:
    output: list[tuple[str, Settings]] = []
    for layout in ("list", "disc"):
        for effect in ("off", "word", "bounce"):
            for glow in (0.0, 1.0, 5.0):
                settings = base_settings()
                settings.lyric_layout = layout
                settings.lyric_effect = effect
                settings.lyric_glow = glow
                output.append(
                    (f"{layout}_{effect}_glow{int(glow * 100):03d}", settings)
                )

    settings = base_settings()
    settings.lyric_align = "left"
    settings.lyric_glow = 1.0
    output.append(("combo_align_left", settings))

    settings = base_settings()
    settings.lyric_effect = "word"
    settings.lyric_glow = 2.0
    settings.opacity = 0.55
    settings.ui_opacity = 0.75
    output.append(("combo_transparent", settings))

    settings = base_settings()
    settings.lyric_layout = "disc"
    settings.cover_size = 64
    settings.lyric_glow = 1.0
    output.append(("combo_disc_compact", settings))

    settings = base_settings()
    settings.lyric_effect = "off"
    settings.lyric_glow = 1.0
    settings.text_depth_h = 0.75
    settings.text_depth_v = 0.16
    settings.text_tilt = -8.0
    output.append(("combo_tilt", settings))
    return output


def render_case(settings: Settings) -> QImage:
    window = SettledWindow(settings, Engine())
    window.screen = lambda: FakeScreen()
    window._timer.stop()
    window._topmost_timer.stop()
    window.show()
    QApplication.processEvents()
    deadline = time.monotonic() + 0.2
    while time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)
    window._anim_t0 = 0.0
    window._spring_line_key = None
    CLOCK.value = 1000.0
    image = None
    for _ in range(30):
        QApplication.processEvents()
        image = window.grab().toImage().convertToFormat(
            QImage.Format.Format_ARGB32
        )
    window.close()
    window.deleteLater()
    QApplication.processEvents()
    return image


def compare(left: QImage, right: QImage) -> tuple[int, int, float]:
    if left.size() != right.size():
        return -1, -1, 1.0
    a = bytes(left.bits())
    b = bytes(right.bits())
    changed = 0
    peak = 0
    for index in range(0, len(a), 4):
        delta = max(abs(a[index + c] - b[index + c]) for c in range(4))
        if delta:
            changed += 1
            peak = max(peak, delta)
    return changed, peak, changed / max(1, len(a) // 4)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    register_all()
    GOLDEN.mkdir(parents=True, exist_ok=True)
    index_path = GOLDEN / "index.json"
    old = {}
    if index_path.exists():
        old = json.loads(index_path.read_text(encoding="utf-8"))
    records = {}
    failed = 0
    current_dpr = round(
        float(QApplication.primaryScreen().devicePixelRatio()),
        3,
    )
    for name, settings in scenarios():
        image = render_case(settings)
        path = GOLDEN / f"{name}.png"
        digest = hashlib.sha256(bytes(image.bits())).hexdigest().upper()
        record = {
            "sha256": digest,
            "size": [image.width(), image.height()],
            "dpr": current_dpr,
            "font": settings.font_family,
            "platform": platform.platform(),
            "qt": PySide6.__version__,
        }
        records[name] = record
        if UPDATE or not path.exists():
            image.save(str(path))
            print(f"UPDATE {name} {digest[:16]}")
            continue
        expected = QImage(str(path)).convertToFormat(
            QImage.Format.Format_ARGB32
        )
        changed, peak, share = compare(image, expected)
        previous = old.get(name, {})
        cross_machine = (
            previous.get("font") != settings.font_family
            or previous.get("dpr") != current_dpr
            or previous.get("platform") != platform.platform()
            or previous.get("qt") != PySide6.__version__
        )
        ok = (
            changed == 0
            if not cross_machine
            else changed >= 0 and share <= 0.001 and peak <= 2
        )
        print(
            f"{name:30s} changed={changed:8d} peak={peak:3d} "
            f"share={share * 100:.4f}% {'OK' if ok else 'FAIL'}"
        )
        failed += 0 if ok else 1
    if UPDATE or not index_path.exists():
        index_path.write_text(
            json.dumps(records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(f"\n结果：{'全部通过' if failed == 0 else f'{failed} 项失败'}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
