"""歌词字体：内置字体 + 在线下载的免费字体。

内置的是「得意黑」（1.9 MB，SIL OFL 1.1），随程序一起分发。
霞鹜文楷 / 霞鹜新晰黑体积较大（24 MB / 7 MB），做成菜单里按需下载，
下载后放在 %APPDATA%\\LyricDesk\\fonts，之后每次启动自动加载。
"""

from __future__ import annotations

import sys
import threading
import zipfile
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

import requests
from PySide6.QtGui import QFontDatabase

from .config import app_dir

# 只保留「有辨识度」的系统字体（常见但没特点的黑体/雅黑之类不列出来，
# 想用它们可以走菜单最后的「从系统字体中选择…」）
RECOMMENDED: tuple[tuple[str, str], ...] = (
    ("华文行楷", "STXingkai"),
    ("华文琥珀", "STHupo"),
    ("华文彩云", "STCaiyun"),
    ("方正舒体", "FZShuTi"),
)


@dataclass(frozen=True)
class OnlineFont:
    key: str
    label: str
    family: str
    filename: str
    url: str
    size_mb: float
    license: str
    author: str
    inner: str = ""      # 若下载的是压缩包，这里写明包内字体路径


# 现在免费字体全部随程序内置，在线下载列表暂时为空。
# 以后想恢复「按需下载」，往这个元组里加条目、菜单会自动出现下载项。
ONLINE_FONTS: tuple[OnlineFont, ...] = ()

# 随程序分发的免费字体（SIL OFL 1.1，可自由分发）
BUNDLED_FONTS: tuple[tuple[str, str, str], ...] = (
    ("SmileySans-Oblique.otf", "得意黑（内置）", "Smiley Sans"),
    ("LXGWMarkerGothic-Regular.ttf", "霞鹜漫黑（内置）", "LXGW Marker Gothic"),
)


def bundled_dir() -> Path:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "assets" / "fonts"
    return Path(__file__).resolve().parent.parent / "assets" / "fonts"


def user_font_dir() -> Path:
    path = app_dir() / "fonts"
    path.mkdir(parents=True, exist_ok=True)
    return path


# 能直接导入的字体文件后缀
FONT_SUFFIXES = (".ttf", ".otf", ".ttc", ".otc")


def _register(path: Path) -> list[str]:
    if not path.exists():
        return []
    font_id = QFontDatabase.addApplicationFont(str(path))
    if font_id < 0:
        return []
    return list(QFontDatabase.applicationFontFamilies(font_id))


# 同一个文件不要重复加载（Qt 每次 addApplicationFont 都会占一份内存）
_FONT_FAMILIES: dict[str, list[str]] = {}


def _register_file(path: Path) -> list[str]:
    key = str(path)
    if key in _FONT_FAMILIES:
        return _FONT_FAMILIES[key]
    families = _register(path)
    _FONT_FAMILIES[key] = families
    return families


def user_font_files() -> list[Path]:
    """用户字体目录里所有字体文件（含自己导入的）。"""
    try:
        items = sorted(user_font_dir().iterdir())
    except OSError:
        return []
    return [item for item in items if item.suffix.lower() in FONT_SUFFIXES]


def imported_fonts() -> list[tuple[str, str]]:
    """用户自己导入的字体，返回 (字体族名, 文件名)。

    一个字体文件里可能同时带英文名、中文名、样式的别名，
    菜单里只列一条（取 Qt 给的主名），不然会重复好几行。
    """
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for path in user_font_files():
        families = _register_file(path)
        if not families:
            continue
        family = families[0]
        if family in seen:
            continue
        seen.add(family)
        result.append((family, path.name))
    return result


def import_font_file(source: Path) -> tuple[bool, str]:
    """把字体文件复制到用户字体目录并加载。

    返回 (成功?, 字体族名 或 错误说明)。
    """
    source = Path(source)
    if source.suffix.lower() not in FONT_SUFFIXES:
        return False, f"{source.name}：不是字体文件（支持 ttf / otf / ttc）"
    if not source.exists():
        return False, f"{source.name}：文件不存在"

    target = user_font_dir() / source.name
    try:
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
    except OSError as exc:
        return False, f"{source.name}：复制失败（{type(exc).__name__}）"

    _FONT_FAMILIES.pop(str(target), None)
    families = _register_file(target)
    if not families:
        return False, f"{source.name}：加载失败，可能不是有效的字体文件"
    return True, families[0]


