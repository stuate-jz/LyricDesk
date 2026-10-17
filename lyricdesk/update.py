"""检查更新。

更新源支持四种写法（右键菜单 → 检查更新… 里可以随时改）：

    1. owner/repo               GitHub 仓库的 Releases（方便，但国内常要代理）
    2. gitee:owner/repo         码云 Gitee 仓库的 Releases（国内直连可用）
    3. https://…/update.json    任意一个能访问到的 JSON 文件
    4. D:\\path\\update.json     本地文件（内网 / 离线分发用）

JSON 里字段名写得宽松一点也能认，最小只要一个版本号：

    {"version": "1.6.0", "notes": "更新了什么", "url": "下载页地址"}

兼容 tag_name / body / html_url 这些 GitHub、Gitee 的原生字段名，
所以直接把 Releases 的接口地址填进来也能用。
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from .fonts import proxy_candidates

# 默认更新源：用户没自己配过时就用它，这样拿到程序就能自动检查更新。
DEFAULT_SOURCE = "gitee:pursue-studies/LyricDesk"

# 项目自己的发布页 / 主页（更新源认不出来时用它兜底）
# 主页是 GitHub Pages 上的发布页站点；发布页（releases）仍旧在 Gitee，自动更新不受影响。
DEFAULT_RELEASES_URL = "https://gitee.com/pursue-studies/LyricDesk/releases"
DEFAULT_HOMEPAGE_URL = "https://stuate-jz.github.io/LyricDesk/"

# GitHub 在国内经常连不上，直连失败后依次试这些镜像。
# ⚠️ 镜像会失效：加之前请先实测一次（用任意公开仓库打一下
#    https://<镜像>/repos/<owner>/<repo>/releases/latest，看能不能拿到 JSON）。
# 2026-10 实测：api.kkgithub.com 连接直接失败、ghproxy.net 对 API 返回 403，
# 所以现在列表为空 —— 也就是「只走 GitHub 直连」。
# 程序默认更新源本来就是 Gitee，这里空着不影响正常使用，也不会报错。
_GITHUB_MIRRORS: tuple[str, ...] = ()


@dataclass
class UpdateInfo:
    """一次检查的结果。ok=False 时看 error。"""

    ok: bool
    latest: str = ""
    notes: str = ""
    url: str = ""
    source: str = ""
    error: str = ""
    # 安装程序 / 免安装包的直链（有的话）。一键更新用的是 installer。
    installer: str = ""
    portable: str = ""


# ----------------------------------------------------------------------
# 版本号
# ----------------------------------------------------------------------


def parse_version(text: str) -> tuple[int, ...]:
    """把 'v1.6.0-beta' 这类字符串抠成 (1, 6, 0)，方便比大小。"""
    numbers = re.findall(r"\d+", str(text or ""))
    if not numbers:
        return (0,)
    return tuple(int(item) for item in numbers[:4])


def is_newer(latest: str, current: str) -> bool:
    left = parse_version(latest)
    right = parse_version(current)
    width = max(len(left), len(right))
    left += (0,) * (width - len(left))
    right += (0,) * (width - len(right))
    return left > right


# ----------------------------------------------------------------------
# 更新源
# ----------------------------------------------------------------------


def bundled_source() -> str:
    """程序目录里放一个 update.json 就能当更新源（发给朋友时很好用）。"""
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "update.json")
    else:
        candidates.append(Path(__file__).resolve().parent.parent / "update.json")
    for path in candidates:
        if path.exists():
            return str(path)
    return ""


def _looks_like_repo(source: str) -> bool:
    return bool(re.fullmatch(r"[\w.\-]+/[\w.\-]+", source))


def describe_source(source: str) -> str:
    text = (source or "").strip()
    if not text:
        return "未配置"
    if text.lower().startswith(("http://", "https://")):
        return text
    if text.lower().startswith("gitee:"):
        return f"Gitee 仓库 {text[6:]}"
    if _looks_like_repo(text):
        return f"GitHub 仓库 {text}"
    return f"本地文件 {text}"


def releases_url(source: str = "") -> str:
    """把更新源换算成「浏览器能打开的发布页地址」。

    · gitee:owner/repo   → https://gitee.com/owner/repo/releases
    · owner/repo         → https://github.com/owner/repo/releases
    · http(s)://...      → 原样返回（用户直接填了发布页/更新 json 地址）
    · 其它 / 空 / 本地文件 → 项目自己的 Gitee 发布页

    `source` 由调用方传进来（窗口那边已经处理过
    「设置里填的 → 程序目录 update.json → 内置默认」的优先级），
    这里只做换算，不重新实现优先级、也不联网。
    """
    text = (source or "").strip()
    low = text.lower()
    if low.startswith(("http://", "https://")):
        return text
    if low.startswith("gitee:"):
        repo = text[6:].strip().strip("/")
        if repo:
            return f"https://gitee.com/{repo}/releases"
    elif _looks_like_repo(text):
        return f"https://github.com/{text}/releases"
    return DEFAULT_RELEASES_URL


def homepage_url(source: str = "") -> str:
    """项目主页：认得出更新源就按平台换算（发布页去掉结尾的 /releases）。

    认不出来（空、本地路径……）或者就是内置的自家源时，给 DEFAULT_HOMEPAGE_URL ——
    也就是 GitHub Pages 上的发布页站点：它比裸仓库页更像「发布页」，用户点开就能看更新动态。
    """
    text = (source or "").strip()
    if not text or text.lower() == DEFAULT_SOURCE.lower():
        return DEFAULT_HOMEPAGE_URL
    url = releases_url(text)
    trimmed = re.sub(r"/releases/?$", "", url)
    return trimmed or DEFAULT_HOMEPAGE_URL


def _load_local(path_text: str) -> dict:
    """本地文件支持 file:// 和普通路径。"""
    text = path_text
    if text.lower().startswith("file://"):
        text = text[7:]
    raw = Path(text).read_text(encoding="utf-8")
    return json.loads(raw)


