r"""回归检查：歌词偏移是「按歌记」的，不能互相影响。

    python dev\check_offsets.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lyricdesk import config  # noqa: E402

config.SETTINGS_PATH = Path(tempfile.mkdtemp(prefix="ld-offset-")) / "settings.json"


def main() -> int:
    failures = 0

    def check(label: str, got, want) -> None:
        nonlocal failures
        ok = got == want
        failures += 0 if ok else 1
        print(f"  {'OK  ' if ok else 'FAIL'} {label}：{got!r}（期望 {want!r}）")

    settings = config.Settings()
    print("刚装上（没有记录）：")
    check("默认偏移", settings.offset_for("A|B"), 0)

    print("\n给《A》调 -2 秒：")
    settings.set_offset_for("A|B", -2000)
    check("《A》的偏移", settings.offset_for("A|B"), -2000)
    check("《B》不受影响", settings.offset_for("C|D"), 0)

    print("\n把默认值改成 +0.5 秒：")
    settings.offset_ms = 500
    check("《A》保持自己的 -2000", settings.offset_for("A|B"), -2000)
    check("没调过的歌用默认 500", settings.offset_for("C|D"), 500)

    print("\n《A》恢复默认：")
    settings.set_offset_for("A|B", 0)
    check("《A》回到 500", settings.offset_for("A|B"), 500)
    check("记录里已经清掉", "A|B" in settings.song_offsets, False)

    print("\n存盘再读回来：")
    settings.set_offset_for("X|Y", 1234)
    settings.save()
    again = config.Settings.load()
    check("默认值", again.offset_ms, 500)
    check("每歌记录", again.song_offsets, {"X|Y": 1234})
    check("《X》的偏移", again.offset_for("X|Y"), 1234)

    print("\n超范围会被夹回去：")
    settings.set_offset_for("Z|W", 999999)
    check("夹到 30000", settings.offset_for("Z|W"), 30000)

    print("\n同名不同歌手 / 不同版本 / 不同播放器 各自独立：")
    keys = {
        "刘若英唱的《后来》": "qqmusic|后来|刘若英|320",
        "别人翻唱的《后来》": "qqmusic|后来|某某某|298",
        "同歌手另一个版本": "qqmusic|后来|刘若英|410",
        "同一首但在 Spotify": "spotify|后来|刘若英|320",
    }
    for offset, key in enumerate(keys.values(), start=1):
        settings.set_offset_for(key, offset * 1000)
    values = [settings.offset_for(key) for key in keys.values()]
    check("四条记录互不影响", values, [1000, 2000, 3000, 4000])

    print("\n老版本留下的全局偏移会被清零（不让它套到每首歌上）：")
    legacy = config.SETTINGS_PATH
    legacy.write_text(
        '{"offset_ms": -6100, "song_offsets": {}, "mode": "lyrics"}',
        encoding="utf-8",
    )
    migrated = config.Settings.load()
    check("全局偏移清零", migrated.offset_ms, 0)
    check("每歌记录为空", migrated.song_offsets, {})

    print("\n新版自己保存过的文件，默认值不会被误清：")
    fresh = config.Settings()
    fresh.offset_ms = -800
    fresh.save()
    again2 = config.Settings.load()
    check("默认值保留 -800", again2.offset_ms, -800)

    print("\n" + ("有失败项" if failures else "全部通过"))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
