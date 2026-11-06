"""把播放状态、歌词获取和界面串起来的后台引擎。"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QTimer, Signal

from .config import Settings
from .bili_client import BiliBridge
from .bili_launcher import BiliWatcher
from .lyrics import Lyrics, fetch_enhanced, load_cached, provider_for_player, save_cached
from .netease_client import NeteaseBridge, configure as configure_netease
from .netease_launcher import NeteaseWatcher, find_ready_port
from .smtc import SMTC_AVAILABLE, SmtcReader, Snapshot


class Engine(QObject):
    lyricsChanged = Signal(object)
    trackChanged = Signal(object)
    # 后台守护想给用户提个醒（标题, 正文）——托盘气泡
    notice = Signal(str, str)

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        if settings.netease_port:
            configure_netease(settings.netease_port)
        self._reader = SmtcReader(preferred_player=settings.preferred_player)
        self._reader.start()

        self._lyrics: Lyrics | None = None
        self._key: str | None = None
        self._token = 0
        self._lock = threading.Lock()

        # B 站字幕（可选）：只有 settings.bili_mode 打开、且确实连上调试端口才会用
        self._bili: BiliBridge | None = None
        self._bili_lyrics: Lyrics | None = None
        self._bili_watch: BiliWatcher | None = None
        self._netease: NeteaseBridge | None = None
        self._netease_watch: NeteaseWatcher | None = None

        self._timer = QTimer(self)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

    # ------------------------------------------------------------------

    @property
    def lyrics(self) -> Lyrics | None:
        return self._lyrics

    @property
    def bili_cover(self) -> str:
        """只在当前确实跟随 B 站时返回视频封面，避免串到音乐播放器。"""
        snapshot = self.snapshot()
        if (
            snapshot is not None
            and (snapshot.source or "").lower() == "bilibili"
            and self._bili is not None
        ):
            return self._bili.cover_url
        return ""

    @property
    def netease_cover(self) -> str:
        """只在当前确实跟随网易云时返回底栏封面。"""
        snapshot = self.snapshot()
        if (
            snapshot is not None
            and (snapshot.source or "").lower() == "netease"
            and self._netease is not None
        ):
            return self._netease.cover_url
        return ""

    @property
    def netease_connected(self) -> bool:
        return bool(self._netease is not None and self._netease.connected)

    @property
    def status_text(self) -> str:
        if self.settings.netease_mode and self.netease_connected:
            return "网易云客户端已连接"
        if not SMTC_AVAILABLE:
            return "系统媒体接口不可用"
        if self._reader.last_error:
            return self._reader.last_error
        return "运行中"

    def snapshot(self) -> Snapshot | None:
        bili = None
        if self.settings.bili_mode and self._bili is not None:
            bili = self._bili.snapshot()
        netease = None
        if self.settings.netease_mode and self._netease is not None:
            netease = self._netease.snapshot()
        smtc = self._reader_view()

        # 正在播放的窗口优先；暂停的客户端不应抢走另一个正在播放的播放器。
        if bili is not None and bili.is_playing:
            return bili
        if netease is not None and netease.is_playing:
            return netease
        if smtc is not None and smtc.is_playing:
            return smtc
        if bili is not None:
            return bili
        if netease is not None:
            return netease
        return smtc

    def _reader_view(self) -> Snapshot | None:
        """普通 SMTC 快照；但 B 站播放页关了以后，B 站自己的媒体会话别再顶着用。"""
        snap = self._reader.snapshot()
        if (
            self.settings.bili_mode
            and self._bili is not None
            and self._bili.has_state()
            and not self._bili.active()
            and snap is not None
            and "bilibili" in (snap.source or "").lower()
        ):
            return None
        return snap

    def players(self) -> list[dict]:
        """当前有媒体会话的播放器（用于让用户选择跟随哪一个）。"""
        return self._reader.players()

    def thumbnail(self) -> bytes | None:
        """系统媒体接口提供的专辑封面（任何播放器通用）。"""
        return self._reader.thumbnail()

    def set_preferred_player(self, app_id: str) -> None:
        self.settings.preferred_player = app_id
        self._reader.set_preferred_player(app_id)
        self._key = None  # 强制按新播放器的歌曲重新取歌词

    def send_control(self, action: str) -> None:
        """转发播放控制指令给播放器。"""
        snapshot = self.snapshot()
        if (
            snapshot is not None
            and (snapshot.source or "").lower() == "netease"
            and self._netease is not None
        ):
            self._netease.send_control(action)
            return
        self._reader.send_control(action)

    def stop(self) -> None:
        self._stop_bili()
        self._stop_netease()
        self._reader.stop()

    def join(self, timeout: float | None = None) -> None:
        self._reader.join(timeout)

    def is_running(self) -> bool:
        return self._reader.is_running()

    # ------------------------------------------------------------------

    def _poll(self) -> None:
        # B 站字幕优先：有字幕就用字幕，没有就一路回退到原来的 SMTC + 曲库流程
        if self.settings.bili_mode:
            if self._bili is None:
                self._bili = BiliBridge()
                self._bili.start()
            if self._bili_watch is None:
                # 只在开关打开时才有这个守护线程：B 站被普通方式打开 → 自动带端口重启
                self._bili_watch = BiliWatcher(self._bili_notice)
                self._bili_watch.start()
        elif self._bili is not None:
            self._stop_bili()
            if self._bili_lyrics is not None:
                self._bili_lyrics = None
                self._lyrics = None
                self._key = None
                self.lyricsChanged.emit(None)

        if self.settings.netease_mode:
            if not self.settings.netease_port:
                ready_port = find_ready_port()
                if ready_port:
                    self.settings.netease_port = ready_port
                    self.settings.save()
                    configure_netease(ready_port)
            if self._netease is None:
                self._netease = NeteaseBridge()
                self._netease.start()
            if self._netease_watch is None:
                self._netease_watch = NeteaseWatcher(
                    self.settings,
                    notify=lambda text: self.notice.emit("网易云歌词", text),
                )
                self._netease_watch.start()
        elif self._netease is not None:
            self._stop_netease()

        snapshot = self.snapshot()
        if snapshot is not None and (snapshot.source or "").lower() == "bilibili":
            bili = self._bili.current() if self._bili is not None else None
            if bili is not None:
                if bili is not self._bili_lyrics:
                    self._bili_lyrics = bili
                    self._lyrics = bili
                    self.lyricsChanged.emit(bili)
                return
        if self._bili_lyrics is not None:
            # 字幕没了、或另一个正在播放的客户端更优先 → 清掉再走普通流程
            self._bili_lyrics = None
            self._lyrics = None
            self._key = None
            self.lyricsChanged.emit(None)

        if snapshot is None or snapshot.track is None:
            if self._key is not None:
                self._key = None
                self._lyrics = None
                self.lyricsChanged.emit(None)
                self.trackChanged.emit(None)
            return

        track = snapshot.track
        if track.key == self._key:
            return

        self._key = track.key
        self._display_idx_reset()
        self.trackChanged.emit(track)

        provider = provider_for_player(snapshot.source)
        song_id = ""
        if provider == "netease" and self._netease is not None:
            song_id = self._netease.song_id
        cached = load_cached(track.title, track.artist, provider, track.key)
        if cached is not None:
            self._lyrics = cached
            self.lyricsChanged.emit(cached)
            if cached.lines:
                return
            if cached.source == "miss":
                return
        else:
            self._lyrics = None
            self.lyricsChanged.emit(None)

        self._start_fetch(
            track.key,
            track.title,
            track.artist,
            track.duration,
            provider,
            track_key=track.key,
            song_id=song_id,
        )

    def _stop_bili(self) -> None:
        watcher, self._bili_watch = self._bili_watch, None
        if watcher is not None:
            watcher.stop()
        bridge, self._bili = self._bili, None
        self._bili_lyrics = None
        if bridge is not None:
            bridge.stop()

    def _bili_notice(self, text: str) -> None:
        self.notice.emit("B 站字幕", text)

    def _stop_netease(self) -> None:
        watcher, self._netease_watch = self._netease_watch, None
        if watcher is not None:
            watcher.stop()
        bridge, self._netease = self._netease, None
        if bridge is not None:
            bridge.stop()

    def _display_idx_reset(self) -> None:
        # 通知界面这是新歌（界面自己判断是否重置动画）
        pass

    # ------------------------------------------------------------------

    def _start_fetch(
        self,
        key: str,
        title: str,
        artist: str,
        duration: float,
        prefer: str = "",
        *,
        track_key: str = "",
        song_id: str = "",
    ) -> None:
        with self._lock:
            self._token += 1
            token = self._token

        def worker() -> None:
            def deliver_partial(result: Lyrics) -> None:
                save_cached(title, artist, result, prefer, track_key)
                with self._lock:
                    if token != self._token:
                        return
                self._deliver(result)

            try:
                result = fetch_enhanced(
                    title,
                    artist,
                    duration,
                    prefer=prefer,
                    track_key=track_key,
                    song_id=song_id,
                    partial=deliver_partial,
                )
            except Exception:
                result = Lyrics(lines=[], source="", title=title, artist=artist)
            save_cached(title, artist, result, prefer, track_key)
            with self._lock:
                if token != self._token:
                    return
            self._deliver(result)

        threading.Thread(target=worker, name="lyric-fetch", daemon=True).start()

    def _deliver(self, result: Lyrics) -> None:
        # 线程安全：Signal 会自动排队到主线程
        self._lyrics = result
        self.lyricsChanged.emit(result)

    def reload(self) -> None:
        """忽略缓存，重新抓取当前歌曲的歌词。"""
        snapshot = self.snapshot()
        if snapshot is None or snapshot.track is None:
            return
        track = snapshot.track
        from .lyrics import _cache_path, _track_cache_key, provider_for_player

        provider = provider_for_player(snapshot.source)
        try:
            path = _cache_path(
                _track_cache_key(track.title, track.artist, provider, track.key)
            )
            if path.exists():
                path.unlink()
        except Exception:
            pass

        self._lyrics = None
        self.lyricsChanged.emit(None)
        song_id = ""
        if provider == "netease" and self._netease is not None:
            song_id = self._netease.song_id
        self._start_fetch(
            track.key,
            track.title,
            track.artist,
            track.duration,
            provider,
            track_key=track.key,
            song_id=song_id,
        )
