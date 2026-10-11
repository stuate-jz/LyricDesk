"""离线验证「检查更新」：版本比较 + 本地/远程 JSON 解析。"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lyricdesk.update import (  # noqa: E402
    _candidate_urls,
    _extract,
    check,
    describe_source,
    is_newer,
    parse_version,
    pick_assets,
    releases_page,
)


def test_versions() -> int:
    cases = [
        ("1.5.1", "1.5.1", False),
        ("v1.5.2", "1.5.1", True),
        ("1.6", "1.5.1", True),
        ("1.4.9", "1.5.0", False),
        ("1.5.1.1", "1.5.1", True),
        ("v2.0.0-beta.1", "1.9.9", True),
    ]
    bad = 0
    for latest, current, want in cases:
        got = is_newer(latest, current)
        ok = got == want
        bad += 0 if ok else 1
        print(f"  {'OK  ' if ok else 'FAIL'} {latest:>16} vs {current:<8} -> {got}")
    print("  parse_version('v1.6.0-beta') =", parse_version("v1.6.0-beta"))
    return bad


def test_extract() -> int:
    samples = [
        ({"version": "1.6.0", "notes": "a", "url": "https://x/d"}, "1.6.0"),
        ({"tag_name": "v1.6.0", "body": "b", "html_url": "https://x/r"}, "v1.6.0"),
        ({"latest": "1.6.0", "changelog": "c"}, "1.6.0"),
    ]
    bad = 0
    for payload, want in samples:
        version, notes, url = _extract(payload)
        ok = version == want
        bad += 0 if ok else 1
        print(f"  {'OK  ' if ok else 'FAIL'} {version!r} notes={notes!r} url={url!r}")
    return bad


def test_sources() -> int:
    print("  describe_source('someone/LyricDesk') ->", describe_source("someone/LyricDesk"))
    print("  describe_source('gitee:a/b')         ->", describe_source("gitee:a/b"))
    print("  releases_page('gitee:a/b')           ->", releases_page("gitee:a/b"))
    print("  releases_page('a/b')                 ->", releases_page("a/b"))
    print("  candidate urls (github):")
    for url in _candidate_urls("someone/LyricDesk"):
        print("     ", url)
    print("  candidate urls (gitee):")
    for url in _candidate_urls("gitee:a/b"):
        print("     ", url)
    return 0


def test_gitee_payload() -> int:
    """Gitee 的 Releases 接口没有 html_url，下载地址在 assets 里。"""
    payload = {
        "tag_name": "v4.8.3",
        "name": "v4.8.3",
        "body": "更新日志：……",
        "assets": [
            {
                "name": "v4.8.3.zip",
                "browser_download_url": "https://gitee.com/x/y/archive/refs/tags/v4.8.3.zip",
            },
            {
                "name": "桌面歌词-v1.5.2-便携版.zip",
                "browser_download_url": "https://gitee.com/x/y/releases/download/v1.5.2/LyricDesk.zip",
            },
        ],
    }
    version, notes, url = _extract(payload)
    ok = version == "v4.8.3" and url.endswith("LyricDesk.zip")
    print(f"  {'OK  ' if ok else 'FAIL'} version={version!r} url={url!r}")

    installer, portable = pick_assets(payload)
    ok3 = installer == "" and portable.endswith("LyricDesk.zip")
    print(
        f"  {'OK  ' if ok3 else 'FAIL'} 没有 exe 时 installer={installer!r} "
        f"portable={portable!r}"
    )

    payload_no_asset = {"tag_name": "v1.5.2", "body": "x"}
    version, _, url = _extract(payload_no_asset)
    fallback = url or releases_page("gitee:x/y")
    ok2 = fallback == "https://gitee.com/x/y/releases"
    print(f"  {'OK  ' if ok2 else 'FAIL'} 无附件时兜底 -> {fallback!r}")
    return 0 if (ok and ok2 and ok3) else 1


def test_pick_assets() -> int:
    """有安装程序时要优先挑出 exe —— 一键更新靠它。"""
    payload = {
        "tag_name": "v1.6.0",
        "body": "说明",
        "assets": [
            {
                "name": "v1.6.0.zip",
                "browser_download_url": "https://gitee.com/a/b/archive/refs/tags/v1.6.0.zip",
            },
            {
                "name": "桌面歌词-v1.6.0-便携版.zip",
                "browser_download_url": "https://gitee.com/a/b/releases/download/v1.6.0/portable.zip",
            },
            {
                "name": "桌面歌词-安装程序-v1.6.0.exe",
                "browser_download_url": "https://gitee.com/a/b/releases/download/v1.6.0/setup.exe",
            },
        ],
    }
    installer, portable = pick_assets(payload)
    ok = installer.endswith("setup.exe") and portable.endswith("portable.zip")
    print(f"  {'OK  ' if ok else 'FAIL'} installer={installer!r}")
    print(f"  {'OK  ' if ok else 'FAIL'} portable ={portable!r}")

    custom = {
        "version": "1.6.0",
        "installer_url": "https://example.com/setup.exe",
    }
    installer2, portable2 = pick_assets(custom)
    ok2 = installer2 == "https://example.com/setup.exe"
    print(f"  {'OK  ' if ok2 else 'FAIL'} 自定义 JSON 的 installer_url -> {installer2!r}")
    return 0 if (ok and ok2) else 1


def test_local_feed() -> int:
    root = Path(tempfile.mkdtemp(prefix="lyricdesk-update-"))
    newest = root / "new.json"
    newest.write_text(
        json.dumps({"version": "9.9.9", "notes": "离线测试用", "url": "https://example.com/dl"}),
        encoding="utf-8",
    )
    same = root / "same.json"
    same.write_text(json.dumps({"version": "1.5.1"}), encoding="utf-8")

    from lyricdesk import __version__

    for path, expect_new in ((newest, True), (same, False)):
        done = threading.Event()
        holder: list = []
        check(str(path), lambda info: (holder.append(info), done.set()), timeout=3.0)
        done.wait(10)
        info = holder[0] if holder else None
        if info is None:
            print("  FAIL 回调没有回来")
            return 1
        got_new = info.ok and is_newer(info.latest, __version__)
        ok = info.ok and got_new == expect_new
        print(
            f"  {'OK  ' if ok else 'FAIL'} {path.name}: ok={info.ok} "
            f"latest={info.latest!r} url={info.url!r} error={info.error!r}"
        )
        if not ok:
            return 1
    return 0


def main() -> int:
    print("版本比较：")
    bad = test_versions()
    print("\nJSON 解析：")
    bad += test_extract()
    print("\n更新源解析：")
    bad += test_sources()
    print("\nGitee Releases 返回格式：")
    bad += test_gitee_payload()
    print("\n挑安装包（一键更新用）：")
    bad += test_pick_assets()
    print("\n本地更新源（离线跑通）：")
    bad += test_local_feed()
    print("\n" + ("有失败项" if bad else "全部通过"))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
