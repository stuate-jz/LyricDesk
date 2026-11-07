"""v1.7.3 软边扫光接线、off 回归、micro 与长句截图。"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from lyricdesk import config

config.SETTINGS_PATH = Path(tempfile.mkdtemp(prefix="lyricdesk-v173-fx-")) / "settings.json"

from lyricdesk.config import Settings
from lyricdesk.fonts import register_all
from lyricdesk.window import LyricWindow


def fake_engine():
    path = ROOT / "dev" / "check_v170_disc.py"
    spec = importlib.util.spec_from_file_location("_v173_engine", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.FakeEngine()


def render(window: LyricWindow) -> QPixmap:
    pixmap = QPixmap(window.size())
    pixmap.fill(QColor(0, 0, 0, 0))
    window.render(pixmap)
    return pixmap


def difference(left: QPixmap, right: QPixmap) -> int:
    a = left.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    b = right.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    if a.size() != b.size():
        return 10**9
    return sum(x != y for x, y in zip(bytes(a.constBits()), bytes(b.constBits())))


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    register_all()
    out = ROOT / "dev" / "v173_shots"
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
    settings.lyric_effect = "off"
    engine = fake_engine()
    current = engine.lyrics.lines[8]
    engine._snapshot.position = current.time + 1.35
    window = LyricWindow(settings, engine)
    window.show()
    app.processEvents()
    window._display_idx = 8
    window._scroll_ready = True
    window._scroll_from = 8.0
    window._scroll_target = 8.0
    render(window)
    app.processEvents()

    off = render(window)
    off_again = render(window)
    off_delta = difference(off, off_again)
    check("off 档逐像素不变", off_delta == 0, str(off_delta))
    off.save(str(out / "off.png"))
    diff_image = QImage(off.size(), QImage.Format.Format_ARGB32)
    diff_image.fill(QColor("#000000"))
    diff_painter = QPainter(diff_image)
    diff_painter.setPen(QColor("#ffffff"))
    diff_painter.drawText(
        diff_image.rect(),
        int(Qt.AlignmentFlag.AlignCenter),
        f"off diff = {off_delta} pixel",
    )
    diff_painter.end()
    diff_image.save(str(out / "off-diff.png"))

    settings.lyric_effect = "word"
    window._commit()
    word = render(window)
    word.save(str(out / "word-有逐字.png"))
    check("有逐字 word 与 off 有可见差异", difference(off, word) > 1000, str(difference(off, word)))

    # 放大前沿，保留软边和拖尾证据。
    crop = word.copy(
        max(0, window.width() // 2 - 300),
        max(0, window.height() // 2 - 70),
        min(600, window.width()),
        140,
    )
    crop.scaled(
        1200,
        280,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.FastTransformation,
    ).save(str(out / "word-软边放大.png"))

    current.words = []
    window._commit()
    plain_word = render(window)
    plain_word.save(str(out / "word-无逐字.png"))
    check("无逐字 word 与 off 有可见差异", difference(off, plain_word) > 1000, str(difference(off, plain_word)))

    micro = engine.lyrics.lines[9]
    micro.text = "嘿"
    micro.words = []
    micro.time = current.time + 3.8
    micro.end = micro.time + 0.08
    engine._snapshot.position = micro.time + 0.02
    micro_image = render(window)
    micro_image.save(str(out / "micro-嘿.png"))
    check("micro 行可绘制", not micro_image.isNull())

    long_line = engine.lyrics.lines[10]
    long_line.text = "这一行故意写得非常非常长用来确认拖尾不会跑到下一行之外"
    long_line.words = []
    long_line.end = long_line.time + 4.5
    engine._snapshot.position = long_line.time + 2.0
    long_image = render(window)
    long_image.save(str(out / "long-拖尾.png"))
    check("20 字以上长句可绘制", not long_image.isNull())

    settings.lyric_layout = "disc"
    window._apply_disc_change(None)
    disc = render(window)
    disc.save(str(out / "disc-扫光.png"))
    check("圆盘 word 可绘制", not disc.isNull())

    window.close()
    window.deleteLater()
    app.processEvents()
    print("全部通过" if not failures else f"{failures} 项失败")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
