r"""测一测常见静态托管在国内（用户当前网络）能不能访问。

做发布页要发给朋友，如果托管地址朋友打不开，做得再好看也没用。
"""

from __future__ import annotations

import time

import requests

TARGETS = {
    "Gitee 仓库页": "https://gitee.com/pursue-studies/LyricDesk",
    "Gitee Releases": "https://gitee.com/pursue-studies/LyricDesk/releases",
    "Cloudflare Pages": "https://pages.dev",
    "Vercel": "https://vercel.app",
    "Netlify": "https://netlify.app",
    "GitHub Pages": "https://pages.github.com",
    "Gitee Pages(已下线?)": "https://pursue-studies.gitee.io/",
    "shields.io 徽章": "https://img.shields.io/badge/test-ok-blue",
}


def main() -> int:
    for name, url in TARGETS.items():
        start = time.time()
        try:
            response = requests.get(
                url,
                timeout=(5, 10),
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            )
            print(
                f"{name:20s} OK    {response.status_code}  {time.time() - start:.1f}s"
            )
        except Exception as exc:  # noqa: BLE001
            print(
                f"{name:20s} FAIL  {type(exc).__name__}  {time.time() - start:.1f}s"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
