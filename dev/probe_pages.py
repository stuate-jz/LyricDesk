r"""探一下 Gitee Pages 这个服务现在还在不在。"""

from __future__ import annotations

import re

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}


def main() -> int:
    checks = [
        "https://pursue-studies.gitee.io/",
        "https://gitee.gitee.io/",
        "https://help.gitee.com/",
    ]
    for url in checks:
        try:
            response = requests.get(url, timeout=(6, 20), headers=HEADERS)
        except Exception as exc:  # noqa: BLE001
            print(f"{url}\n    打不开：{type(exc).__name__}")
            continue
        body = re.sub(r"\s+", " ", response.text)
        print(f"{url}\n    HTTP {response.status_code}  长度 {len(response.text)}")
        print("    正文片段:", body[:160])

        hits = re.findall(r".{0,20}Pages.{0,50}", response.text)
        hits = list(dict.fromkeys(hits))[:6]
        if hits:
            print("    提到 Pages：")
            for item in hits:
                print("      -", re.sub(r"\s+", " ", item)[:100])

        links = sorted(
            set(re.findall(r'href="([^"]*pages[^"]*)"', response.text, re.I))
        )[:10]
        if links:
            print("    Pages 链接:", links)
        print()

    print("=== help.gitee.com 里有没有 Gitee Pages 的文档 ===")
    try:
        sitemap = requests.get(
            "https://help.gitee.com/sitemap.xml", timeout=(6, 25), headers=HEADERS
        )
        print("sitemap:", sitemap.status_code, len(sitemap.text))
        urls = re.findall(r"<loc>(.*?)</loc>", sitemap.text)
        print("文档总数:", len(urls))
        hits = [u for u in urls if "page" in u.lower()]
        for item in hits[:20]:
            print("   -", item)
        if not hits:
            print("   没有找到 Pages 相关文档（可能已下线）")
    except Exception as exc:  # noqa: BLE001
        print("sitemap 失败:", type(exc).__name__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
