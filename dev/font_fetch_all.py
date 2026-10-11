"""把在线字体全部下载到 %APPDATA%\\LyricDesk\\fonts。"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lyricdesk.fonts import (  # noqa: E402
    ONLINE_FONTS,
    download,
    downloaded,
    family_for,
    register_all,
    user_font_dir,
)


def main() -> int:
    app = QApplication(sys.argv)
    register_all()
    print("字体目录:", user_font_dir())
    todo = [item for item in ONLINE_FONTS if not downloaded(item)]
    print(f"待下载 {len(todo)} 款，共约 {sum(i.size_mb for i in todo):.0f} MB\n")

    for index, item in enumerate(todo, 1):
        print(f"[{index}/{len(todo)}] {item.label}  ({item.size_mb:.1f} MB) ...", flush=True)
        result: list[tuple[bool, str]] = []
        download(item, lambda ok, msg: result.append((ok, msg)))
        deadline = time.time() + 900
        while not result and time.time() < deadline:
            time.sleep(0.5)
        if not result:
            print("      超时")
            continue
        ok, message = result[0]
        target = user_font_dir() / item.filename
        size = target.stat().st_size / 1024 / 1024 if target.exists() else 0
        print(f"      {'成功' if ok else '失败'}：{message}  文件 {size:.2f} MB  族名 {family_for(item)}")

    print("\n最终字体目录：")
    for path in sorted(user_font_dir().glob("*")):
        print(f"   {path.name:<40} {path.stat().st_size/1024/1024:6.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
