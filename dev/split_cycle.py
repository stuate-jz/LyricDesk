r"""跑真实的 app.main()，在不同界面模式之间来回切换，检查窗口进出场。

用临时 APPDATA 启动，不会动到本机设置：
    $env:APPDATA="$env:TEMP\lyricdesk-cycle"; python dev\split_cycle.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import lyricdesk.app as app_mod  # noqa: E402
from lyricdesk.window import LyricWindow  # noqa: E402

RESULTS: list[str] = []


def live_windows() -> list[LyricWindow]:
    app = QApplication.instance()
    wins = [w for w in app.topLevelWidgets() if isinstance(w, LyricWindow)]
    return [w for w in wins if w.isVisible()]


def describe(tag: str) -> None:
    wins = live_windows()
    parts = []
    for win in wins:
        parts.append(
            f"{win.role}@{win.x()},{win.y()} {win.width()}x{win.height()}"
            f" mode={win._effective_mode()}"
        )
    RESULTS.append(f"[{tag}] {len(wins)} windows: " + " | ".join(parts))


def main() -> int:
    original_exec = QApplication.exec

    def patched_exec(*args, **kwargs):  # noqa: ANN001
        def step1() -> None:
            describe("startup(split)")
            wins = live_windows()
            target = wins[0] if wins else None
            if target is None:
                RESULTS.append("FAIL: 启动后没有窗口")
                QApplication.instance().quit()
                return
            target._set_mode("depth3d")

        def step2() -> None:
            describe("after-to-depth3d")
            wins = live_windows()
            target = wins[0] if wins else None
            if target is None:
                RESULTS.append("FAIL: 切回单窗口后没有窗口")
                QApplication.instance().quit()
                return
            target._set_mode("split")

        def step3() -> None:
            describe("after-to-split")
            QApplication.instance().quit()

        QTimer.singleShot(1200, step1)
        QTimer.singleShot(2600, step2)
        QTimer.singleShot(4000, step3)
        return original_exec()

    QApplication.exec = staticmethod(patched_exec)
    try:
        code = app_mod.main()
    finally:
        QApplication.exec = original_exec
    print("\n".join(RESULTS))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
