"""v1.7.2 网易云 12 首官方逐字覆盖率检查。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lyricdesk.lyricdoc import validate
from lyricdesk.sources.netease import fetch_doc

SAMPLES = (
    ("演员", "32507038"),
    ("孤勇者", "1901371647"),
    ("后来", "254574"),
    ("光年之外", "449818741"),
    ("晴天", "186016"),
    ("起风了", "1330348068"),
    ("平凡之路", "28815250"),
    ("悬溺（1.1x）", "2055864684"),
    ("你", "1996909642"),
    ("稻香", "185809"),
    ("Shape of You", "461324794"),
    ("Lemon", "536622304"),
)


def main() -> int:
    rows = []
    with_words = 0
    for title, song_id in SAMPLES:
        try:
            doc = fetch_doc(song_id, song_id)
        except Exception as exc:
            rows.append((title, song_id, 0, 0, f"网络失败：{type(exc).__name__}"))
            continue
        if doc is None:
            rows.append((title, song_id, 0, 0, "无歌词"))
            continue
        words = sum(len(line.words) for line in doc.lines)
        valid, errors = validate(doc, 0.0)
        has_words = bool(doc.has_words)
        with_words += 1 if has_words else 0
        rows.append(
            (
                title,
                song_id,
                len(doc.lines),
                words,
                "逐字" if has_words else "逐行",
                "通过" if valid else " / ".join(errors),
            )
        )
        print(f"{title:14s} id={song_id:10s} lines={len(doc.lines):3d} words={words:4d} {'KLYRIC' if has_words else 'LRC'}")

    print(f"\n12 首官方逐字覆盖：{with_words}/12")
    return 0 if with_words >= 4 else 1


if __name__ == "__main__":
    raise SystemExit(main())
