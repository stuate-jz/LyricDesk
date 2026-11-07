"""v1.7.6 副歌识别、缓存与 off 接入回归。"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import QApplication

from lyricdesk import config

config.SETTINGS_PATH = Path(tempfile.mkdtemp(prefix="lyricdesk-v176-chorus-")) / "settings.json"

from lyricdesk.config import Settings
from lyricdesk.fonts import register_all
from lyricdesk.lyricfx import _CHORUS_CACHE, chorus_weights
from lyricdesk.lyrics import LyricLine
from lyricdesk.window import LyricWindow


def fake_engine():
    path = ROOT / "dev" / "check_v170_disc.py"
    spec = importlib.util.spec_from_file_location("_v176_chorus_engine", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.FakeEngine()


def render(window: LyricWindow) -> QPixmap:
    pixmap = QPixmap(window.size())
    pixmap.fill(QColor(0, 0, 0, 0))
    window.render(pixmap)
    return pixmap


def raw(pixmap: QPixmap) -> bytes:
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    return bytes(image.constBits())


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    register_all()
    failures = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        failures += 0 if ok else 1
        print(f"  {'OK  ' if ok else 'FAIL'} {name}" + (f"  —— {detail}" if detail else ""))

    lines = [
        LyricLine(0.0, "主歌第一句", 3.0),
        LyricLine(4.0, "副歌重复句", 7.0),
        LyricLine(8.0, "主歌第二句", 11.0),
        LyricLine(12.0, "副歌重复句", 15.0),
        LyricLine(16.0, "副歌重复句", 19.0),
        LyricLine(20.0, "副歌重复变体", 23.0),
    ]
    weights = chorus_weights(lines)
    check("重复 3 次的副歌权重为 1", weights[1] == weights[3] == weights[4] == 1.0, str(weights))
    check("前 4 字相同的变体权重为 0.5", weights[5] == 0.5, str(weights[5]))
    unique = [
        LyricLine(index * 3.0, f"完全不同第{index}句", index * 3.0 + 2.5)
        for index in range(10)
    ]
    unique_weights = chorus_weights(unique)
    check("无重复歌词返回全 0", unique_weights == [0.0] * 10, str(unique_weights))

    _CHORUS_CACHE.clear()
    started = time.perf_counter()
    for index in range(5):
        sample = [
            LyricLine(
                index * 100.0 + row * 2.0,
                f"歌曲{index}副歌" if row % 3 == 0 else f"歌曲{index}正文{row}",
                index * 100.0 + row * 2.0 + 1.8,
            )
            for row in range(200)
        ]
        chorus_weights(sample)
    elapsed = (time.perf_counter() - started) / 5.0 * 1000.0
    check("换歌 5 次缓存不超过 4", len(_CHORUS_CACHE) <= 4, str(len(_CHORUS_CACHE)))
    check("单次副歌检测 ≤5ms", elapsed <= 5.0, f"{elapsed:.3f}ms")

    settings = Settings()
    settings.font_family = "Smiley Sans"
    settings.background = False
    settings.show_song_info = False
    settings.lyric_effect = "off"
    engine = fake_engine()
    window = LyricWindow(settings, engine)
    window.show()
    app.processEvents()
    window._display_idx = 8
    window._scroll_ready = True
    window._scroll_from = window._scroll_target = 8.0
    line = engine.lyrics.lines[8]
    window._chorus_key = (id(engine.lyrics), len(engine.lyrics.lines))
    window._chorus_map = {id(line): 0.0}
    render(window)
    off0 = render(window)
    window._chorus_map[id(line)] = 1.0
    off1 = render(window)
    check("effect=off 时副歌乘子不改变画面", raw(off0) == raw(off1))

    window.close()
    window.deleteLater()
    app.processEvents()
    print("全部通过" if not failures else f"{failures} 项失败")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
