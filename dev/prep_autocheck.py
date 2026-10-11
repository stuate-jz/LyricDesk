r"""准备一个临时的 APPDATA，用来验证「启动时静默自查更新」。

    python dev\prep_autocheck.py <版本号>

会写好 settings.json（更新源指向同目录的 update.json）并把目录打印出来。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


def main() -> int:
    version = sys.argv[1] if len(sys.argv) > 1 else "9.9.9"
    root = Path(tempfile.mkdtemp(prefix="lyricdesk-autocheck-"))
    config = root / "LyricDesk"
    config.mkdir(parents=True, exist_ok=True)

    feed = config / "update.json"
    feed.write_text(
        json.dumps(
            {"version": version, "notes": "自动自查测试", "url": "https://example.com/dl"},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (config / "settings.json").write_text(
        json.dumps(
            {
                "mode": "depth3d",
                "update_source": feed.as_posix(),
                "update_last_check": 0,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(root)
    print("APPDATA", os.environ.get("APPDATA"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
