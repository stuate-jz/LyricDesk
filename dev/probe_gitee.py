r"""看一眼某个 Gitee 账号的情况：主页能不能打开、有哪些仓库。

    python dev\probe_gitee.py pursue-studies
"""

from __future__ import annotations

import re
import sys

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}


def get(url: str):
    try:
        return requests.get(url, timeout=(5, 12), headers=HEADERS)
    except Exception as exc:  # noqa: BLE001
        print(f"  {url} -> 打不开（{type(exc).__name__}）")
        return None


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    user = sys.argv[1].strip().strip("/")

    profile = get(f"https://gitee.com/{user}")
    if profile is None:
        return 1
    print(f"主页 https://gitee.com/{user} -> HTTP {profile.status_code}")
    if profile.status_code != 200:
        print("  主页打不开，检查用户名或账号是否已完成验证。")
        return 1

    title = re.search(r"<title>(.*?)</title>", profile.text, re.S)
    if title:
        print("  标题:", title.group(1).strip()[:70])

    pattern = re.compile(r'href="(/' + re.escape(user) + r'/[A-Za-z0-9_.\-]+)"')
    repos = sorted(set(pattern.findall(profile.text)))
    internal = ("/followers", "/following", "/projects", "/stars", "/watching")
    repos = [r for r in repos if not r.endswith(internal)]
    if repos:
        print("  主页上出现的仓库：")
        for repo in repos[:15]:
            print("   ", f"https://gitee.com{repo}")
    else:
        print("  主页上没看到仓库（可能还没建）")

    for candidate in ("LyricDesk", "lyricdesk", "桌面歌词"):
        response = get(f"https://gitee.com/{user}/{candidate}")
        if response is not None and response.status_code == 200:
            print(f"  仓库 {candidate} 已存在")
            return 0
    print("  LyricDesk 仓库还不存在")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
