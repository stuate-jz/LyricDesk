"""把三种字体的渲染结果拼成一张对比图。"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

ITEMS = (
    ("A.  Microsoft YaHei UI  /  微软雅黑（系统默认）", "_font_yahei.png"),
    ("B.  Smiley Sans  /  得意黑（内置 1.9 MB）", "_font_smiley.png"),
    ("C.  LXGW Neo XiHei  /  霞鹜新晰黑（在线 7 MB）", "_font_xihei.png"),
    ("D.  LXGW Marker Gothic  /  霞鹜漫黑（在线 3.5 MB）", "_font_marker.png"),
)
ROW_H = 470


def main() -> int:
    app = QApplication(sys.argv)
    here = Path(__file__).resolve().parent
    canvas = QPixmap(1280, ROW_H * len(ITEMS) + 20)
    canvas.fill(QColor("#1c2029"))
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    font = QFont("Consolas")
    font.setPixelSize(17)
    painter.setFont(font)
    painter.setPen(QColor("#ffffff"))

    for index, (title, name) in enumerate(ITEMS):
        top = 12 + index * ROW_H
        painter.drawText(QRectF(20, top, 1240, 30), int(Qt.AlignmentFlag.AlignLeft), title)
        shot = QPixmap(str(here / name))
        if shot.isNull():
            continue
        painter.drawPixmap(20, int(top + 34), 1208, 423, shot)

    painter.end()
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else here / "font_montage.png"
    canvas.save(str(out))
    print("saved", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
