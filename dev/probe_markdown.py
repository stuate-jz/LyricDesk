r"""看看 Gitee 的 Markdown 渲染支不支持 HTML（决定 README 能不能排版得更好看）。"""

from __future__ import annotations

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Content-Type": "application/json",
}

SAMPLE = """
<div align="center">

<h1>桌面歌词 LyricDesk</h1>

悬浮在桌面上的歌词组件

<a href="https://gitee.com/pursue-studies/LyricDesk/releases">
<img src="https://img.shields.io/badge/download-v1.5.2-38bdf8" alt="download">
</a>

</div>

| 版本 | 文件 |
| --- | --- |
| 免安装版 | 桌面歌词-v1.5.2-便携版.zip |
"""


def main() -> int:
    for url in (
        "https://gitee.com/api/v5/markdown",
        "https://gitee.com/api/v5/markdown/render",
    ):
        try:
            response = requests.post(
                url, json={"text": SAMPLE}, timeout=(6, 20), headers=HEADERS
            )
        except Exception as exc:  # noqa: BLE001
            print(f"{url} -> 请求失败 {type(exc).__name__}")
            continue
        print(f"{url} -> HTTP {response.status_code}")
        body = response.text[:600]
        print("   返回:", body.replace("\n", " ")[:400])
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
