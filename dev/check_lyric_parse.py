"""v1.7.2 网易云混合歌词与 klyric 解析回归。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lyricdesk.sources.netease import fetch_doc, parse_payload


def main() -> int:
    mixed = (
        '{"t":0,"c":[{"tx":"作词: "},{"tx":"测试作者"}]}\n'
        '{"t":1000,"c":[{"tx":"作曲: "},{"tx":"测试作者"}]}\n'
        "[00:02.76]我想要你的爱\n"
        "[00:05.71]想要被你爱\n"
        "[00:09.30]思念它从何来"
    )
    klyric = (
        "[2760,1800]<0,300,0>我<300,300,0>想<600,300,0>要\n"
        "[5710,2500]<0,500,0>想<500,500,0>要<1000,500,0>被\n"
        "[9300,2600]<0,600,0>思<600,600,0>念"
    )
    doc = parse_payload(
        {
            "lrc": {"lyric": mixed},
            "klyric": {"lyric": klyric},
        },
        "mixed-test",
    )
    checks = []
    checks.append(("混合格式保留正文", doc is not None and len(doc.lines) == 3))
    checks.append(("制作信息被过滤", doc is not None and doc.lines[0].text == "我想要你的爱"))
    checks.append(("首句时间正确", doc is not None and abs(doc.lines[0].time - 2.76) < 0.001))
    checks.append(("klyric 逐字生效", bool(doc and doc.has_words and len(doc.lines[0].words) == 3)))
    checks.append((
        "klyric 偏移相对行首",
        bool(doc and abs(doc.lines[0].words[1].time - 3.06) < 0.001),
    ))

    live = fetch_doc(1996909642, "you")
    checks.append(("《你》首行不是制作信息", bool(live and live.lines and live.lines[0].time == 2.76)))
    checks.append(("《你》至少 50 行", bool(live and len(live.lines) >= 50)))

    failed = 0
    for name, ok in checks:
        print(f"  {'OK  ' if ok else 'FAIL'} {name}")
        failed += 0 if ok else 1
    print("全部通过" if not failed else f"{failed} 项失败")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
