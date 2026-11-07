"""v1.7.2 现场错位样本回归：制作信息、变速版与官方逐字。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lyricdesk.lyricdoc import validate
from lyricdesk.sources.netease import fetch_doc
from lyricdesk.titles import is_variant_title, variant_speed


def main() -> int:
    failures = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        failures += 0 if ok else 1
        print(f"  {'OK  ' if ok else 'FAIL'} {name}" + (f"  —— {detail}" if detail else ""))

    check("识别 1.1x", is_variant_title("悬溺（1.1x）") and variant_speed("悬溺（1.1x）") == 1.1)
    check("识别 Sped Up", is_variant_title("Song (Sped Up)"))
    check("普通歌名不误判", not is_variant_title("普通歌曲"))

    you = fetch_doc(1996909642, "you")
    check("《你》取得歌词", you is not None and bool(you.lines))
    if you:
        check("《你》首句正确", you.lines[0].text == "我想要你的爱" and you.lines[0].time == 2.76)
        check("《你》没有制作信息", not any("作词" in line.text or "作曲" in line.text for line in you.lines))
        check("《你》至少 50 行", len(you.lines) >= 50, str(len(you.lines)))

    fast = fetch_doc(2055864684, "fast")
    check("《悬溺 1.1x》使用官方时间轴", fast is not None and bool(fast.lines))
    if fast:
        check("《悬溺 1.1x》首句 28.77s", fast.lines[0].time == 28.77, str(fast.lines[0].time))
        check("《悬溺 1.1x》没有原版 31.43s 首句", fast.lines[0].time != 31.43)

    for title, song_id, minimum_words in (
        ("演员", 32507038, 400),
        ("孤勇者", 1901371647, 400),
        ("后来", 254574, 200),
        ("光年之外", 449818741, 300),
    ):
        doc = fetch_doc(song_id, str(song_id))
        words = sum(len(line.words) for line in doc.lines) if doc else 0
        check(f"{title}逐字", words >= minimum_words, f"{words} 字")
        if doc and doc.has_words:
            check(f"{title}校验", validate(doc, 0.0)[0], str(validate(doc, 0.0)[1]))

    print("全部通过" if not failures else f"{failures} 项失败")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
