"""用 Qt 抓取整屏（Qt 是 DPI 感知的，坐标与物理像素一致）。"""

import sys

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication


def main() -> int:
    app = QApplication(sys.argv)
    screen = QGuiApplication.primaryScreen()
    geo = screen.geometry()
    print(f"screen geometry={geo.width()}x{geo.height()} dpr={screen.devicePixelRatio()}")

    pixmap = screen.grabWindow(0)
    print(f"grab size={pixmap.width()}x{pixmap.height()} dpr={pixmap.devicePixelRatio()}")

    out = sys.argv[1] if len(sys.argv) > 1 else "shot.png"
    pixmap.save(out)
    print("saved", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
