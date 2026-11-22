"""收编同步 / 子进程渲染等价性检查。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEV = ROOT / "dev"


def run(name: str, extra_env: dict[str, str] | None = None) -> int:
    env = os.environ.copy()
    env.update(
        {
            "QT_QPA_PLATFORM": "offscreen",
            "QT_SCALE_FACTOR": "1.5",
            "CHECK_SPACING": "4.5",
        }
    )
    if extra_env:
        env.update(extra_env)
    print(f"== {name} ==")
    result = subprocess.run(
        [sys.executable, str(DEV / name)],
        cwd=str(ROOT),
        env=env,
    )
    return result.returncode


def main() -> int:
    failed = 0
    failed += run("check_line_art_parity.py") != 0
    failed += run("check_line_art_worker.py", {"CHECK_LAYOUT": "list"}) != 0
    failed += run("check_line_art_worker.py", {"CHECK_LAYOUT": "disc"}) != 0
    print(f"\n结果：{'全部通过' if failed == 0 else f'{failed} 条路径失败'}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
