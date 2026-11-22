"""检查 QImage 子进程路径与 QPixmap 同步路径是否逐像素一致。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QColor, QFont, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lyricdesk import render  # noqa: E402
from lyricdesk.fonts import register_all  # noqa: E402

TEXT = "那些说不出口的话都留在风里"
SPACING = 4.5


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    register_all()
    render.set_letter_spacing(SPACING)
    sprite = render.make_sprite(
        TEXT,
        "AaLingSheZhuan",
        51,
        QFont.Weight.Bold,
    )
    print(f"advance={sprite.advance:.2f} spacing={SPACING}")
    failed = 0
    for dpr in (1.0, 1.25, 1.5, 2.0):
        image_art = render.render_line_images(
            sprite,
            QColor(255, 255, 255, 120),
            ("#7dd3fc", "#a78bfa", "#f0abfc"),
            QColor("#38bdf8"),
            2.55,
            QColor(0, 0, 0, 150),
            True,
            dpr,
            True,
        )
        pixmap_art = render._render_line_art_pixmaps(
            (f"parity-{dpr}",),
            sprite,
            QColor(255, 255, 255, 120),
            ("#7dd3fc", "#a78bfa", "#f0abfc"),
            QColor("#38bdf8"),
            2.55,
            QColor(0, 0, 0, 150),
            True,
            dpr,
            True,
        )
        for name in ("base", "highlight", "soft_highlight"):
            left = getattr(image_art, name).convertToFormat(
                QImage.Format.Format_ARGB32
            )
            right = getattr(pixmap_art, name).toImage().convertToFormat(
                QImage.Format.Format_ARGB32
            )
            equal = (
                left.size() == right.size()
                and bytes(left.bits()) == bytes(right.bits())
            )
            print(
                f"dpr={dpr:.2f} {name:15s} "
                f"{'OK' if equal else 'FAIL'} {left.width()}x{left.height()}"
            )
            failed += 0 if equal else 1
    print(f"\n结果：{'全部通过' if failed == 0 else f'{failed} 项失败'}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
