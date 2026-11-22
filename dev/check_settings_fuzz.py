"""随机设置压力：几何锚点、写盘事务、重复渲染和当前句可见性。"""

from __future__ import annotations

import hashlib
import json
import os
import random
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_SCALE_FACTOR", "1.5")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPointF, QRect  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lyricdesk import config, heat, render  # noqa: E402

config.SETTINGS_PATH = Path(tempfile.mkdtemp(prefix="lyricdesk-fuzz-")) / "settings.json"

from lyricdesk.config import Settings  # noqa: E402
from lyricdesk.fonts import register_all  # noqa: E402
from lyricdesk.lyrics import LyricLine, Lyrics  # noqa: E402
from lyricdesk.smtc import Snapshot, Track  # noqa: E402
from lyricdesk.window import LyricWindow  # noqa: E402

heat.lookup = lambda *args, **kwargs: None  # type: ignore[assignment]
heat.cached = lambda key: None  # type: ignore[assignment]

TEXT = [
    "随机设置不能推动窗口漂移",
    "圆盘圆心必须保持不动",
    "当前句不能因为缓存而空行",
]


class FakeScreen:
    def availableGeometry(self) -> QRect:
        return QRect(0, 0, 1707, 1067)


class Engine:
    def __init__(self) -> None:
        self.lyrics = Lyrics(
            lines=[
                LyricLine(10.0 + index * 4.0, text, 13.6 + index * 4.0)
                for index, text in enumerate(TEXT)
            ],
            source="test",
            title="压力测试",
            artist="LyricDesk",
            provider="test",
        )
        self.snapshot_value = Snapshot(
            track=Track("压力测试", "LyricDesk", "", 240.0),
            position=10.8,
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


def build(layout: str) -> LyricWindow:
    settings = Settings()
    settings.width = 900
    settings.font_size = 58
    settings.lyric_lines = 5
    settings.lyric_layout = layout
    settings.lyric_effect = "off"
    settings.lyric_glow = 1.6
    settings.show_wave = False
    settings.real_wave = False
    settings.beat_boost = False
    settings.chorus_boost = False
    settings.auto_show_on_music = False
    window = LyricWindow(settings, Engine())
    window.screen = lambda: FakeScreen()
    window._timer.stop()
    window._topmost_timer.stop()
    window.show()
    QApplication.processEvents()
    window._anim_t0 = -1000.0
    return window


def anchor(window: LyricWindow) -> QPointF:
    if window.settings.lyric_layout == "disc":
        point = window._disc_center_on_screen()
    else:
        rect = window.geometry()
        over = window._overscan
        if window.settings.lyric_align == "left":
            x = rect.x() + 24 + over + 20
        elif window.settings.lyric_align == "center":
            x = rect.x() + rect.width() / 2.0
        else:
            x = rect.x() + rect.width() - (24 + over + 20)
        point = QPointF(x, rect.y() + rect.height() / 2.0)
    return point


def apply_random(window: LyricWindow, rng: random.Random) -> None:
    choice = rng.randrange(12)
    settings = window.settings
    if choice == 0:
        window._set_font_size(rng.randint(24, 92))
    elif choice == 1:
        window._set_glow(rng.uniform(0.0, 5.0))
    elif choice == 2:
        window._set_opacity(rng.uniform(0.3, 1.0))
    elif choice == 3:
        window._set_ui_opacity(rng.uniform(0.2, 1.0))
    elif choice == 4:
        window._set_spacing(rng.uniform(0.8, 2.4))
    elif choice == 5:
        window._set_lines(rng.randint(2, 8))
    elif choice == 6:
        window._set_depth(
            v=rng.uniform(-0.6, 0.6),
            h=rng.uniform(-0.6, 0.6),
        )
    elif choice == 7:
        window._set_spin(rng.uniform(-30.0, 30.0))
    elif choice == 8:
        window._set_lyric_effect(rng.choice(("off", "word", "bounce")))
    elif choice == 9:
        window._set_lyric_arc(rng.random())
        window._set_lyric_breath(rng.random())
        window._set_lyric_jitter(rng.random())
    elif choice == 10:
        window._set_cover(rng.randrange(40, 202, 2))
    else:
        window._set_player_width(rng.choice((0, *range(240, 521, 20))))


def cache_render(window: LyricWindow) -> str:
    window.settings.lyric_effect = "off"
    window.settings.lyric_arc = 0.0
    window.settings.lyric_breath = 0.0
    window.settings.lyric_jitter = 0.0
    window.settings.show_cover = False
    window.settings.show_progress = False
    window.settings.show_controls = False
    window._commit(scope="visual")
    window._anim_t0 = -1000.0
    window._spin_angle = 0.0
    for _ in range(4):
        window.update()
        QApplication.processEvents()
        window.grab()
    image = window.grab().toImage().convertToFormat(
        QImage.Format.Format_ARGB32
    )
    return hashlib.sha256(bytes(image.bits())).hexdigest().upper()


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    register_all()
    rng = random.Random(20261122)
    failed = 0
    max_drift = 0.0
    total_saves = 0

    for layout in ("list", "disc"):
        window = build(layout)
        save_count = [0]
        real_save = window.settings.save

        def counted_save():
            save_count[0] += 1
            real_save()

        window.settings.save = counted_save
        for _ in range(100):
            before_anchor = anchor(window)
            before_rect = window.geometry()
            window.begin_edit()
            apply_random(window, rng)
            QApplication.processEvents()
            if window.geometry() != before_rect:
                failed += 1
                print(f"FAIL {layout}: 拖动中窗口移动 {before_rect} -> {window.geometry()}")
            window.end_edit()
            QApplication.processEvents()
            after_anchor = anchor(window)
            drift = max(
                abs(after_anchor.x() - before_anchor.x()),
                abs(after_anchor.y() - before_anchor.y()),
            )
            max_drift = max(max_drift, drift)
            if drift > 2.0:
                failed += 1
                print(f"FAIL {layout}: 锚点漂移 {before_anchor} -> {after_anchor}")
            alpha_image = window.grab().toImage().convertToFormat(
                QImage.Format.Format_ARGB32
            )
            alpha = sum(bytes(alpha_image.bits())[3::4])
            if alpha <= 0:
                failed += 1
                print(f"FAIL {layout}: 当前句空行")

        hash_a = cache_render(window)
        hash_b = cache_render(window)
        if hash_a != hash_b:
            failed += 1
            print(f"FAIL {layout}: 同参数重复渲染不一致")
        total_saves += save_count[0]
        print(
            f"{layout}: edits=100 saves={save_count[0]} "
            f"max_drift={max_drift:.2f}px stable_hash={hash_a[:16]}"
        )
        window.close()
        window.deleteLater()
        QApplication.processEvents()

    stats = render.cache_stats()
    print(
        f"fallback={stats['line_fallbacks']} "
        f"fallbacks_per_minute={stats['fallbacks_per_minute']:.2f} "
        f"total_saves={total_saves}"
    )
    print(f"\n结果：{'全部通过' if failed == 0 else f'{failed} 项失败'}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
