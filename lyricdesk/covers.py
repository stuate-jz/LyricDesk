"""专辑封面下载与缓存。"""

from __future__ import annotations

import threading

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


def _cache_path(albummid: str):
    safe = "".join(ch for ch in albummid if ch.isalnum() or ch in "-_")
    return cover_dir() / f"{safe}.jpg"


def load_cover_bytes(albummid: str) -> bytes | None:
    if not albummid:
        return None
    path = _cache_path(albummid)
    if path.exists():
        try:
            data = path.read_bytes()
            if len(data) > 2048:
                return data
        except OSError:
            pass
    try:
        response = requests.get(cover_url(albummid), headers=HEADERS, timeout=8.0)
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