def _candidate_urls(source: str) -> list[str]:
    """把更新源展开成一串实际要请求的地址，按顺序试。"""
    text = (source or "").strip()
    if not text:
        return []
    if text.lower().startswith("gitee:"):
        repo = text[6:].strip().strip("/")
        return [f"https://gitee.com/api/v5/repos/{repo}/releases/latest"]
    if _looks_like_repo(text):
        repo = text.strip("/")
        # 直连优先，后面才轮到镜像；_GITHUB_MIRRORS 为空时这里就是「只有直连」，不会出错
        urls = [f"https://api.github.com/repos/{repo}/releases/latest"]
        urls += [mirror.format(repo=repo) for mirror in _GITHUB_MIRRORS]
        return urls
    return [text]


def _fetch(url: str, proxy: str | None, timeout: float) -> dict:
    if not url.lower().startswith(("http://", "https://")):
        return _load_local(url)
    session = requests.Session()
    if proxy:
        session.proxies = {"http": proxy, "https": proxy}
    session.headers.update(
        {
            "User-Agent": "LyricDesk-UpdateCheck",
            "Accept": "application/vnd.github+json, application/json",
        }
    )
    response = session.get(url, timeout=(timeout, timeout * 2))
    response.raise_for_status()
    return response.json()


def _asset_url(payload: dict) -> str:
    """GitHub / Gitee 的 Releases 会把附件放在 assets 里，挑一个像安装包的。

    自动生成的源码包（archive/refs/tags 那种）跳过，优先 zip / exe / 7z。
    """
    assets = payload.get("assets")
    if not isinstance(assets, list):
        return ""
    fallback = ""
    for item in assets:
        if not isinstance(item, dict):
            continue
        url = ""
        for key in ("browser_download_url", "download_url", "url"):
            value = item.get(key)
            if isinstance(value, str) and value.strip().lower().startswith("http"):
                url = value.strip()
                break
        if not url:
            continue
        low = url.lower()
        name = str(item.get("name") or "").lower()
        if "refs/tags" in low or "/archive/" in low:
            continue
        if name.endswith((".zip", ".exe", ".7z", ".msi")):
            return url
        fallback = fallback or url
    return fallback


