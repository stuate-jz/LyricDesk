"""输出 v1.7.2 圆盘十个角度的逐帧叠加图和圆心坐标。"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from lyricdesk import config

config.SETTINGS_PATH = Path(tempfile.mkdtemp(prefix="lyricdesk-v172-angles-")) / "settings.json"

from lyricdesk.config import Settings
from lyricdesk.fonts import register_all
from lyricdesk.window import LyricWindow


def fake_engine():
    path = ROOT / "dev" / "check_v170_disc.py"
    spec = importlib.util.spec_from_file_location("_v172_angles", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.FakeEngine()


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    register_all()
    settings = Settings()
    settings.font_family = "Smiley Sans"
    settings.background = False
    settings.lyric_layout = "disc"
    settings.lyric_lines = 7
    window = LyricWindow(settings, fake_engine())
    window.show()
    app.processEvents()
    out = ROOT / "dev" / "v172_shots"
    out.mkdir(parents=True, exist_ok=True)

    frames = []
    rows = []
    start = window._disc_center_on_screen()
    angles = (-90, -70, -50, -30, -10, 10, 30, 50, 70, 90)
    for angle in angles:
        window._set_disc_angle(angle)
        app.processEvents()
        center = window._disc_center_on_screen()
        rows.append((angle, center.x(), center.y(), center.x() - start.x(), center.y() - start.y()))
        pixmap = QPixmap(window.size())
        pixmap.fill(QColor(0, 0, 0, 0))
        window.render(pixmap)
        frames.append((angle, pixmap))

    cell_w, cell_h = 420, 330
    sheet = QImage(cell_w * 5, cell_h * 2, QImage.Format.Format_ARGB32)
    painter = QPainter(sheet)
    background = QLinearGradient(0, 0, sheet.width(), sheet.height())
    background.setColorAt(0.0, QColor("#0f172a"))
    background.setColorAt(1.0, QColor("#2b2140"))
    painter.fillRect(sheet.rect(), background)
    title_font = QFont("Microsoft YaHei UI")
    title_font.setPixelSize(18)
    painter.setFont(title_font)
    for index, (angle, pixmap) in enumerate(frames):
        x = (index % 5) * cell_w
        y = (index // 5) * cell_h
        scaled = pixmap.scaled(
            cell_w - 20,
            cell_h - 42,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        painter.setPen(QColor("#f8fafc"))
        painter.drawText(x + 12, y + 24, f"{angle:+d}°")
        painter.drawPixmap(
            x + (cell_w - scaled.width()) // 2,
            y + 32 + (cell_h - 42 - scaled.height()) // 2,
            scaled,
        )
    painter.end()
    sheet.save(str(out / "angle-10-step-overlay.png"))
    csv = out / "angle-centers.csv"
    csv.write_text(
        "angle,x,y,dx,dy\n"
        + "\n".join(
            f"{angle},{x:.2f},{y:.2f},{dx:.2f},{dy:.2f}"
            for angle, x, y, dx, dy in rows
        )
        + "\n",
        encoding="utf-8",
    )
    print(out / "angle-10-step-overlay.png")
    print(csv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
