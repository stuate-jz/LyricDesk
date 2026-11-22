"""检查最近邻缩放兜底、未命中重排和单帧自愈。"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["LYRICDESK_FORCE_LINE_WORKER"] = "1"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QRect, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lyricdesk import config, heat, render  # noqa: E402
from lyricdesk import line_art_worker  # noqa: E402

config.SETTINGS_PATH = Path(tempfile.mkdtemp(prefix="lyricdesk-fallback-")) / "settings.json"

from lyricdesk.config import Settings  # noqa: E402
from lyricdesk.fonts import register_all  # noqa: E402
from lyricdesk.lyrics import LyricLine, Lyrics  # noqa: E402
from lyricdesk.smtc import Snapshot, Track  # noqa: E402
from lyricdesk import window as window_module  # noqa: E402
from lyricdesk.window import LyricWindow  # noqa: E402

heat.lookup = lambda *args, **kwargs: None  # type: ignore[assignment]
heat.cached = lambda key: None  # type: ignore[assignment]

TEXT = "单行偏移和逐字挤压必须自动恢复"


class FakeScreen:
    def availableGeometry(self) -> QRect:
        return QRect(0, 0, 1707, 1067)


class Engine:
    def __init__(self) -> None:
        self.lyrics = Lyrics(
            lines=[LyricLine(10.0, TEXT, 14.0)],
            source="test",
            title="兜底测试",
            artist="LyricDesk",
            provider="test",
        )
        self.snapshot_value = Snapshot(
            track=Track("兜底测试", "LyricDesk", "", 60.0),
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


def ink_width(image: QImage) -> int:
    image = image.convertToFormat(QImage.Format.Format_ARGB32)
    raw = bytes(image.bits())
    stride = image.bytesPerLine()
    left, right = image.width(), -1
    for y in range(image.height()):
        row = y * stride
        for x in range(image.width()):
            if raw[row + x * 4 + 3] > 8:
                left = min(left, x)
                right = max(right, x)
    return 0 if right < 0 else right - left + 1


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    register_all()
    temp = Path(tempfile.mkdtemp(prefix="lyricdesk-fallback-log-"))
    original_app_dir = window_module.app_dir
    window_module.app_dir = lambda: temp

    settings = Settings()
    settings.font_family = "Microsoft YaHei UI"
    settings.font_size = 60
    settings.width = 900
    settings.lyric_lines = 1
    settings.lyric_effect = "off"
    settings.lyric_glow = 0.0
    settings.lyric_jitter = 0.0
    settings.lyric_align = "center"
    settings.show_song_info = False
    settings.background = False
    settings.text_depth_h = 0.0
    settings.text_depth_v = 0.0
    settings.text_tilt = 0.0
    settings.show_wave = False
    settings.real_wave = False
    settings.auto_show_on_music = False

    window = LyricWindow(settings, Engine())
    window.screen = lambda: FakeScreen()
    window._timer.stop()
    window._topmost_timer.stop()
    window.show()
    QApplication.processEvents()
    worker = line_art_worker.client()
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and worker._connection is None:
        QApplication.processEvents()
        time.sleep(0.02)

    family, size, weight = window._fonts["list_cur"]
    fitted = window_module.fit_size(
        TEXT,
        family,
        weight,
        size,
        window._current_line_width(),
    )
    live_sprite = window_module.make_sprite(TEXT, family, fitted, weight)
    base_color = QColor(255, 255, 255, 120)
    args = (base_color, None, None)
    live_key = render.line_art_key(
        live_sprite,
        *args,
        shadow=True,
        dpr=window.devicePixelRatioF(),
        glow=False,
    )

    render.clear_line_cache()
    old_sprite = window_module.make_sprite(TEXT, family, max(12, fitted - 12), weight)
    old_art = render.make_line_art(
        old_sprite,
        *args,
        shadow=True,
        dpr=window.devicePixelRatioF(),
        glow=False,
    )
    old_key = render.line_art_key(
        old_sprite,
        *args,
        shadow=True,
        dpr=window.devicePixelRatioF(),
        glow=False,
    )
    live_art = render.make_line_art(
        live_sprite,
        *args,
        shadow=True,
        dpr=window.devicePixelRatioF(),
        glow=False,
    )
    live_image = QImage(1200, 220, QImage.Format.Format_ARGB32)
    live_image.fill(Qt.GlobalColor.transparent)
    live_painter = QPainter(live_image)
    render.draw_line_art(live_painter, live_art, 600, 120)
    live_painter.end()
    live_width = ink_width(live_image)
    render._LINE_CACHE.clear()
    render._LINE_CACHE[old_key] = old_art
    render.start_draw_trace()
    fallback_art = window_module._paint_line_art(
        window,
        live_sprite,
        *args,
        shadow=True,
        dpr=window.devicePixelRatioF(),
        glow=False,
    )
    image = QImage(1200, 220, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    render.draw_line_art(
        painter,
        fallback_art,
        600,
        120,
        scale=fallback_art.render_scale,
    )
    painter.end()
    fallback_width = ink_width(image)
    trace = render.stop_draw_trace()
    fallback_row = next((item for item in trace if item["text"] == TEXT), None)
    width_error = abs(fallback_width - live_width)
    print(f"live_advance={live_sprite.advance:.1f} ink_width={fallback_width} "
          f"exact_ink_width={live_width} width_error={width_error} "
          f"scale={fallback_row['scale'] if fallback_row else None}")

    recovered_in = -1
    for frame in range(1, 6):
        window._drain_line_art_jobs(2)
        QApplication.processEvents()
        if live_key in render._LINE_CACHE:
            recovered_in = frame
            break
        time.sleep(0.033)
    print(f"recovered_in_frames={recovered_in}")
    print(f"live_key_in_jobs={live_key in window._prefetch_jobs}")
    print(f"cache_keys={len(render._LINE_CACHE)} jobs={len(window._prefetch_jobs)}")

    log_path = temp / "line-art.log"
    log_text = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    miss_requeue = log_text.count('"event": "miss_requeue"')
    mismatch = log_text.count('"event": "advance-mismatch"')
    print(f"miss_requeue={miss_requeue} advance_mismatch_logged={mismatch}")

    max_font_width_error = width_error
    for font_size in range(46, 66):
        live = window_module.make_sprite(TEXT, family, font_size, weight)
        exact = render.make_line_art(
            live,
            *args,
            shadow=True,
            dpr=window.devicePixelRatioF(),
            glow=False,
        )
        exact_image = QImage(1200, 220, QImage.Format.Format_ARGB32)
        exact_image.fill(Qt.GlobalColor.transparent)
        exact_painter = QPainter(exact_image)
        render.draw_line_art(exact_painter, exact, 600, 120)
        exact_painter.end()
        exact_width = ink_width(exact_image)

        old = window_module.make_sprite(TEXT, family, max(12, font_size - 8), weight)
        old_art = render.make_line_art(
            old,
            *args,
            shadow=True,
            dpr=window.devicePixelRatioF(),
            glow=False,
        )
        old_key = render.line_art_key(
            old,
            *args,
            shadow=True,
            dpr=window.devicePixelRatioF(),
            glow=False,
        )
        render._LINE_CACHE.clear()
        render._LINE_CACHE[old_key] = old_art
        fallback = window_module._paint_line_art(
            window,
            live,
            *args,
            shadow=True,
            dpr=window.devicePixelRatioF(),
            glow=False,
        )
        fallback_image = QImage(1200, 220, QImage.Format.Format_ARGB32)
        fallback_image.fill(Qt.GlobalColor.transparent)
        fallback_painter = QPainter(fallback_image)
        render.draw_line_art(
            fallback_painter,
            fallback,
            600,
            120,
            scale=fallback.render_scale,
        )
        fallback_painter.end()
        max_font_width_error = max(
            max_font_width_error,
            abs(ink_width(fallback_image) - exact_width),
        )
        QApplication.processEvents()
    print(f"font_size_20_max_width_error={max_font_width_error}")

    # 稳定态重新开日志：所有精确图已在缓存时不应再出现 mismatch。
    if log_path.exists():
        log_path.unlink()
    render.clear_line_cache()
    colors = settings.colors
    render.make_line_art(
        live_sprite,
        QColor(255, 255, 255, 120),
        (colors["c1"], colors["c2"], colors["c3"]),
        QColor(colors["glow"]),
        outline_width=max(2.0, fitted * 0.05),
        outline_color=QColor(0, 0, 0, 150),
        shadow=True,
        dpr=window.devicePixelRatioF(),
        glow=settings.lyric_glow > 0,
    )
    window._prefetch_jobs.clear()
    for _ in range(10):
        window._tick()
        QApplication.processEvents()
    final_log = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    final_mismatch = final_log.count('"event": "advance-mismatch"')
    print(f"stable_advance_mismatch={final_mismatch}")

    ok = (
        max_font_width_error <= 2
        and recovered_in > 0
        and recovered_in <= 5
        and miss_requeue > 0
        and mismatch > 0
        and final_mismatch == 0
    )
    print(f"\n结果：{'通过' if ok else '失败'}")
    window.close()
    window.deleteLater()
    QApplication.processEvents()
    window_module.app_dir = original_app_dir
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
