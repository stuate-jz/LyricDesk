"""把设置窗口的每个分类渲染成 PNG，用来肉眼检查排版。

用假引擎 + 临时设置文件（不碰用户真正的 settings.json），offscreen 渲染，
不需要真的把窗口弹到桌面上。
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

config.SETTINGS_PATH = Path(tempfile.mkdtemp(prefix="lyricdesk-shot-")) / "settings.json"

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
        return [{"app_id": "QQMusic.exe", "playing": True}, {"app_id": "Spotify.exe"}]

    def send_control(self, _action):
        return None

    def reload(self):
        return None


def main() -> int:
    app = QApplication(sys.argv)
    settings = Settings.load()
    window = LyricWindow(settings, FakeEngine())
    window.resize(1200, 500)
    window.show()

    dialog = SettingsDialog(window)
    dialog.resize(920, 640)
    dialog.show()
    app.processEvents()

    names = ["界面", "歌词", "播放", "窗口与交互", "更新与关于"]
    for index, name in enumerate(names):
        dialog.nav.setCurrentRow(index)
        app.processEvents()
        path = OUT / f"_settings_{index}_{name}.png"
        dialog.grab().save(str(path))
        print("saved", path)

    # 歌词窗口本身也抓一张：确认放大后的透明余量没有把歌词裁掉
    window.grab().save(str(OUT / "_settings_window_depth3d.png"))
    dialog.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