def register_all() -> list[str]:
    """加载内置字体、用户下载的字体、用户自己导入的字体。"""
    loaded: list[str] = []
    for filename, _label, _family in BUNDLED_FONTS:
        loaded += _register_file(bundled_dir() / filename)
    for item in ONLINE_FONTS:
        loaded += _register_file(user_font_dir() / item.filename)
    for path in user_font_files():
        loaded += _register_file(path)
    return loaded


def downloaded(item: OnlineFont) -> bool:
    path = user_font_dir() / item.filename
    try:
        return path.exists() and path.stat().st_size > 100_000
    except OSError:
        return False


_FAMILY_CACHE: dict[str, str] = {}

# 本机常见的代理端口：Clash / v2ray / sing-box 之类默认开在这儿。
# 有些代理软件只开本地端口、不开系统代理，这时直连会失败，需要显式指过去。
_LOCAL_PROXIES = (
    "http://127.0.0.1:7890",
    "http://127.0.0.1:7897",
    "http://127.0.0.1:7891",
    "http://127.0.0.1:10809",
    "http://127.0.0.1:10808",
    "http://127.0.0.1:1080",
    "http://127.0.0.1:20171",
    "http://127.0.0.1:8080",
)


def _proxy_candidates() -> list[str | None]:
    """先按系统设置走，再直连，最后挨个试本机代理端口。"""
    candidates: list[str | None] = [None]
    for key in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
        value = os.environ.get(key)
        if value:
            candidates.insert(0, value)
            break
    candidates.extend(_LOCAL_PROXIES)
    seen: list[str | None] = []
    for item in candidates:
        if item not in seen:
            seen.append(item)
    return seen


# 更新检查（lyricdesk.update）也要走同一套代理探测
proxy_candidates = _proxy_candidates


def family_for(item: OnlineFont) -> str | None:
    """已下载的字体在系统里的实际族名（没下载就返回 None）。"""
    cached = _FAMILY_CACHE.get(item.filename)
    if cached:
        return cached
    path = user_font_dir() / item.filename
    if not path.exists():
        return None
    font_id = QFontDatabase.addApplicationFont(str(path))
    if font_id < 0:
        return None
    families = list(QFontDatabase.applicationFontFamilies(font_id))
    if not families:
        return None
    resolved = item.family if item.family in families else families[0]
    _FAMILY_CACHE[item.filename] = resolved
    return resolved


def download(item: OnlineFont, on_done) -> None:
    """后台下载字体，完成后回调 on_done(ok, 文本)。"""
    target = user_font_dir() / item.filename

    def worker() -> None:
        try:
            tmp = target.with_suffix(target.suffix + ".part")
            error = ""
            for proxy in _proxy_candidates():
                try:
                    session = requests.Session()
                    if proxy:
                        session.proxies = {"http": proxy, "https": proxy}
                    response = session.get(item.url, timeout=(8, 180), stream=True)
                    response.raise_for_status()
                    with tmp.open("wb") as handle:
                        for chunk in response.iter_content(chunk_size=262144):
                            if chunk:
                                handle.write(chunk)
                    error = ""
                    break
                except Exception as exc:  # noqa: BLE001
                    error = type(exc).__name__
                    continue
            if error:
                raise RuntimeError(error)
            if tmp.stat().st_size < 100_000:
                tmp.unlink(missing_ok=True)
                on_done(False, f"{item.label} 下载不完整")
                return
            if item.inner:
                # 下载的是压缩包，把里面的字体取出来
                with zipfile.ZipFile(tmp) as archive:
                    names = [
                        n for n in archive.namelist()
                        if n.lower().endswith((".ttf", ".otf"))
                    ]
                    member = item.inner if item.inner in archive.namelist() else (
                        names[0] if names else ""
                    )
                    if not member:
                        tmp.unlink(missing_ok=True)
                        on_done(False, f"{item.label} 压缩包里没有字体文件")
                        return
                    with archive.open(member) as src, target.open("wb") as dst:
                        dst.write(src.read())
                tmp.unlink(missing_ok=True)
            else:
                tmp.replace(target)
        except Exception as exc:  # noqa: BLE001
            on_done(False, f"{item.label} 下载失败：{type(exc).__name__}")
            return
        families = _register(target)
        if families:
            _FAMILY_CACHE[item.filename] = (
                item.family if item.family in families else families[0]
            )
            on_done(True, f"{item.label} 下载完成，已可选用")
        else:
            on_done(False, f"{item.label} 下载了但加载失败")

    threading.Thread(target=worker, name="font-download", daemon=True).start()
