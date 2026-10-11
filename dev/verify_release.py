r"""核对 Gitee 仓库上到底传上去了什么。

    python dev\verify_release.py pursue-studies/LyricDesk
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

HEADERS = {"User-Agent": "LyricDesk-verify"}


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    repo = sys.argv[1].strip().strip("/")
    if repo.lower().startswith("gitee:"):
        repo = repo[6:]

    print(f"=== 仓库文件 {repo} ===")
    try:
        response = requests.get(
            f"https://gitee.com/api/v5/repos/{repo}/contents/",
            timeout=(6, 15),
            headers=HEADERS,
        )
        print("  HTTP", response.status_code)
        if response.status_code == 200:
            for item in response.json():
                print(
                    f"    {item['type']:4s} {item['name']:22s} {item.get('size', '')}"
                )
        else:
            print("   ", response.text[:120])
    except Exception as exc:  # noqa: BLE001
        print("  FAIL", type(exc).__name__)

    print("\n=== 仓库首页的 README 是不是最新版 ===")
    try:
        response = requests.get(
            f"https://gitee.com/{repo}/raw/master/README.md",
            timeout=(6, 15),
            headers=HEADERS,
            allow_redirects=True,
        )
        print("  HTTP", response.status_code, "长度", len(response.text))
        print("  开头:", response.text[:60].replace("\n", " | "))
        print("  居中头图:", 'align="center"' in response.text)
        print("  还有占位符:", "你的用户名" in response.text)
    except Exception as exc:  # noqa: BLE001
        print("  FAIL", type(exc).__name__)

    print(f"\n=== 最新发行版 ===")
    try:
        response = requests.get(
            f"https://gitee.com/api/v5/repos/{repo}/releases/latest",
            timeout=(6, 15),
            headers=HEADERS,
        )
        print("  HTTP", response.status_code)
        if response.status_code == 200:
            data = response.json()
            print("  tag_name :", data.get("tag_name"))
            print("  name     :", data.get("name"))
            body = (data.get("body") or "").replace("\n", " ")
            print("  body     :", body[:70])
            assets = data.get("assets") or []
            print("  附件数量 :", len(assets))
            for item in assets:
                print("   -", item.get("name"))
                print("     ", item.get("browser_download_url"))
        else:
            print("   ", response.text[:120])
    except Exception as exc:  # noqa: BLE001
        print("  FAIL", type(exc).__name__)

    print("\n=== 所有发行版 ===")
    try:
        response = requests.get(
            f"https://gitee.com/api/v5/repos/{repo}/releases",
            timeout=(6, 15),
            headers=HEADERS,
        )
        print("  HTTP", response.status_code)
        if response.status_code == 200:
            for item in response.json():
                names = [a.get("name") for a in (item.get("assets") or [])]
                print(f"   {item.get('tag_name'):8s} {item.get('name')}")
                for name in names:
                    print("        -", name)
    except Exception as exc:  # noqa: BLE001
        print("  FAIL", type(exc).__name__)

    print("\n=== 直接用程序里的检查更新跑一遍 ===")
    from lyricdesk.update import check, describe_source, is_newer
    from lyricdesk import __version__

    import threading

    done = threading.Event()
    box: list = []
    check(f"gitee:{repo}", lambda info: (box.append(info), done.set()))
    if not done.wait(25) or not box:
        print("  超时，没拿到结果")
        return 1
    info = box[0]
    print("  来源      :", describe_source(info.source))
    print("  成功      :", info.ok, info.error)
    print("  最新版本  :", info.latest)
    print("  当前版本  :", __version__)
    print("  有更新吗  :", is_newer(info.latest, __version__))
    print("  下载地址  :", info.url or "（空）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
