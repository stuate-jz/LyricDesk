r"""自检：视频标题清洗（任务 7）。

用 10 个真实样式的 B 站标题 + 几条正常歌名，确认「噪声被洗掉、书名叫不动」。

用法： python dev\check_titles.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from lyricdesk.titles import clean_title  # noqa: E402

FAILS = 0

CASES = [
    # (原始标题, 期望)
    ("【4K修复】周杰伦 - 七里香 (Official MV)_哔哩哔哩_bilibili", "周杰伦 - 七里香"),
    ("周杰伦《晴天》官方MV_哔哩哔哩_bilibili", "周杰伦《晴天》"),
    ("【Hi-Res】五月天 - 倔强【1080P】_bilibili", "五月天 - 倔强"),
    ("邓紫棋 - 光年之外 (Lyric Video) - YouTube", "邓紫棋 - 光年之外"),
    ("【MV】陈奕迅 - 十年 官方MV", "陈奕迅 - 十年"),
    ("李荣浩 - 年少有为 [Official MV]_哔哩哔哩_bilibili", "李荣浩 - 年少有为"),
    ("【合集】周杰伦 20 首经典歌曲_哔哩哔哩_bilibili", "周杰伦 20 首经典歌曲"),
    ("《后浪》_哔哩哔哩_bilibili", "《后浪》"),
    ("Taylor Swift - Blank Space (Official Music Video)_哔哩哔哩_bilibili", "Taylor Swift - Blank Space"),
    ("【中日字幕】米津玄師 - Lemon_哔哩哔哩_bilibili", "米津玄師 - Lemon"),
    # 下面这些是「不该动」的：内容标签 / 正常歌名 / 书名号
    ("【纯音乐】久石让 - Summer", "【纯音乐】久石让 - Summer"),
    ("七里香", "七里香"),
    ("《晴天》", "《晴天》"),
    ("后浪", "后浪"),
    ("周杰伦", "周杰伦"),
]


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILS
    if not ok:
        FAILS += 1
    print(f"  {'OK  ' if ok else 'FAIL'} {name}" + (f"  —— {detail}" if detail else ""))


def main() -> int:
    for raw, want in CASES:
        got = clean_title(raw)
        check(f"{raw[:34]:<34} → {got!r}", got == want, f"期望 {want!r}")

    print()
    print("边界情况：")
    check("纯噪声洗成空（调用方要用原始标题兜底）", clean_title("【4K】_哔哩哔哩_bilibili") == "", repr(clean_title("【4K】_哔哩哔哩_bilibili")))
    check("空字符串安全", clean_title("") == "")
    check("None 安全", clean_title(None) == "")
    sample = "【4K修复】周杰伦 - 七里香 (Official MV)_哔哩哔哩_bilibili"
    check("清洗是幂等的", clean_title(clean_title(sample)) == clean_title(sample), repr(clean_title(clean_title(sample))))
    check("多余空白被收掉", clean_title("  周杰伦   -   七里香  ") == "周杰伦 - 七里香", repr(clean_title("  周杰伦   -   七里香  ")))

    print()
    print("全部通过" if FAILS == 0 else f"{FAILS} 项没通过")
    return 0 if FAILS == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
