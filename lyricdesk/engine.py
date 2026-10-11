"""把播放状态、歌词获取和界面串起来的后台引擎。"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QTimer, Signal

from .config import Settings
from .lyrics import Lyrics, fetch, load_cached, provider_for_player, save_cached
from .smtc import SMTC_AVAILABLE, SmtcReader, Snapshot


class Engine(QObject):
    lyricsChanged = Signal(object)
    trackChanged = Signal(object)

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self._reader = SmtcReader(preferred_player=settings.preferred_player)
        self._reader.start()

        self._lyrics: Lyrics | None = None
        self._key: str | None = None
        self._token = 0
        self._lock = threading.Lock()

        self._timer = QTimer(self)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

    # ------------------------------------------------------------------

    @property
    def lyrics(self) -> Lyrics | None:
        return self._lyrics

    @property
    def status_text(self) -> str:
        if not SMTC_AVAILABLE:
            return "系统媒体接口不可用"
        if self._reader.last_error:
            return self._reader.last_error
        return "运行中"

    def snapshot(self) -> Snapshot | None:
        return self._reader.snapshot()

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
        self._reader.send_control(action)

    def stop(self) -> None:
        self._reader.stop()

    def join(self, timeout: float | None = None) -> None:
        self._reader.join(timeout)

    def is_running(self) -> bool:
        return self._reader.is_running()

    # ------------------------------------------------------------------

    def _poll(self) -> None:
        snapshot = self._reader.snapshot()
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

        cached = load_cached(track.title, track.artist)
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
            provider_for_player(snapshot.source),
        )

    def _display_idx_reset(self) -> None:
        # 通知界面这是新歌（界面自己判断是否重置动画）
        pass

    # ------------------------------------------------------------------

    def _start_fetch(
        self, key: str, title: str, artist: str, duration: float, prefer: str = ""
    ) -> None:
        with self._lock:
            self._token += 1
            token = self._token

        def worker() -> None:
            try:
                result = fetch(title, artist, duration, prefer=prefer)
            except Exception:
                result = Lyrics(lines=[], source="", title=title, artist=artist)
            save_cached(title, artist, result)
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
        snapshot = self._reader.snapshot()
        if snapshot is None or snapshot.track is None:
            return
        track = snapshot.track
        from .lyrics import _cache_path, normalize

        try:
            path = _cache_path(f"{normalize(track.title)}|{normalize(track.artist)}")
            if path.exists():
                path.unlink()
        except Exception:
            pass

        self._lyrics = None
        self.lyricsChanged.emit(None)
        self._start_fetch(track.key, track.title, track.artist, track.duration)
