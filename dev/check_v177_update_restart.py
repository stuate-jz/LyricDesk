"""v1.7.7 更新安装提示、自动重启与一次性成功反馈回归。"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lyricdesk import config  # noqa: E402

config.SETTINGS_PATH = Path(tempfile.mkdtemp(prefix="lyricdesk-v177-restart-")) / "settings.json"

from lyricdesk import update as update_mod  # noqa: E402
from lyricdesk.config import Settings  # noqa: E402
from lyricdesk.i18n import set_language, tr  # noqa: E402
from lyricdesk.update import UpdateInfo  # noqa: E402
from lyricdesk.window import LyricWindow  # noqa: E402

FAILS = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILS
    if not ok:
        FAILS += 1
    print(f"  {'OK  ' if ok else 'FAIL'} {name}" + (f"  —— {detail}" if detail else ""))


class FakeEngine:
    lyrics = None

    def snapshot(self):
        return None

    def players(self):
        return []

    def send_control(self, _action):
        return None

    def reload(self):
        return None


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    temp_dir = Path(tempfile.mkdtemp(prefix="lyricdesk-update-restart-test-"))
    settings = Settings()
    settings.always_on_top = False
    window = LyricWindow(settings, FakeEngine())

    print("1) 批处理安装、兜底重启与标记")
    exe_dir = temp_dir / "Program Files" / "LyricDesk"
    exe = exe_dir / "LyricDesk.exe"
    setup = temp_dir / "LyricDesk-Setup-1.7.7.exe"
    setup.write_bytes(b"MZ")
    with patch("lyricdesk.window.tempfile.gettempdir", return_value=str(temp_dir)):
        script = window._write_update_script(setup, exe, "1.7.7")
    text = script.read_text(encoding="mbcs", errors="replace")
    check("脚本成功写出", script is not None and script.exists())
    check(
        "静默安装参数完整",
        "/SILENT /SUPPRESSMSGBOXES /NORESTART /SP-" in text,
    )
    check(
        "兜底启动显式带工作目录",
        f'start "" /D "{exe.parent}" "{exe}"' in text,
        f'{exe.parent}',
    )
    check(
        "成功路径写入新版本标记",
        '>"%TEMP%\\lyricdesk-updated.txt" echo 1.7.7' in text,
    )
    check(
        "成功路径清掉失败标记",
        'del /q "%TEMP%\\lyricdesk-update-failed.txt"' in text,
    )
    check(
        "失败路径清掉成功标记",
        text.count('del /q "%TEMP%\\lyricdesk-updated.txt"') >= 2,
    )
    check(
        "失败路径保留手动安装包标记",
        '>"%TEMP%\\lyricdesk-update-failed.txt" echo LyricDesk-Setup-1.7.7.exe' in text,
    )

    installer = (ROOT / "installer.iss").read_text(encoding="utf-8-sig")
    run_section = installer.split("[Run]", 1)[1].split("[UninstallDelete]", 1)[0]
    check(
        "Inno 静默安装后自动启动",
        'Filename: "{app}\\{#AppExeName}"; Flags: nowait' in run_section,
        run_section.strip(),
    )

    print("\n2) 退出前提示")
    notices: list[tuple[str, int]] = []
    single_shots: list[int] = []
    with (
        patch.object(window, "_write_update_script", return_value=script),
        patch.object(window, "show_notice", side_effect=lambda text, ms: notices.append((text, ms))),
        patch("lyricdesk.window.run_hidden") as hidden,
        patch("lyricdesk.window.QTimer.singleShot", side_effect=lambda ms, cb: single_shots.append(ms)),
        patch.object(window, "_clear_pending"),
    ):
        window._on_update_downloaded(
            True,
            str(setup),
            SimpleNamespace(latest="1.7.7", url="https://example.test"),
        )
    check("更新脚本由隐藏包装器启动", hidden.call_count == 1)
    check(
        "下载完成后先显示安装提示",
        bool(notices) and notices[0][0] == "正在安装更新，完成后会自动重启。",
        str(notices),
    )
    check(
        "提示至少保留 2 秒再退出",
        3_200 in single_shots and all(ms >= 3_000 for ms, _cb in []),
        f"singleShot={single_shots}，提示 {notices[0][1] if notices else 0}ms",
    )

    print("\n3) 更新成功标记只提示一次")
    updated = temp_dir / update_mod.UPDATED_MARKER
    failed = temp_dir / update_mod.FAILED_MARKER
    updated.write_text("1.7.7", encoding="mbcs")
    with patch("lyricdesk.update.tempfile.gettempdir", return_value=str(temp_dir)):
        first = update_mod.consume_updated_version()
        second = update_mod.consume_updated_version()
    check("第一次读到 v1.7.7", first == "1.7.7")
    check("标记读后删除，第二次为空", second == "" and not updated.exists())

    updated.write_text("1.7.7", encoding="mbcs")
    failed.write_text("LyricDesk-Setup-1.7.7.exe", encoding="mbcs")
    with patch("lyricdesk.update.tempfile.gettempdir", return_value=str(temp_dir)):
        failed_result = update_mod.consume_updated_version()
    check(
        "失败标记优先，不显示已更新",
        failed_result == "" and not updated.exists() and failed.exists(),
    )
    failed.unlink(missing_ok=True)

    print("\n4) 窗内轻提示与 i18n")
    notice = tr("update.updated.notice", "已更新到 v{version}").format(version="1.7.7")
    window.show()
    app.processEvents()
    window.show_notice(notice, 220)
    check("提示文本进入歌词窗", window._notice_text == notice)
    window.render(window.grab().toImage())
    QTest.qWait(280)
    check("提示 3 秒机制可按时清空（测试用 220ms）", window._notice_text == "")

    set_language("en")
    english = tr("update.installing.notice", "已更新到 v{version}")
    set_language("")
    check(
        "英文环境不显示中文提示",
        english.isascii() and "安装" not in english,
        english,
    )

    source = (ROOT / "lyricdesk" / "app.py").read_text(encoding="utf-8")
    check("启动时消费一次性更新标记", "consume_updated_version()" in source)
    check("主窗出现后 1 秒提示", "QTimer.singleShot(1_000, report_updated_version)" in source)
    check("单实例机制仍在", 'QSharedMemory("LyricDesk_SingleInstance")' in source)

    window.hide()
    window.deleteLater()
    app.processEvents()
    print("\n结果：", "全部通过" if FAILS == 0 else f"{FAILS} 项失败")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
