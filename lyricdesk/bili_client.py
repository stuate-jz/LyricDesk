r"""B 站客户端字幕桥（通过 Chrome DevTools Protocol）。

配合 `packaging\启动B站歌词模式.cmd` 使用：那个脚本会用
`--remote-debugging-port=9225` 重启 B 站客户端。这里连进页面，注入一段 JS
截获播放器接口的返回（`/x/player/v2` 里的字幕轨、`/x/web-interface/view` 里的标题），
再把字幕 JSON 下载下来转成带时间轴的歌词。

设计要点：
- 所有网络 / WebSocket 都在自己的 daemon 线程里跑，主线程只读缓存；
- 没开调试端口 / 没字幕 / 出错 → 静默返回 None，调用方回退到普通歌词；
- 只在 settings.bili_mode 打开时才会被 engine 创建，普通听歌一行都不跑。
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass

import requests

from .lyrics import LyricLine, Lyrics
from .smtc import Snapshot, Track
from .titles import clean_title

DEBUG_PORT = 9225
DEBUG_URL = f"http://127.0.0.1:{DEBUG_PORT}/json"

# 页面里注入的 JS：包一层 fetch / XHR，把播放器接口的返回存到 window.__LD
INJECT_JS = r"""
(function () {
  if (window.__LD && window.__LD.v === 2) { return; }
  window.__LD = { v: 2, view: null, player: null, ts: Date.now() };
  function keep(obj, key) {
    try { window.__LD[key] = obj; window.__LD.ts = Date.now(); } catch (e) {}
  }
  function kindOf(u) {
    u = String(u || '');
    if (/player\/(wbi\/)?v2/.test(u)) return 'player';
    if (/web-interface\/(wbi\/)?view/.test(u)) return 'view';
    return '';
  }
  var origFetch = window.fetch;
  if (origFetch) {
    window.fetch = function (input) {
      var url = (typeof input === 'string') ? input : (input && input.url) || '';
      var kind = kindOf(url);
      var promise = origFetch.apply(this, arguments);
      if (kind) {
        try {
          promise.then(function (resp) {
            try {
              resp.clone().json().then(function (j) { keep(j, kind); }).catch(function () {});
            } catch (e) {}
          }).catch(function () {});
        } catch (e) {}
      }
      return promise;
    };
  }
  var origOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (method, url) {
    var kind = kindOf(url);
    if (kind) {
      var xhr = this;
      xhr.addEventListener('load', function () {
        try { keep(JSON.parse(xhr.responseText), kind); } catch (e) {}
      });
    }
    return origOpen.apply(this, arguments);
  };
})();
"""

# 读当前状态：标题、两个接口的返回、<video> 的进度
READ_JS = r"""
(function () {
  // 注入比页面请求晚时，从 performance 里找到已经发生过的请求，带上同样的签名再取一次
  function refetch(kind, re) {
    var list = performance.getEntriesByType('resource').filter(function (e) { return re.test(e.name); });
    if (!list.length) { return; }
    list.sort(function (a, b) { return b.startTime - a.startTime; });
    fetch(list[0].name, { credentials: 'include' })
      .then(function (r) { return r.json(); })
      .then(function (j) { try { window.__LD[kind] = j; } catch (e) {} })
      .catch(function () {});
  }
  if (window.__LD && !window.__LD.player) { refetch('player', /player\/(wbi\/)?v2/); }
  if (window.__LD && !window.__LD.view) { refetch('view', /web-interface\/(wbi\/)?view/); }
  var v = document.querySelector('video');
  var out = {
    title: document.title || '',
    view: (window.__LD && window.__LD.view) || null,
    player: (window.__LD && window.__LD.player) || null,
    position: v ? Number(v.currentTime || 0) : 0,
    duration: v ? Number(v.duration || 0) : 0,
    paused: v ? !!v.paused : true
  };
  return JSON.stringify(out);
})()
"""


@dataclass
class BiliState:
    """页面里读到的状态（标题 / 字幕地址 / 播放进度）。"""

    title: str = ""
    subtitle_url: str = ""
    duration: float = 0.0
    position: float = 0.0
    playing: bool = False
    stamp: float = 0.0  # 读到这份状态时的 time.monotonic()

    def snapshot(self) -> Snapshot | None:
        """合成一个给界面用的快照；播放中按时间插值，避免进度一格一格跳。"""
        if not self.title:
            return None
        position = self.position
        if self.playing and self.stamp:
            position += max(0.0, time.monotonic() - self.stamp)
        if self.duration > 0:
            position = min(position, self.duration)
        track = Track(title=self.title, artist="", album="", duration=self.duration)
        return Snapshot(
            track=track,
            position=max(0.0, position),
            is_playing=self.playing,
            status=4 if self.playing else 5,
            source="bilibili",
            can_next=False,
            can_prev=False,
            can_seek=False,
        )


def _num(value, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number == number else default  # 排除 NaN


def _dig(obj, *keys):
    current = obj
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def parse_state(raw: str | None) -> BiliState | None:
    """把页面里读回来的 JSON 解析成 BiliState（纯函数，方便自检）。"""
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None

    view_data = _dig(data, "view", "data") or {}
    # /x/web-interface/view 是 data.title；/x/web-interface/wbi/view/detail 是 data.View.title
    view = _dig(data, "view", "data", "View") or {}
    player = _dig(data, "player", "data") or {}
    title = str(
        view.get("title") or view_data.get("title") or data.get("title") or ""
    ).strip()
    if title.lower() in ("undefined", "null", "about:blank"):
        title = ""
    title = clean_title(title) or title

    subtitle_url = ""
    subtitles = _dig(player, "subtitle", "subtitles") or []
    if isinstance(subtitles, list):
        for item in subtitles:
            if isinstance(item, dict) and item.get("subtitle_url"):
                subtitle_url = str(item["subtitle_url"])
                break

    # 有字幕轨但标题还没加载出来（刚重启播放器时常见）→ 先给个占位标题
    if not title and subtitle_url:
        title = "B 站视频"

    return BiliState(
        title=title,
        subtitle_url=subtitle_url,
        duration=(
            _num(view.get("duration"))
            or _num(view_data.get("duration"))
            or _num(data.get("duration"))
        ),
        position=_num(data.get("position")),
        playing=not bool(data.get("paused")),
        stamp=time.monotonic(),
    )


def to_lines(payload) -> list[LyricLine]:
    """B 站字幕 JSON（body: [{from, to, content}]）→ 歌词行。"""
    if not isinstance(payload, dict):
        return []
    body = payload.get("body")
    if not isinstance(body, list):
        return []
    lines: list[LyricLine] = []
    for item in body:
        if not isinstance(item, dict):
            continue
        text = str(item.get("content") or "").strip()
        if not text:
            continue
        start = _num(item.get("from"))
        end = _num(item.get("to")) or start
        lines.append(LyricLine(time=start, text=text, end=end))
    return lines


def _find_page(timeout: float = 0.8) -> dict | None:
    """调试端口里找一个 bilibili 的页面 target。

    优先 `player.html`：视频、`<video>` 和播放器接口都在那一页；首页只用来兜底。
    """
    try:
        resp = requests.get(DEBUG_URL, timeout=timeout)
        if resp.status_code != 200:
            return None
        targets = resp.json()
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(targets, list):
        return None
    fallback = None
    for item in targets:
        if not isinstance(item, dict) or item.get("type") != "page":
            continue
        url = str(item.get("url") or "")
        if "bilibili.com" not in url or not item.get("webSocketDebuggerUrl"):
            continue
        if "player.html" in url:
            return item
        if fallback is None:
            fallback = item
    return fallback


def available(timeout: float = 0.25) -> bool:
    """调试端口有没有响应、并且开着 B 站页面。"""
    return _find_page(timeout) is not None


class BiliBridge:
    """后台线程：连页面 → 注入 JS → 轮询状态 → 下载字幕 → 缓存 Lyrics。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: BiliState | None = None
        self._lyrics: Lyrics | None = None
        self._subtitle_url = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ws = None
        self._next_id = 0

    # ---------- 对外 ----------

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="bili-bridge", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._close()

    def alive(self) -> bool:
        return (
            self._thread is not None
            and self._thread.is_alive()
            and not self._stop.is_set()
        )

    def current(self) -> Lyrics | None:
        with self._lock:
            return self._lyrics

    def snapshot(self) -> Snapshot | None:
        with self._lock:
            state = self._state
        return state.snapshot() if state is not None else None

    # ---------- 线程体 ----------

    def _run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                target = _find_page(1.0)
                if target is None:
                    self._clear()
                    self._stop.wait(2.0)
                    continue
                self._connect(str(target["webSocketDebuggerUrl"]))
                self._install()
                backoff = 1.0
                while not self._stop.is_set():
                    state = parse_state(self._evaluate(READ_JS))
                    if state is None:
                        self._stop.wait(1.0)
                        continue
                    self._update(state)
                    self._stop.wait(0.8)
            except Exception:  # noqa: BLE001
                self._close()
                self._clear()
                if self._stop.wait(backoff):
                    return
                backoff = min(5.0, backoff * 1.5)

    def _connect(self, url: str) -> None:
        import websocket  # 延迟导入：没装依赖时不影响普通听歌

        self._close()
        self._ws = websocket.create_connection(
            url,
            timeout=3.0,
            suppress_origin=True,
            enable_multithread=True,
        )
        self._next_id = 0

    def _close(self) -> None:
        ws, self._ws = self._ws, None
        if ws is not None:
            try:
                ws.close()
            except Exception:  # noqa: BLE001
                pass

    def _call(self, method: str, params: dict | None = None, timeout: float = 3.0):
        if self._ws is None:
            return None
        self._next_id += 1
        cmd_id = self._next_id
        try:
            self._ws.send(
                json.dumps({"id": cmd_id, "method": method, "params": params or {}})
            )
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
                msg = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if isinstance(msg, dict) and msg.get("id") == cmd_id:
                return msg
        return None

    def _install(self) -> None:
        self._call("Runtime.enable")
        self._call("Page.enable")
        self._call("Page.addScriptToEvaluateOnNewDocument", {"source": INJECT_JS})
        self._call(
            "Runtime.evaluate", {"expression": INJECT_JS, "returnByValue": True}
        )

    def _evaluate(self, expression: str) -> str | None:
        msg = self._call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": False},
        )
        if not msg:
            return None
        result = _dig(msg, "result", "result")
        value = result.get("value") if isinstance(result, dict) else None
        return value if isinstance(value, str) else None

    def _update(self, state: BiliState) -> None:
        if not state.subtitle_url:
            # 这个视频没有字幕轨（或者还没加载出来）→ 回退普通歌词
            with self._lock:
                self._state = state
                self._lyrics = None
                self._subtitle_url = ""
            return

        with self._lock:
            self._state = state
            need_load = state.subtitle_url != self._subtitle_url
        if need_load:
            lines = self._download(state.subtitle_url)
            with self._lock:
                if lines:
                    self._subtitle_url = state.subtitle_url
                    self._lyrics = Lyrics(
                        lines=lines,
                        source="B站字幕",
                        title=state.title,
                        artist="",
                        albummid="",
                        album="",
                    )
                else:
                    self._lyrics = None

    def _download(self, url: str) -> list[LyricLine]:
        if url.startswith("//"):
            url = "https:" + url
        try:
            resp = requests.get(url, timeout=6.0)
            if resp.status_code != 200:
                return []
            return to_lines(resp.json())
        except Exception:  # noqa: BLE001
            return []

    def _clear(self) -> None:
        with self._lock:
            self._state = None
            self._lyrics = None
            self._subtitle_url = ""
