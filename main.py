"""打包入口（PyInstaller 使用）。"""

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _fatal(message: str) -> None:
    """无控制台环境下也能看到错误。"""
    # 先落一份日志，方便事后排查（打包版没有控制台）
    try:
        from pathlib import Path

        base = os.environ.get("APPDATA") or os.environ.get("TEMP") or "."
        log_dir = Path(base) / "LyricDesk"
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "startup-error.log").write_text(message, encoding="utf-8")
    except Exception:
        pass
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "桌面歌词 · 启动失败", 0x10)
    except Exception:
        pass


def run() -> int:
    if "--uninstall" in sys.argv:
        from lyricdesk.uninstall import main as uninstall_main

        return uninstall_main()
    try:
        from lyricdesk.app import main
    except Exception:
        _fatal(
            "缺少运行库，程序无法启动。\n\n"
            "如果你是直接拿到 exe 的，请确认文件下载完整；\n"
            "如果是源码运行，请先安装 requirements.txt 里的依赖。\n\n"
            + traceback.format_exc(limit=3)
        )
        return 1
    return main()


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except SystemExit:
        raise
    except Exception:
        _fatal("程序发生未预期的错误：\n\n" + traceback.format_exc())
        raise SystemExit(1)
