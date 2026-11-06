"""v1.7.0 歌词准确度样本：网易云官方搜索 + 官方 LRC/YRC + 五项校验。"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from lyricdesk.lyricdoc import validate  # noqa: E402
from lyricdesk.lyrics import MIN_MATCH, fetch_enhanced  # noqa: E402

OUT = Path(__file__).resolve().parent / "v1.7.0-歌词准确度样本.md"

SAMPLES = [
    ("晴天", "周杰伦"),
    ("稻香", "周杰伦"),
    ("平凡之路", "朴树"),
    ("后来", "刘若英"),
    ("演员", "薛之谦"),
    ("Shape of You", "Ed Sheeran"),
    ("Someone Like You", "Adele"),
    ("Blinding Lights", "The Weeknd"),
    ("Yellow", "Coldplay"),
    ("Rolling in the Deep", "Adele"),
    ("Lemon", "米津玄師"),
    ("夜に駆ける", "YOASOBI"),
    ("ただ声一つ", "lol"),
    ("残酷な天使のテーゼ", "高橋洋子"),
    ("打上花火", "DAOKO/米津玄師"),
    ("海阔天空", "Beyond"),
    ("光辉岁月", "Beyond"),
    ("富士山下", "陈奕迅"),
    ("喜帖街", "谢安琪"),
    ("千千阙歌", "陈慧娴"),
]


def main() -> int:
    rows = []
    successful = 0
    word_tracks = 0
    alignment_ok = 0
    for index, (title, artist) in enumerate(SAMPLES, 1):
        print(f"[{index:02d}/20] {title} - {artist}")
        try:
            found = fetch_enhanced(title, artist)
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL 取词：{exc}")
            rows.append((title, artist, "-", "-", "-", f"取词失败：{exc}"))
            continue
        if not found.lines:
            rows.append((title, artist, "-", "-", "-", "无匹配歌词"))
            continue
        duration = float(found.track_duration or 0.0)
        score = float(found.match_score or 0.0)
        if score < MIN_MATCH:
            rows.append(
                (
                    title,
                    artist,
                    found.title or "-",
                    f"{score:.3f}",
                    "-",
                    f"低于阈值 {MIN_MATCH:.2f}",
                )
            )
            continue
        doc = found.doc or found.to_doc()
        ok, errors = validate(doc, duration)
        words = sum(len(line.words) for line in doc.lines)
        first_ok = all(
            not line.words or abs(line.words[0].time - line.time) <= 0.031
            for line in doc.lines
        )
        if ok:
            successful += 1
        if words:
            word_tracks += 1
        if first_ok:
            alignment_ok += 1
        detail = "通过" if ok else " / ".join(errors)
        rows.append(
            (
                title,
                artist,
                f"{found.title or '-'}（{found.source or found.provider}）",
                f"{score:.3f}",
                f"{len(doc.lines)} 行 / {words} 字" if words else f"{len(doc.lines)} 行",
                detail,
            )
        )
        time.sleep(0.12)

    lines = [
        "# v1.7.0 歌词准确度样本",
        "",
        f"- 通过五项校验：{successful}/20",
        f"- 含逐字时间：{word_tracks}/20",
        f"- 首字时间对齐：{alignment_ok}/20",
        f"- 匹配阈值：{MIN_MATCH:.2f}",
        "",
        "| # | 曲目 | 歌手 | 最高匹配 | 匹配分 | 行/字 | 校验 |",
        "| ---: | --- | --- | --- | ---: | --- | --- |",
    ]
    for index, row in enumerate(rows, 1):
        lines.append(
            "| {} | {} |".format(index, " | ".join(str(value) for value in row))
        )
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n通过 {successful}/20，逐字 {word_tracks}/20，首字对齐 {alignment_ok}/20")
    print(f"报告：{OUT}")
    return 0 if successful >= 17 and alignment_ok >= 17 else 1


if __name__ == "__main__":
    raise SystemExit(main())
