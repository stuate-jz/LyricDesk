r"""自检：新装默认值 + 默认落位 + 老配置不被覆盖（任务 4）。

用法： python dev\check_defaults.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from PySide6.QtWidgets import QApplication  # noqa: E402

from lyricdesk import config  # noqa: E402
from lyricdesk.config import Settings  # noqa: E402
from lyricdesk.window import LyricWindow  # noqa: E402

FAILS = 0


class FakeEngine:
    def snapshot(self):
        return None

    @property
    def lyrics(self):
        return None


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILS
    if not ok:
        FAILS += 1
    print(f"  {'OK  ' if ok else 'FAIL'} {name}" + (f"  —— {detail}" if detail else ""))


def main() -> int:
    app = QApplication(sys.argv)
    tmpdir = Path(tempfile.mkdtemp(prefix="ld-defaults-"))
    original = config.SETTINGS_PATH
    try:
        print("1) 新装默认值")
        config.SETTINGS_PATH = tmpdir / "missing.json"
        fresh = Settings.load()
        check("默认界面 = 纯歌词面板", fresh.mode == "lyrics", fresh.mode)
        check("默认不置顶", fresh.always_on_top is False, str(fresh.always_on_top))

        print()
        print("2) 默认落位（右上偏中，比例算）")
        window = LyricWindow(fresh, FakeEngine())
        area = (window.screen() or QApplication.primaryScreen()).availableGeometry()
        want_x = area.x() + int(area.width() * 0.81) - window.width()
        want_y = area.y() + 25
        print(f"      屏幕可用区 {area.width()}x{area.height()}，窗口 {window.width()}x{window.height()}"
              f"，实际位置 ({window.x()}, {window.y()})，期望 ({want_x}, {want_y})")
        check("x 按 0.81 比例落在右侧", abs(window.x() - want_x) <= 2)
        check("y 距顶部 25px", abs(window.y() - want_y) <= 2)
        check(
            "没有跑出屏幕",
            area.x() <= window.x() and window.x() + window.width() <= area.x() + area.width(),
        )

        print()
        print("3) 老配置不被覆盖")
        config.SETTINGS_PATH = tmpdir / "old.json"
        config.SETTINGS_PATH.write_text(
            json.dumps(
                {
                    "settings_version": 3,
                    "mode": "depth3d",
                    "always_on_top": True,
                    "x": 839,
                    "y": 25,
                    "width": 380,
                }
            ),
            encoding="utf-8",
        )
        old = Settings.load()
        check("老用户模式保持 depth3d", old.mode == "depth3d", old.mode)
        check("老用户置顶保持打开", old.always_on_top is True)
        old_window = LyricWindow(old, FakeEngine())
        check("老用户位置保持 839,25", (old_window.x(), old_window.y()) == (839, 25), f"{old_window.x()},{old_window.y()}")
    finally:
        config.SETTINGS_PATH = original
        for item in tmpdir.iterdir():
            item.unlink()
        tmpdir.rmdir()

    print()
    print("全部通过" if FAILS == 0 else f"{FAILS} 项没通过")
    return 0 if FAILS == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
