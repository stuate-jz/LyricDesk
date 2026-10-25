"""B 站客户端的「找到 / 带调试端口启动 / 重启」小工具。

调试端口是启动参数，运行中没法再打开，所以「勾选 B 站字幕」时需要这里帮忙：
- 端口已经在 → 什么都不做；
- B 站没在跑 → 直接带端口启动；
- B 站正在跑（不带端口）→ 调用方先问用户，再 restart_with_debug()。
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path

DEBUG_PORT = 9225
DEBUG_FLAG = f"--remote-debugging-port={DEBUG_PORT}"


def _exe_in(folder: Path) -> Path | None:
    try:
        files = [
            path
            for path in folder.glob("*.exe")
            if not any(
                word in path.name.lower()
                for word in ("uninst", "update", "helper", "crash", "卸载")
            )
        ]
    except OSError:
        return None
    if not files:
        return None
    # 主程序通常最大；先挑大的，避免拿到小工具
    files.sort(key=lambda path: path.stat().st_size, reverse=True)
    return files[0]


def _common_dirs() -> list[Path]:
    dirs: list[Path] = []
    for base in (
        os.environ.get("LOCALAPPDATA"),
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
    ):
        if not base:
            continue
        dirs.append(Path(base) / "bilibili")
        dirs.append(Path(base) / "Programs" / "bilibili")
    return dirs


def _registry_dirs() -> list[Path]:
    """从卸载信息里反推安装目录（B 站的 exe 可能叫「哔哩哔哩.exe」）。"""
    dirs: list[Path] = []
    try:
        import winreg
    except ImportError:
        return dirs
    roots = (
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (
            winreg.HKEY_LOCAL_MACHINE,
            r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
        ),
    )
    for hive, root in roots:
        try:
            parent = winreg.OpenKey(hive, root)
        except OSError:
            continue
        with parent:
            for index in range(winreg.QueryInfoKey(parent)[0]):
                try:
                    sub = winreg.OpenKey(parent, winreg.EnumKey(parent, index))
                except OSError:
                    continue
                values: dict[str, str] = {}
                with sub:
                    for name in ("DisplayName", "InstallLocation", "DisplayIcon", "UninstallString"):
                        try:
                            values[name] = str(winreg.QueryValueEx(sub, name)[0])
                        except OSError:
                            pass
                hint = " ".join(values.values()).lower()
                if "bilibili" not in hint:
                    continue
                location = values.get("InstallLocation")
                if location:
                    dirs.append(Path(location))
                for name in ("DisplayIcon", "UninstallString"):
                    raw = values.get(name, "")
                    if raw:
                        path = raw.strip().strip('"').split(",")[0]
                        if path:
                            dirs.append(Path(path).parent)
    return dirs


def find_exe() -> Path | None:
    """找 B 站客户端主程序；找不到返回 None。"""
    seen: set[str] = set()
    for folder in _common_dirs() + _registry_dirs():
        key = str(folder).lower()
        if key in seen:
            continue
        seen.add(key)
        exe = _exe_in(folder)
        if exe is not None:
            return exe
    return None


def is_running(exe: Path) -> bool:
    """有没有同名进程（用 tasklist，避免引入 psutil）。"""
    try:
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            timeout=6,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:  # noqa: BLE001
        return False
    text = (result.stdout or b"").decode("mbcs", errors="replace").lower()
    return exe.name.lower() in text


def debug_ready() -> bool:
    """9225 有没有响应、并且开着 B 站页面。"""
    from .bili_client import available

    return available(0.25)


def launch_with_debug(exe: Path) -> bool:
    try:
        subprocess.Popen([str(exe), DEBUG_FLAG])
        return True
    except OSError:
        return False


def restart_with_debug(exe: Path) -> bool:
    """关掉 B 站再带端口启动（会中断当前播放，调用方要先问用户）。"""
    try:
        subprocess.run(
            ["taskkill", "/F", "/IM", exe.name],
            capture_output=True,
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:  # noqa: BLE001
        pass
    time.sleep(0.8)
    return launch_with_debug(exe)


def wait_ready(timeout: float = 6.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if debug_ready():
            return True
        time.sleep(0.4)
    return False


def prepare_existing_for_debug(
    timeout: float = 10.0,
    should_continue=None,
) -> tuple[bool, str]:
    """桌面歌词启动时，把已经在跑的普通 B 站自动切换成字幕模式。

    - 已经是字幕模式 → 不动；
    - B 站没在跑 → 不主动打开，留给 BiliWatcher 在用户下次打开时接管；
    - B 站正在跑但没端口 → 自动带端口重启。

    返回值：(是否已就绪, 状态)。状态用于程序给出准确提示。
    """
    if debug_ready():
        return True, "ready"
    exe = find_exe()
    if exe is None:
        return False, "not_found"
    if not is_running(exe):
        return True, "not_running"
    if should_continue is not None and not should_continue():
        return False, "cancelled"
    if not restart_with_debug(exe):
        return False, "restart_failed"
    return wait_ready(timeout), "restarted"


class BiliWatcher:
    """开关打开时的后台守护：B 站被「普通方式」打开就自动带端口重启一次。

    只在「刚刚出现」的这一刻动手（还没开始播，重启基本无感）；
    已经在跑却没有端口的（比如启动本程序前就开着 B 站）**不会**擅自打断，
    只提示一次让用户关掉重开 / 取消再勾选一次。
    """

    def __init__(self, notify=None, interval: float = 2.0) -> None:
        self._notify = notify
        self._interval = interval
        self._exe: Path | None = None
        self._was_running: bool | None = None
        self._notified = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="bili-watch", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        # 先立刻记一次基线，避免用户在程序启动后 2 秒内打开 B 站时
        # 被误判成「启动前就已经开着」，从而漏掉自动切换。
        try:
            self._tick()
        except Exception:  # noqa: BLE001
            pass
        while not self._stop.wait(self._interval):
            try:
                self._tick()
            except Exception:  # noqa: BLE001
                pass

    def _tick(self) -> None:
        """一次检查（单独拆出来，方便自检直接调）。"""
        if self._stop.is_set():
            return
        if debug_ready():
            self._was_running = True
            self._notified = False
            return
        if self._exe is None:
            self._exe = find_exe()
            if self._exe is None:
                return
        if self._was_running is None:
            # 第一次只记基线：启动前就开着的 B 站不擅自重启
            self._was_running = is_running(self._exe)
            return
        if not is_running(self._exe):
            self._was_running = False
            self._notified = False
            return
        if not self._was_running:
            # 刚刚出现 = 用户用普通方式打开了 B 站 → 趁还没开始播，带端口重启
            self._was_running = True
            if restart_with_debug(self._exe):
                wait_ready(6.0)
            return
        if not self._notified:
            self._notified = True
            if self._notify is not None:
                self._notify(
                    "B 站当前不是以「歌词模式」启动的。关掉再打开（或取消再勾选一次开关）即可。"
                )
