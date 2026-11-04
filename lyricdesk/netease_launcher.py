"""网易云客户端的查找 / 带调试端口启动 / 重启。"""

from __future__ import annotations

import os
import socket
import subprocess
import time
from pathlib import Path

DEBUG_PORT_MIN = 9222
DEBUG_PORT_MAX = 9232


def _exe_in(folder: Path) -> Path | None:
    candidate = folder / "cloudmusic.exe"
    if candidate.is_file():
        return candidate
    try:
        files = [
            path
            for path in folder.glob("*.exe")
            if path.name.lower() not in ("uninstall.exe", "cloudmusic_util.exe")
        ]
    except OSError:
        return None
    return files[0] if files else None


def _common_dirs() -> list[Path]:
    dirs = [
        Path(r"D:\CloudMusic"),
        Path(r"C:\Program Files\Netease\CloudMusic"),
        Path(r"C:\Program Files (x86)\Netease\CloudMusic"),
    ]
    for key in ("LOCALAPPDATA", "APPDATA", "ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(key)
        if not base:
            continue
        dirs.extend(
            [
                Path(base) / "Netease" / "CloudMusic",
                Path(base) / "NetEase" / "CloudMusic",
                Path(base) / "CloudMusic",
            ]
        )
    return dirs


def _registry_dirs() -> list[Path]:
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
                    for name in (
                        "DisplayName",
                        "InstallLocation",
                        "DisplayIcon",
                        "UninstallString",
                    ):
                        try:
                            values[name] = str(winreg.QueryValueEx(sub, name)[0])
                        except OSError:
                            pass
                hint = " ".join(values.values()).lower()
                if "cloudmusic" not in hint and "网易云音乐" not in hint:
                    continue
                location = values.get("InstallLocation")
                if location:
                    dirs.append(Path(location))
                for name in ("DisplayIcon", "UninstallString"):
                    raw = values.get(name, "")
                    if not raw:
                        continue
                    path = raw.strip().strip('"').split(",")[0]
                    if path:
                        dirs.append(Path(path).parent)
    return dirs


def find_exe() -> Path | None:
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
    try:
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH", "/FI", f"IMAGENAME eq {exe.name}"],
            capture_output=True,
            timeout=6,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:  # noqa: BLE001
        return False
    text = (result.stdout or b"").decode("mbcs", errors="replace").lower()
    return exe.name.lower() in text


def port_available(port: int) -> bool:
    """本机端口当前是否可绑定（True = 空闲）。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", int(port)))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def pick_port(preferred: int = 0) -> int:
    """优先使用上次端口；否则从 9222 起找到第一个空闲端口。"""
    if preferred and DEBUG_PORT_MIN <= int(preferred) <= DEBUG_PORT_MAX:
        if port_available(int(preferred)):
            return int(preferred)
    for port in range(DEBUG_PORT_MIN, DEBUG_PORT_MAX + 1):
        if port_available(port):
            return port
    return DEBUG_PORT_MIN


def find_ready_port() -> int:
    """扫描自动端口范围，返回已经有网易云页面的端口；没有返回 0。"""
    from .netease_client import available

    for port in range(DEBUG_PORT_MIN, DEBUG_PORT_MAX + 1):
        if available(0.12, port):
            return port
    return 0


def debug_ready(port: int = 0) -> bool:
    from .netease_client import available

    return available(0.3, port or None)


def launch_with_debug(exe: Path, port: int = DEBUG_PORT_MIN) -> bool:
    try:
        subprocess.Popen(
            [str(exe), f"--remote-debugging-port={int(port)}"],
            cwd=str(exe.parent),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return True
    except OSError:
        return False


def restart_with_debug(exe: Path, port: int = DEBUG_PORT_MIN) -> bool:
    try:
        subprocess.run(
            ["taskkill", "/F", "/IM", exe.name],
            capture_output=True,
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:  # noqa: BLE001
        pass
    time.sleep(0.9)
    return launch_with_debug(exe, port)


def wait_ready(timeout: float = 10.0, port: int = 0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if debug_ready(port):
            return True
        time.sleep(0.4)
    return False
