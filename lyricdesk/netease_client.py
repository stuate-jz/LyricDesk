r"""网易云音乐客户端桥（CEF / Chrome DevTools Protocol）。

网易云桌面版不注册 SMTC，因此普通媒体会话读不到它。这里只在该开关打开时
连接客户端在 9222 端口暴露的页面，从底栏读取歌名、歌手、播放状态、封面和
播放条进度。所有网络与 WebSocket 操作都在后台线程，连接失败时静默回退。
"""

from __future__ import annotations

import ctypes
import json
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from .config import app_dir
from .smtc import Snapshot, Track

DEBUG_PORT_MIN = 9222
DEBUG_PORT_MAX = 9232
DEBUG_PORT = DEBUG_PORT_MIN
_debug_port = DEBUG_PORT
DEBUG_URL = f"http://127.0.0.1:{_debug_port}/json/list"
TARGET_RECHECK_SECONDS = 8.0
POLL_INTERVAL_SECONDS = 0.3
STATS_INTERVAL_SECONDS = 60.0
MAX_READ_TIMEOUTS = 2


def configure(port: int | None) -> None:
    """切换本进程读取/启动网易云时使用的调试端口。"""
    global _debug_port, DEBUG_URL
    try:
        value = int(port or 0)
    except (TypeError, ValueError):
        value = 0
    if not DEBUG_PORT_MIN <= value <= DEBUG_PORT_MAX:
        value = DEBUG_PORT_MIN
    _debug_port = value
    DEBUG_URL = f"http://127.0.0.1:{value}/json/list"


def current_port() -> int:
    return _debug_port

# 全部集中在这里：网易云改版时通常只需要调整这几个选择器。
PLAYBAR_SELECTORS = (
    "footer",
    "#page_pc_mini_bar",
    ".default-bar-wrapper",
)
TITLE_SELECTORS = (
    "[data-testid='tid_minibar_title'] .main-title",
    ".songPlayInfo_s1140jsx .main-title",
    ".title-container .main-title",
)
ARTIST_SELECTORS = (
    ".songPlayInfo_s1140jsx .author",
    ".title-container .author",
    "footer .author",
)
PLAY_BUTTON_SELECTORS = (
    "[data-testid='tid_playbar_play_btn']",
    "#btn_pc_minibar_play",
)
PROGRESS_SELECTORS = (
    "[aria-label='播放进度调节']",
    ".StyledSliderContainer_smigcsb",
    ".slider-default",
)


def _json_tuple(values: tuple[str, ...]) -> str:
    return json.dumps(values, ensure_ascii=False)


