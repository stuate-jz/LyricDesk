r"""看看常见音乐软件有没有把歌词缓存在本地（能不能直接读）。

    python dev\probe_player_lyrics.py
"""

from __future__ import annotations

import os
from pathlib import Path

APP_DATA = Path(os.environ.get("APPDATA", ""))
LOCAL_APP_DATA = Path(os.environ.get("LOCALAPPDATA", ""))
USER_PROFILE = Path(os.environ.get("USERPROFILE", ""))

CANDIDATES: tuple[tuple[str, Path], ...] = (
    ("网易云·歌词缓存", LOCAL_APP_DATA / "Netease" / "CloudMusic" / "webdata" / "lyrics"),
    ("网易云·根目录", LOCAL_APP_DATA / "Netease" / "CloudMusic"),
    ("QQ音乐·AppData", APP_DATA / "Tencent" / "QQMusic"),
    ("QQ音乐·LocalAppData", LOCAL_APP_DATA / "Tencent" / "QQMusic"),
    ("QQ音乐·Documents", USER_PROFILE / "Documents" / "QQMusic"),
    ("酷狗·AppData", APP_DATA / "KuGou8"),
    ("酷我", APP_DATA / "KwMusic"),
    ("Spotify", LOCAL_APP_DATA / "Spotify"),
)


def describe(path: Path, limit: int = 4) -> None:
    if not path.exists():
        print(f"  x {path}  （不存在）")
        return
    files = 0
    samples: list[str] = []
    lyric_hits: list[str] = []
    for item in path.rglob("*"):
        try:
            if not item.is_file():
                continue
        except OSError:
            continue
        files += 1
        if files <= limit:
            samples.append(item.name)
        if (
            item.suffix.lower() in (".lrc", ".krc", ".qrc", ".txt")
            and len(lyric_hits) < 5
        ):
            lyric_hits.append(str(item.relative_to(path)))
    print(f"  OK {path}  文件数≈{files}")
    if samples:
        print(f"     示例：{samples}")
    if lyric_hits:
        print(f"     歌词类文件：{lyric_hits}")


def main() -> int:
    print("查找各播放器的本地歌词缓存：\n")
    for label, path in CANDIDATES:
        print(f"[{label}]")
        describe(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
