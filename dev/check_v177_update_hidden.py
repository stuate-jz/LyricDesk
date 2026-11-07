"""v1.7.7 更新脚本隐藏控制台回归。"""

from __future__ import annotations

import ctypes
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from lyricdesk.win_util import hidden_creation_flags, run_hidden  # noqa: E402

FAILS = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILS
    if not ok:
        FAILS += 1
    print(f"  {'OK  ' if ok else 'FAIL'} {name}" + (f"  —— {detail}" if detail else ""))


def visible_console_count() -> int:
    user32 = ctypes.windll.user32
    count = 0

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def callback(hwnd, _lparam):
        nonlocal count
        if not user32.IsWindowVisible(hwnd):
            return True
        name = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, name, 64)
        if name.value == "ConsoleWindowClass":
            count += 1
        return True

    user32.EnumWindows(callback, 0)
    return count


def main() -> int:
    flags = hidden_creation_flags()
    create_no_window = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    detached = int(getattr(subprocess, "DETACHED_PROCESS", 0))
    check("flags 包含 CREATE_NO_WINDOW", bool(flags & create_no_window))
    check("flags 不包含 DETACHED_PROCESS", not bool(flags & detached))

    with patch("lyricdesk.win_util.subprocess.Popen") as popen:
        run_hidden(["cmd", "/c", "echo hidden"])
        args, kwargs = popen.call_args
    actual_flags = int(kwargs.get("creationflags", 0))
    check("封装后仍使用隐藏标志", bool(actual_flags & create_no_window))
    check("封装后没有 DETACHED_PROCESS", not bool(actual_flags & detached))
    check("stdin 指向 DEVNULL", kwargs.get("stdin") is subprocess.DEVNULL)
    check("stdout 指向 DEVNULL", kwargs.get("stdout") is subprocess.DEVNULL)
    check("stderr 指向 DEVNULL", kwargs.get("stderr") is subprocess.DEVNULL)
    check("保持新进程组", bool(actual_flags & int(subprocess.CREATE_NEW_PROCESS_GROUP)))
    check("命令仍是 cmd /c", args[0][:2] == ["cmd", "/c"])

    source = (ROOT / "lyricdesk" / "window.py").read_text(encoding="utf-8")
    check("更新脚本走 run_hidden", 'run_hidden(["cmd", "/c"' in source)
    check("window.py 不再使用 DETACHED_PROCESS", "DETACHED_PROCESS" not in source)

    script = Path(tempfile.gettempdir()) / "lyricdesk-hidden-console-check.cmd"
    script.write_text("@echo off\r\nping -n 3 127.0.0.1 >nul\r\n", encoding="ascii")
    before = visible_console_count()
    process = run_hidden(["cmd", "/c", str(script)])
    time.sleep(0.35)
    during = visible_console_count()
    try:
        process.terminate()
        process.wait(timeout=2)
    except Exception:  # noqa: BLE001
        pass
    script.unlink(missing_ok=True)
    check("实际启动期间新增可见控制台", during - before == 0, f"{before} → {during}")

    print("\n结果：", "全部通过" if FAILS == 0 else f"{FAILS} 项失败")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
