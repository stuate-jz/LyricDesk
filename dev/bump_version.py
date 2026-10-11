r"""把版本号从 OLD 改成 NEW，覆盖所有需要同步的文件。

    python dev\bump_version.py 1.5.2
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    new = sys.argv[1].strip()
    parts = [int(p) for p in re.findall(r"\d+", new)[:4]]
    while len(parts) < 4:
        parts.append(0)
    tuple_text = f"({parts[0]}, {parts[1]}, {parts[2]}, {parts[3]})"

    jobs = {
        "lyricdesk/__init__.py": [
            (r'__version__ = "[^"]+"', f'__version__ = "{new}"')
        ],
        "packaging/version_info.txt": [
            (r"filevers=\([^)]*\)", f"filevers={tuple_text}"),
            (r"prodvers=\([^)]*\)", f"prodvers={tuple_text}"),
            (r'"FileVersion", "[^"]+"', f'"FileVersion", "{parts[0]}.{parts[1]}.{parts[2]}.{parts[3]}"'),
            (r'"ProductVersion", "[^"]+"', f'"ProductVersion", "{new}"'),
        ],
        "packaging/installer_version_info.txt": [
            (r"filevers=\([^)]*\)", f"filevers={tuple_text}"),
            (r"prodvers=\([^)]*\)", f"prodvers={tuple_text}"),
            (r'"FileVersion", "[^"]+"', f'"FileVersion", "{parts[0]}.{parts[1]}.{parts[2]}.{parts[3]}"'),
            (r'"ProductVersion", "[^"]+"', f'"ProductVersion", "{new}"'),
        ],
        "installer.iss": [
            (r'#define AppVersion "[^"]+"', f'#define AppVersion "{new}"'),
            (r"OutputBaseFilename=.*", f"OutputBaseFilename=桌面歌词-安装程序-v{new}"),
        ],
        "installer/setup_app.py": [
            (r'APP_VERSION = "[^"]+"', f'APP_VERSION = "{new}"')
        ],
        "packaging/update.json": [
            (r'"version": "[^"]+"', f'"version": "{new}"')
        ],
    }

    for relative, rules in jobs.items():
        path = ROOT / relative
        if not path.exists():
            print(f"  跳过（不存在）{relative}")
            continue
        text = path.read_text(encoding="utf-8")
        for pattern, replacement in rules:
            text = re.sub(pattern, replacement, text)
        path.write_text(text, encoding="utf-8")
        print(f"  已更新 {relative}")

    print(f"\n版本号已经统一成 {new}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
