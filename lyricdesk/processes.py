"""看一眼常见音乐软件有没有在运行（用于「打开音乐软件时自动显示歌词」）。"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

# 常见音乐软件的主程序名（小写）
MUSIC_EXES = frozenset(
    name.lower()
    for name in (
        "QQMusic.exe",
        "CloudMusic.exe",        # 网易云音乐
        "KuGou.exe",             # 酷狗音乐
        "KuGouService.exe",
        "KwMusic.exe",           # 酷我音乐
        "Spotify.exe",
        "foobar2000.exe",
        "PotPlayerMini64.exe",
        "PotPlayerMini.exe",
        "AIMP.exe",
        "AIMP64.exe",
        "MusicBee.exe",
        "deadbeef.exe",
        "iTunes.exe",
        "AppleMusic.exe",
        "Music.UWP.exe",
    )
)

TH32CS_SNAPPROCESS = 0x00000002
_INVALID_HANDLE = ctypes.c_void_p(-1).value


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


def running_processes() -> set[str] | None:
    """当前所有进程的可执行文件名（小写）；探测失败时返回 None。"""
    names: set[str] = set()
    try:
        kernel32 = ctypes.windll.kernel32
        snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if not snapshot or snapshot == _INVALID_HANDLE:
            return None
        try:
            entry = _PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
            if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
                return None
            while True:
                names.add(str(entry.szExeFile).lower())
                if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                    break
        finally:
            kernel32.CloseHandle(snapshot)
    except Exception:  # noqa: BLE001
        return None
    return names or None


def music_app_running() -> bool | None:
    """有没有音乐软件在跑；None 表示这次系统进程探测失败。"""
    names = running_processes()
    if names is None:
        return None
    return bool(names & MUSIC_EXES)
