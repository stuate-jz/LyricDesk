"""录制 v1.7.4：入场、双光晕扫光、逐字弹簧、确定性错落。"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dev"))

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from lyricdesk import config

config.SETTINGS_PATH = Path(tempfile.mkdtemp(prefix="lyricdesk-v174-video-")) / "settings.json"

from lyricdesk.config import Settings
from lyricdesk.fonts import register_all
from lyricdesk.window import LyricWindow
import rec_diff


def fake_engine():
    path = ROOT / "dev" / "check_v170_disc.py"
    spec = importlib.util.spec_from_file_location("_v174_video_engine", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.FakeEngine()


def compose(window: LyricWindow, label: str) -> QImage:
    width, height = 960, 360
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    gradient = QLinearGradient(0, 0, width, height)
    gradient.setColorAt(0.0, QColor("#dce7f7"))
    gradient.setColorAt(0.55, QColor("#b9cce6"))
    gradient.setColorAt(1.0, QColor("#d9c5e8"))
    painter.fillRect(image.rect(), gradient)
    layer = QPixmap(window.size())
    layer.fill(Qt.GlobalColor.transparent)
    window.render(layer)
    painter.drawPixmap(
        QPointF((width - layer.width()) / 2, (height - layer.height()) / 2 + 12),
        layer,
    )
    painter.setPen(QColor("#13213a"))
    font = QFont("Microsoft YaHei UI")
    font.setPixelSize(19)
    font.setWeight(QFont.Weight.DemiBold)
    painter.setFont(font)
    painter.drawText(30, 40, "LyricDesk v1.7.4 · " + label)
    painter.end()
    return image


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    register_all()
    settings = Settings()
    settings.font_family = "Smiley Sans"
    settings.background = False
    settings.show_song_info = False
    settings.lyric_glow = 1.0
    engine = fake_engine()
    window = LyricWindow(settings, engine)
    window.show()
    app.processEvents()
    ffmpeg = rec_diff.ffmpeg_path()
    if ffmpeg is None:
        print("找不到 ffmpeg")
        return 2
    output = ROOT / "dev" / "v1.7.4-effects-30s.mp4"
    output.unlink(missing_ok=True)
    fps = 10
    process = subprocess.Popen(
        [
            str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "bgra", "-s", "960x360",
            "-r", str(fps), "-i", "-", "-an", "-c:v", "mpeg4",
            "-q:v", "3", "-pix_fmt", "yuv420p", str(output),
        ],
        stdin=subprocess.PIPE,
    )
    assert process.stdin is not None
    sections = (
        (8, "word", 0.0, "整行入场：模糊到清晰"),
        (9, "word", 0.0, "双光晕软边扫光"),
        (10, "bounce", 0.0, "逐字弹簧：相邻字错峰"),
        (11, "off", 0.5, "列表确定性错落"),
    )
    try:
        for line_index, effect, chaos, label in sections:
            line = engine.lyrics.lines[line_index]
            settings.lyric_effect = effect
            settings.lyric_chaos = chaos
            window._word_spring.reset()
            window._commit()
            window._display_idx = line_index
            window._scroll_ready = True
            window._scroll_from = window._scroll_target = float(line_index)
            for index in range(75):
                progress = index / max(1, 74)
                if label.startswith("整行入场"):
                    engine._snapshot.position = line.time + progress * 0.5
                else:
                    engine._snapshot.position = line.time + 0.05 + progress * 3.6
                app.processEvents()
                frame = compose(window, label).convertToFormat(QImage.Format.Format_ARGB32)
                process.stdin.write(bytes(frame.constBits()))
    finally:
        process.stdin.close()
        process.wait(timeout=30)
    print(output)
    return 0 if output.exists() else 1


if __name__ == "__main__":
    raise SystemExit(main())
