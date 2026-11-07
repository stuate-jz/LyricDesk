"""v1.7.2 圆盘稳定性、伪逐字与菜单更新圆环回归。"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu, QWidgetAction

from lyricdesk import config

config.SETTINGS_PATH = Path(tempfile.mkdtemp(prefix="lyricdesk-v172-")) / "settings.json"

from lyricdesk.config import Settings
from lyricdesk.fonts import register_all
from lyricdesk.update import UpdateInfo
from lyricdesk.window import LyricWindow, UpdateRingActionWidget


def load_fake_engine():
    path = ROOT / "dev" / "check_v170_disc.py"
    spec = importlib.util.spec_from_file_location("_v172_disc", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.FakeEngine


def image_difference(left: QPixmap, right: QPixmap) -> int:
    a = left.toImage().convertToFormat(left.toImage().Format.Format_RGBA8888)
    b = right.toImage().convertToFormat(right.toImage().Format.Format_RGBA8888)
    if a.size() != b.size():
        return 10**9
    return sum(x != y for x, y in zip(bytes(a.constBits()), bytes(b.constBits())))


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    register_all()
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  {'OK  ' if ok else 'FAIL'} {name}" + (f"  —— {detail}" if detail else ""))
        if not ok:
            failures.append(name)

    settings = Settings()
    settings.font_family = "Smiley Sans"
    settings.background = False
    settings.show_song_info = False
    settings.lyric_layout = "disc"
    settings.lyric_lines = 7
    engine = load_fake_engine()()
    window = LyricWindow(settings, engine)
    window.show()
    app.processEvents()

    sizes = set()
    scales = set()
    centers = []
    for spread in (20, 60, 120):
        window._set_disc_spread(spread)
        for angle in (-90, -45, 0, 45, 90):
            window._set_disc_angle(angle)
            app.processEvents()
            sizes.add((window.width(), window.height()))
            scales.add(window._disc_render_layout()[2])
            centers.append(window._disc_center_on_screen())
    check("张角和角度变化不改窗口尺寸", len(sizes) == 1, str(sizes))
    check("圆盘字号缩放始终为 1", scales == {1.0}, str(scales))
    check(
        "角度旋转圆心不动",
        max(abs(point.x() - centers[0].x()) + abs(point.y() - centers[0].y()) for point in centers) <= 1.0,
    )

    settings.lyric_layout = "list"
    settings.lyric_effect = "off"
    engine.lyrics.lines[8].words = []
    engine._snapshot.position = engine.lyrics.lines[8].time + 1.1
    window._commit(resize=True)
    off = QPixmap(window.size())
    window.render(off)
    settings.lyric_effect = "word"
    window._commit()
    word = QPixmap(window.size())
    window.render(word)
    changed = image_difference(off, word)
    check("无逐字歌词仍有逐字点亮", changed > 20, f"changed={changed}")

    # 拖出一半后重排，不应被拉回。
    screen = window.screen() or QApplication.primaryScreen()
    area = screen.availableGeometry()
    window.move(area.left() - window.width() // 2, area.top() + 80)
    before_x = window.x()
    window._commit(resize=True)
    check("露出一半时重排不强行拉回", window.x() == before_x, str(window.x()))

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
    menu.addAction("下一个项目")
    menu.addAction("再下一个项目")
    widget.ensurePolished()
    window._menu_update_widget = widget
    window._set_menu_update_state("downloading", done=42, total=100)
    check("圆环下载状态可绘制", not widget.grab().isNull())
    window._set_menu_update_state("installing", done=100, total=100)
    check("圆环安装状态可绘制", not widget.grab().isNull())
    window._set_menu_update_state("failed", done=100, total=100)
    check("圆环失败状态可绘制", not widget.grab().isNull())

    clicked = []
    original = window._start_menu_update
    window._start_menu_update = lambda item: clicked.append(item)
    try:
        window._set_menu_update_state("idle")
        menu.show()
        app.processEvents()
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
        app.processEvents()
        check("点击更新圆环只触发更新", clicked == [info])
        check("更新圆环点击后菜单保持打开", menu.isVisible())
    finally:
        window._start_menu_update = original
        menu.close()

    window.close()
    window.deleteLater()
    app.processEvents()
    print("全部通过" if not failures else "失败：" + ", ".join(failures))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
