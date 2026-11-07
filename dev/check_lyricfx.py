"""v1.7.3 字素切分、字级时间轴与动画预算回归（50 例）。"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from PySide6.QtWidgets import QApplication

from lyricdesk.lyricdoc import LyricLine, LyricWord
from lyricdesk.lyricfx import (
    WordSpring,
    build_char_timeline,
    graphemes,
    render_budget,
    reveal_state,
    spring_step,
)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    del app
    cases: list[tuple[str, list[str], str]] = []
    for text in ("桌面歌词", "春风十里", "Hello", "world", "A B"):
        cases.append((text, list(text), "中文/英文/空格"))
    for text in ("e\u0301", "a\u0308", "n\u0303", "o\u0302", "u\u0308"):
        cases.append((text, [text], "组合音标"))
    for text in ("👨‍👩‍👧‍👦", "👩‍💻", "🏳️‍🌈", "❤️", "👍🏽"):
        cases.append((text, [text], "ZWJ/变体/肤色"))
    for text in ("🇨🇳", "🇺🇸", "🇯🇵", "🇰🇷", "🇫🇷"):
        cases.append((text, [text], "国旗"))
    for text in ("1️⃣", "2️⃣", "3️⃣", "#️⃣", "*️⃣"):
        cases.append((text, [text], "键帽"))
    for text in ("你好，世界", "Hi!", "¿Qué?", "“标题”", "……"):
        cases.append((text, graphemes(text), "标点保留"))
    cases.extend(
        [
            ("ab", ["a", "b"], "基础"),
            ("你😀", ["你", "😀"], "混合"),
            ("🇨🇳🇺🇸", ["🇨🇳", "🇺🇸"], "连续国旗"),
            ("👩🏽‍🚀", ["👩🏽‍🚀"], "职业 emoji"),
            ("x\u20e3", ["x\u20e3"], "组合键帽"),
        ]
    )
    for text in ("夜色温柔", "海阔天空", "光辉岁月", "富士山下", "喜帖街"):
        cases.append((text, list(text), "中文补充"))
    for text in ("shape", "sped up", "slowed", "nightcore", "remix"):
        cases.append((text, list(text), "英文补充"))
    for text in ("《歌词》", "Hello, world!", "A-B", "问：答", "（纯音乐）"):
        cases.append((text, graphemes(text), "标点补充"))
    for text in ("😀😃😄", "🎵🎶", "👨‍👩‍👧", "🏴‍☠️", "☺️"):
        cases.append((text, graphemes(text), "emoji 补充"))
    failed = 0
    for text, expected, label in cases:
        got = graphemes(text)
        ok = got == expected
        failed += 0 if ok else 1
        print(f"  {'OK  ' if ok else 'FAIL'} {label:10s} {text!r} -> {got!r}")

    line = LyricLine(
        time=10.0,
        end=14.0,
        text="Hello，世界！",
        words=[
            LyricWord(10.0, 1.0, "Hello"),
            LyricWord(11.0, 1.0, "，"),
            LyricWord(12.0, 2.0, "世界！"),
        ],
    )
    timings = build_char_timeline(line, "Microsoft YaHei UI", 32, 600, 600)
    punctuation_hidden = all(
        timing.char not in ("，", "！") for timing in timings
    )
    ordered = all(
        later.start >= earlier.start - 0.001
        for earlier, later in zip(timings, timings[1:])
    )
    solid, tail, feather, opacity = reveal_state(timings, 11.4)
    timeline_ok = punctuation_hidden and ordered and 0.0 < solid <= tail <= 1.0 and feather > 0 and opacity == 1
    failed += 0 if timeline_ok else 1
    print(f"  {'OK  ' if timeline_ok else 'FAIL'} 真实词展开与标点并时 {timings!r}")

    plain = LyricLine(time=20.0, end=23.0, text="i am a long lyric")
    plain_timings = build_char_timeline(plain, "Microsoft YaHei UI", 32, 400, 600)
    width_split = (
        len(plain_timings) >= 10
        and plain_timings[0].start == 20.0
        and plain_timings[-1].end <= 23.001
        and plain_timings[2].width > plain_timings[1].width
    )
    failed += 0 if width_split else 1
    print(f"  {'OK  ' if width_split else 'FAIL'} 无逐字按字宽分配")

    budgets = [render_budget(value) for value in (0.08, 0.15, 2.0)]
    budget_ok = (
        budgets[0].klass == "micro"
        and budgets[0].reveal == "instant"
        and budgets[1].klass == "short"
        and budgets[1].reveal == "fast"
        and budgets[2].klass == "normal"
    )
    failed += 0 if budget_ok else 1
    print(f"  {'OK  ' if budget_ok else 'FAIL'} 动画预算 {budgets!r}")

    spring = WordSpring()
    states = []
    for frame in range(30):
        states = spring.update(timings, 10.8 + frame * 0.033, budgets[2], 0.033)
    scales = [state.value for state in states]
    spring_ok = (
        len(set(round(value, 4) for value in scales)) >= 2
        and max(scales) > 1.0
        and all(1.0 <= value <= 1.25 for value in scales)
    )
    failed += 0 if spring_ok else 1
    print(f"  {'OK  ' if spring_ok else 'FAIL'} 逐字弹簧错峰 {scales!r}")

    state = spring_step(states[0], 0.5, 1.16)
    bounded = 1.0 <= state.value <= 1.25
    failed += 0 if bounded else 1
    print(f"  {'OK  ' if bounded else 'FAIL'} 极端 dt 弹簧仍夹紧 {state.value:.3f}")

    print(f"\n字素样例：{len(cases)} 个；失败 {failed} 项")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
