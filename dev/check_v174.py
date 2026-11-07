"""v1.7.4 双光晕、逐字弹簧、入场和确定性错落回归。"""

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

config.SETTINGS_PATH = Path(tempfile.mkdtemp(prefix="lyricdesk-v174-")) / "settings.json"

from lyricdesk.config import Settings
from lyricdesk.fonts import register_all
from lyricdesk.lyricfx import build_char_timeline, render_budget
from lyricdesk.window import LyricWindow


def fake_engine():
    path = ROOT / "dev" / "check_v170_disc.py"
    spec = importlib.util.spec_from_file_location("_v174_engine", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.FakeEngine()


def render(window: LyricWindow) -> QPixmap:
    pixmap = QPixmap(window.size())
    pixmap.fill(QColor(0, 0, 0, 0))
    window.render(pixmap)
    return pixmap


def image_delta(left: QPixmap, right: QPixmap) -> int:
    a = left.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    b = right.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    if a.size() != b.size():
        return 10**9
    return sum(x != y for x, y in zip(bytes(a.constBits()), bytes(b.constBits())))


def alpha_energy(pixmap: QPixmap) -> int:
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    return sum(bytes(image.constBits())[3::4])


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    register_all()
    out = ROOT / "dev" / "v174_shots"
    out.mkdir(parents=True, exist_ok=True)
    failures = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        failures += 0 if ok else 1
        print(f"  {'OK  ' if ok else 'FAIL'} {name}" + (f"  —— {detail}" if detail else ""))

    settings = Settings()
    settings.font_family = "Smiley Sans"
    settings.background = False
    settings.show_song_info = False
    settings.lyric_effect = "word"
    engine = fake_engine()
    line = engine.lyrics.lines[8]
    window = LyricWindow(settings, engine)
    window.show()
    app.processEvents()
    window._display_idx = 8
    window._scroll_ready = True
    window._scroll_from = window._scroll_target = 8.0
    window._anim_t0 = -100.0
    render(window)

    # 光晕强度必须单调。
    engine._snapshot.position = line.time + 1.4
    energies = []
    for glow in (0.0, 0.5, 1.0, 2.0):
        settings.lyric_glow = glow
        window._commit()
        image = render(window)
        image.save(str(out / f"glow-{glow:g}.png"))
        energies.append(alpha_energy(image))
    check(
        "光晕亮度单调递增",
        all(later >= earlier for earlier, later in zip(energies, energies[1:])),
        str(energies),
    )

    settings.lyric_effect = "off"
    settings.lyric_glow = 0.0
    window._commit()
    off0 = render(window)
    settings.lyric_glow = 2.0
    window._commit()
    off2 = render(window)
    check("off 档不受光晕开关影响", image_delta(off0, off2) == 0, str(image_delta(off0, off2)))

    # 入场三帧。
    settings.lyric_effect = "word"
    settings.lyric_glow = 1.0
    budget = render_budget(line.end - line.time)
    for index, fraction in enumerate((0.02, 0.5, 1.0)):
        engine._snapshot.position = line.time + max(0.001, budget.enter * fraction)
        window._commit()
        frame = render(window)
        frame.save(str(out / f"entry-{index + 1}.png"))
    check("normal 入场三帧生成", True)

    # 逐字弹簧帧。
    settings.lyric_effect = "bounce"
    window._commit()
    spring_frames = []
    for index in range(6):
        engine._snapshot.position = line.time + 0.8 + index * 0.035
        frame = render(window)
        spring_frames.append(frame)
        frame.save(str(out / f"bounce-{index + 1}.png"))
    check(
        "bounce 连续帧发生变化",
        any(image_delta(spring_frames[0], item) > 20 for item in spring_frames[1:]),
    )

    # chaos 确定性。
    settings.lyric_effect = "off"
    settings.lyric_chaos = 0.5
    settings.lyric_layout = "list"
    window._commit(resize=True)
    a = window._chaos_transform(line)
    b = window._chaos_transform(line)
    c = window._chaos_transform(engine.lyrics.lines[10])
    check("同一行 chaos 完全确定", a == b, str((a, b)))
    check("不同行 chaos 位置不同", a != c, str((a, c)))
    chaos1 = render(window)
    chaos2 = render(window)
    check("chaos 重绘像素一致", image_delta(chaos1, chaos2) == 0, str(image_delta(chaos1, chaos2)))

    settings.lyric_layout = "disc"
    settings.lyric_chaos = 1.0
    disc1 = window._chaos_transform(line)
    settings.lyric_chaos = 0.0
    disc0 = window._chaos_transform(line)
    check("圆盘忽略 chaos", disc1 == disc0 == (0.0, 0.0, 1.0, 0.0), str((disc1, disc0)))

    window.close()
    window.deleteLater()
    app.processEvents()
    print("全部通过" if not failures else f"{failures} 项失败")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
