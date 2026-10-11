r"""把 release-page/ 同步到 docs/（GitHub Pages 用的那一份）。

用法：
    python dev\build_pages.py

做的事：
    1. release-page\index.html       → docs\index.html
    2. release-page\update.json      → docs\update.json
    3. release-page\screenshots\*.png → docs\screenshots\（只这三张，不会把根目录的截图拉进来）
    4. 确保 docs\.nojekyll 存在（空文件；不然 Jekyll 会忽略 _ 开头的文件）
    5. 外链自查：页面里出现 <link href="http / <script src="http / @import url(http / url(http
       就打印警告并以非零退出码结束（弱网下外链会卡住，整页白屏）
    6. 再确认两个下载入口写死在页面里

Pages 的源是 main 分支的 /docs 目录，所以这个脚本跑完还要 commit + push 才在网页上生效。
两份页面（release-page\index.html 与 docs\index.html）内容保持一致，改页面时跑一次这个脚本即可，
不要手改两份。
"""

from __future__ import annotations

import filecmp
import shutil
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "release-page"
TARGET = ROOT / "docs"

# 命中任意一条就说明页面引进了外链资源
BAD_PATTERNS = (
    '<link href="http',
    "<link href='http",
    '<script src="http',
    "<script src='http",
    "@import url(http",
    "url(http",
)

# 两个下载入口必须写死在页面里（不依赖 update.json 才点得动）
REQUIRED = (
    "https://gitee.com/pursue-studies/LyricDesk/releases/latest",
    "https://github.com/stuate-jz/LyricDesk/releases/latest",
)


def copy_file(source: Path, target: Path) -> str:
    """复制；内容一样就跳过，返回一句状态。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and filecmp.cmp(source, target, shallow=False):
        return "未变"
    shutil.copy2(source, target)
    return "已更新"


def scan_external(page: Path) -> list[str]:
    """查页面里的外链资源，返回问题清单（空 = 干净）。"""
    if not page.exists():
        return []
    problems: list[str] = []
    for line_no, line in enumerate(page.read_text(encoding="utf-8").splitlines(), 1):
        for pattern in BAD_PATTERNS:
            if pattern in line:
                problems.append(
                    f"  {page.name} 第 {line_no} 行出现外链资源 {pattern!r}：{line.strip()[:100]}"
                )
    return problems


def main() -> int:
    if not (SOURCE / "index.html").exists():
        print(f"找不到 {SOURCE / 'index.html'}：先确认 release-page/ 里有没有 index.html。")
        return 1

    print(f"同步 {SOURCE} → {TARGET}\n")

    # 复制之前先把两份页面都扫一遍：只改 docs/ 那一份也要能挡住（否则会被复制覆盖掉，看不出问题）
    problems = scan_external(SOURCE / "index.html") + scan_external(TARGET / "index.html")
    if problems:
        print("[!] 页面引用了外链资源（CDN / 外链字体 / 外链 JS），弱网下会卡住整页，先删掉再跑：")
        for item in problems:
            print(item)
        return 1

    states: list[tuple[str, str]] = [
        ("index.html", copy_file(SOURCE / "index.html", TARGET / "index.html")),
        ("update.json", copy_file(SOURCE / "update.json", TARGET / "update.json")),
    ]

    shots = sorted((SOURCE / "screenshots").glob("*.png"))
    for item in shots:
        states.append(
            (
                f"screenshots/{item.name}",
                copy_file(item, TARGET / "screenshots" / item.name),
            )
        )

    nojekyll = TARGET / ".nojekyll"
    if nojekyll.exists():
        states.append((".nojekyll", "未变"))
    else:
        nojekyll.parent.mkdir(parents=True, exist_ok=True)
        nojekyll.write_bytes(b"")
        states.append((".nojekyll", "新建（空文件）"))

    for name, state in states:
        print(f"  [{state}] {name}")
    if len(shots) != 3:
        print(
            f"  [!] release-page/screenshots 里有 {len(shots)} 张图，"
            "预期 3 张（3d.png / album.png / split.png）"
        )

    page = (TARGET / "index.html").read_text(encoding="utf-8")
    missing = [url for url in REQUIRED if url not in page]
    if missing:
        print("\n[!] 页面里找不到必需的下载入口（两个按钮的地址要写死）：")
        for url in missing:
            print(f"  {url}")
        return 1

    print("\n自查通过：没有外链资源，两个下载入口都在。")
    print("提示：docs/ 要 git add + commit + push 到 main，Pages（源 = main 的 /docs）才会更新。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
