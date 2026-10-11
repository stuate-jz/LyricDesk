r"""回归检查：歌词残缺时会不会换源。

之前出过的事故：某个曲库的同名条目只有半首（200 秒的歌只有 59 秒的歌词），
程序却认了它，结果播到一半歌词就卡在最后一行不动。

这里用假的曲库来验证选源逻辑，不联网。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lyricdesk import lyrics as L  # noqa: E402
from lyricdesk.lyrics import Lyrics, _coverage  # noqa: E402


def lrc(*times: float) -> str:
    return "\n".join(
        f"[{int(t) // 60:02d}:{t % 60:05.2f}]第 {index + 1} 句歌词"
        for index, t in enumerate(times)
    )


def make_candidate(title: str, artist: str, duration: float) -> dict:
    return L.make_candidate(title, artist, duration)


def main() -> int:
    failures = 0

    print("时长筛选（正在播的歌 197 秒，同名不同版本）：")
    for duration, label in ((193.0, "时长接近"), (60.0, "只有 60 秒"), (209.1, "抖音版")):
        candidate = make_candidate("我们俩", "Yihuik苡慧", duration)
        score = L.score_candidate(candidate, "我们俩", "Yihuik苡慧", 197.0)
        print(f"  候选时长={duration:6.1f}s（{label}）→ 匹配分 {score:.3f}")
    near = L.score_candidate(make_candidate("我们俩", "Yihuik苡慧", 193.0), "我们俩", "Yihuik苡慧", 197.0)
    far = L.score_candidate(make_candidate("我们俩", "Yihuik苡慧", 60.0), "我们俩", "Yihuik苡慧", 197.0)
    ok_near = near > far
    print(f"  {'OK  ' if ok_near else 'FAIL'} 时长接近的更优先（{near:.3f} > {far:.3f}）")
    failures += 0 if ok_near else 1

    print("\n覆盖率计算：")
    lines = L.parse_lrc(lrc(1, 30, 59), "x", 200.0, "y")
    covered = _coverage(lines, 200.0)
    ok = abs(covered - 0.295) < 0.01
    print(f"  {'OK  ' if ok else 'FAIL'} 59s / 200s -> {covered:.2f}")
    failures += 0 if ok else 1

    print("\n选源（第一个源的歌词只有 30%，应该换到第二个源）：")
    calls: list[str] = []

    def search_short(query: str) -> list[dict]:
        return [make_candidate("我们俩", "Yihuik苡慧", 200.0)]

    def search_full(query: str) -> list[dict]:
        return [make_candidate("我们俩", "Yihuik苡慧", 200.0)]

    def resolve_short(candidate: dict) -> str:
        calls.append("short")
        return lrc(1, 20, 59)

    def resolve_full(candidate: dict) -> str:
        calls.append("full")
        return lrc(1, 40, 80, 120, 160, 190)

    saved = L._PROVIDERS
    try:
        L._PROVIDERS = (
            ("short", "残缺源", search_short, resolve_short),
            ("full", "完整源", search_full, resolve_full),
        )
        result = L.fetch("我们俩", "Yihuik苡慧", 200.0)
    finally:
        L._PROVIDERS = saved

    ok2 = result.source == "完整源" and len(result.lines) >= 6
    print(f"  {'OK  ' if ok2 else 'FAIL'} 选中来源={result.source!r} 行数={len(result.lines)}")
    print(f"       实际调用顺序：{calls}")
    failures += 0 if ok2 else 1

    print("\n选源（第一个源就完整，应该直接用，不去碰第二个源）：")
    calls.clear()

    def resolve_ok(candidate: dict) -> str:
        calls.append("first")
        return lrc(1, 60, 120, 190)

    try:
        L._PROVIDERS = (
            ("first", "首选源", search_short, resolve_ok),
            ("second", "备用源", search_full, resolve_full),
        )
        result2 = L.fetch("我们俩", "Yihuike", 200.0)
    finally:
        L._PROVIDERS = saved

    ok3 = result2.source == "首选源" and calls == ["first"]
    print(f"  {'OK  ' if ok3 else 'FAIL'} 选中来源={result2.source!r} 调用={calls}")
    failures += 0 if ok3 else 1

    print("\n按播放器优先（在放网易云时，应该先试网易云的曲库）：")
    calls.clear()

    def search_any(query: str) -> list[dict]:
        return [make_candidate("我们俩", "Yihuik苡慧", 197.0)]

    def resolve_a(candidate: dict) -> str:
        calls.append("qq")
        return lrc(1, 60, 120, 190)

    def resolve_b(candidate: dict) -> str:
        calls.append("netease")
        return lrc(1, 60, 120, 190)

    try:
        L._PROVIDERS = (
            ("qq", "QQ音乐", search_any, resolve_a),
            ("netease", "网易云", search_any, resolve_b),
        )
        result3 = L.fetch("我们俩", "Yihuik苡慧", 197.0, prefer="netease")
    finally:
        L._PROVIDERS = saved

    ok4 = result3.source == "网易云" and calls[:1] == ["netease"]
    print(f"  {'OK  ' if ok4 else 'FAIL'} 选中来源={result3.source!r} 调用顺序={calls}")
    failures += 0 if ok4 else 1

    print("\n" + ("有失败项" if failures else "全部通过"))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
