"""v1.7.5：随机错落行槽、净空、开关与圆盘禁用回归。"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import QApplication

from lyricdesk import config

config.SETTINGS_PATH = Path(tempfile.mkdtemp(prefix="lyricdesk-v175-")) / "settings.json"

from lyricdesk.config import Settings
from lyricdesk.fonts import register_all
from lyricdesk import render as render_mod
from lyricdesk.window import MARGIN, PAD, LyricWindow


def fake_engine():
    path = ROOT / "dev" / "check_v170_disc.py"
    spec = importlib.util.spec_from_file_location("_v175_engine", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.FakeEngine()


def render(window: LyricWindow) -> QPixmap:
    pixmap = QPixmap(window.size())
    pixmap.fill(QColor(0, 0, 0, 0))
    window.render(pixmap)
    return pixmap


def bytes_of(pixmap: QPixmap) -> bytes:
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    return bytes(image.constBits())


def ink_bands(pixmap: QPixmap) -> tuple[list[tuple[int, int]], int]:
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    raw = bytes(image.constBits())
    rows = []
    for y in range(image.height()):
        start = y * image.width() * 4
        has_ink = any(raw[start + x * 4 + 3] > 12 for x in range(image.width()))
        rows.append(has_ink)
    bands = []
    start = None
    for y, has_ink in enumerate(rows + [False]):
        if has_ink and start is None:
            start = y
        elif not has_ink and start is not None:
            bands.append((start, y - 1))
            start = None
    gaps = [
        right[0] - left[1] - 1
        for left, right in zip(bands, bands[1:])
    ]
    return bands, min(gaps) if gaps else 10**9


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    register_all()
    failures = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        failures += 0 if ok else 1
        print(f"  {'OK  ' if ok else 'FAIL'} {name}" + (f"  —— {detail}" if detail else ""))

    settings = Settings()
    settings.font_family = "Smiley Sans"
    settings.background = False
    settings.show_song_info = False
    settings.lyric_effect = "off"
    settings.lyric_layout = "list"
    settings.lyric_lines = 5
    settings.lyric_scatter = True
    settings.lyric_chaos = 1.0
    engine = fake_engine()
    window = LyricWindow(settings, engine)
    window.show()
    app.processEvents()
    window._display_idx = 8
    window._scroll_ready = True
    window._scroll_from = window._scroll_target = 8.0
    window._anim_t0 = -100.0
    render(window)
    app.processEvents()

    image = render(window)
    image.save(str(ROOT / "dev" / "v175_scatter-100.png"))
    bands, clearance = ink_bands(image)
    check("5 行面板错落 100% 墨迹带数为 5", len(bands) == 5, str(bands))
    check("相邻行最小净空 ≥ 2px", clearance >= 2, str(clearance))

    for chaos in (0.0, 0.35, 1.0):
        settings.lyric_chaos = chaos
        window._commit(resize=True)
        expected_h = int(PAD * 2 + window._list_slot * window._list_count) + MARGIN * 2
        check(
            f"错落 {chaos:.0%} 时窗口高度等于行槽总和",
            window.height() == expected_h,
            f"{window.height()} / {expected_h}",
        )

    settings.lyric_scatter = False
    settings.lyric_chaos = 1.0
    window._commit(resize=True)
    disabled = render(window)
    width_disabled = window._auto_width()
    settings.lyric_scatter = True
    settings.lyric_chaos = 0.0
    window._commit(resize=True)
    zero = render(window)
    width_zero = window._auto_width()
    check("开关关闭与强度 0% 逐字节相同", bytes_of(disabled) == bytes_of(zero))
    check("开关关闭时自动宽度与强度 0 相同", width_disabled == width_zero, f"{width_disabled} / {width_zero}")

    settings.lyric_layout = "disc"
    settings.lyric_scatter = False
    settings.lyric_chaos = 1.0
    window._commit(resize=True)
    window._display_idx = 8
    window._scroll_ready = True
    window._scroll_from = window._scroll_target = 8.0
    render(window)
    disc_off = render(window)
    settings.lyric_scatter = True
    disc_on = render(window)
    check(
        "圆盘 scatter_amount 恒为 0",
        settings.scatter_amount() == 0.0,
    )
    disc_equal = bytes_of(disc_off) == bytes_of(disc_on)
    disc_off.save(str(ROOT / "dev" / "v175_disc-off.png"))
    disc_on.save(str(ROOT / "dev" / "v175_disc-on.png"))
    check("圆盘开关前后渲染一致", disc_equal)

    window.close()
    window.deleteLater()
    app.processEvents()
    print("全部通过" if not failures else f"{failures} 项失败")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
