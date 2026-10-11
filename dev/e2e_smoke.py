"""端到端冒烟：真的把程序跑起来，开一次设置窗口，切一遍分离面板再切回来。

跟 check_*.py 不一样，这个用的是**真的引擎**（读系统媒体控制里正在播的歌），
所以能顺带看一眼真实歌词在新余量下的样子。

安全措施：
* 单实例检查被换成「永远放行」，不影响你正在运行的那一份；
* 设置文件写到临时目录，**不会动**你 `%APPDATA%\\LyricDesk\\settings.json`；
* 跑完自己退出。

    python dev\\e2e_smoke.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from PySide6.QtCore import QSharedMemory, QTimer  # noqa: E402

# 你机器上可能已经开着桌面歌词，这里把单实例检查拆掉，方便并行跑
QSharedMemory.create = lambda self, size=1: True  # type: ignore[method-assign]

from lyricdesk import config  # noqa: E402

config.SETTINGS_PATH = Path(tempfile.mkdtemp(prefix="lyricdesk-e2e-")) / "settings.json"

from PySide6.QtWidgets import QApplication  # noqa: E402

from lyricdesk import app as app_module  # noqa: E402
from lyricdesk.window import LyricWindow  # noqa: E402

OUT = Path(__file__).resolve().parent
PROBLEMS: list[str] = []


def step(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'OK  ' if ok else 'FAIL'} {name}" + (f"  —— {detail}" if detail else ""))
    if not ok:
        PROBLEMS.append(name)


def panels(role: str) -> list[LyricWindow]:
    return [
        w
        for w in QApplication.topLevelWidgets()
        if isinstance(w, LyricWindow) and w.role == role and w.isVisible()
    ]


def main() -> int:
    # main() 里会阻塞跑事件循环，所以这里自己把窗口装起来，逻辑和 app.main 一致
    original_main = app_module.main
    result = {"code": 0}

    def run_steps(app: QApplication) -> None:
        wins = [
            w
            for w in QApplication.topLevelWidgets()
            if isinstance(w, LyricWindow) and w.role == "main"
        ]
        if not wins:
            print("没找到主窗口，跳过")
            app.quit()
            return
        main_window = wins[0]
        engine = main_window.engine
        snapshot = engine.snapshot()
        track = getattr(snapshot, "track", None)
        print("  现在系统媒体里播的是：", track.display if track else "（没有在播的歌）")

        print("\n打开设置窗口：")
        main_window.open_settings()
        app.processEvents()
        dialog = main_window._settings_dialog
        step("主窗口能打开设置窗口", dialog is not None and dialog.isVisible())
        if dialog is not None:
            dialog.grab().save(str(OUT / "_e2e_settings.png"))
            print("  设置窗口截图：dev\\_e2e_settings.png")

        print("\n切到分离面板，并在面板上开设置窗口：")
        main_window._set_mode("split")
        app.processEvents()
        QTimer.singleShot(400, lambda: after_split(app, main_window))

    def after_split(app: QApplication, main_window: LyricWindow) -> None:
        player = panels("player")
        step("分离面板出现了唱片窗口", bool(player), f"{len(player)} 个")
        if not player:
            app.quit()
            return
        # 设置窗口这时候还挂在主窗口上，再来一个挂在面板上，专门测转交
        main_window._settings_dialog.close()
        app.processEvents()
        player[0].open_settings()
        app.processEvents()
        step("面板窗口能打开设置窗口", getattr(player[0], "_settings_dialog", None) is not None)

        print("\n切回单窗口：")
        main_window._set_mode("depth3d")
        app.processEvents()
        QTimer.singleShot(600, lambda: finish(app, main_window))

    def finish(app: QApplication, main_window: LyricWindow) -> None:
        dialog = getattr(main_window, "_settings_dialog", None)
        alive = dialog is not None
        if alive:
            try:
                alive = dialog.isVisible()
            except RuntimeError:
                alive = False
        step("面板被销毁后，设置窗口还在（没有崩）", alive)
        if alive:
            dialog.grab().save(str(OUT / "_e2e_settings_after_split.png"))
            dialog.close()
        windows = [
            w
            for w in QApplication.topLevelWidgets()
            if isinstance(w, LyricWindow) and w.isVisible()
        ]
        step("切回单窗口后只剩一扇歌词窗口", len(windows) == 1, f"{len(windows)} 扇")
        if windows:
            windows[0].grab().save(str(OUT / "_e2e_live_lyrics.png"))
            print("  实时歌词截图：dev\\_e2e_live_lyrics.png")
        result["code"] = 1 if PROBLEMS else 0
        app.quit()

    # 借 app.main() 装配托盘 / 引擎 / 单实例（它内部会跑事件循环阻塞住），
    # 所以钩住窗口第一次 show，把测试步骤排进事件循环
    original_show = LyricWindow.show
    fired = {"done": False}

    def show_hook(self) -> None:
        original_show(self)
        if fired["done"]:
            return
        fired["done"] = True
        QTimer.singleShot(1500, lambda: run_steps(QApplication.instance()))

    LyricWindow.show = show_hook  # type: ignore[method-assign]
    try:
        original_main()
    finally:
        LyricWindow.show = original_show  # type: ignore[method-assign]

    if PROBLEMS:
        print("\n失败：", ", ".join(PROBLEMS))
        return 1
    print("\n端到端冒烟通过")
    return result["code"]


if __name__ == "__main__":
    raise SystemExit(main())
