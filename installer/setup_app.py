"""桌面歌词 · 安装程序

一个自带卸载器的安装界面：选择安装位置、创建快捷方式、注册到「应用和功能」。
安装到 %LOCALAPPDATA%\\Programs\\LyricDesk，全程不需要管理员权限。

同一个 exe 也充当卸载器（复制为「卸载.exe」，带 --uninstall 参数运行）。
"""

from __future__ import annotations

import base64
import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import time
import winreg
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

APP_NAME = "桌面歌词"
APP_ID = "LyricDesk"
APP_VERSION = "1.6.5"
PUBLISHER = "LyricDesk"
EXE_NAME = "LyricDesk.exe"

UNINSTALL_KEY = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_ID}"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

PAYLOAD_FILES = (EXE_NAME, "使用说明.txt", "更新说明.txt", "许可协议.txt")


# ----------------------------------------------------------------------
# 工具
# ----------------------------------------------------------------------


def payload_dir() -> Path:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "payload"
    return Path(__file__).resolve().parent / "payload"


def default_install_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "Programs" / APP_ID


def resource(*parts: str) -> Path:
    base = getattr(sys, "_MEIPASS", None)
    root = Path(base) if base else Path(__file__).resolve().parent
    return root.joinpath(*parts)


def app_icon() -> QIcon:
    for candidate in (resource("icon.ico"), resource("desktop-lyric.ico")):
        if candidate.exists():
            return QIcon(str(candidate))
    return QIcon()


def run_ps(script: str) -> None:
    """用 PowerShell 做事，-EncodedCommand 避免任何引号/中文转义问题。"""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
        timeout=60,
    )


def create_shortcut(lnk: Path, target: Path, workdir: Path, icon: Path, desc: str) -> None:
    lnk.parent.mkdir(parents=True, exist_ok=True)
    script = (
        "$ws = New-Object -ComObject WScript.Shell;"
        f"$s = $ws.CreateShortcut('{lnk}');"
        f"$s.TargetPath = '{target}';"
        f"$s.WorkingDirectory = '{workdir}';"
        f"$s.IconLocation = '{icon}';"
        f"$s.Description = '{desc}';"
        "$s.Save()"
    )
    run_ps(script)


def kill_running_app() -> None:
    subprocess.run(
        ["taskkill", "/IM", EXE_NAME, "/F"],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
        capture_output=True,
    )
    time.sleep(1.2)


def desktop_dir() -> Path:
    return Path(os.path.join(os.environ.get("USERPROFILE", ""), "Desktop"))


def start_menu_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def dir_size_kb(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                pass
    return max(1, total // 1024)


# ----------------------------------------------------------------------
# 安装 / 卸载逻辑
# ----------------------------------------------------------------------


def do_install(
    install_dir: Path,
    desktop_lnk: bool,
    start_lnk: bool,
    autostart: bool,
    report,
) -> None:
    source = payload_dir()
    exe_src = source / EXE_NAME
    if not exe_src.exists():
        raise FileNotFoundError(f"安装包内缺少 {EXE_NAME}")

    report(4, "正在关闭正在运行的程序…")
    kill_running_app()

    report(12, "正在创建安装目录…")
    install_dir.mkdir(parents=True, exist_ok=True)

    total = len(PAYLOAD_FILES)
    for index, name in enumerate(PAYLOAD_FILES):
        src = source / name
        if not src.exists():
            continue
        report(15 + int(50 * index / total), f"正在安装 {name}…")
        shutil.copy2(src, install_dir / name)

    app_exe = install_dir / EXE_NAME

    if desktop_lnk:
        report(78, "正在创建桌面快捷方式…")
        create_shortcut(
            desktop_dir() / f"{APP_NAME}.lnk", app_exe, install_dir, app_exe, APP_NAME
        )
    if start_lnk:
        report(84, "正在创建开始菜单快捷方式…")
        create_shortcut(
            start_menu_dir() / f"{APP_NAME}.lnk", app_exe, install_dir, app_exe, APP_NAME
        )

    report(90, "正在注册到「应用和功能」…")
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, UNINSTALL_KEY, 0, winreg.KEY_SET_VALUE
    ) as key:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
        winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, APP_VERSION)
        winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, PUBLISHER)
        winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, str(install_dir))
        winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, str(app_exe))
        winreg.SetValueEx(
            key, "UninstallString", 0, winreg.REG_SZ, f'"{app_exe}" --uninstall'
        )
        winreg.SetValueEx(
            key,
            "QuietUninstallString",
            0,
            winreg.REG_SZ,
            f'"{app_exe}" --uninstall --silent',
        )
        winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "EstimatedSize", 0, winreg.REG_DWORD, dir_size_kb(install_dir))

    if autostart:
        report(95, "正在设置开机自启…")
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, APP_ID, 0, winreg.REG_SZ, f'"{app_exe}"')

    report(100, "安装完成")


