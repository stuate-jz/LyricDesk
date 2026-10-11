r"""把仓库里的 README.md 抓下来看一眼（raw 被拦截时换别的接口）。"""

from __future__ import annotations

import base64
import sys

import requests

REPO = sys.argv[1] if len(sys.argv) > 1 else "pursue-studies/LyricDesk"
BROWSER = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
}


def try_contents_api() -> str | None:
    url = f"https://gitee.com/api/v5/repos/{REPO}/contents/README.md"
    response = requests.get(url, timeout=(6, 20), headers=BROWSER)
    print(f"contents API -> {response.status_code}")
    if response.status_code != 200:
        print("   ", response.text[:100])
        return None
    payload = response.json()
    content = base64.b64decode(payload.get("content") or "").decode("utf-8", "replace")
    return content


def try_raw() -> str | None:
    url = f"https://gitee.com/{REPO}/raw/master/README.md"
    headers = dict(BROWSER)
    headers["Referer"] = f"https://gitee.com/{REPO}/blob/master/README.md"
    response = requests.get(url, timeout=(6, 20), headers=headers, allow_redirects=True)
    print(f"raw -> {response.status_code}")
    if response.status_code != 200:
        print("   ", response.text[:100])
        return None
    return response.text


def main() -> int:
    content = try_contents_api()
    if content is None:
        print("改用 raw 再试一次")
        content = try_raw()
    if content is None:
        print("两个接口都没拿到内容")
        return 1
    print("长度:", len(content))
    print("开头:", content[:70].replace("\n", " | "))
    print('居中头图 align="center":', 'align="center"' in content)
    print("还有占位符:", "你的用户名" in content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
