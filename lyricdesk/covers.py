"""专辑封面下载与缓存。"""

from __future__ import annotations

import hashlib
import threading
from urllib.parse import urlparse

import requests
from PySide6.QtCore import QObject, Signal

from .config import app_dir

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
HEADERS = {"User-Agent": UA, "Referer": "https://y.qq.com/"}


def cover_dir():
    path = app_dir() / "covers"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cover_url(albummid: str, size: int = 500) -> str:
    return f"https://y.qq.com/music/photo_new/T002R{size}x{size}M000{albummid}.jpg"


def _is_http(key: str) -> bool:
    return key.lower().startswith(("http://", "https://"))


def _cache_path(key: str):
    if _is_http(key):
        safe = hashlib.md5(key.encode("utf-8")).hexdigest()[:16]
    else:
        safe = "".join(ch for ch in key if ch.isalnum() or ch in "-_")
    return cover_dir() / f"{safe}.jpg"


def _headers_for(url: str) -> dict[str, str]:
    host = urlparse(url).hostname or ""
    referer = "https://www.bilibili.com/" if "hdslb.com" in host else "https://y.qq.com/"
    return {"User-Agent": UA, "Referer": referer}


def load_cover_bytes(key: str) -> bytes | None:
    if not key:
        return None
    path = _cache_path(key)
    if path.exists():
        try:
            data = path.read_bytes()
            if len(data) > 2048:
                return data
        except OSError:
            pass
    try:
        url = key if _is_http(key) else cover_url(key)
        response = requests.get(url, headers=_headers_for(url), timeout=8.0)
        if response.status_code == 200 and len(response.content) > 2048:
            try:
                path.write_bytes(response.content)
            except OSError:
                pass
            return response.content
    except Exception:
        pass
    return None


class CoverLoader(QObject):
    """后台线程下载封面，完成后通过信号把字节送回主线程。"""

    ready = Signal(str, bytes)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._token = 0
        self._lock = threading.Lock()

    def request(self, albummid: str) -> None:
        if not albummid:
            return
        with self._lock:
            self._token += 1
            token = self._token

        def worker() -> None:
            data = load_cover_bytes(albummid)
            if not data:
                return
            with self._lock:
                if token != self._token:
                    return
            self.ready.emit(albummid, data)

        threading.Thread(target=worker, name="cover-fetch", daemon=True).start()