READ_JS = f"""
(function () {{
  const playbars = {_json_tuple(PLAYBAR_SELECTORS)};
  const titleSelectors = {_json_tuple(TITLE_SELECTORS)};
  const artistSelectors = {_json_tuple(ARTIST_SELECTORS)};
  const playSelectors = {_json_tuple(PLAY_BUTTON_SELECTORS)};
  const progressSelectors = {_json_tuple(PROGRESS_SELECTORS)};

  function first(selectors, root) {{
    for (const selector of selectors) {{
      try {{
        const found = (root || document).querySelector(selector);
        if (found) return found;
      }} catch (e) {{}}
    }}
    return null;
  }}

  function text(node) {{
    if (!node) return '';
    return String(
      node.getAttribute('title') ||
      node.getAttribute('aria-label') ||
      node.textContent ||
      ''
    ).trim();
  }}

  const footer = first(playbars, document);
  const root = footer || document;
  const titleNode = first(titleSelectors, root);
  const artistNode = first(artistSelectors, root);
  let title = text(titleNode);
  let artist = text(artistNode);

  // 极少数主题把两行合成一个节点；只在这种情况下才按分隔符拆。
  if (!artist && title) {{
    const parts = title.split(/\\s+[-·]\\s+/);
    if (parts.length >= 2) {{
      title = parts.shift().trim();
      artist = parts.join(' - ').trim();
    }}
  }}

  const slider = first(progressSelectors, root);
  const range = slider && slider.querySelector('input[type="range"]');
  let position = NaN;
  let duration = NaN;
  if (range) {{
    const rawPosition = range.getAttribute('aria-valuetext') || range.value;
    position = Number.parseFloat(rawPosition);
    duration = Number.parseFloat(range.getAttribute('max'));
  }}
  if (slider) {{
    // 兼容旧版：播放条旁边直接显示 "mm:ss" 或 "mm:ss / mm:ss"。
    const candidates = [...slider.querySelectorAll('span, button, div')]
      .map(text)
      .filter(Boolean);
    const pair = candidates.find((value) =>
      /^\\d{{1,3}}:\\d{{2}}\\s*\\/\\s*\\d{{1,3}}:\\d{{2}}$/.test(value)
    );
    if (pair) {{
      const times = pair.split('/').map((value) => value.trim());
      if (!Number.isFinite(position)) position = parseClock(times[0]);
      if (!Number.isFinite(duration)) duration = parseClock(times[1]);
    }} else if (!Number.isFinite(position)) {{
      const singles = candidates.filter((value) =>
        /^\\d{{1,3}}:\\d{{2}}$/.test(value)
      );
      if (singles.length >= 2) {{
        position = parseClock(singles[0]);
        duration = parseClock(singles[1]);
      }}
    }}
  }}

  function parseClock(value) {{
    const match = /^(\\d{{1,3}}):(\\d{{2}})$/.exec(String(value || '').trim());
    return match ? Number(match[1]) * 60 + Number(match[2]) : NaN;
  }}

  const playButton = first(playSelectors, root);
  const icon = playButton && playButton.querySelector('[role="img"], .cmd-icon');
  const playHint = [
    icon && icon.className,
    icon && icon.getAttribute('aria-label'),
    icon && icon.getAttribute('title'),
    playButton && playButton.getAttribute('aria-label'),
    playButton && playButton.getAttribute('title')
  ].filter(Boolean).join(' ').toLowerCase();
  let playing = null;
  if (/pause|暂停/.test(playHint)) playing = true;
  else if (/play|播放/.test(playHint)) playing = false;

  const image = root.querySelector(
    'footer img, .miniVinylWrapper img, .vinylImgCls_v1vffxgf img'
  );
  let cover = image ? (image.currentSrc || image.src || '') : '';
  if (cover.startsWith('orpheus://cache/?')) {{
    cover = cover.slice('orpheus://cache/?'.length);
  }}
  if (cover.startsWith('//')) cover = 'https:' + cover;
  // 底栏 img 默认是 60×60 的缩略图（常小于 2 KB）。去掉缓存参数后
  // 主动请求 500×500；曲库封面加载器会按窗口尺寸再缩放。
  if (cover.indexOf('music.126.net') >= 0) {{
    cover = cover.split('?')[0] + '?param=500y500';
  }}

  return JSON.stringify({{
    title: title,
    artist: artist,
    position: Number.isFinite(position) ? position : null,
    duration: Number.isFinite(duration) ? duration : null,
    playing: playing,
    cover: cover,
    visible: document.visibilityState === 'visible'
  }});
}})()
"""

CONTROL_JS = {
    "toggle": """
      (() => {
        const button = document.querySelector(
          '[data-testid="tid_playbar_play_btn"], #btn_pc_minibar_play'
        );
        if (button) button.click();
        return !!button;
      })()
    """,
    "next": """
      (() => {
        const button = document.querySelector('[data-testid="tid_playbar_next_btn"]');
        if (button) button.click();
        return !!button;
      })()
    """,
    "prev": """
      (() => {
        const button = document.querySelector('[data-testid="tid_playbar_prev_btn"]');
        if (button) button.click();
        return !!button;
      })()
    """,
}


@dataclass
class NeteaseState:
    title: str = ""
    artist: str = ""
    position: float = 0.0
    duration: float = 0.0
    playing: bool = False
    position_known: bool = True
    cover_url: str = ""
    visible: bool = True
    stamp: float = 0.0

    def snapshot(self, position: float | None = None) -> Snapshot | None:
        if not self.title:
            return None
        position = self.position if position is None else float(position)
        if self.duration > 0:
            position = min(position, self.duration)
        track = Track(
            title=self.title,
            artist=self.artist,
            album="",
            duration=self.duration,
        )
        return Snapshot(
            track=track,
            position=max(0.0, position),
            is_playing=self.playing,
            status=4 if self.playing else 5,
            source="netease",
            can_next=self.position_known,
            can_prev=self.position_known,
            can_seek=self.position_known,
            position_known=self.position_known,
        )