def pick_assets(payload: dict) -> tuple[str, str]:
    """从返回内容里挑出 (安装程序直链, 免安装包直链)。

    优先认顶层字段（自定义 JSON 可以写 installer_url / portable_url），
    没有再翻 GitHub / Gitee 的 assets 列表。
    Gitee 自动生成的源码包（archive/refs/tags）一律忽略。
    """
    if not isinstance(payload, dict):
        return "", ""
    flat = {str(key).lower(): value for key, value in payload.items()}

    def http(value) -> str:
        if isinstance(value, str) and value.strip().lower().startswith("http"):
            return value.strip()
        return ""

    installer = ""
    for key in ("installer_url", "installer", "setup_url", "setup"):
        installer = http(flat.get(key))
        if installer:
            break
    portable = ""
    for key in ("portable_url", "portable", "zip_url"):
        portable = http(flat.get(key))
        if portable:
            break

    assets = payload.get("assets")
    if isinstance(assets, list):
        for item in assets:
            if not isinstance(item, dict):
                continue
            url = ""
            for key in ("browser_download_url", "download_url", "url"):
                url = http(item.get(key))
                if url:
                    break
            if not url:
                continue
            low = url.lower()
            if "refs/tags" in low or "/archive/" in low:
                continue
            name = str(item.get("name") or "").lower()
            if not installer and name.endswith((".exe", ".msi")):
                installer = url
            elif not portable and name.endswith((".zip", ".7z")):
                portable = url

    return installer, portable


def _extract(payload) -> tuple[str, str, str]:
    """从各种长得不太一样的 JSON 里取出 (版本号, 更新说明, 下载页)。"""
    if not isinstance(payload, dict):
        return "", "", ""
    flat = {str(key).lower(): value for key, value in payload.items()}

    version = ""
    for key in ("version", "latest", "latest_version", "tag_name", "tag", "name"):
        value = flat.get(key)
        if isinstance(value, str) and value.strip():
            version = value.strip()
            break

    notes = ""
    for key in ("notes", "changelog", "body", "message", "detail", "description"):
        value = flat.get(key)
        if isinstance(value, str) and value.strip():
            notes = value.strip()
            break

    url = ""
    # 优先给「直接能下载的地址」，没有再退到发布页
    for key in ("html_url", "download_url", "download", "url", "page_url", "page", "link"):
        value = flat.get(key)
        if isinstance(value, str) and value.strip().lower().startswith("http"):
            url = value.strip()
            break
    if not url:
        url = _asset_url(flat)

    return version, notes, url


def releases_page(source: str) -> str:
    """更新源是仓库时，兜底给出一个「Releases 页面」地址。"""
    text = (source or "").strip()
    if text.lower().startswith("gitee:"):
        repo = text[6:].strip().strip("/")
        return f"https://gitee.com/{repo}/releases" if repo else ""
    if _looks_like_repo(text):
        return f"https://github.com/{text.strip('/')}/releases"
    return ""


def check(source: str, on_done, timeout: float = 8.0) -> None:
    """后台检查更新，完成后在主线程回调 on_done(UpdateInfo)。"""
    source = (source or "").strip()

    def worker() -> None:
        urls = _candidate_urls(source)
        if not urls:
            on_done(UpdateInfo(False, source=source, error="还没设置更新源"))
            return

        error = ""
        for url in urls:
            for proxy in proxy_candidates():
                try:
                    payload = _fetch(url, proxy, timeout)
                except Exception as exc:  # noqa: BLE001
                    error = type(exc).__name__
                    continue
                version, notes, link = _extract(payload)
                if not version:
                    error = "返回内容里没有版本号"
                    continue
                installer, portable = pick_assets(payload)
                on_done(
                    UpdateInfo(
                        True,
                        latest=version,
                        notes=notes,
                        url=link or installer or portable or releases_page(source),
                        source=source,
                        installer=installer,
                        portable=portable,
                    )
                )
                return

        on_done(UpdateInfo(False, source=source, error=error or "连不上更新源"))

    threading.Thread(target=worker, name="update-check", daemon=True).start()


# ----------------------------------------------------------------------
# 下载更新包
# ----------------------------------------------------------------------


# 自动安装失败时留下的标记（写安装包文件名），下次启动用它提示用户手动装
FAILED_MARKER = "lyricdesk-update-failed.txt"


