"""程序入口：托盘、单实例、窗口装配。"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .autostart import set_enabled
from .config import Settings
from .engine import Engine
from .processes import music_app_running
from .window import LyricWindow

_SHARED_MEMORY = None
# 翻译器要一直活着，否则被 GC 掉之后翻译会失效（Qt 不持有所有权）
_TRANSLATORS: list = []


def install_translations(app) -> list:
    """给 Qt 内置对话框（字体选择、颜色选择等）装中文翻译。

    不装的话「从系统字体中选择…」弹出来的是英文界面（Font / Font style / OK）。
    翻译文件由 PySide6 自带，路径用 QLibraryInfo 查，别写死；
    打包时要在 spec 的 datas 里一起带上（见 desktop-lyric.spec）。
    """
    from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator

    path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    locale = QLocale.system().name()  # 例如 zh_CN / en_US
    translators: list = []
    for name in ("qtbase", "qt"):
        translator = QTranslator(app)
        if translator.load(f"{name}_{locale}", path):
            app.installTranslator(translator)
            translators.append(translator)
    return translators


def make_icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    gradient = QLinearGradient(4, 4, 60, 60)
    gradient.setColorAt(0.0, QColor("#38bdf8"))
    gradient.setColorAt(1.0, QColor("#a78bfa"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(gradient)
    painter.drawRoundedRect(QRectF(3, 3, 58, 58), 17, 17)

    font = QFont("Segoe UI Symbol")
    font.setPixelSize(40)
    font.setWeight(QFont.Weight.DemiBold)
    painter.setFont(font)
    painter.setPen(QColor("#0b1020"))
    painter.drawText(QRectF(0, 2, 64, 64), Qt.AlignmentFlag.AlignCenter, "\u266a")
    painter.end()
    return QIcon(pixmap)


def main() -> int:
    global _SHARED_MEMORY, _TRANSLATORS

    app = QApplication(sys.argv)
    app.setApplicationName("LyricDesk")
    app.setApplicationDisplayName("桌面歌词")
    app.setQuitOnLastWindowClosed(False)

    # 给 Qt 自带对话框装中文（必须赶在建任何窗口之前）
    _TRANSLATORS = install_translations(app)

    # 注册内置字体和用户下载过的字体（必须在建窗口前做）
    from .fonts import register_all

    register_all()

    from PySide6.QtCore import QSharedMemory

    shared = QSharedMemory("LyricDesk_SingleInstance")
    if not shared.create(1):
        return 0
    _SHARED_MEMORY = shared

    settings = Settings.load()
    engine = Engine(settings)

    # ---------- 窗口装配 ----------
    # 普通模式只有一扇主窗口；「分离面板」模式下主窗口让位给
    # 唱片面板 + 歌词面板两扇独立窗口，都可以各自拖动。
    main_window: LyricWindow | None = LyricWindow(settings, engine)
    panel_windows: list[LyricWindow] = []

    def active_windows() -> list[LyricWindow]:
        if panel_windows:
            return list(panel_windows)
        return [main_window] if main_window is not None else []

    settings.save()

    tray = QSystemTrayIcon(make_icon(), app)
    tray.setToolTip("桌面歌词")
    tray.show()

    def notify(title: str, message: str) -> None:
        tray.showMessage(title, message, make_icon(), 8000)

    # 引擎的后台守护（B 站字幕）也用同一个托盘气泡
    engine.notice.connect(notify)

    def toggle_visibility() -> None:
        windows = active_windows()
        if not windows:
            return
        visible = any(win.isVisible() for win in windows)
        for win in windows:
            if visible:
                win.hide()
            else:
                win.show()
                win.raise_()
                win.keep_on_screen()

    tray_menu = QMenu()

    def rebuild_tray_menu() -> None:
        # 复用同一个菜单对象，只重填内容，避免反复创建/销毁原生菜单
        windows = active_windows()
        if not windows:
            return
        windows[0].populate_menu(tray_menu)
        visible = any(win.isVisible() for win in windows)
        toggle = QAction("隐藏歌词" if visible else "显示歌词", tray_menu)
        toggle.triggered.connect(toggle_visibility)
        actions = tray_menu.actions()
        if actions:
            tray_menu.insertAction(actions[0], toggle)
            tray_menu.insertSeparator(actions[0])
        else:
            tray_menu.addAction(toggle)

    def update_tooltip(track) -> None:
        if track is None:
            tray.setToolTip("桌面歌词 · 等待播放")
        else:
            tray.setToolTip(f"桌面歌词 · {track.display}")

    def on_autostart(enabled: bool) -> None:
        set_enabled(enabled)
        rebuild_tray_menu()

    def on_quit() -> None:
        settings.save()
        engine.stop()
        tray.hide()
        app.quit()

    def hide_all() -> None:
        for win in active_windows():
            win.hide()
        rebuild_tray_menu()

    def wire(win: LyricWindow) -> None:
        win.requestQuit.connect(on_quit)
        win.requestAutostart.connect(on_autostart)
        win.requestReload.connect(engine.reload)
        win.requestNotify.connect(notify)
        win.requestHide.connect(hide_all)
        win.settingsChanged.connect(schedule_sync)

    # ---------- 分离面板的进出场 ----------

    def enter_split() -> None:
        player = LyricWindow(settings, engine, role="player")
        wire(player)
        player.show()
        player.keep_on_screen()
        player.raise_()
        lyrics = LyricWindow(
            settings,
            engine,
            role="lyrics",
            anchor_y=player.y() + player.height() + 24,
        )
        wire(lyrics)
        lyrics.show()
        lyrics.keep_on_screen()
        panel_windows.extend([player, lyrics])
        settings.save()

    def exit_split() -> None:
        for win in panel_windows:
            # 设置窗口可能挂在某个面板上；面板要销毁了，先把它转交出去，
            # 不然用户开着的设置窗口会指向已释放的窗口
            transfer = getattr(win, "transfer_settings_dialog", None)
            if transfer is not None and main_window is not None:
                transfer(main_window)
            win.hide()
            win.setParent(None)
            win.deleteLater()
        panel_windows.clear()
        if main_window is not None:
            main_window.recalculate()
            main_window.show()
            main_window.keep_on_screen()
            main_window.raise_()

    def sync_mode_windows() -> None:
        want_split = settings.mode == "split"
        if want_split and not panel_windows:
            if main_window is not None:
                main_window.hide()
            enter_split()
        elif not want_split and panel_windows:
            exit_split()

    _sync_queued = False
    # 鼠标穿透这种真正的窗口标志改了以后，两扇面板都要重新套一遍。
    # 「置顶」不在这里：它走原生 SetWindowPos（win_util.set_native_topmost），
    # 走 setWindowFlags 会把窗口重建一次、闪一下。
    _flag_state = {"click_through": settings.click_through}

    def schedule_sync() -> None:
        """模式切换可能发生在某个面板自己的菜单里，延后一拍再拆/建窗口。"""
        nonlocal _sync_queued
        if _sync_queued:
            return
        _sync_queued = True

        def run() -> None:
            nonlocal _sync_queued
            _sync_queued = False
            sync_mode_windows()
            rebuild_tray_menu()
            if _flag_state["click_through"] != settings.click_through:
                _flag_state["click_through"] = settings.click_through
                for win in active_windows():
                    win.apply_flags()
            for win in active_windows():
                # 字号 / 行数这类设置会让另一扇面板的尺寸也变，需要一起重算
                win.recalculate()
                win.keep_on_screen()
                win.update()
            # 设置窗口开着的话要留在最前面：切模式新建的面板会盖在它上面
            hosts = list(active_windows())
            if main_window is not None and main_window not in hosts:
                hosts.append(main_window)
            for win in hosts:
                raiser = getattr(win, "raise_settings", None)
                if raiser is not None:
                    raiser()

        QTimer.singleShot(0, run)

    wire(main_window)
    engine.trackChanged.connect(update_tooltip)
    engine.trackChanged.connect(lambda _track: rebuild_tray_menu())

    def on_tray_activated(reason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            toggle_visibility()
            rebuild_tray_menu()

    tray.activated.connect(on_tray_activated)

    # 首次装配：按保存的模式决定显示哪（几）扇窗口
    sync_mode_windows()
    if not panel_windows and main_window is not None:
        main_window.show()
        main_window.keep_on_screen()

    rebuild_tray_menu()
    tray.setContextMenu(tray_menu)

    # 验收用：LD_OPEN_SETTINGS=1 时启动后自动打开设置窗口（普通用户不会设置这个变量）
    if os.environ.get("LD_OPEN_SETTINGS") == "1":
        def _open_settings_for_check() -> None:
            windows = active_windows()
            if windows:
                windows[0].open_settings()

        QTimer.singleShot(1500, _open_settings_for_check)

    # 上次自动安装没成功（杀软拦截、系统版本不够……）：安装包已经保留下来，
    # 这里主动告诉用户，别让他以为「更新了但还是旧版本」。
    def report_failed_update() -> None:
        from .update import failed_installer

        kept = failed_installer()
        if kept is None:
            return
        from PySide6.QtWidgets import QMessageBox

        windows = active_windows()
        box = QMessageBox(windows[0] if windows else None)
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("更新没有装成功")
        box.setText("上次自动更新没有装成功，程序仍是旧版本。")
        box.setInformativeText(f"安装包已经保留下来，可以双击手动安装：\n{kept}")
        open_folder = box.addButton("打开所在文件夹", QMessageBox.ButtonRole.ActionRole)
        box.addButton("知道了", QMessageBox.ButtonRole.AcceptRole)
        box.exec()
        if box.clickedButton() is open_folder:
            subprocess.Popen(["explorer", "/select,", str(kept)])

    QTimer.singleShot(1200, report_failed_update)

    # 首次启动提示托盘图标在哪（Windows 11 会把新图标收进「^」溢出区）
    def first_run_hint() -> None:
        if settings.tray_hint_shown:
            return
        settings.tray_hint_shown = True
        settings.save()
        tray.showMessage(
            "桌面歌词已在后台运行",
            "双击托盘里的音符图标可以显示 / 隐藏歌词，右键是设置菜单。\n"
            "如果你在任务栏右下角看不到它，点一下「^」展开隐藏的图标。",
            make_icon(),
            10000,
        )

    QTimer.singleShot(2500, first_run_hint)
    # B 站字幕开着、并且 B 站已经在普通模式运行：启动桌面歌词时自动重启一次。
    # 这段不依赖窗口可见，所以最小化到托盘 / 开机后台启动也会执行。
    bili_launch_result: queue.Queue[tuple[bool, str]] = queue.Queue(maxsize=1)

    def prepare_bili_on_launch() -> None:
        if not settings.bili_mode:
            return
        from . import bili_launcher

        def worker() -> None:
            try:
                result = bili_launcher.prepare_existing_for_debug(
                    should_continue=lambda: settings.bili_mode
                )
            except Exception:  # noqa: BLE001
                result = (False, "error")
            bili_launch_result.put(result)

        threading.Thread(
            target=worker,
            name="bili-launch-prepare",
            daemon=True,
        ).start()

        def poll_result() -> None:
            try:
                ready, status = bili_launch_result.get_nowait()
            except queue.Empty:
                QTimer.singleShot(250, poll_result)
                return
            if not settings.bili_mode or status in ("ready", "not_running", "cancelled"):
                return
            if status == "not_found":
                notify("B 站字幕", "没有找到哔哩哔哩客户端，暂时无法读取 B 站字幕。")
            elif status == "restarted" and ready:
                notify("B 站字幕", "B 站已自动切换到可读取字幕的模式。")
            elif status == "restarted":
                notify(
                    "B 站字幕",
                    "B 站已重启，但字幕调试端口还没就绪，请稍后重新打开 B 站。",
                )
            else:
                notify(
                    "B 站字幕",
                    "B 站字幕模式准备失败；关闭后再勾选一次设置即可自动重试。",
                )

        QTimer.singleShot(200, poll_result)

    QTimer.singleShot(900, prepare_bili_on_launch)
    # 配好更新源之后，启动时静默自查一次（24 小时内只查一次）
    QTimer.singleShot(8000, main_window.auto_check_update)

    def heartbeat() -> None:
        snapshot = engine.snapshot()
        if snapshot is None:
            return

    idle_timer = QTimer()
    idle_timer.setInterval(1500)
    idle_timer.timeout.connect(heartbeat)
    idle_timer.start()

    # ---------- 打开音乐软件时自动把歌词显示出来 ----------
    music_state = {"running": None}

    def watch_music_apps() -> None:
        if not settings.auto_show_on_music:
            return
        running = music_app_running()
        previous = music_state["running"]
        music_state["running"] = running
        # 只在「本来没有、现在有了」的那一下动手，免得跟手动隐藏打架
        if previous is None or previous or not running:
            return
        windows = active_windows()
        if not windows:
            return
        for win in windows:
            if not win.isVisible():
                win.show()
            win.raise_()
            win.keep_on_screen()
        rebuild_tray_menu()

    music_timer = QTimer()
    music_timer.setInterval(4000)
    music_timer.timeout.connect(watch_music_apps)
    music_timer.start()

    for win in active_windows():
        win.raise_()
    exit_code = app.exec()

    # 收尾：先把读取线程停下来再退出，避免 WinRT 回调在解释器销毁后才回来
    engine.stop()
    engine.join(2.0)
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    if engine.is_running():
        os._exit(exit_code)
    return exit_code
