"""生成 Windows 应用图标 desktop-lyric.ico。"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

SIZES = (16, 24, 32, 48, 64, 128, 256)


def render(size: int) -> bytes:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    inset = size * 0.045
    radius = size * 0.26
    gradient = QLinearGradient(inset, inset, size - inset, size - inset)
    gradient.setColorAt(0.0, QColor("#38bdf8"))
    gradient.setColorAt(0.55, QColor("#818cf8"))
    gradient.setColorAt(1.0, QColor("#c084fc"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(gradient)
    painter.drawRoundedRect(
        QRectF(inset, inset, size - inset * 2, size - inset * 2), radius, radius
    )

    font = QFont("Segoe UI Symbol")
    font.setPixelSize(int(size * 0.62))
    font.setWeight(QFont.Weight.DemiBold)
    painter.setFont(font)
    painter.setPen(QColor(11, 16, 32))
    painter.drawText(QRectF(0, size * 0.03, size, size), Qt.AlignmentFlag.AlignCenter, "\u266a")
    painter.end()

    # 注意：不要用 QBuffer(QByteArray())，那个 QByteArray 是临时对象会被回收
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    pixmap.save(buffer, "PNG")
    data = bytes(buffer.data())
    buffer.close()
    return data


def build_ico(path: Path) -> None:
    images = [render(size) for size in SIZES]

    header = struct.pack("<HHH", 0, 1, len(SIZES))
    offset = len(header) + 16 * len(SIZES)
    entries = b""
    for size, data in zip(SIZES, images):
        entries += struct.pack(
            "<BBBBHHII",
            0 if size >= 256 else size,
            0 if size >= 256 else size,
            0,
            0,
            1,
            32,
            len(data),
            offset,
        )
        offset += len(data)

    path.write_bytes(header + entries + b"".join(images))


def main() -> int:
    QApplication(sys.argv)
    target = Path(__file__).resolve().parent.parent / "desktop-lyric.ico"
    build_ico(target)
    print(f"icon written: {target} ({target.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