def _num(value, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number == number else default


def parse_state(raw: str | None, previous_playing: bool = False) -> NeteaseState | None:
    """解析页面返回；JSON 不合法或没有歌名时返回 None。"""
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    title = str(data.get("title") or "").strip()
    if not title or title.lower() in ("undefined", "null", "about:blank"):
        return None
    artist = str(data.get("artist") or "").strip()
    raw_position = data.get("position")
    raw_duration = data.get("duration")
    position_known = raw_position is not None and _num(raw_position, -1.0) >= 0
    raw_playing = data.get("playing")
    playing = previous_playing if raw_playing is None else bool(raw_playing)
    return NeteaseState(
        title=title,
        artist=artist,
        position=max(0.0, _num(raw_position)),
        duration=max(0.0, _num(raw_duration)),
        playing=playing,
        position_known=position_known,
        cover_url=str(data.get("cover") or "").strip(),
        visible=bool(data.get("visible", True)),
        stamp=time.monotonic(),
    )


def parse_window_title(title: str, previous_playing: bool = False) -> NeteaseState | None:
    """窗口标题兜底：通常是「歌名 - 歌手」，但没有进度。"""
    title = (title or "").strip()
    if not title or title in ("网易云音乐", "NetEase Cloud Music"):
        return None
    if " - " in title:
        song, artist = title.rsplit(" - ", 1)
    else:
        song, artist = title, ""
    song = song.strip()
    if not song:
        return None
    return NeteaseState(
        title=song,
        artist=artist.strip(),
        playing=previous_playing,
        position_known=False,
        stamp=time.monotonic(),
    )


def _find_page(timeout: float = 0.4, port: int | None = None) -> dict | None:
    url = (
        f"http://127.0.0.1:{int(port)}/json/list"
        if port is not None
        else DEBUG_URL
    )
    try:
        response = requests.get(url, timeout=timeout)
        if response.status_code != 200:
            return None
        targets = response.json()
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(targets, list):
        return None
    fallback = None
    for item in targets:
        if not isinstance(item, dict) or item.get("type") != "page":
            continue
        url = str(item.get("url") or "")
        # 只认网易云 CEF 页面；别的 Electron 程序即使占了同一个端口也不能误判。
        if "orpheus" not in url.lower():
            continue
        if not item.get("webSocketDebuggerUrl"):
            continue
        if "orpheus://orpheus/pub/app.html" in url:
            return item
        if fallback is None:
            fallback = item
    return fallback


def available(timeout: float = 0.25, port: int | None = None) -> bool:
    return _find_page(timeout, port) is not None


def running_window_title() -> str:
    """用 Win32 找 cloudmusic.exe 的可见顶层窗口标题。"""
    if not hasattr(ctypes, "windll"):
        return ""
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
    except Exception:  # noqa: BLE001
        return ""

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    values: list[str] = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def callback(hwnd, _lparam):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            length = int(user32.GetWindowTextLengthW(hwnd))
            if length <= 0:
                return True
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            handle = kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value
            )
            if not handle:
                return True
            try:
                buffer = ctypes.create_unicode_buffer(2048)
                size = ctypes.c_ulong(len(buffer))
                if not kernel32.QueryFullProcessImageNameW(
                    handle, 0, buffer, ctypes.byref(size)
                ):
                    return True
                if Path(buffer.value).name.lower() != "cloudmusic.exe":
                    return True
            finally:
                kernel32.CloseHandle(handle)
            title_buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
            value = title_buffer.value.strip()
            if value:
                values.append(value)
        except Exception:  # noqa: BLE001
            pass
        return True

    try:
        user32.EnumWindows(callback_type(callback), 0)
    except Exception:  # noqa: BLE001
        return ""
    return max(values, key=len) if values else ""


