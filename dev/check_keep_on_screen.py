"""回归检查：窗口拉到极端尺寸时，keep_on_screen() 不会再把它推出屏幕。

旧版只按「左上角夹在可用区 ± 余量」算，窗口比屏幕还大时那个公式会翻车：
2560 宽 + 200 号字 + 15 行 + 满倾斜 → 窗口 3728×3703、可用区 1707×1067，
旧公式算出来的 x 是负的一千多，整扇窗口（包括歌词本体）全被推到屏幕左边外面。

    python dev\\check_keep_on_screen.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from PySide6.QtWidgets import QApplication  # noqa: E402

from lyricdesk import config  # noqa: E402

config.SETTINGS_PATH = Path(tempfile.mkdtemp(prefix="lyricdesk-keep-")) / "settings.json"

from lyricdesk.config import Settings  # noqa: E402
from lyricdesk.lyrics import LyricLine, Lyrics  # noqa: E402
from lyricdesk.smtc import Snapshot, Track  # noqa: E402
from lyricdesk.window import MARGIN, LyricWindow  # noqa: E402

FAILED: list[str] = []


class FakeEngine:
    def __init__(self) -> None:
        self._snapshot = Snapshot(
            track=Track(title="海屿你", artist="马也_Crabbit", album="海屿你", duration=219.0),
            position=10.0,
            is_playing=True,
            status=4,
            source="QQMusic.exe",
        )
        self._lyrics = Lyrics(
            lines=[
                LyricLine(time=0.0, text="他们说爱过就可以伤和别离", end=4.0),
                LyricLine(time=4.0, text="像放在手心就能够发光美丽", end=8.0),
            ],
            source="QQ音乐",
            title="海屿你",
            artist="马也_Crabbit",
            albummid="",
            album="海屿你",
        )

    @property
    def lyrics(self):
        return self._lyrics

    def snapshot(self):
        return self._snapshot

    def players(self):
        return []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'OK  ' if ok else 'FAIL'} {name}" + (f"  —— {detail}" if detail else ""))
    if not ok:
        FAILED.append(name)


def old_position(window: LyricWindow, area) -> tuple[int, int]:
    """按改动前的公式算一遍，用来对比「变了没有 / 好在哪里」。"""
    return (
        min(max(window.x(), area.x() - 40), area.x() + area.width() - window.width() + 40),
        min(max(window.y(), area.y() - 10), area.y() + area.height() - window.height() + 10),
    )


def make(settings: Settings, role: str = "main") -> LyricWindow:
    win = LyricWindow(settings, FakeEngine(), role=role)
    win.show()
    return win


def main() -> int:
    app = QApplication(sys.argv)
    area = app.primaryScreen().availableGeometry()
    print(f"可用区：{area.width()}×{area.height()}（左上角 {area.x()},{area.y()}）")

    print("\n1) 放得下的窗口：位置行为必须和改动前完全一致")
    settings = Settings()
    settings.width = max(240, min(400, area.width() - 300))
    settings.clamp()
    win = make(settings)
    win.recalculate()
    check(
        "构造出来的窗口确实放得下",
        win.width() <= area.width() and win.height() <= area.height(),
        f"{win.width()}×{win.height()}",
    )
    for spot in (
        (area.x() - 500, area.y() - 500),
        (area.right() + 500, area.bottom() + 500),
        (area.x() + 10, area.y() + 10),
    ):
        win.move(*spot)
        want = old_position(win, area)
        win.keep_on_screen()
        check(
            f"从 {spot} 拉回：和旧公式一致",
            (win.x(), win.y()) == want,
            f"实际 ({win.x()},{win.y()}) / 旧公式 {want}",
        )
    # 拖动记忆：拉回后的坐标要写进设置
    win.move(area.right() + 500, area.bottom() + 500)
    win.keep_on_screen()
    check(
        "拉回后的位置被记住",
        (settings.x, settings.y) == (win.x(), win.y()),
        f"settings.x/y = {settings.x},{settings.y}",
    )
    win.hide()
    win.deleteLater()

    print("\n2) 放不下的窗口（计划里的极端参数）：左上角对齐可用区")
    settings = Settings()
    settings.mode = "depth3d"
    settings.width = 2560
    settings.cover_size = 320
    settings.font_size = 200
    settings.lyric_lines = 15
    settings.text_depth_v = 0.80
    settings.text_depth_h = 0.80
    settings.text_tilt = 45.0
    settings.clamp()
    win = make(settings)
    win.recalculate()
    huge = win.width() > area.width() or win.height() > area.height()
    check(
        "这组参数确实做出了比屏幕还大的窗口",
        huge,
        f"{win.width()}×{win.height()}（可用区 {area.width()}×{area.height()}）",
    )

    win.move(area.x() + 400, area.y() + 400)
    before = old_position(win, area)
    win.move(area.x() + 400, area.y() + 400)
    win.keep_on_screen()
    after = (win.x(), win.y())
    check(
        "左上角贴住可用区左上角",
        after == (area.x(), area.y()),
        f"实际 {after} / 旧公式会放成 {before}",
    )
    check(
        "窗口本体（含歌词）不再被推到左边/上边外面",
        win.x() >= area.x() and win.y() >= area.y(),
        f"左边缘 {win.x()}，上边缘 {win.y()}",
    )
    # 歌词本体是从「窗口左边 + MARGIN + 透明余量」开始画的
    inset = MARGIN + win._overscan
    old_content_left = before[0] + inset
    new_content_left = win.x() + inset
    print(
        f"     歌词区左侧：旧公式 {old_content_left}（屏幕外 {(area.x() - old_content_left)}px）"
        f" → 现在 {new_content_left}（屏幕内）"
    )
    print(
        f"     右侧/下侧仍会越界：{win.x() + win.width() - (area.x() + area.width())}px / "
        f"{win.y() + win.height() - (area.y() + area.height())}px"
        "（窗口本身比屏幕大，这一步无法避免）"
    )
    check(
        "越界只来自窗口太大，而不是被摆歪",
        win.x() == area.x() and win.y() == area.y(),
    )

    print("\n3) 三种角色都走一遍（分离面板的两扇窗口也一样）")
    for role in ("main", "player", "lyrics"):
        s = Settings()
        s.width = 2560
        s.font_size = 200
        s.lyric_lines = 15
        s.clamp()
        w = make(s, role=role)
        w.recalculate()
        w.move(area.x() - 3000, area.y() - 3000)
        w.keep_on_screen()
        # 放得下的那一边仍然保留原有的 40 / 10 像素余量（拖到边上不粘手），
        # 放不下的那一边必须贴住可用区，不能被甩到屏幕外。
        ok = w.x() >= area.x() - 40 and w.y() >= area.y() - 10
        if w.width() > area.width():
            ok = ok and w.x() == area.x()
        if w.height() > area.height():
            ok = ok and w.y() == area.y()
        check(f"role={role}", ok, f"({w.x()},{w.y()}) 窗口 {w.width()}×{w.height()}")
        w.hide()
        w.deleteLater()

    app.processEvents()
    if FAILED:
        print("\n失败：", ", ".join(FAILED))
        return 1
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