def do_uninstall(install_dir: Path, report) -> None:
    report(10, "正在关闭程序…")
    kill_running_app()

    report(28, "正在删除快捷方式…")
    for lnk in (
        desktop_dir() / f"{APP_NAME}.lnk",
        start_menu_dir() / f"{APP_NAME}.lnk",
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

    # 只在自启项确实指向本安装目录时才删除，避免误删用户自己设置的
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE
        ) as key:
            value, _ = winreg.QueryValueEx(key, APP_ID)
            if str(install_dir).lower() in str(value).lower():
                winreg.DeleteValue(key, APP_ID)
    except OSError:
        pass

    report(70, "正在删除程序文件…")
    # 卸载器是从临时目录运行的，安装目录里没有正在运行的文件，可以直接删
    for attempt in range(4):
        shutil.rmtree(install_dir, ignore_errors=True)
        if not install_dir.exists():
            break
        time.sleep(0.6)

    report(100, "卸载完成")


# ----------------------------------------------------------------------
# 界面
# ----------------------------------------------------------------------


class Worker(QThread):
    progress = Signal(int, str)
    finished_ok = Signal()
    failed = Signal(str)

    def __init__(self, job) -> None:
        super().__init__()
        self._job = job

    def run(self) -> None:  # noqa: D102
        try:
            self._job(self.progress.emit)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        else:
            self.finished_ok.emit()


STYLE = """
QWidget { background: #14161f; color: #e6e9f2; font-family: "Microsoft YaHei UI"; }
QLabel#title { font-size: 22px; font-weight: 600; }
QLabel#subtitle { color: #8b93a7; font-size: 12px; }
QLabel#section { color: #aab2c5; font-size: 12px; }
QLineEdit {
    background: #1c1f2b; border: 1px solid #2c3245; border-radius: 6px;
    padding: 7px 10px; color: #e6e9f2; font-size: 12px;
}
QCheckBox { font-size: 13px; padding: 4px 0; }
QCheckBox::indicator { width: 16px; height: 16px; }
QPushButton {
    background: #232838; border: 1px solid #333a4f; border-radius: 6px;
    padding: 7px 18px; font-size: 13px;
}
QPushButton:hover { background: #2b3145; }
QPushButton#primary {
    background: #4f46e5; border: none; color: white; font-weight: 600;
}
QPushButton#primary:hover { background: #5b52f0; }
QPushButton#primary:disabled { background: #33384d; color: #7c8399; }
QProgressBar {
    border: none; border-radius: 4px; background: #1c1f2b; height: 8px;
    text-align: center; color: transparent;
}
QProgressBar::chunk { border-radius: 4px; background: #6d5cf5; }
QFrame#card { background: #191c26; border: 1px solid #262b3a; border-radius: 12px; }
QTextEdit#license {
    background: #14161f; border: 1px solid #262b3a; border-radius: 8px;
    color: #c3cad9; font-size: 12px; padding: 10px 12px;
}
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #333a4f; border-radius: 5px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
"""

