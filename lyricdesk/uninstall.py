"""卸载流程：主程序带 --uninstall 参数时走这里。

卸载器不能从安装目录里运行（否则删不掉自己），所以先把自己复制到临时目录，
再从那里执行删除。
"""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import time
import winreg
from pathlib import Path

APP_NAME = "桌面歌词"
APP_ID = "LyricDesk"
EXE_NAME = "LyricDesk.exe"

UNINSTALL_KEY = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_ID}"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _no_window() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _message(text: str, error: bool = False) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(None, text, APP_NAME, 0x10 if error else 0x40)
    except Exception:
        pass


def _desktop_dir() -> Path:
    return Path(os.path.join(os.environ.get("USERPROFILE", ""), "Desktop"))


def _start_menu_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def _install_dir() -> Path:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
            value, _ = winreg.QueryValueEx(key, "InstallLocation")
            if value:
                return Path(value)
    except OSError:
        pass
    return Path(sys.executable).resolve().parent


def _kill_running_app() -> None:
    subprocess.run(
        ["taskkill", "/IM", EXE_NAME, "/F"],
        creationflags=_no_window(),
        check=False,
        capture_output=True,
    )
    time.sleep(1.2)


def _self_delete(path: Path) -> None:
    """延时删除自己。用 PowerShell 的编码命令，避免引号和中文路径的转义问题。"""
    import base64

    script = (
        "Start-Sleep -Seconds 3;"
        f"Remove-Item -LiteralPath '{path}' -Force -ErrorAction SilentlyContinue"
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        subprocess.Popen(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-WindowStyle",
                "Hidden",
                "-EncodedCommand",
                encoded,
            ],
            creationflags=_no_window(),
        )
    except OSError:
        pass


def _do_uninstall(install_dir: Path, report) -> None:
    report(10, "正在关闭程序…")
    _kill_running_app()

    report(28, "正在删除快捷方式…")
    for lnk in (
        _desktop_dir() / f"{APP_NAME}.lnk",
        _start_menu_dir() / f"{APP_NAME}.lnk",
    ):
        try:
            if lnk.exists():
                lnk.unlink()
        except OSError:
            pass

    report(48, "正在清理注册表…")
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except OSError:
        pass

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE
        ) as key:
            value, _ = winreg.QueryValueEx(key, APP_ID)
            if str(install_dir).lower() in str(value).lower():
                winreg.DeleteValue(key, APP_ID)
    except OSError:
        pass

    report(72, "正在删除程序文件…")
    for _ in range(5):
        shutil.rmtree(install_dir, ignore_errors=True)
        if not install_dir.exists():
            break
        time.sleep(0.6)

    report(100, "卸载完成")


def _relaunch_from_temp(install_dir: Path, silent: bool) -> int:
    temp_exe = Path(tempfile.gettempdir()) / f"{APP_ID}-uninstall.exe"
    try:
        shutil.copy2(Path(sys.executable), temp_exe)
    except OSError as exc:
        _message(f"无法创建卸载程序：\n{exc}", error=True)
        return 1
    args = [str(temp_exe), "--uninstall", "--from-temp", str(install_dir)]
    if silent:
        args.append("--silent")
    subprocess.Popen(args, close_fds=True)
    return 0


def _run_ui(install_dir: Path) -> int:
    from PySide6.QtCore import QThread, Signal
    from PySide6.QtWidgets import (
        QApplication,
        QLabel,
        QMessageBox,
        QProgressBar,
        QVBoxLayout,
        QWidget,
    )

    class Worker(QThread):
        progress = Signal(int, str)
        finished_ok = Signal()
        failed = Signal(str)

        def run(self) -> None:
            try:
                _do_uninstall(install_dir, self.progress.emit)
            except Exception as exc:  # noqa: BLE001
                self.failed.emit(f"{type(exc).__name__}: {exc}")
            else:
                self.finished_ok.emit()

    app = QApplication.instance() or QApplication(sys.argv)
    answer = QMessageBox.question(
        None,
        f"卸载 {APP_NAME}",
        f"确定要卸载 {APP_NAME} 吗？\n\n程序目录：\n{install_dir}\n\n"
        "（设置和歌词缓存会保留在 %APPDATA%\\LyricDesk，需要的话请手动删除）",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    if answer != QMessageBox.StandardButton.Yes:
        return 0

    window = QWidget()
    window.setWindowTitle(f"卸载 {APP_NAME}")
    window.setFixedSize(380, 110)
    layout = QVBoxLayout(window)
    layout.setContentsMargins(22, 20, 22, 20)
    layout.setSpacing(12)
    label = QLabel("正在卸载…")
    bar = QProgressBar()
    bar.setRange(0, 100)
    layout.addWidget(label)
    layout.addWidget(bar)
    window.show()

    error = {"text": ""}
    worker = Worker()
    worker.progress.connect(lambda value, text: (bar.setValue(value), label.setText(text)))

    def on_failed(message: str) -> None:
        error["text"] = message
        app.quit()

    worker.failed.connect(on_failed)
    worker.finished_ok.connect(app.quit)
    worker.start()
    app.exec()
    worker.wait()
    window.close()

    if error["text"]:
        QMessageBox.critical(None, APP_NAME, f"卸载过程中出现问题：\n{error['text']}")
    else:
        QMessageBox.information(None, APP_NAME, f"{APP_NAME} 已卸载。")
    return 0


def main() -> int:
    args = sys.argv
    silent = any(a.lower() in ("--silent", "/s", "-s") for a in args)

    if "--from-temp" in args:
        index = args.index("--from-temp")
        target = Path(args[index + 1]) if index + 1 < len(args) else _install_dir()
        if silent:
            try:
                _do_uninstall(target, lambda *_: None)
            except Exception as exc:  # noqa: BLE001
                _message(f"卸载失败：\n{exc}", error=True)
                return 1
            _self_delete(Path(sys.executable).resolve())
            return 0
        code = _run_ui(target)
        _self_delete(Path(sys.executable).resolve())
        return code

    return _relaunch_from_temp(_install_dir(), silent)
