"""v1.7.0 A3：网易云 songId、富文本 LRC、YRC 与翻译/音译。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from lyricdesk.sources.netease import fetch_doc, parse_payload

FAILS = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILS
    if not ok:
        FAILS += 1
    print(f"  {'OK  ' if ok else 'FAIL'} {name}" + (f"  —— {detail}" if detail else ""))


def main() -> int:
    rich = (
        '{"t":0,"c":[{"tx":"第一句"}]}\n'
        '{"t":1000,"c":[{"tx":"第二句"}]}'
    )
    yrc = "[3000,2000](3000,500,0)逐(3500,500,0)字(4000,500,0)演(4500,500,0)示"
    payload = {
        "lrc": {"lyric": rich},
        "yrc": {"lyric": yrc},
        "tlyric": {"lyric": "[00:03.00]翻译"},
        "romalrc": {"lyric": "[00:03.00]roma"},
    }
    doc = parse_payload(payload, "test")
    check("解析富文本 LRC", doc is not None and len(doc.lines) == 3)
    check("YRC 变成逐字", doc is not None and doc.lines[-1].words[0].text == "逐")
    check("首字等于行首", doc is not None and abs(doc.lines[-1].words[0].time - doc.lines[-1].time) < 0.001)
    check("翻译按时间戳对齐", doc is not None and doc.lines[-1].trans == "翻译")
    check("音译按时间戳对齐", doc is not None and doc.lines[-1].roma == "roma")

    print("\n真实 songId：")
    rich_live = fetch_doc(1403318151, "live-rich")
    check("富文本官方词", rich_live is not None and bool(rich_live.lines))
    detailed_live = fetch_doc(1901371647, "live-yrc")
    check("YRC 官方词", detailed_live is not None and detailed_live.has_words)
    if detailed_live is not None:
        check("真实 YRC 行数", len(detailed_live.lines) >= 8, str(len(detailed_live.lines)))

    print("\n结果：", "全部通过" if FAILS == 0 else f"{FAILS} 项失败")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