LICENSE_FALLBACK = "（未找到许可协议文本，请查看随附的「许可协议.txt」）"


def license_text() -> str:
    here = Path(__file__).resolve().parent
    for candidate in (
        resource("许可协议.txt"),
        resource("payload", "许可协议.txt"),
        here.parent / "packaging" / "许可协议.txt",  # 源码方式运行
    ):
        if candidate.exists():
            try:
                return candidate.read_text(encoding="utf-8")
            except OSError:
                continue
    return LICENSE_FALLBACK


class InstallerWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION} 安装程序")
        self.setFixedSize(600, 540)
        self.setWindowIcon(app_icon())
        self.setStyleSheet(STYLE)
        screen = QApplication.primaryScreen()
        if screen is not None:
            self.move(screen.availableGeometry().center() - self.rect().center())
        self._worker: Worker | None = None
        self._step = 0
        self._target = default_install_dir()

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(14)

        root.addLayout(self._build_header())

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_license_page())
        self.stack.addWidget(self._build_options_page())
        root.addWidget(self.stack, 1)

        self.status = QLabel(" ")
        self.status.setObjectName("subtitle")
        root.addWidget(self.status)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        root.addWidget(self.bar)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.back_btn = QPushButton("取消")
        self.back_btn.clicked.connect(self._on_back)
        self.next_btn = QPushButton("下一步")
        self.next_btn.setObjectName("primary")
        self.next_btn.setDefault(True)
        self.next_btn.clicked.connect(self._on_next)
        buttons.addWidget(self.back_btn)
        buttons.addWidget(self.next_btn)
        root.addLayout(buttons)

        self._sync_buttons()

    # ------------------------------------------------------------------
    # 页面
    # ------------------------------------------------------------------

    def _build_header(self) -> QHBoxLayout:
        head = QHBoxLayout()
        head.setSpacing(12)
        icon_label = QLabel()
        pixmap: QPixmap = app_icon().pixmap(48, 48)
        icon_label.setPixmap(pixmap)
        icon_label.setFixedSize(48, 48)
        head.addWidget(icon_label)

        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = QLabel(APP_NAME)
        title.setObjectName("title")
        subtitle = QLabel(f"版本 {APP_VERSION} · 悬浮在桌面上的通用歌词组件")
        subtitle.setObjectName("subtitle")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        head.addLayout(titles)
        head.addStretch(1)
        return head

    def _build_license_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        section = QLabel("许可协议")
        section.setObjectName("section")
        layout.addWidget(section)

        self.license_view = QTextEdit()
        self.license_view.setObjectName("license")
        self.license_view.setReadOnly(True)
        self.license_view.setPlainText(license_text())
        layout.addWidget(self.license_view, 1)

        self.agree = QCheckBox("我已阅读并同意上述条款")
        self.agree.stateChanged.connect(lambda _state: self._sync_buttons())
        layout.addWidget(self.agree)
        return page

    def _build_options_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 14, 16, 16)
        card_layout.setSpacing(8)
        section = QLabel("安装位置")
        section.setObjectName("section")
        card_layout.addWidget(section)

        path_row = QHBoxLayout()
        path_row.setSpacing(8)
        self.path_edit = QLineEdit(str(default_install_dir()))
        browse = QPushButton("浏览…")
        browse.clicked.connect(self._browse)
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(browse)
        card_layout.addLayout(path_row)
        layout.addWidget(card)

        self.chk_desktop = QCheckBox("创建桌面快捷方式")
        self.chk_desktop.setChecked(True)
        self.chk_start = QCheckBox("创建开始菜单快捷方式")
        self.chk_start.setChecked(True)
        self.chk_launch = QCheckBox("安装完成后启动程序")
        self.chk_launch.setChecked(True)
        self.chk_auto = QCheckBox("开机自动运行")
        for box in (self.chk_desktop, self.chk_start, self.chk_launch, self.chk_auto):
            layout.addWidget(box)
        layout.addStretch(1)
        return page

    # ------------------------------------------------------------------

    def _sync_buttons(self) -> None:
        if self._step == 0:
            self.back_btn.setText("取消")
            self.next_btn.setText("下一步")
            self.next_btn.setEnabled(self.agree.isChecked())
        else:
            self.back_btn.setText("上一步")
            self.next_btn.setText("安装")
            self.next_btn.setEnabled(True)

    def _on_back(self) -> None:
        if self._step == 0:
            self.close()
            return
        self._step = 0
        self.stack.setCurrentIndex(0)
        self._sync_buttons()

    def _on_next(self) -> None:
        if self._step == 0:
            self._step = 1
            self.stack.setCurrentIndex(1)
            self._sync_buttons()
            return
        self._install()

    # ------------------------------------------------------------------

    def _browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "选择安装位置", str(default_install_dir().parent)
        )
        if chosen:
            self.path_edit.setText(str(Path(chosen) / APP_ID))

    def _set_busy(self, busy: bool) -> None:
        for widget in (
            self.path_edit,
            self.chk_desktop,
            self.chk_start,
            self.chk_launch,
            self.chk_auto,
            self.license_view,
            self.agree,
        ):
            widget.setEnabled(not busy)
        self.back_btn.setEnabled(not busy)
        self.next_btn.setEnabled(not busy)

    def _install(self) -> None:
        target = Path(self.path_edit.text().strip())
        if not str(target):
            QMessageBox.warning(self, APP_NAME, "请先选择安装位置。")
            return
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.critical(self, APP_NAME, f"无法创建安装目录：\n{exc}")
            return

        self._set_busy(True)
        self._target = target
        job = lambda report: do_install(  # noqa: E731
            target,
            self.chk_desktop.isChecked(),
            self.chk_start.isChecked(),
            self.chk_auto.isChecked(),
            report,
        )
        self._worker = Worker(job)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_progress(self, value: int, text: str) -> None:
        self.bar.setValue(value)
        self.status.setText(text)

    def _on_done(self) -> None:
        self._set_busy(True)
        self.status.setText("安装完成")
        self.bar.setValue(100)
        self.next_btn.setText("完成")
        try:
            self.next_btn.clicked.disconnect()
        except (RuntimeError, TypeError):
            pass
        self.next_btn.clicked.connect(self.close)
        self.next_btn.setEnabled(True)
        self.back_btn.setText("打开文件夹")
        try:
            self.back_btn.clicked.disconnect()
        except (RuntimeError, TypeError):
            pass
        self.back_btn.clicked.connect(
            lambda: subprocess.Popen(["explorer", str(self._target)])
        )
        self.back_btn.setEnabled(True)

        if self.chk_launch.isChecked():
            exe = self._target / EXE_NAME
            if exe.exists():
                subprocess.Popen([str(exe)], cwd=str(self._target))

    def _on_failed(self, message: str) -> None:
        self._set_busy(False)
        self.status.setText("安装失败")
        QMessageBox.critical(self, APP_NAME, f"安装失败：\n{message}")

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._worker is not None and self._worker.isRunning():
            event.ignore()
            return
        super().closeEvent(event)


