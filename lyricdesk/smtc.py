"""通过 Windows 系统媒体控制接口 (SMTC) 读取 QQ音乐 的播放状态。

关键点：QQ音乐 的 SMTC 时间轴大约每 1 秒刷新一次采样值。
如果每次轮询都直接用采样值，进度会「卡顿—跳跃」。
因此这里只在采样值真正变化时重新锚定，两次采样之间用本地单调时钟外推，
得到平滑且准确的播放位置。
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass

try:
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as _SessionManager,
    )
    from winrt.windows.storage.streams import DataReader as _DataReader

    SMTC_AVAILABLE = True
except Exception:  # pragma: no cover - 缺依赖时降级
    _SessionManager = None
    _DataReader = None
    SMTC_AVAILABLE = False


PLAYING = 4
PAUSED = 5
STOPPED = 3
CLOSED = 0

# 常见播放器的可读名字（识别不到就退回 exe 名）
_PLAYER_NAMES = {
    "qqmusic": "QQ音乐",
    "cloudmusic": "网易云音乐",
    "kugou": "酷狗音乐",
    "kuwo": "酷我音乐",
    "spotify": "Spotify",
    "potplayer": "PotPlayer",
    "music.ui": "网易云音乐",
    "foobar2000": "foobar2000",
    "aimp": "AIMP",
    "netease": "网易云音乐",
}


def friendly_player_name(app_id: str) -> str:
    """把 SMTC 的 app id 变成人类能看懂的播放器名。"""
    if not app_id:
        return "未知播放器"
    lowered = app_id.lower()
    for key, name in _PLAYER_NAMES.items():
        if key in lowered:
            return name
    stem = app_id.replace("\\", "/").split("/")[-1]
    if stem.lower().endswith(".exe"):
        stem = stem[:-4]
    return stem or app_id


@dataclass(frozen=True)
class Track:
    title: str
    artist: str
    album: str
    duration: float

    @property
    def key(self) -> str:
        return f"{self.title}\u241f{self.artist}"

    @property
    def display(self) -> str:
        return f"{self.title} - {self.artist}" if self.artist else self.title


@dataclass
class Snapshot:
    track: Track | None
    position: float
    is_playing: bool
    status: int
    source: str
    can_next: bool = True
    can_prev: bool = True
    can_seek: bool = True


class SmtcReader:
    """后台线程轮询 SMTC，对外提供线程安全的快照。"""

    def __init__(self, interval: float = 0.25, preferred_player: str = "") -> None:
        self._interval = interval
        self._preferred = preferred_player

        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

        self._track: Track | None = None
        self._is_playing = False
        self._status = CLOSED
        self._source = ""
        self._can_next = True
        self._can_prev = True
        self._can_seek = True
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._players: list[dict] = []
        self._thumbnail: bytes | None = None
        self._thumbnail_key: str | None = None

        # 位置外推锚点
        self._anchor_pos = 0.0
        self._anchor_mono = time.monotonic()
        self._rate = 0.0
        self._raw_sample: float | None = None

        self.last_error: str = ""

    # ------------------------------------------------------------------

    def start(self) -> None:
        if not SMTC_AVAILABLE:
            self.last_error = "未安装 winrt-Windows.Media.Control"
            return
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="smtc", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def join(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout)

    def is_running(self) -> bool:
        thread = self._thread
        return bool(thread is not None and thread.is_alive())

    # ------------------------------------------------------------------

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._event_loop = loop
        try:
            loop.run_until_complete(self._loop())
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"{type(exc).__name__}: {exc}"
        finally:
            try:
                loop.close()
            except Exception:
                pass

    async def _loop(self) -> None:
        manager = None
        while not self._stop.is_set():
            try:
                if manager is None:
                    manager = await _SessionManager.request_async()
                await self._poll_once(manager)
                self.last_error = ""
            except Exception as exc:  # noqa: BLE001
                self.last_error = f"{type(exc).__name__}: {exc}"
                manager = None
                await asyncio.sleep(1.0)
            await asyncio.sleep(self._interval)

    # ------------------------------------------------------------------

    def set_preferred_player(self, app_id: str) -> None:
        self._preferred = app_id or ""

    def players(self) -> list[dict]:
        """当前系统里存在媒体会话的播放器列表（供界面选择）。"""
        with self._lock:
            return [dict(item) for item in self._players]

    def thumbnail(self) -> bytes | None:
        with self._lock:
            return self._thumbnail

    def _rank_sessions(self, manager) -> list[tuple]:
        """按「用户指定 > 正在播放」排序，不挑特定播放器。"""
        ranked = []
        for session in list(manager.get_sessions() or []):
            app_id = session.source_app_user_model_id or ""
            try:
                status = int(session.get_playback_info().playback_status)
            except Exception:
                status = 0
            ranked.append((session, app_id, status))

        preferred = (self._preferred or "").strip().lower()

        def sort_key(item):
            _session, app_id, status = item
            return (
                1 if (preferred and preferred in app_id.lower()) else 0,
                1 if status == PLAYING else 0,
            )

        ranked.sort(key=sort_key, reverse=True)
        return ranked

    async def _read_thumbnail(self, props) -> bytes | None:
        """从系统媒体信息里读专辑封面（任何播放器通用）。"""
        if _DataReader is None:
            return None
        try:
            reference = props.thumbnail
            if reference is None:
                return None
            stream = await reference.open_read_async()
            size = int(stream.size)
            if size <= 0 or size > 8_000_000:
                return None
            reader = _DataReader(stream.get_input_stream_at(0))
            await reader.load_async(size)
            return bytes(reader.read_buffer(size))
        except Exception:
            return None

    async def _poll_once(self, manager) -> None:
        candidates = self._rank_sessions(manager)
        with self._lock:
            self._players = [
                {"app_id": app_id, "playing": status == PLAYING}
                for _session, app_id, status in candidates
            ]

        chosen = None
        props = None
        for session, app_id, status in candidates:
            try:
                candidate_props = await session.try_get_media_properties_async()
            except Exception:
                continue
            if (candidate_props.title or "").strip():
                chosen = session
                props = candidate_props
                break

        if chosen is None or props is None:
            self._set_idle()
            return

        session = chosen
        title = (props.title or "").strip()

        artist = (props.artist or "").strip()
        album = (props.album_title or "").strip()

        timeline = session.get_timeline_properties()
        playback = session.get_playback_info()

        duration = _seconds(timeline.end_time) - _seconds(timeline.start_time)
        duration = max(0.0, duration)

        status = int(playback.playback_status)
        # 有些播放器只给 OPENED/CHANGING，凡是能取到进度就当作在播。
        is_playing = status == PLAYING
        if status in (CLOSED, STOPPED):
            is_playing = False

        raw_pos = _seconds(timeline.position) - _seconds(timeline.start_time)
        raw_pos = max(0.0, raw_pos)

        source = session.source_app_user_model_id or ""
        controls = playback.controls

        with self._lock:
            track = Track(title=title, artist=artist, album=album, duration=duration)
            track_changed = self._track is None or self._track.key != track.key
            self._track = track
            if track_changed:
                self._thumbnail = None
                self._thumbnail_key = None
            self._source = source
            self._status = status
            self._is_playing = is_playing
            self._can_next = bool(getattr(controls, "is_next_enabled", True))
            self._can_prev = bool(getattr(controls, "is_previous_enabled", True))
            self._can_seek = bool(getattr(controls, "is_playback_position_enabled", True))

            sample_changed = self._raw_sample is None or abs(raw_pos - self._raw_sample) > 0.004
            if track_changed or sample_changed:
                self._raw_sample = raw_pos
                self._anchor_pos = raw_pos
                self._anchor_mono = time.monotonic()
                self._rate = 1.0 if is_playing else 0.0
            else:
                # 采样没变：保持外推，但暂停/续播要立刻改速率。
                new_rate = 1.0 if is_playing else 0.0
                if new_rate != self._rate:
                    self._anchor_pos = self._position_locked()
                    self._anchor_mono = time.monotonic()
                    self._rate = new_rate

        # 换歌时抓一次专辑封面（任何播放器都通用）
        if track_changed:
            data = await self._read_thumbnail(props)
            with self._lock:
                if self._track is not None and self._track.key == track.key:
                    self._thumbnail = data
                    self._thumbnail_key = track.key

    def _set_idle(self) -> None:
        with self._lock:
            self._track = None
            self._is_playing = False
            self._status = CLOSED
            self._rate = 0.0
            self._raw_sample = None
            self._source = ""
            self._thumbnail = None
            self._thumbnail_key = None

    # ------------------------------------------------------------------

    def _position_locked(self) -> float:
        return self._anchor_pos + (time.monotonic() - self._anchor_mono) * self._rate

    def snapshot(self) -> Snapshot | None:
        with self._lock:
            if self._track is None:
                return None
            return Snapshot(
                track=self._track,
                position=max(0.0, self._position_locked()),
                is_playing=self._is_playing,
                status=self._status,
                source=self._source,
                can_next=self._can_next,
                can_prev=self._can_prev,
                can_seek=self._can_seek,
            )

    def seek_hint(self, delta: float) -> None:
        """用户手动微调进度时调用（不改变歌曲，只挪动锚点）。"""
        with self._lock:
            self._anchor_pos = max(0.0, self._position_locked() + delta)
            self._anchor_mono = time.monotonic()

    # ------------------------------------------------------------------
    # 播放控制
    # ------------------------------------------------------------------

    def send_control(self, action: str) -> None:
        """action: toggle / next / prev / seek:<秒数>"""
        loop = self._event_loop
        if loop is None or loop.is_closed():
            return
        try:
            asyncio.run_coroutine_threadsafe(self._control(action), loop)
        except Exception:
            pass

    async def _control(self, action: str) -> None:
        try:
            manager = await _SessionManager.request_async()
            session = None
            for candidate in self._rank_sessions(manager):
                session = candidate[0]
                break
            if session is None:
                return
            if action == "toggle":
                await session.try_toggle_play_pause_async()
            elif action == "next":
                await session.try_skip_next_async()
            elif action == "prev":
                await session.try_skip_previous_async()
            elif action.startswith("seek:"):
                from datetime import timedelta

                seconds = float(action.split(":", 1)[1])
                await session.try_change_playback_position_async(
                    timedelta(seconds=max(0.0, seconds))
                )
        except Exception:
            pass


def _seconds(value) -> float:
    try:
        return float(value.total_seconds())
    except Exception:
        try:
            return float(value)
        except Exception:
            return 0.0
