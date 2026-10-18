r"""自检：倾斜改成真 3D 透视（任务 1）。

量两件事：
  1. 同一句歌词在倾斜 0 / 0.2 / 0.5 / 0.8 下渲染出来的实际像素宽度
     （应该只变小、不放大；0.8 时也不能突然撑大）；
  2. 窗口宽 380 与 1440 时，同一句歌词的变形幅度应该接近
     （不能出现「窗口越宽越扭曲」）。

用法： python dev\check_perspective.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from PySide6.QtGui import QColor, QImage, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lyricdesk import config  # noqa: E402

config.SETTINGS_PATH = Path(tempfile.mkdtemp(prefix="lyricdesk-persp-")) / "settings.json"

from lyricdesk.config import Settings  # noqa: E402
from lyricdesk.lyrics import LyricLine, Lyrics  # noqa: E402
from lyricdesk.smtc import Snapshot, Track  # noqa: E402
from lyricdesk.window import LyricWindow, _project_points  # noqa: E402

FAILS = 0
LINE = "他们说爱过就可以伤和别离"


class FakeEngine:
    def __init__(self) -> None:
        self._snapshot = Snapshot(
            track=Track(title="海屿你", artist="马也_Crabbit", album="海屿你", duration=219.0),
            position=10.0,
            is_playing=True,
            status=4,
            source="QQMusic.exe",
        )
        self._lyrics = Lyrics(
            lines=[LyricLine(time=0.0, text=LINE, end=8.0)],
            source="QQ音乐",
            title="海屿你",
            artist="马也_Crabbit",
            albummid="",
            album="海屿你",
        )

    @property
    def lyrics(self):
        return self._lyrics

    def snapshot(self):
        return self._snapshot

    def players(self):
        return []


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILS
    if not ok:
        FAILS += 1
    print(f"  {'OK  ' if ok else 'FAIL'} {name}" + (f"  —— {detail}" if detail else ""))


def make_window(width: int) -> LyricWindow:
    settings = Settings()
    settings.mode = "lyrics"
    settings.width = width
    settings.lyric_lines = 1
    settings.show_song_info = False
    settings.background = False
    settings.text_depth_v = 0.0
    settings.text_depth_h = 0.0
    settings.text_tilt = 0.0
    settings.clamp()
    window = LyricWindow(settings, FakeEngine())
    window._anim_t0 = -1000.0  # 跳过切词回弹，保证每次渲染的缩放一致
    return window


def ink_bbox(window: LyricWindow) -> tuple[int, int, int, int] | None:
    layer = QPixmap(window.size())
    layer.fill(QColor(0, 0, 0, 0))
    window.render(layer)
    img = layer.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    width, height = img.width(), img.height()
    data = bytes(img.constBits())
    bpl = img.bytesPerLine()
    min_x, min_y, max_x, max_y = width, height, -1, -1
    for y in range(height):
        row = data[y * bpl:(y + 1) * bpl]
        hits = [x for x, a in enumerate(row[3::4]) if a > 28]
        if not hits:
            continue
        min_x = min(min_x, hits[0])
        max_x = max(max_x, hits[-1])
        min_y = min(min_y, y)
        max_y = max(max_y, y)
    if max_x < 0:
        return None
    return min_x, min_y, max_x, max_y


def text_span(window: LyricWindow) -> int:
    box = ink_bbox(window)
    return 0 if box is None else box[2] - box[0] + 1


def main() -> int:
    app = QApplication(sys.argv)

    print("1) 倾斜 0 → 0.8：同一句歌词的实际像素宽度")
    window = make_window(380)
    base = 0
    ratios = {}
    for depth in (0.0, 0.2, 0.5, 0.8):
        window.settings.text_depth_h = depth
        window._commit(resize=True)
        span = text_span(window)
        if depth == 0.0:
            base = span
        ratios[depth] = span / base if base else 0
        box = ink_bbox(window)
        print(f"      倾斜 {depth:.1f}：宽 {span}px  高 {box[3] - box[1] + 1 if box else 0}px  "
              f"（相对 0：{span / base:.3f}×）")
    check("0.8 时没有变大", ratios[0.8] <= 1.02, f"{ratios[0.8]:.3f}×")
    check("0.8 时明显变小（不是只差几个像素）", ratios[0.8] <= 0.95, f"{ratios[0.8]:.3f}×")
    check(
        "变化是连续的（0.2 的缩小幅度 < 0.5 < 0.8）",
        ratios[0.2] >= ratios[0.5] >= ratios[0.8],
        f"{ratios[0.2]:.3f} / {ratios[0.5]:.3f} / {ratios[0.8]:.3f}",
    )

    print()
    print("2) 近边 / 远边长度比（0.8 = 42°）")
    width = float(window.settings.width)
    height = window._list_slot * window._list_count
    import math

    from lyricdesk.window import depth_angle

    theta = math.radians(depth_angle(0.8))
    corners = _project_points(((-1, -1), (1, -1), (1, 1), (-1, 1)), width, height, theta, 0.0)
    left_edge = abs(corners[3][1] - corners[0][1])
    right_edge = abs(corners[2][1] - corners[1][1])
    near, far = max(left_edge, right_edge), min(left_edge, right_edge)
    print(f"      左边缘 {left_edge:.1f}px / 右边缘 {right_edge:.1f}px → 比值 {near / far:.2f}")
    check("两侧宽度差 ≤ 1.6 倍", near / far <= 1.6, f"{near / far:.2f}")

    print()
    print("3) 窗口宽 380 vs 1440：同一句歌词的变形幅度")
    spans = {}
    for width_px in (380, 1440):
        w = make_window(width_px)
        plain = text_span(w)
        w.settings.text_depth_h = 0.8
        w._commit(resize=True)
        tilted = text_span(w)
        spans[width_px] = tilted / plain
        print(f"      宽 {width_px}：平放 {plain}px → 倾斜 {tilted}px（{tilted / plain:.3f}×）")
    diff = abs(spans[380] - spans[1440])
    check("两种窗口宽度下变形幅度接近（差 < 0.12）", diff < 0.12, f"差 {diff:.3f}")

    print()
    print("4) 上下 + 左右 + 旋转 同时开")
    w = make_window(380)
    w.settings.text_depth_h = 0.6
    w.settings.text_depth_v = -0.5
    w.settings.text_tilt = 18.0
    w._commit(resize=True)
    box = ink_bbox(w)
    check("组合倾斜能正常渲染", box is not None and box[2] > box[0], str(box))

    print()
    print("全部通过" if FAILS == 0 else f"{FAILS} 项没通过")
    return 0 if FAILS == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
