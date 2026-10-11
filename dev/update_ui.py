r"""跑真实的 app.main()，触发一次「检查更新」，把弹窗截下来。

用法（先用临时 APPDATA 塞好更新源）：
    python dev\update_ui.py <截图输出目录>
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import lyricdesk.app as app_mod  # noqa: E402
from lyricdesk.window import LyricWindow  # noqa: E402

LOG: list[str] = []
FLOW = os.environ.get("LD_FLOW", "check")


def live_window() -> LyricWindow | None:
    app = QApplication.instance()
    for widget in app.topLevelWidgets():
        if isinstance(widget, LyricWindow):
            return widget
    return None


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    out.mkdir(parents=True, exist_ok=True)
    feed_version = sys.argv[2] if len(sys.argv) > 2 else "9.9.9"

    # 伪更新源：本地 JSON，版本号比当前高
    feed = Path(tempfile.mkdtemp(prefix="lyricdesk-feed-")) / "update.json"
    feed.write_text(
        json.dumps(
            {
                "version": feed_version,
                "notes": "· 新增：检查更新功能\n· 修复：纯歌词面板打不开\n· 优化：切歌不再误拖窗口",
                "url": "https://example.com/download",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    config_dir = Path(os.environ["APPDATA"]) / "LyricDesk"
    config_dir.mkdir(parents=True, exist_ok=True)
    # LD_NO_SOURCE=1 时不写更新源，用来检查「第一次点检查更新」的引导弹窗
    payload: dict = {"mode": "depth3d"}
    if os.environ.get("LD_SOURCE"):
        # LD_SOURCE=gitee:用户/仓库 可以直接拿真实仓库试
        payload["update_source"] = os.environ["LD_SOURCE"]
    elif not os.environ.get("LD_NO_SOURCE"):
        payload["update_source"] = str(feed)
    (config_dir / "settings.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    original_exec = QApplication.exec

    def shot(name: str) -> None:
        screen = QGuiApplication.primaryScreen()
        pixmap = screen.grabWindow(0)
        path = out / name
        pixmap.save(str(path))
        LOG.append(f"saved {path.name}")

    def patched_exec(*_args, **_kwargs):
        def step_check() -> None:
            window = live_window()
            if window is None:
                LOG.append("FAIL 没有窗口")
                QApplication.instance().quit()
                return
            LOG.append(f"update_source={window.settings.update_source}")
            window._check_update()

        def step_capture() -> None:
            modal = QApplication.activeModalWidget()
            LOG.append(f"modal={type(modal).__name__ if modal else None}")
            if modal is not None:
                LOG.append(f"  text={getattr(modal, 'text', lambda: '')()!r}")
                info = getattr(modal, "informativeText", lambda: "")()
                LOG.append(f"  info={info!r}")
                LOG.append(
                    "  buttons="
                    + ", ".join(b.text() for b in getattr(modal, "buttons", lambda: [])())
                )
            shot("update_dialog.png")
            if modal is not None:
                modal.reject()

        def click(label: str) -> bool:
            modal = QApplication.activeModalWidget()
            if modal is None:
                LOG.append(f"  想点「{label}」但当前没有弹窗")
                return False
            for button in getattr(modal, "buttons", lambda: [])():
                if button.text().replace("&", "") == label:
                    LOG.append(f"  点了「{label}」")
                    LOG.append(f"    弹窗内容: {getattr(modal, 'text', lambda: '')()!r}")
                    button.click()
                    return True
            LOG.append(
                f"  没找到「{label}」，按钮有："
                + ", ".join(b.text() for b in modal.buttons())
            )
            return False

        def step_click_update() -> None:
            shot("update_found.png")
            click("立即更新")

        def step_click_confirm() -> None:
            shot("update_confirm.png")
            click("下载并安装")

        QTimer.singleShot(2200, step_check)
        if FLOW == "self-update":
            QTimer.singleShot(4000, step_click_update)
            QTimer.singleShot(5200, step_click_confirm)
            # 剩下的交给程序自己：下载 → 写脚本 → 退出 → 静默安装 → 重新打开
            QTimer.singleShot(60000, lambda: QApplication.instance().quit())
        else:
            QTimer.singleShot(4200, step_capture)
            QTimer.singleShot(5600, lambda: QApplication.instance().quit())
        return original_exec()

    QApplication.exec = staticmethod(patched_exec)
    try:
        code = app_mod.main()
    finally:
        QApplication.exec = original_exec
    print("\n".join(LOG))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
