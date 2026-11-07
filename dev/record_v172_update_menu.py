"""录制 v1.7.2 右键更新圆环：点击后菜单不关闭，进度持续推进。"""

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

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu, QWidgetAction

from lyricdesk import config

config.SETTINGS_PATH = Path(tempfile.mkdtemp(prefix="lyricdesk-v172-update-")) / "settings.json"

from lyricdesk.config import Settings
from lyricdesk.fonts import register_all
from lyricdesk.update import UpdateInfo
from lyricdesk.window import LyricWindow, UpdateRingActionWidget
import rec_diff


def fake_engine():
    path = ROOT / "dev" / "check_v170_disc.py"
    spec = importlib.util.spec_from_file_location("_v172_update_engine", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.FakeEngine()


def compose(menu: QMenu, state: str) -> QImage:
    menu.adjustSize()
    menu_layer = menu.grab()
    width = max(900, menu_layer.width() + 180)
    height = max(420, menu_layer.height() + 120)
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    background = QLinearGradient(0, 0, width, height)
    background.setColorAt(0.0, QColor("#111827"))
    background.setColorAt(1.0, QColor("#2b2140"))
    painter.fillRect(image.rect(), background)
    painter.drawPixmap(
        QPointF(
            (width - menu_layer.width()) / 2,
            (height - menu_layer.height()) / 2,
        ),
        menu_layer,
    )
    painter.setPen(QColor("#cbd5e1"))
    painter.drawText(30, 34, f"LyricDesk v1.7.2 · {state}")
    painter.end()
    return image


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    register_all()
    settings = Settings()
    settings.background = False
    window = LyricWindow(settings, fake_engine())
    info = UpdateInfo(
        ok=True,
        latest="9.9.9",
        notes="",
        url="https://example.com",
        installer="https://example.com/setup.exe",
    )
    menu = QMenu()
    widget = UpdateRingActionWidget(window, info)
    action = QWidgetAction(menu)
    action.setDefaultWidget(widget)
    menu.addAction(action)
    menu.addSeparator()
    menu.addAction("重新获取歌词")
    menu.addAction("手动选歌词…")
    menu.addAction("设置…")
    window._menu_update_widget = widget
    window._set_menu_update_state("idle")
    clicked: list = []
    window._start_menu_update = lambda item: clicked.append(item)
    menu.show()
    app.processEvents()
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=QPoint(30, 20))
    app.processEvents()
    if not clicked or not menu.isVisible():
        print("点击后菜单关闭或未触发更新")
        return 1

    ffmpeg = rec_diff.ffmpeg_path()
    if ffmpeg is None:
        print("找不到 ffmpeg")
        return 2
    output = ROOT / "dev" / "v1.7.2-update-ring.mp4"
    output.unlink(missing_ok=True)
    fps = 12
    seconds = 6
    process = subprocess.Popen(
        [
            str(ffmpeg),
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgra",
            "-s",
            "900x420",
            "-r",
            str(fps),
            "-i",
            "-",
            "-an",
            "-c:v",
            "mpeg4",
            "-q:v",
            "3",
            "-pix_fmt",
            "yuv420p",
            str(output),
        ],
        stdin=subprocess.PIPE,
    )
    assert process.stdin is not None
    try:
        for frame_index in range(fps * seconds):
            elapsed = frame_index / fps
            if elapsed < 1.0:
                state = "idle"
                window._set_menu_update_state("idle")
            elif elapsed < 5.0:
                state = "downloading"
                done = int((elapsed - 1.0) / 4.0 * 100)
                window._set_menu_update_state("downloading", done=done, total=100)
            else:
                state = "installing"
                window._set_menu_update_state("installing", done=100, total=100)
            app.processEvents()
            image = compose(menu, state).convertToFormat(QImage.Format.Format_ARGB32)
            process.stdin.write(bytes(image.constBits()))
    finally:
        process.stdin.close()
        process.wait(timeout=30)
        menu.close()
    print(output)
    return 0 if output.exists() else 1


if __name__ == "__main__":
    raise SystemExit(main())