# ----------------------------------------------------------------------
# 入口
# ----------------------------------------------------------------------


def find_install_dir() -> Path:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
            value, _ = winreg.QueryValueEx(key, "InstallLocation")
            if value:
                return Path(value)
    except OSError:
        pass
    return Path(sys.executable).resolve().parent


def _relaunch_from_temp(install_dir: Path) -> int:
    """卸载器不能从安装目录里运行，否则删不掉自己。复制到临时目录再跑。"""
    temp_exe = Path(tempfile.gettempdir()) / f"{APP_ID}-uninstall.exe"
    try:
        shutil.copy2(Path(sys.executable), temp_exe)
    except OSError:
        pass  # 复制失败就就地运行，最多是安装目录残留一个卸载器
    else:
        subprocess.Popen(
            [
                str(temp_exe),
                "--uninstall",
                "--from-temp",
                str(install_dir),
                *(["--silent"] if "--silent" in sys.argv else []),
            ],
            close_fds=True,
        )
        return 0
    return run_uninstall_ui(install_dir, temp_exe)


def _self_delete(path: Path) -> None:
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
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        pass


def run_uninstall_ui(install_dir: Path, self_path: Path, from_temp: bool = False) -> int:
    app = QApplication.instance() or QApplication(sys.argv)

    answer = QMessageBox.question(
        None,
        f"卸载 {APP_NAME}",
        f"确定要卸载 {APP_NAME} 吗？\n\n程序目录：\n{install_dir}\n\n"
        "（设置和歌词缓存会保留在 %APPDATA%\\LyricDesk，如需彻底清理请手动删除）",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    if answer != QMessageBox.StandardButton.Yes:
        if from_temp:
            _self_delete(self_path)
        return 0

    window = QWidget()
    window.setWindowTitle(f"卸载 {APP_NAME}")
    window.setFixedSize(420, 130)
    window.setWindowIcon(app_icon())
    window.setStyleSheet(STYLE)
    layout = QVBoxLayout(window)
    layout.setContentsMargins(22, 20, 22, 20)
    layout.setSpacing(12)
    status = QLabel("正在卸载…")
    bar = QProgressBar()
    bar.setRange(0, 100)
    layout.addWidget(status)
    layout.addWidget(bar)
    window.show()

    result = {"error": ""}
    worker = Worker(lambda report: do_uninstall(install_dir, report))
    worker.progress.connect(lambda value, text: (bar.setValue(value), status.setText(text)))

    def on_failed(message: str) -> None:
        result["error"] = message
        app.quit()

    worker.failed.connect(on_failed)
    worker.finished_ok.connect(app.quit)
    worker.start()
    app.exec()
    worker.wait()
    window.close()

    if result["error"]:
        QMessageBox.critical(None, APP_NAME, f"卸载过程中出现问题：\n{result['error']}")
    else:
        QMessageBox.information(None, APP_NAME, f"{APP_NAME} 已卸载。")

    if from_temp:
        _self_delete(self_path)
    return 0


def run_uninstall() -> int:
    args = sys.argv
    if "--from-temp" in args:
        index = args.index("--from-temp")
        install_dir = Path(args[index + 1]) if index + 1 < len(args) else find_install_dir()
        if "--silent" in args:
            try:
                do_uninstall(install_dir, lambda *_: None)
            except Exception as exc:  # noqa: BLE001
                _message_box(f"卸载失败：\n{exc}", error=True)
                return 1
            _self_delete(Path(sys.executable).resolve())
            return 0
        return run_uninstall_ui(install_dir, Path(sys.executable).resolve(), from_temp=True)
    return _relaunch_from_temp(find_install_dir())


def _message_box(text: str, error: bool = False) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(
            None, text, APP_NAME, 0x10 if error else 0x40
        )
    except Exception:
        pass


def run_silent_install() -> int:
    """命令行静默安装：/S 或 --silent。默认创建桌面与开始菜单快捷方式。"""
    try:
        do_install(default_install_dir(), True, True, False, lambda *_: None)
    except Exception as exc:  # noqa: BLE001
        _message_box(f"安装失败：\n{exc}", error=True)
        return 1
    return 0


def main() -> int:
    lowered = {arg.lower() for arg in sys.argv[1:]}
    if lowered & {"--silent", "/s", "-s"} and "--uninstall" not in lowered:
        return run_silent_install()

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setApplicationName(APP_ID)
    app.setWindowIcon(app_icon())

    if "--uninstall" in sys.argv:
        return run_uninstall()

    window = InstallerWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
