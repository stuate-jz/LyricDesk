"""从网易云客户端 CDP 流量中收集当前登录态才能拿到的 YRC。"""

from __future__ import annotations

import json
import re
import threading
import time
from urllib.parse import parse_qs, urlparse

from .lyricdoc import LyricDoc
from .netease_client import _find_page
from .sources.netease import parse_payload

TARGET_RECHECK_SECONDS = 8.0
EVENT_WAIT_SECONDS = 0.45
_ID_PATTERNS = (
    re.compile(r'["\']?id["\']?\s*[:=]\s*["\']?(\d{3,})', re.I),
    re.compile(r'["\']?songId["\']?\s*[:=]\s*["\']?(\d{3,})', re.I),
)


def _song_id_from(url: str, post_data: str) -> str:
    try:
        values = parse_qs(urlparse(url).query).get("id") or []
        if values and str(values[0]).isdigit():
            return str(values[0])
    except Exception:
        pass
    for pattern in _ID_PATTERNS:
        match = pattern.search(post_data or "")
        if match:
            return match.group(1)
    return ""


class NeteaseYrcCollector:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._docs: dict[str, LyricDoc] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ws = None
        self._next_id = 0
        self._connected = False

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._connected

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="netease-yrc",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._close()

    def get(self, song_id: str) -> LyricDoc | None:
        song_id = str(song_id or "").strip()
        if not song_id:
            return None
        with self._lock:
            doc = self._docs.get(song_id)
        if doc is None or not doc.real_word_lines:
            return None
        return doc

    def _store(self, payload, song_id: str) -> None:
        if not song_id:
            return
        try:
            doc = parse_payload(payload, song_id)
        except Exception:
            return
        if doc is None or not doc.real_word_lines:
            return
        with self._lock:
            self._docs[song_id] = doc
            # 长期播放时最多保留 40 首，避免后台进程无限占用。
            if len(self._docs) > 40:
                for key in list(self._docs)[:-40]:
                    self._docs.pop(key, None)

    def _run(self) -> None:
        backoff = 0.8
        while not self._stop.is_set():
            target = _find_page(0.5)
            if target is None:
                self._stop.wait(0.8)
                continue
            url = str(target.get("webSocketDebuggerUrl") or "")
            if not url:
                self._stop.wait(0.8)
                continue
            try:
                self._connect(url)
                backoff = 0.8
                next_target_check = time.monotonic() + TARGET_RECHECK_SECONDS
                requests_seen: dict[str, tuple[str, str]] = {}
                while not self._stop.is_set():
                    if time.monotonic() >= next_target_check:
                        next_target_check = (
                            time.monotonic() + TARGET_RECHECK_SECONDS
                        )
                        newer = _find_page(0.3)
                        newer_url = (
                            str(newer.get("webSocketDebuggerUrl") or "")
                            if newer is not None
                            else ""
                        )
                        if newer_url and newer_url != url:
                            break
                    message = self._recv_command(
                        None,
                        None,
                        timeout=EVENT_WAIT_SECONDS,
                    )
                    if message is None:
                        continue
                    method = str(message.get("method") or "")
                    params = message.get("params") or {}
                    if method == "Network.requestWillBeSent":
                        request = params.get("request") or {}
                        request_url = str(request.get("url") or "")
                        if "lyric" in request_url.lower():
                            requests_seen[str(params.get("requestId") or "")] = (
                                request_url,
                                str(request.get("postData") or ""),
                            )
                            if len(requests_seen) > 80:
                                for key in list(requests_seen)[:-80]:
                                    requests_seen.pop(key, None)
                        continue
                    if method != "Network.responseReceived":
                        continue
                    request_id = str(params.get("requestId") or "")
                    meta = requests_seen.pop(request_id, None)
                    response = params.get("response") or {}
                    response_url = str(response.get("url") or "")
                    if meta is None:
                        meta = (
                            response_url,
                            "",
                        )
                    if "lyric" not in meta[0].lower():
                        continue
                    song_id = _song_id_from(meta[0], meta[1])
                    if not song_id:
                        continue
                    body = self._call(
                        "Network.getResponseBody",
                        {"requestId": request_id},
                        timeout=1.5,
                    )
                    text = str(
                        (body or {}).get("result", {}).get("body") or ""
                    )
                    if not text:
                        continue
                    try:
                        payload = json.loads(text)
                    except Exception:
                        continue
                    self._store(payload, song_id)
            except Exception:
                pass
            finally:
                self._close()
                with self._lock:
                    self._connected = False
            if not self._stop.is_set():
                self._stop.wait(backoff)
                backoff = min(4.0, backoff * 1.5)

    def _connect(self, url: str) -> None:
        import websocket

        self._close()
        self._ws = websocket.create_connection(
            url,
            timeout=2.5,
            suppress_origin=True,
            enable_multithread=True,
        )
        message = self._call("Network.enable", {}, timeout=2.0)
        if message is None or message.get("error"):
            raise RuntimeError("CDP Network.enable failed")
        with self._lock:
            self._connected = True

    def _close(self) -> None:
        ws, self._ws = self._ws, None
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass

    def _send(self, method: str, params: dict | None = None) -> int:
        if self._ws is None:
            raise RuntimeError("CDP disconnected")
        self._next_id += 1
        command_id = self._next_id
        self._ws.send(
            json.dumps(
                {
                    "id": command_id,
                    "method": method,
                    "params": params or {},
                }
            )
        )
        return command_id

    def _recv_command(
        self,
        method: str | None = None,
        params: dict | None = None,
        timeout: float = 1.0,
    ):
        """发命令后读消息；无命令时只等待并返回一个 CDP 事件。"""
        command_id = self._send(method, params) if method else 0
        deadline = time.monotonic() + timeout
        while self._ws is not None and time.monotonic() < deadline:
            try:
                remaining = max(0.05, deadline - time.monotonic())
                self._ws.settimeout(remaining)
                raw = self._ws.recv()
            except Exception:
                return None
            if not raw:
                return None
            try:
                message = json.loads(raw)
            except Exception:
                continue
            if not isinstance(message, dict):
                continue
            if command_id and message.get("id") == command_id:
                return message
            if not command_id:
                return message
        return None

    def _call(
        self,
        method: str,
        params: dict | None = None,
        timeout: float = 1.0,
    ):
        return self._recv_command(method, params, timeout)


_COLLECTOR = NeteaseYrcCollector()


def start() -> None:
    _COLLECTOR.start()


def stop() -> None:
    _COLLECTOR.stop()


def get(song_id: str) -> LyricDoc | None:
    return _COLLECTOR.get(song_id)


def connected() -> bool:
    return _COLLECTOR.connected