class _UpdateCancelled(Exception):
    """用户在进度条上点了「取消」。"""


def _check_installer(path: Path, downloaded: int, total: int) -> str:
    """下完先验一下，返回问题描述（空字符串 = 没问题）。

    网络被代理/杀软插一脚时常见的是：下到一页 HTML、或者半截文件。
    这种直接交给安装程序只会静默失败，所以这里先挡掉。
    """
    if total and downloaded < total:
        return f"下载不完整：只拿到 {downloaded / 1048576:.1f} / {total / 1048576:.1f} MB"
    if downloaded < 1_000_000:
        return f"下载到的文件太小（{downloaded / 1024:.0f} KB），不像安装程序"
    try:
        with path.open("rb") as handle:
            head = handle.read(2)
    except OSError:
        return "下载到的文件读不出来"
    if head != b"MZ":
        return "下载到的不是安装程序（可能被网络或代理拦截了）"
    return ""


def failed_installer() -> Path | None:
    """上次自动安装失败时保留下来的安装包；读完就把标记删掉。"""
    marker = Path(tempfile.gettempdir()) / FAILED_MARKER
    try:
        name = marker.read_text(encoding="mbcs", errors="replace").strip()
    except OSError:
        return None
    marker.unlink(missing_ok=True)
    path = Path(tempfile.gettempdir()) / name if name else None
    return path if path is not None and path.exists() else None


def download(
    url: str,
    target: Path,
    on_done,
    timeout: float = 20.0,
    on_progress=None,
    should_stop=None,
) -> None:
    """后台下载更新包，完成后回调 on_done(ok: bool, 文本)。

    on_progress(已下载字节, 总字节或 0, 字节/秒) 大约每 0.3 秒调一次，界面拿它画进度条；
    should_stop() 返回 True 时中止下载（进度条上的「取消」）。

    和字体下载共用同一套代理探测（直连 → 系统代理 → 常见本地代理端口）。
    慢链路断流时，最后会再补一次直连重试。
    """
    target = Path(target)
    attempts = list(proxy_candidates())
    if attempts:
        attempts.append(None)  # 整轮都失败后，直连再试一次

    def worker() -> None:
        last_error = ""
        for proxy in attempts:
            if should_stop is not None and should_stop():
                target.unlink(missing_ok=True)
                on_done(False, "已取消")
                return
            try:
                session = requests.Session()
                if proxy:
                    session.proxies = {"http": proxy, "https": proxy}
                session.headers.update({"User-Agent": "LyricDesk-Updater"})
                # 读超时别给 300 秒：断流时要尽快发现并重试，而不是干等五分钟
                response = session.get(
                    url, timeout=(timeout, timeout * 3), stream=True, allow_redirects=True
                )
                response.raise_for_status()
                total = int(response.headers.get("Content-Length") or 0)
                downloaded = 0
                started = time.time()
                last_report = 0.0
                with target.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=262144):
                        if should_stop is not None and should_stop():
                            raise _UpdateCancelled
                        if not chunk:
                            continue
                        handle.write(chunk)
                        downloaded += len(chunk)
                        now = time.time()
                        if on_progress is not None and now - last_report >= 0.3:
                            last_report = now
                            on_progress(
                                downloaded, total, downloaded / max(now - started, 0.001)
                            )
                elapsed = max(time.time() - started, 0.001)
                if on_progress is not None:
                    on_progress(downloaded, total or downloaded, downloaded / elapsed)
                problem = _check_installer(target, downloaded, total)
                if problem:
                    target.unlink(missing_ok=True)
                    on_done(False, problem)
                    return
                on_done(True, str(target))
                return
            except _UpdateCancelled:
                target.unlink(missing_ok=True)
                on_done(False, "已取消")
                return
            except requests.exceptions.ReadTimeout:
                last_error = "下载超时（网络太慢或被中断）"
                continue
            except Exception as exc:  # noqa: BLE001
                last_error = type(exc).__name__
                continue
        # 半截文件没法用（Gitee 的 CDN 又不支持续传），别在 temp 里留垃圾
        target.unlink(missing_ok=True)
        on_done(False, f"下载失败：{last_error or '连不上'}")

    threading.Thread(target=worker, name="update-download", daemon=True).start()
