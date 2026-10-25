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

import hashlib
import json
import re
import threading
import time
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from .lyrics import LyricLine, Lyrics
from .smtc import Snapshot, Track
from .titles import clean_title

DEBUG_PORT = 9225
DEBUG_URL = f"http://127.0.0.1:{DEBUG_PORT}/json"
NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
TARGET_RECHECK_SECONDS = 2.0
MAX_READ_MISSES = 2

# WBI 签名用的乱序表（B 站 web 端通用）
_WBI_TAB = (
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52,
)
_WBI_CACHE: tuple[float, str] | None = None
_MUSIC_NOTE_EDGE = re.compile(r"^\s*[\u2669-\u266C]+\s*|\s*[\u2669-\u266C]+\s*$")

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
    paused: v ? !!v.paused : true,
    hasVideo: !!v,
    visible: document.visibilityState === 'visible'
  };
  return JSON.stringify(out);
})()
"""


@dataclass
class BiliState:
    """页面里读到的状态（标题 / 字幕地址 / 封面 / 播放进度）。"""

    title: str = ""
    bvid: str = ""
    cover_url: str = ""
    subtitle_url: str = ""
    duration: float = 0.0
    position: float = 0.0
    playing: bool = False
    has_video: bool = True
    visible: bool = True
    stamp: float = 0.0  # 读到这份状态时的 time.monotonic()

    @property
    def active(self) -> bool:
        """这个页面还算不算「正在看 B 站」。

        B 站关掉播放窗口时只是把 player.html 隐藏，`<video>` 和字幕数据都还在；
        如果只看`字幕地址存在`就会一直挂着旧字幕。规则：
        - 正在播（哪怕窗口最小化/隐藏）→ 有效；
        - 暂停但窗口可见（停下来读字幕）→ 有效；
        - 暂停 + 窗口隐藏（关掉播放页）→ 失效；
        - 没有 <video>（页面被回收）→ 失效。
        """
        return bool(self.has_video and (self.playing or self.visible))

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
    bvid = str(view.get("bvid") or view_data.get("bvid") or "").strip()
    pic = str(view.get("pic") or view_data.get("pic") or "").strip()
    if pic.startswith("//"):
        pic = "https:" + pic

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
        bvid=bvid,
        cover_url=pic,
        subtitle_url=subtitle_url,
        duration=(
            _num(view.get("duration"))
            or _num(view_data.get("duration"))
            or _num(data.get("duration"))
        ),
        position=_num(data.get("position")),
        playing=not bool(data.get("paused")),
        has_video=bool(data.get("hasVideo", True)),
        visible=bool(data.get("visible", True)),
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
        text = _MUSIC_NOTE_EDGE.sub("", str(item.get("content") or "")).strip()
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


def _wbi_mixin_from_raw(raw: str) -> str:
    """把 nav 返回的两段 key 拼成 WBI mixin，并缓存 10 分钟。"""
    global _WBI_CACHE
    if len(raw) < 64:
        return ""
    try:
        mixin = "".join(raw[index] for index in _WBI_TAB)[:32]
    except IndexError:
        return ""
    _WBI_CACHE = (time.time() + 600, mixin)
    return mixin


def _wbi_mixin(timeout: float = 6.0) -> str:
    """用 Python 请求 nav 取 WBI mixin（页面请求失败时的兜底）。"""
    global _WBI_CACHE
    now = time.time()
    if _WBI_CACHE is not None and _WBI_CACHE[0] > now:
        return _WBI_CACHE[1]
    try:
        response = requests.get(NAV_URL, timeout=timeout)
        wbi = (response.json().get("data") or {}).get("wbi_img") or {}
        img = str(wbi.get("img_url") or "").rsplit("/", 1)[-1].split(".")[0]
        sub = str(wbi.get("sub_url") or "").rsplit("/", 1)[-1].split(".")[0]
        return _wbi_mixin_from_raw(img + sub)
    except Exception:  # noqa: BLE001
        return ""


def signed_player_url(page_url: str, raw_wbi_key: str = "") -> str:
    """给播放器页地址里的 aid/cid 生成带 WBI 签名的 /x/player/wbi/v2 地址。

    B 站客户端有时不会自己请求 player/v2（尤其是切换视频后复用同一个页面），
    拿到字幕轨就全靠这里主动去要。
    """
    query = parse_qs(urlparse(page_url or "").query)
    aid = (query.get("aid") or [""])[0]
    cid = (query.get("cid") or [""])[0]
    if not aid or not cid:
        return ""
    mixin = _wbi_mixin_from_raw(raw_wbi_key) if raw_wbi_key else _wbi_mixin()
    if not mixin:
        return ""
    params = sorted({"aid": aid, "cid": cid, "wts": int(time.time())}.items())
    text = urlencode(
        {key: "".join(ch for ch in str(value) if ch not in "!'()*") for key, value in params}
    )
    w_rid = hashlib.md5((text + mixin).encode()).hexdigest()
    return f"https://api.bilibili.com/x/player/wbi/v2?{text}&w_rid={w_rid}"


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
        self._ws_url = ""
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
            state = self._state
            lyrics = self._lyrics
        if state is None or not state.active:
            return None
        return lyrics

    def has_state(self) -> bool:
        """有没有连上 B 站页面（不管当前算不算在播）。"""
        with self._lock:
            return self._state is not None

    def active(self) -> bool:
        """B 站当前算不算「正在看」（关掉播放页后是 False）。"""
        with self._lock:
            return bool(self._state is not None and self._state.active)

    def snapshot(self) -> Snapshot | None:
        with self._lock:
            state = self._state
        if state is None or not state.active:
            return None
        return state.snapshot()

    @property
    def cover_url(self) -> str:
        with self._lock:
            state = self._state
        return state.cover_url if state is not None and state.active else ""

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
                read_misses = 0
                next_target_check = time.monotonic() + TARGET_RECHECK_SECONDS
                while not self._stop.is_set():
                    if self._ws is None:
                        break
                    if time.monotonic() >= next_target_check:
                        next_target_check = time.monotonic() + TARGET_RECHECK_SECONDS
                        newer = _find_page(0.35)
                        if (
                            newer is not None
                            and str(newer.get("webSocketDebuggerUrl") or "")
                            != self._ws_url
                        ):
                            # B 站首页和播放页是两个 target。用户点进视频后必须
                            # 从旧的首页连接切到 player.html，否则永远读不到 song。
                            break
                    raw = self._evaluate(READ_JS)
                    state = parse_state(raw)
                    if state is None:
                        read_misses += 1
                        if read_misses >= MAX_READ_MISSES or self._ws is None:
                            break
                        self._stop.wait(0.4)
                        continue
                    read_misses = 0
                    if not state.subtitle_url and state.active:
                        # 页面没自己请求过 player/v2 → 我们带 WBI 签名去要一份
                        player = self._fetch_player()
                        if player:
                            try:
                                data = json.loads(raw) if raw else {}
                            except (TypeError, ValueError):
                                data = {}
                            data["player"] = player
                            state = parse_state(json.dumps(data)) or state
                    self._update(state)
                    self._stop.wait(0.8)
                # 连接失效 / B 站重启 / target 从首页切到播放页 → 外层重连。
                self._close()
                self._clear()
                if not self._stop.is_set():
                    self._stop.wait(0.4)
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
        self._ws_url = url
        self._next_id = 0

    def _close(self) -> None:
        ws, self._ws = self._ws, None
        self._ws_url = ""
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
        value = self._evaluate_raw(expression)
        return value if isinstance(value, str) else None

    def _evaluate_raw(self, expression: str, timeout: float = 4.0, await_promise: bool = False):
        msg = self._call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": await_promise,
            },
            timeout=timeout,
        )
        if not msg:
            return None
        result = _dig(msg, "result", "result")
        return result.get("value") if isinstance(result, dict) else None

    def _fetch_player(self) -> dict | None:
        """主动要一份 /x/player/wbi/v2（带 WBI 签名，页面里带登录态发）。"""
        href = self._evaluate("location.href")
        # 优先让 B 站页面自己请求 nav。单文件打包版里 requests 的证书 / 代理
        # 环境偶尔与系统 Python 不同，页面内请求则完全复用客户端现有网络环境。
        raw_key = self._page_wbi_key()
        url = signed_player_url(href or "", raw_key)
        if not url:
            return None
        expression = (
            "fetch("
            + json.dumps(url)
            + ", {credentials:'include'})"
            ".then(function(r){return r.json()}).catch(function(){return null})"
        )
        data = self._evaluate_raw(expression, timeout=10.0, await_promise=True)
        if isinstance(data, dict) and data.get("code") == 0:
            return data
        return None

    def _page_wbi_key(self) -> str:
        expression = r"""
        (async function () {
          try {
            const response = await fetch(
              'https://api.bilibili.com/x/web-interface/nav',
              {credentials: 'include'}
            );
            const data = await response.json();
            const wbi = (data && data.data && data.data.wbi_img) || {};
            const name = function (url) {
              return String(url || '').split('/').pop().split('.')[0];
            };
            return name(wbi.img_url) + name(wbi.sub_url);
          } catch (error) {
            return '';
          }
        })()
        """
        value = self._evaluate_raw(expression, timeout=10.0, await_promise=True)
        return value if isinstance(value, str) and len(value) >= 64 else ""

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
                        cover_url=state.cover_url,
                    )
                else:
                    self._lyrics = None

    def _download(self, url: str) -> list[LyricLine]:
        if url.startswith("//"):
            url = "https:" + url
        expression = (
            "fetch("
            + json.dumps(url)
            + ", {credentials:'include'})"
            ".then(function(r){return r.json()}).catch(function(){return null})"
        )
        payload = self._evaluate_raw(expression, timeout=10.0, await_promise=True)
        lines = to_lines(payload)
        if lines:
            return lines
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
