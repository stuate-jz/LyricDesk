"""v1.7.6 发版元信息纯文本校验。"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def match(path: Path, pattern: str) -> str:
    text = path.read_text(encoding="utf-8-sig")
    found = re.search(pattern, text, re.MULTILINE)
    return found.group(1).strip() if found else ""


def main() -> int:
    version = match(
        ROOT / "lyricdesk" / "__init__.py",
        r'^__version__\s*=\s*"([^"]+)"',
    )
    app_version = match(
        ROOT / "installer.iss", r'^#define\s+AppVersion\s+"([^"]+)"'
    )
    output_name = match(
        ROOT / "installer.iss", r'^OutputBaseFilename\s*=\s*([^\r\n]+)'
    )
    setup_version = match(
        ROOT / "installer" / "setup_app.py",
        r'^APP_VERSION\s*=\s*"([^"]+)"',
    )
    packaging = json.loads(
        (ROOT / "packaging" / "update.json").read_text(encoding="utf-8-sig")
    )
    docs = json.loads(
        (ROOT / "docs" / "update.json").read_text(encoding="utf-8-sig")
    )
    expected_name = f"LyricDesk-Setup-v{version}.exe"
    checks = [
        ("__version__ 与 installer.iss", bool(version) and app_version == version),
        ("OutputBaseFilename", output_name == f"LyricDesk-Setup-v{version}"),
        ("packaging/update.json", packaging.get("version") == version),
        ("docs/update.json", docs.get("version") == version),
        ("installer/setup_app.py", setup_version == version),
        (
            "发布资产命名",
            bool(re.fullmatch(r"LyricDesk-Setup-v\d+\.\d+\.\d+\.exe", expected_name)),
        ),
    ]
    failed = 0
    for name, ok in checks:
        failed += 0 if ok else 1
        print(f"  {'OK  ' if ok else 'FAIL'} {name}")
    print(f"版本：{version}")
    print("全部通过" if not failed else f"{failed} 项失败")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