class NeteaseBridge:
    """后台轮询网易云页面；CDP 不通时改用窗口标题。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: NeteaseState | None = None
        self._connected = False
        self._playing_hint = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ws = None
        self._ws_url = ""
        self._next_id = 0
        self._connect_count = 0
        self._reconnects = 0
        self._last_stats = time.monotonic()
        self._pos_anchor: float | None = None
        self._pos_mono = 0.0
        self._pos_title = ""

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run, name="netease-bridge", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._close()
        self._write_stats("stopped")

    @property
    def reconnects(self) -> int:
        with self._lock:
            return self._reconnects

    def _write_stats(self, reason: str) -> None:
        try:
            line = (
                f"[{time.strftime('%H:%M:%S')}] reason={reason} "
                f"reconnects={self.reconnects} connected={int(self.connected)}"
            )
            with (app_dir() / "netease.log").open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except Exception:  # noqa: BLE001
            pass

    def snapshot(self) -> Snapshot | None:
        with self._lock:
            state = self._state
            anchor = self._pos_anchor
            anchor_mono = self._pos_mono
        if state is None:
            return None
        position = state.position
        if (
            state.position_known
            and state.playing
            and anchor is not None
        ):
            position = anchor + max(0.0, time.monotonic() - anchor_mono)
            if state.duration > 0:
                position = min(position, state.duration)
        return state.snapshot(position=position)

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._connected

    @property
    def cover_url(self) -> str:
        with self._lock:
            state = self._state
        return state.cover_url if state is not None else ""

    def send_control(self, action: str) -> None:
        if action in CONTROL_JS:
            self._evaluate(CONTROL_JS[action])
            return
        if action.startswith("seek:"):
            try:
                seconds = max(0.0, float(action.split(":", 1)[1]))
            except (TypeError, ValueError):
                return
            self._seek(seconds)

    def _smooth_position(
        self,
        sample: float,
        playing: bool,
        title: str,
        duration: float,
    ) -> float:
        """把网易云 1 秒一级的播放条抹平，只允许位置前进。"""
        now = time.monotonic()
        if self._pos_title != title:
            self._pos_title = title
            self._pos_anchor = None
        if self._pos_anchor is None or not playing:
            self._pos_anchor, self._pos_mono = sample, now
            value = sample
        else:
            guess = self._pos_anchor + (now - self._pos_mono)
            if abs(sample - guess) > 2.0:
                # 用户 seek、换歌或播放器重新锚定：直接接受新位置。
                self._pos_anchor, self._pos_mono = sample, now
                value = sample
            else:
                value = max(guess, sample)
                self._pos_anchor, self._pos_mono = value, now
        if duration > 0:
            value = min(max(0.0, value), duration)
        return value

    def _set_state(self, state: NeteaseState | None) -> None:
        if state is not None:
            self._playing_hint = state.playing
            if state.position_known:
                state.position = self._smooth_position(
                    state.position,
                    state.playing,
                    state.title,
                    state.duration,
                )
            else:
                self._pos_anchor = None
                self._pos_title = state.title
            # snapshot() 由 NeteaseBridge 负责外推，State 本身不要再算一次。
            state.stamp = 0.0
        else:
            self._pos_anchor = None
            self._pos_mono = 0.0
            self._pos_title = ""
        with self._lock:
            self._state = state

    def _run(self) -> None:
        backoff = 0.5
        while not self._stop.is_set():
            try:
                target = _find_page(0.5)
                if target is None:
                    with self._lock:
                        self._connected = False
                    self._set_state(parse_window_title(
                        running_window_title(), self._playing_hint
                    ))
                    self._stop.wait(0.6)
                    continue
                url = str(target.get("webSocketDebuggerUrl") or "")
                if not url:
                    self._stop.wait(0.5)
                    continue
                self._connect(url)
                with self._lock:
                    self._connected = True
                backoff = 0.5
                next_target_check = time.monotonic() + TARGET_RECHECK_SECONDS
                misses = 0
                read_timeouts = 0
                while not self._stop.is_set():
                    if time.monotonic() - self._last_stats >= STATS_INTERVAL_SECONDS:
                        self._last_stats = time.monotonic()
                        self._write_stats("running")
                    if time.monotonic() >= next_target_check:
                        next_target_check = time.monotonic() + TARGET_RECHECK_SECONDS
                        newer = _find_page(0.3)
                        # None = 本次探测未知（客户端忙 / HTTP 超时），保持现有连接；
                        # 只有明确拿到另一个 target URL 才重连。
                        if newer is not None:
                            newer_url = str(newer.get("webSocketDebuggerUrl") or "")
                            if newer_url and newer_url != self._ws_url:
                                break
                    raw = self._evaluate(READ_JS)
                    if raw is None:
                        read_timeouts += 1
                        if read_timeouts >= MAX_READ_TIMEOUTS:
                            break
                        self._stop.wait(POLL_INTERVAL_SECONDS)
                        continue
                    read_timeouts = 0
                    state = parse_state(raw, self._playing_hint)
                    if state is None:
                        misses += 1
                        if misses >= 5:
                            break
                    else:
                        misses = 0
                        self._set_state(state)
                    self._stop.wait(POLL_INTERVAL_SECONDS)
            except Exception:  # noqa: BLE001
                self._stop.wait(backoff)
                backoff = min(3.0, backoff * 1.5)
            finally:
                self._close()
                with self._lock:
                    self._connected = False
            if not self._stop.is_set():
                self._stop.wait(0.3)

    def _connect(self, url: str) -> None:
        import websocket  # 懒加载：普通听歌不依赖这个模块也能启动

        self._close()
        self._ws = websocket.create_connection(
            url,
            timeout=2.5,
            suppress_origin=True,
            enable_multithread=True,
        )
        self._ws_url = url
        self._next_id = 0
        with self._lock:
            self._connect_count += 1
            if self._connect_count > 1:
                self._reconnects += 1

    def _close(self) -> None:
        ws, self._ws = self._ws, None
        self._ws_url = ""
        if ws is not None:
            try:
                ws.close()
            except Exception:  # noqa: BLE001
                pass

    def _call(self, method: str, params: dict | None = None, timeout: float = 2.0):
        if self._ws is None:
            return None
        self._next_id += 1
        command_id = self._next_id
        try:
            self._ws.send(json.dumps({
                "id": command_id,
                "method": method,
                "params": params or {},
            }))
        except Exception:  # noqa: BLE001
            self._close()
            return None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and self._ws is not None:
            try:
                self._ws.settimeout(max(0.2, deadline - time.monotonic()))
                raw = self._ws.recv()
            except Exception:  # noqa: BLE001
                return None
            if not raw:
                return None
            try:
                message = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if isinstance(message, dict) and message.get("id") == command_id:
                return message
        return None

    def _evaluate(self, expression: str):
        message = self._call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True},
        )
        if not message:
            return None
        result = message.get("result", {}).get("result", {})
        return result.get("value") if isinstance(result, dict) else None

    def _seek(self, seconds: float) -> None:
        raw = self._evaluate("""
          (() => {
            const slider = document.querySelector(
              '[aria-label="播放进度调节"], .StyledSliderContainer_smigcsb'
            );
            const range = slider && slider.querySelector('input[type="range"]');
            if (!slider || !range) return '';
            const rect = slider.getBoundingClientRect();
            const max = Number.parseFloat(range.getAttribute('max') || '0');
            return JSON.stringify({
              x: rect.x, y: rect.y, width: rect.width, height: rect.height, max: max
            });
          })()
        """)
        if not raw:
            return
        try:
            data = json.loads(raw)
            maximum = _num(data.get("max"))
            width = _num(data.get("width"))
            if maximum <= 0 or width <= 0:
                return
            fraction = max(0.0, min(1.0, seconds / maximum))
            x = _num(data.get("x")) + width * fraction
            y = _num(data.get("y")) + _num(data.get("height")) / 2.0
        except (TypeError, ValueError):
            return
        for event_type in ("mousePressed", "mouseReleased"):
            self._call(
                "Input.dispatchMouseEvent",
                {
                    "type": event_type,
                    "x": x,
                    "y": y,
                    "button": "left",
                    "clickCount": 1,
                },
            )
