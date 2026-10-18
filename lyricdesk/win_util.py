"""Windows 原生窗口小工具。

Qt 的 ``setWindowFlag()`` 在**可见窗口**上会重建原生窗口（hide → 改样式 → show），
表现就是"闪一下"。改置顶其实只需要动 Z 序，用 SetWindowPos 就够了，不重建、不闪。
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

_HWND_TOPMOST = -1
_HWND_NOTOPMOST = -2
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOACTIVATE = 0x0010
_GWL_EXSTYLE = -20
_WS_EX_TOPMOST = 0x00000008

try:
    _USER32 = ctypes.windll.user32
    # 必须声明参数类型：64 位下 HWND 是指针大小，
    # 直接传 -1/-2 这种整数会被当成 32 位 int，调用就会失败（实测 SetWindowPos 返回 0）。
    _USER32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    _USER32.SetWindowPos.restype = wintypes.BOOL
    _USER32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    _USER32.GetWindowLongW.restype = ctypes.c_long
except Exception:  # noqa: BLE001
    _USER32 = None


def set_native_topmost(widget, on: bool) -> bool:
    """用 SetWindowPos 改置顶（不重建窗口）。

    返回 True = 调用成功；False = 环境不支持（非 Windows / 没有 HWND），
    调用方可以退回 setWindowFlag 的老办法。
    """
    try:
        if _USER32 is None:
            return False
        hwnd = int(widget.winId())
        if not hwnd:
            return False
        return bool(
            _USER32.SetWindowPos(
                wintypes.HWND(hwnd),
                wintypes.HWND(_HWND_TOPMOST if on else _HWND_NOTOPMOST),
                0,
                0,
                0,
                0,
                _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE,
            )
        )
    except Exception:  # noqa: BLE001
        return False


def is_topmost(widget) -> bool:
    """当前是否真的置顶（排查 / 自检用）。"""
    try:
        if _USER32 is None:
            return False
        hwnd = int(widget.winId())
        if not hwnd:
            return False
        style = _USER32.GetWindowLongW(wintypes.HWND(hwnd), _GWL_EXSTYLE)
        return bool(style & _WS_EX_TOPMOST)
    except Exception:  # noqa: BLE001
        return False
