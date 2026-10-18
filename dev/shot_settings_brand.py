r"""任务 3 的验收截图：品牌区 / 分类图标 / 选中竖条 / 白色对勾（深色 + 浅色 + 换主题）。

用法： python dev\shot_settings_brand.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from PySide6.QtWidgets import QApplication  # noqa: E402

from lyricdesk import config  # noqa: E402

config.SETTINGS_PATH = Path(tempfile.mkdtemp(prefix="ld-brand-")) / "settings.json"

from lyricdesk.config import Settings  # noqa: E402
from lyricdesk.settings_dialog import SettingsDialog  # noqa: E402
from lyricdesk.window import LyricWindow  # noqa: E402

OUT = Path(__file__).resolve().parent


class FakeEngine:
    def __init__(self) -> None:
        self.lyrics = None

    def snapshot(self):
        return None

    def players(self):
        return []

    def send_control(self, _action):
        return None

    def reload(self) -> None:
        return None


def main() -> int:
    app = QApplication(sys.argv)
    settings = Settings.load()
    window = LyricWindow(settings, FakeEngine())
    window.show()
    dialog = SettingsDialog(window)
    dialog.resize(920, 640)
    dialog.show()
    app.processEvents()

    # 勾上一个复选框，检查「主题色块 + 白色对勾」
    dialog._ontop_box.setChecked(True)
    app.processEvents()
    path = OUT / "_brand_dark.png"
    dialog.grab().save(str(path))
    print(f"saved {path.name}")

    # 浅色 + 素白
    settings.theme = "ink"
    settings.dialog_theme = "light"
    window._commit()
    app.processEvents()
    path = OUT / "_brand_light.png"
    dialog.grab().save(str(path))
    print(f"saved {path.name}")

    # 再换个主题（樱花）：图标颜色应该跟着变
    settings.theme = "sakura"
    window._commit()
    app.processEvents()
    path = OUT / "_brand_sakura.png"
    dialog.grab().save(str(path))
    print(f"saved {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
