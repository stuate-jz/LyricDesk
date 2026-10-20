"""悬浮歌词 / 播放器窗口：透明、无边框、置顶、可自由拖动。"""

from __future__ import annotations

import math
import os
import subprocess
import tempfile
import threading
import time
import weakref
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QFontDatabase,
    QFontMetricsF,
    QImage,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QRadialGradient,
    QTransform,
)
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMenu,
    QToolButton,
    QWidget,
    QWidgetAction,
)

from .config import PLAYER_WIDTH_MIN, THEMES, WIDTH_MAX, WIDTH_MIN, Settings
from .covers import CoverLoader
from . import heat as heat_lookup
from .i18n import tr
from .processes import music_app_running
from .fonts import (
    BUNDLED_FONTS,
    ONLINE_FONTS,
    RECOMMENDED,
    download,
    downloaded,
    family_for,
    import_font_file,
    imported_fonts,
    user_font_dir,
)
from . import APP_TITLE, __version__
from .smtc import friendly_player_name
from .update import (
    DEFAULT_SOURCE as UPDATE_DEFAULT_SOURCE,
    FAILED_MARKER,
    bundled_source,
    check as check_update,
    download as download_update,
    describe_source,
    is_newer,
)
from .win_util import set_native_topmost
from .lyrics import normalize
from .render import (
    draw_karaoke,
    draw_sprite,
    ease_out_back,
    ease_out_cubic,
    fit_size,
    make_sprite,
    quad_transform,
)
from . import render as render_mod

MARGIN = 24
PAD = 20

# 深度拉满时平面转多少度（约等于手指在桌面上一张卡片的倾斜）
MAX_DEPTH_ANGLE = 42.0


def depth_angle(value: float) -> float:
    """把滑块的 -0.80~+0.80 映射成旋转角（1.35 次幂让小值更平缓）。"""
    v = max(-0.80, min(0.80, float(value))) / 0.80
    return math.copysign(MAX_DEPTH_ANGLE * (abs(v) ** 1.35), v)


def _project_points(
    points, width: float, height: float, theta_h: float, theta_v: float
) -> list[tuple[float, float]]:
    """把单位坐标点 (u,v) ∈ [-1,1]² 投影到屏幕（相对平面中心）。

    虚拟相机在平面正前方 D 处，按透视除法缩小远处的点；最后按
    「离相机最近的点的缩放 = 1」归一化 —— 这样把倾斜调大只会让远侧变小，
    不会出现「一开倾角整块缩小」或者「越调越大」的跳变。
    """
    D = 1.5 * width
    cos_h, sin_h = math.cos(theta_h), math.sin(theta_h)
    cos_v, sin_v = math.cos(theta_v), math.sin(theta_v)
    raw: list[tuple[float, float, float]] = []
    for u, v in points:
        x, y, z = u * width / 2.0, v * height / 2.0, 0.0
        # 绕竖直轴（左右倾斜）
        x, z = x * cos_h + z * sin_h, -x * sin_h + z * cos_h
        # 绕水平轴（上下倾斜）
        y, z = y * cos_v - z * sin_v, y * sin_v + z * cos_v
        k = D / (D + z)
        raw.append((x * k, y * k, k))
    nearest = max(item[2] for item in raw) or 1.0
    return [(x / nearest, y / nearest) for x, y, _k in raw]
TEXT_GAP = 18
CONTROLS_GAP = 16.0
ANIM_DURATION = 0.34
NEXT_GAP = 0.34  # 下一句与当前句的间距系数（相对下一句行高）

WEIGHT_LYRIC = QFont.Weight.Bold
WEIGHT_MEDIUM = QFont.Weight.Medium
WEIGHT_TITLE = QFont.Weight.DemiBold

# 这些界面都是直接浮在壁纸上的，不画背景板
_NO_BOARD_MODES = ("depth3d", "album", "lyrics")

# 分离面板模式下会有多扇窗口同时轮询全局热键，
# 用共享状态保证一次按键只触发一次切换。
_HOTKEY_STATE = {"prev": False}

# 活着的那几扇歌词窗（单窗口 1 个、分离面板 2 个）。
# 打开设置窗口时要把它们的「置顶」临时摘掉，否则歌词会画在设置窗口上面；
# 用 WeakSet 就不会拖住已经销毁的窗口。
_LIVE_WINDOWS: "weakref.WeakSet" = weakref.WeakSet()


def set_all_topmost_suspended(suspended: bool) -> None:
    """把所有歌词窗的「置顶」临时挂起 / 恢复（设置窗口开着的时候用）。"""
    for window in list(_LIVE_WINDOWS):
        window.set_topmost_suspended(suspended)


# 右键菜单里的极简播放控制图标：系统自带的图标字体（Windows 10/11 都有）
ICON_PREV = "\ue892"
ICON_NEXT = "\ue893"
ICON_PLAY = "\ue768"
ICON_PAUSE = "\ue769"
# 图标字体被精简掉时的兜底（Segoe UI Symbol 里就有这三个）
SYMBOL_PREV = "\u23ee"
SYMBOL_PLAY = "\u23ef"
SYMBOL_NEXT = "\u23ed"


def _icon_font() -> str:
    families = set(QFontDatabase.families())
    for name in ("Segoe Fluent Icons", "Segoe MDL2 Assets"):
        if name in families:
            return name
    return "Segoe UI Symbol"


def _play_glyphs(family: str) -> dict[str, str]:
    """播放控制那几个图标字符；图标字体不在时退化成 ⏮ ⏯ ⏭。"""
    if family == "Segoe UI Symbol":
        return {"prev": SYMBOL_PREV, "play": SYMBOL_PLAY, "pause": SYMBOL_PLAY, "next": SYMBOL_NEXT}
    return {"prev": ICON_PREV, "play": ICON_PLAY, "pause": ICON_PAUSE, "next": ICON_NEXT}


def _qt_font(family: str, size: int, weight) -> QFont:
    font = QFont(family)
    font.setPixelSize(max(1, int(size)))
    font.setWeight(weight)
    return font


def _format_time(seconds: float) -> str:
    if not seconds or seconds <= 0:
        return "0:00"
    total = int(seconds)
    return f"{total // 60}:{total % 60:02d}"


def _fast_blur(pixmap: QPixmap, factor: int = 8) -> QPixmap:
    """缩小再放大，得到廉价但效果不错的模糊。"""
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    if image.width() < 4 or image.height() < 4:
        return pixmap
    small = image.scaled(
        max(1, image.width() // factor),
        max(1, image.height() // factor),
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    blurred = small.scaled(
        image.size(),
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    return QPixmap.fromImage(blurred)




class LyricWindow(QWidget):
    requestQuit = Signal()
    requestAutostart = Signal(bool)
    requestReload = Signal()
    requestNotify = Signal(str, str)
    requestHide = Signal()
    # 检查更新是在后台线程做的，结果用信号送回主线程再弹窗
    updateChecked = Signal(object)
    # 更新包下载完（或失败）也送回主线程：(成功?, 路径或错误, 版本信息)
    updateDownloaded = Signal(bool, str, object)
    # 下载进度（已下载字节, 总字节, 字节/秒）——后台线程发、主线程画进度条
    updateProgress = Signal(int, int, float)
    # 热度查询结果（后台线程查完送回来）：歌曲 key, 热度值（可能为 None）
    heatReady = Signal(str, object)
    settingsChanged = Signal()

    def __init__(
        self,
        settings: Settings,
        engine,
        role: str = "main",
        anchor_y: int | None = None,
    ) -> None:
        super().__init__(None)
        self.settings = settings
        self.engine = engine
        # role: main(单窗口) / player(唱片面板) / lyrics(歌词面板)
        self.role = role
        # 歌词面板首次出现时贴着唱片面板下方，由 app.py 传入唱片面板底边的 y
        self._anchor_y = anchor_y

        self._drag_offset: QPoint | None = None
        self._press_global = QPoint()
        self._dragging = False
        self._anim_t0 = 0.0
        self._display_idx = -1
        self._lyrics_ref = None
        self._bg_key: tuple | None = None
        self._bg_pixmap: QPixmap | None = None
        self._hover = ""
        self._hotkey_prev = False
        self._update_busy = False
        self._update_silent = False
        self._spin_angle = 0.0
        self._last_tick = time.monotonic()

        self._covers: dict[str, QPixmap] = {}
        self._cover_tints: dict[str, QColor] = {}
        self._cover_cache: dict[tuple, QPixmap] = {}
        self._thumb_pixmap: QPixmap | None = None
        self._thumb_key: str | None = None

        # 纯歌词面板顶部的歌名 / 作者 / 热度
        self._heat_key = ""
        self._heat_value: float | None = None
        self._head_h = 0.0
        self._head_sub_h = 0.0
        self._head_gap = 0.0
        self._head_block = 0.0

        # 自动宽度：记录上一次算宽度用的歌词对象 / 缓存
        self._auto_lyrics_ref = None
        self._auto_width_cache = None

        self._hit_prev = QRectF()
        self._hit_play = QRectF()
        self._hit_next = QRectF()
        self._hit_bar = QRectF()

        # 各模式的排版尺寸：正常都会在 recalculate() 里算出来，
        # 这里先给一份安全初值，保证任何路径下绘制都不会缺属性
        self._list_slot = 0.0
        self._list_count = 0
        self._main_h = 0.0
        self._disc_size = 44.0
        self._wave_h = 18.0
        self._album_title_h = 0.0
        self._album_artist_h = 0.0
        self._album_bar_h = 6.0
        self._album_label_h = 0.0
        self._album_text_h = 0.0

        self._overscan = 0
        self._overscan_v = 0
        # 设置窗口开着时，本窗口的「置顶」临时挂起（见 set_topmost_suspended）
        self._suspend_topmost = False
        _LIVE_WINDOWS.add(self)
        self._scroll_from = 0.0
        self._scroll_target = 0.0
        self._scroll_t0 = 0.0
        self._scroll_ready = False

        self._icon_family = _icon_font()
        self._cover_loader = CoverLoader(self)
        self._cover_loader.ready.connect(self._on_cover)
        self.updateChecked.connect(self._on_update_result)
        self.updateDownloaded.connect(self._on_update_downloaded)
        self.updateProgress.connect(self._on_update_progress)
        self.heatReady.connect(self._on_heat_ready)

        self.setWindowTitle("桌面歌词")
        # 先设窗口标志，再设透明属性
        self._apply_window_flags()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        self.recalculate(initial=True)
        self._update_cursor()

    # ==================================================================
    # 窗口标志 / 尺寸
    # ==================================================================

    def _apply_window_flags(self) -> None:
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.NoDropShadowWindowHint
        )
        # 设置窗口开着的时候临时不置顶：设置窗口本身不是置顶的，
        # 而我们这几扇歌词窗是置顶的，不摘掉的话歌词会画在设置窗口上面、挡着点不动
        if self.settings.always_on_top and not self._suspend_topmost:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        if self.settings.click_through:
            flags |= Qt.WindowType.WindowTransparentForInput
        was_visible = self.isVisible()
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        if was_visible:
            self.show()

    def apply_flags(self) -> None:
        self._apply_window_flags()
        self._bg_key = None
        self._update_cursor()

    def set_topmost_suspended(self, suspended: bool) -> None:
        """把「置顶」临时挂起 / 恢复（设置窗口开关时由 set_all_topmost_suspended 调）。

        只影响窗口标志，不动 settings.always_on_top —— 设置里存的值始终是用户选的那个，
        所以设置窗口一关就回到原样，中途崩了下次启动也是对的。
        """
        suspended = bool(suspended)
        if suspended == self._suspend_topmost:
            return
        self._suspend_topmost = suspended
        # 本来就没置顶的窗口不用折腾（重复 setWindowFlags 会让窗口闪一下）
        if self.settings.always_on_top:
            # 走原生 Z 序，避免「打开设置窗口时歌词窗闪一下」
            if not set_native_topmost(self, self.settings.always_on_top and not suspended):
                self.apply_flags()

    def _build_fonts(self) -> dict[str, tuple]:
        size = int(self.settings.font_size)
        family = self.settings.font_family
        return {
            "lyric": (family, size, WEIGHT_LYRIC),
            "next": (family, max(12, int(size * 0.50)), WEIGHT_MEDIUM),
            "prev": (family, max(11, int(size * 0.44)), WEIGHT_MEDIUM),
            "title": (family, max(14, int(size * 0.44)), WEIGHT_TITLE),
            "artist": (family, max(11, int(size * 0.33)), WEIGHT_MEDIUM),
            "time": (family, max(10, int(size * 0.29)), WEIGHT_MEDIUM),
            "icon": (self._icon_family, max(12, int(size * 0.42)), QFont.Weight.Normal),
            "list": (family, max(12, int(size * 0.50)), WEIGHT_MEDIUM),
            "list_cur": (family, max(14, int(size * 0.82)), WEIGHT_LYRIC),
            # 纯歌词面板顶部的歌名 / 作者
            "head": (family, max(16, int(size * 0.58)), WEIGHT_TITLE),
            "head_sub": (family, max(11, int(size * 0.34)), WEIGHT_MEDIUM),
        }

    def recalculate(self, initial: bool = False) -> None:
        # 字间距会影响每个字的 advance，必须在算字体 / 自动宽度之前设置
        render_mod.set_letter_spacing(float(self.settings.letter_spacing))
        self._fonts = self._build_fonts()
        # 保留 QFont 实例本身，避免度量对象引用到已被回收的字体
        self._qt_fonts = {key: _qt_font(*spec) for key, spec in self._fonts.items()}
        self._metrics = {
            key: QFontMetricsF(font) for key, font in self._qt_fonts.items()
        }

        settings = self.settings
        fm_lyric = self._metrics["lyric"]
        fm_next = self._metrics["next"]

        # 自动宽度：按当前歌词最长的一行算，写回 settings.width（窗口/锚点/位置用同一口径）
        auto = self._auto_width()
        if auto != int(settings.width):
            settings.width = auto

        # 这几个是各模式分支各自算出来的排版尺寸。绘制分支与 settings.mode 可能瞬间不一致
        # （模式刚改、还没重算就来了一次重绘），缺任何一个都会让 paintEvent 抛 AttributeError，
        # 所以这里先无条件给安全初值，再由下面的分支覆盖。
        self._list_slot = 0.0
        self._list_count = 0
        self._main_h = 0.0
        self._disc_size = 44.0
        self._wave_h = 18.0
        self._album_title_h = 0.0
        self._album_artist_h = 0.0
        self._album_bar_h = 6.0
        self._album_label_h = 0.0
        self._album_text_h = 0.0

        self._overscan = 0
        self._overscan_v = 0
        mode = self._effective_mode()
        # 窗口宽 = 内容宽 + 左右 PAD + 左右 MARGIN / 倾斜余量。
        # 歌词 / 立体卡片用 settings.width（歌词实际能画多宽），
        # 唱片面板用 settings.player_width（0 = 按封面自动算）。
        window_w = float(settings.width)
        if mode == "depth3d":
            fm_list = self._metrics["list"]
            self._list_slot = fm_list.height() * 1.52 * settings.line_spacing
            self._list_count = max(1, int(settings.lyric_lines))
            list_h = self._list_slot * self._list_count
            album_h = float(settings.cover_size) * 1.4143
            content_h = PAD * 2 + max(list_h, album_h)
            self._overscan, self._overscan_v = self._tilt_overscan(
                float(settings.width), list_h
            )
        elif mode == "album":
            fm_title = self._metrics["title"]
            fm_artist = self._metrics["artist"]
            fm_time = self._metrics["time"]
            # 唱片按封面尺寸放大，但别放太猛 —— 分离面板里默认就小巧一点
            # （上限放到 420，不然封面滑到 185 以上就看不出一丁点变化了）
            self._disc_size = max(44.0, min(420.0, float(settings.cover_size) * 1.30))
            self._wave_h = max(18.0, fm_title.height() * 1.5 * settings.line_spacing)
            self._album_title_h = fm_title.height()
            self._album_artist_h = fm_artist.height()
            self._album_bar_h = 6.0
            self._album_label_h = fm_time.height()
            text_h = (
                self._album_title_h
                + self._album_title_h * 0.18
                + self._album_artist_h
                + self._album_title_h * 0.40
                + self._wave_h
                + self._album_title_h * 0.42
                + self._album_bar_h
                + 8
                + self._album_label_h
            )
            self._album_text_h = text_h
            art_h = self._disc_size if settings.show_cover else 0.0
            content_h = PAD * 2 + max(art_h, text_h)
            if settings.player_width >= PLAYER_WIDTH_MIN:
                window_w = float(settings.player_width)
            else:
                # 自动：按封面 + 文字需要的宽度（保持原来的观感）
                window_w = float(max(280, int(self._disc_size) + 220))
        elif mode == "lyrics":
            fm_list = self._metrics["list"]
            self._list_slot = fm_list.height() * 1.52 * settings.line_spacing
            self._list_count = max(1, int(settings.lyric_lines))
            # 顶部还要给歌名 / 作者 / 热度留一块地方（分离面板不加）
            want_info = self._want_song_info()
            self._head_h = self._metrics["head"].height() if want_info else 0.0
            self._head_sub_h = (
                self._metrics["head_sub"].height() if want_info else 0.0
            )
            self._head_gap = 20.0 if want_info else 0.0
            self._head_block = (
                self._head_h + 6.0 + self._head_sub_h + self._head_gap
                if want_info
                else 0.0
            )
            content_h = (
                PAD * 2 + self._list_slot * self._list_count + self._head_block
            )
            self._overscan, self._overscan_v = self._tilt_overscan(
                float(settings.width),
                self._list_slot * self._list_count + self._head_block,
            )
        elif mode == "player":
            # 遗留的 player 模式（已不在菜单里），按播放器卡片算尺寸
            fm_title = self._metrics["title"]
            fm_artist = self._metrics["artist"]
            fm_time = self._metrics["time"]

            text_h = fm_title.height() * 1.24 + fm_artist.height()
            text_h += fm_title.height() * 0.55 + fm_lyric.height()
            if settings.show_next:
                text_h += fm_next.height() * NEXT_GAP * settings.line_spacing + fm_next.height()

            cover_h = settings.cover_size if settings.show_cover else 0
            self._main_h = max(text_h, float(cover_h))
            content_h = PAD * 2 + self._main_h
            if settings.show_progress:
                content_h += 14.0 + 10.0 + 7.0 + fm_time.height()
        else:
            # 兜底：按歌词面板的尺寸
            fm_list = self._metrics["list"]
            self._list_slot = fm_list.height() * 1.52 * settings.line_spacing
            self._list_count = max(1, int(settings.lyric_lines))
            content_h = PAD * 2 + self._list_slot * self._list_count
            self._overscan, self._overscan_v = self._tilt_overscan(
                float(settings.width), self._list_slot * self._list_count
            )

        self.resize(
            int(window_w) + PAD * 2 + (MARGIN + self._overscan) * 2,
            int(content_h) + (MARGIN + self._overscan_v) * 2,
        )
        self._bg_key = None
        self._cover_cache.clear()

        if initial:
            self._apply_initial_position()

    # ------------------------------------------------------------------

    def _tilt_overscan(self, list_w: float, list_h: float) -> tuple[int, int]:
        """按当前的倾斜 / 旋转算出要留的透明余量（x, y）。

        `_list_transform()` 用的是真透视投影（虚拟相机 + 透视除法），
        「近边放大」的幅度不再是 1 + 0.45×depth 那种线性公式，
        所以这里干脆按同一套公式把 8 个点（四角 + 四边中点）投影出来，
        取旋转后的包围盒，多出来的那圈就是必须留的余量。
        """
        # 和 _list_transform() 用同一块「文字宽度」来算，透视平面才是同一张
        width = self._lyric_text_width(max(60.0, float(list_w)))
        height = max(40.0, float(list_h))
        theta_h = math.radians(depth_angle(self.settings.text_depth_h))
        theta_v = math.radians(depth_angle(self.settings.text_depth_v))
        projected = _project_points(
            (
                (-1, -1), (1, -1), (1, 1), (-1, 1),
                (0, -1), (0, 1), (-1, 0), (1, 0),
            ),
            width,
            height,
            theta_h,
            theta_v,
        )
        angle = math.radians(min(90.0, abs(float(self.settings.text_tilt))))
        cos_a = abs(math.cos(angle))
        sin_a = abs(math.sin(angle))
        bound_x = max(abs(px) * cos_a + abs(py) * sin_a for px, py in projected)
        bound_y = max(abs(px) * sin_a + abs(py) * cos_a for px, py in projected)
        extra_x = max(0.0, bound_x - width / 2.0)
        extra_y = max(0.0, bound_y - height / 2.0)
        # 上限只是防止极端组合把窗口撑到几千像素
        return (int(min(560.0, extra_x)), int(min(360.0, extra_y)))

    def _auto_width(self) -> int:
        """按当前歌词里最长的一行算窗口宽度（歌词可用宽度口径）。

        用整首歌的最长行（而不是当前句），换句时窗口不会一跳一跳。
        没有歌词 / 唱片模式 → 沿用 settings.width。
        """
        mode = self._effective_mode()
        if mode == "album":
            return int(self.settings.width)
        lyrics = getattr(self.engine, "lyrics", None)
        if lyrics is None or not getattr(lyrics, "lines", None):
            return int(self.settings.width)

        key = (
            id(lyrics),
            round(float(self.settings.letter_spacing), 2),
            int(self.settings.font_size),
            self.settings.font_family,
            mode,
            int(self.settings.cover_size),
        )
        cached = getattr(self, "_auto_width_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]

        # 当前句用的是 list_cur（最大号），按它量最长行最保险：
        # 这样任何一行变成"当前句"时都不会被 fit_size 缩小
        family, size, weight = self._fonts["list_cur"]
        widest = 0.0
        for line in lyrics.lines:
            if line.text:
                widest = max(widest, render_mod.measure(line.text, family, size, weight))
        if widest <= 0:
            return int(self.settings.width)

        extra = 0.0
        if mode == "depth3d":
            # 立体卡片左边还有封面块
            extra = float(self.settings.cover_size) * 1.4143 + TEXT_GAP
        value = int(widest + extra + 48)

        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            room = screen.availableGeometry().width() - 2 * (MARGIN + PAD)
            value = min(value, max(WIDTH_MIN, room))
        value = max(WIDTH_MIN, min(WIDTH_MAX, value))
        self._auto_width_cache = (key, value)
        return value

    def _effective_mode(self) -> str:
        """面板角色优先于全局界面模式。"""
        if self.role == "player":
            return "album"
        if self.role == "lyrics":
            return "lyrics"
        return self.settings.mode

    def _apply_initial_position(self) -> None:
        settings = self.settings
        screen = self.screen() or QApplication.primaryScreen()
        area = screen.availableGeometry()

        if self.role == "player":
            slot = settings.player_pos
            if slot[0] < 0:
                # 默认落在桌面右上角
                self.move(area.right() - self.width() - 60, area.top() + 60)
                self._remember_position()
            else:
                self.move(int(slot[0]), int(slot[1]))
            return

        if self.role == "lyrics":
            slot = settings.lyrics_pos
            if slot[0] < 0:
                # 默认紧贴在唱片面板下方（app.py 会把唱片面板底边的 y 传进来）
                y = (
                    int(self._anchor_y)
                    if self._anchor_y is not None
                    else area.top() + 60 + self.height() + 24
                )
                self.move(
                    area.right() - self.width() - 60,
                    y,
                )
                self._remember_position()
            else:
                self.move(int(slot[0]), int(slot[1]))
            return

        if settings.x < 0:
            self._default_position()
        else:
            self.move(settings.x, settings.y)

    def _default_position(self) -> None:
        """新装用户的默认落位：屏幕右上偏中（1707 宽的屏上大约 x≈915、y=25）。

        用比例算而不是写死坐标，换分辨率 / 缩放也不会跑到屏幕外。
        """
        screen = self.screen() or QApplication.primaryScreen()
        area = screen.availableGeometry()
        self.move(
            area.x() + int(area.width() * 0.81) - self.width(),
            area.y() + 25,
        )
        self._remember_position()

    def keep_on_screen(self) -> None:
        """把窗口拉回可见区域。

        · 窗口放得下：跟以前完全一样，左上角夹在「可用区 ± 一点余量」里
          （留那点余量是为了拖到屏幕边上时不粘手）；
        · 窗口比屏幕还大（宽 2560 + 200 号字 + 15 行 + 满倾斜能到 3728×3703）：
          没地方放，就把左上角对齐到可用区左上角，允许右/下越界。
          旧版这里是按同一个公式夹的，结果窗口会「贴着右下」跑出去 ——
          左边缘被推到屏幕外几十像素，看起来像整扇窗口跑没影了。
        """
        screen = self.screen() or QApplication.primaryScreen()
        area = screen.availableGeometry()
        width, height = self.width(), self.height()
        if width > area.width():
            x = area.x()
        else:
            x = min(
                max(self.x(), area.x() - 40),
                area.x() + area.width() - width + 40,
            )
        if height > area.height():
            y = area.y()
        else:
            y = min(
                max(self.y(), area.y() - 10),
                area.y() + area.height() - height + 10,
            )
        if (x, y) != (self.x(), self.y()):
            self.move(x, y)
            self._remember_position()

    def _remember_position(self) -> None:
        if self.role == "player":
            self.settings.player_pos = [self.x(), self.y()]
        elif self.role == "lyrics":
            self.settings.lyrics_pos = [self.x(), self.y()]
        else:
            self.settings.x = self.x()
            self.settings.y = self.y()

    # ==================================================================
    # 刷新
    # ==================================================================

    def _tick(self) -> None:
        now = time.monotonic()
        delta = min(0.25, max(0.0, now - self._last_tick))
        self._last_tick = now
        self._check_hotkey()
        # 换歌 / 换歌词 → 按"最长一行"重算自动宽度（不是每句都跳）
        lyrics = self.engine.lyrics
        if lyrics is not self._auto_lyrics_ref:
            self._auto_lyrics_ref = lyrics
            self._apply_new_width(QRect(self.geometry()), self.settings.lyric_align)
        snapshot = self.engine.snapshot()
        playing = bool(snapshot and snapshot.is_playing)
        if playing:
            # 唱片转速：约 26°/秒，看起来像在转但不晕
            self._spin_angle = (self._spin_angle + delta * 26.0) % 360.0
        animating = (time.monotonic() - self._anim_t0) < (ANIM_DURATION + 0.25)
        interval = 16 if (playing or animating) else 180
        if self._timer.interval() != interval:
            self._timer.setInterval(interval)
        self.update()

    # ==================================================================
    # 背景
    # ==================================================================

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        # 整体透明度：下面的绘制都用相乘方式，所以这里设一次就能影响全部
        painter.setOpacity(max(0.05, min(1.0, float(self.settings.ui_opacity))))

        # 立体卡片 / 唱片 / 纯歌词面板都不要背景板，直接浮在壁纸上
        if self.settings.background and self._effective_mode() not in _NO_BOARD_MODES:
            painter.drawPixmap(0, 0, self._background())

        over_x = self._overscan
        over_y = self._overscan_v
        card = QRectF(
            MARGIN + over_x,
            MARGIN + over_y,
            self.width() - (MARGIN + over_x) * 2,
            self.height() - (MARGIN + over_y) * 2,
        )
        snapshot = self.engine.snapshot()
        lyrics = self.engine.lyrics

        if lyrics is not self._lyrics_ref:
            self._lyrics_ref = lyrics
            self._display_idx = -1
            self._anim_t0 = time.monotonic()
            self._scroll_ready = False
            albummid = getattr(lyrics, "albummid", "") if lyrics is not None else ""
            if albummid and albummid not in self._covers:
                self._cover_loader.request(albummid)

        mode = self._effective_mode()
        if mode == "depth3d":
            self._paint_depth3d(painter, card, snapshot, lyrics)
        elif mode == "album":
            self._paint_album(painter, card, snapshot, lyrics)
        elif mode == "lyrics":
            self._paint_lyrics_panel(painter, card, snapshot, lyrics)
        elif mode == "player":
            self._paint_player(painter, card, snapshot, lyrics)
        else:
            self._paint_compact(painter, card, snapshot, lyrics)
        painter.end()

    def _background(self) -> QPixmap:
        ratio = self.devicePixelRatioF()
        key = (
            self.width(),
            self.height(),
            round(ratio, 2),
            self.settings.theme,
            round(self.settings.opacity, 2),
        )
        if self._bg_key == key and self._bg_pixmap is not None:
            return self._bg_pixmap

        pixmap = QPixmap(int(self.width() * ratio), int(self.height() * ratio))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        card = QRectF(
            MARGIN,
            MARGIN,
            self.width() - MARGIN * 2,
            self.height() - MARGIN * 2,
        )
        radius = min(28.0, card.height() * 0.24)
        alpha = self.settings.opacity

        for step in range(14, 0, -1):
            shade = int(9 * (1.0 - step / 14.0) ** 1.4) + 1
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, shade))
            grow = step * 0.55
            painter.drawRoundedRect(
                card.adjusted(-grow, -grow * 0.5, grow, grow * 1.1),
                radius + grow * 0.5,
                radius + grow * 0.5,
            )

        body = QLinearGradient(card.topLeft(), card.bottomLeft())
        body.setColorAt(0.0, QColor(21, 24, 35, int(230 * alpha)))
        body.setColorAt(0.55, QColor(13, 15, 24, int(216 * alpha)))
        body.setColorAt(1.0, QColor(9, 11, 18, int(226 * alpha)))
        painter.setBrush(body)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(card, radius, radius)

        accent = QColor(THEMES[self.settings.theme]["glow"])
        sheen = QLinearGradient(card.topLeft(), card.topRight())
        sheen.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), 0))
        sheen.setColorAt(
            0.5, QColor(accent.red(), accent.green(), accent.blue(), int(48 * alpha))
        )
        sheen.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 0))
        painter.setBrush(sheen)
        painter.drawRoundedRect(
            QRectF(
                card.left() + radius * 0.6,
                card.top() + 1.0,
                card.width() - radius * 1.2,
                1.4,
            ),
            0.7,
            0.7,
        )

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QColor(255, 255, 255, int(28 * alpha)))
        painter.drawRoundedRect(card.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        painter.end()

        self._bg_key = key
        self._bg_pixmap = pixmap
        return pixmap

    # ==================================================================
    # 立体卡片模式
    # ==================================================================

    def _paint_depth3d(self, painter, card, snapshot, lyrics) -> None:
        settings = self.settings
        colors = settings.colors
        now = time.monotonic()

        cover = float(settings.cover_size)
        style = getattr(settings, "depth_album_style", "classic")
        if style == "vinyl":
            block = cover * 1.46
        elif style == "cover_vinyl":
            block = cover * 1.64
        else:
            block = cover * 1.41421

        center_x = card.left() + PAD + block / 2.0
        center_y = card.center().y()

        albummid = getattr(lyrics, "albummid", "") if lyrics is not None else ""
        self._draw_album_3d(
            painter, center_x, center_y, cover, block, colors, albummid, snapshot, now
        )

        text_left = card.left() + PAD + block + TEXT_GAP
        self._draw_lyric_list(
            painter, text_left, card.right() - PAD, center_y, snapshot, lyrics, colors, now
        )

    def _draw_album_3d(
        self, painter, cx, cy, cover, block, colors, albummid, snapshot, now
    ) -> None:
        """立体卡片左侧的封面区，样式可在右键菜单里切换。"""
        style = getattr(self.settings, "depth_album_style", "classic")

        if style == "vinyl":
            radius = block / 2.0
            box = QRectF(cx - radius, cy - radius, block, block)
            art = self._cover_for(albummid, int(radius * 1.24))
            self._draw_vinyl(painter, box, art, snapshot, colors)
            self._draw_tonearm(painter, box, colors)
            return

        if style == "cover_vinyl":
            side = block / self.SQUARE_BLOCK_RATIO
            art = self._cover_for(albummid, int(side))
            self._draw_album_square(
                painter, cx - block / 2.0, cy, side, art, snapshot, colors
            )
            return

        self._draw_depth_classic(painter, cx, cy, cover, colors, albummid)

    def _draw_tonearm(self, painter, box, colors) -> None:
        """黑胶唱臂：从唱片右上方伸下来，唱针落在唱片上。"""
        radius = box.width() / 2.0
        cx, cy = box.center().x(), box.center().y()

        pivot = QPointF(cx + radius * 0.72, cy - radius * 1.02)
        elbow = QPointF(cx + radius * 0.92, cy - radius * 0.52)
        head = QPointF(cx + radius * 0.46, cy - radius * 0.06)

        arm = QPainterPath()
        arm.moveTo(pivot)
        arm.quadTo(elbow, head)

        painter.save()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        pen = QPen(QColor(198, 206, 220, 235))
        pen.setWidthF(max(2.0, radius * 0.045))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawPath(arm)

        pen.setColor(QColor(90, 98, 112, 200))
        pen.setWidthF(max(1.0, radius * 0.014))
        painter.setPen(pen)
        painter.drawPath(arm)

        # 唱头
        head_w = max(7.0, radius * 0.30)
        head_h = max(5.0, radius * 0.16)
        painter.translate(head)
        painter.rotate(28.0)
        head_grad = QLinearGradient(0, -head_h / 2, 0, head_h / 2)
        head_grad.setColorAt(0.0, QColor(226, 231, 240))
        head_grad.setColorAt(1.0, QColor(120, 128, 142))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(head_grad)
        painter.drawRoundedRect(
            QRectF(-head_w / 2.0, -head_h / 2.0, head_w, head_h),
            head_h / 2.0,
            head_h / 2.0,
        )
        painter.setBrush(QColor(70, 76, 88))
        painter.drawRoundedRect(
            QRectF(-head_w * 0.12, head_h * 0.42, head_w * 0.24, head_h * 0.55),
            head_w * 0.08,
            head_w * 0.08,
        )
        painter.restore()

        # 转轴底座
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        base_r = max(5.0, radius * 0.20)
        painter.setBrush(QColor(0, 0, 0, 70))
        painter.drawEllipse(
            QRectF(pivot.x() - base_r, pivot.y() - base_r + 2.0, base_r * 2, base_r * 2)
        )
        base_grad = QRadialGradient(pivot, base_r)
        base_grad.setColorAt(0.0, QColor(214, 220, 230))
        base_grad.setColorAt(1.0, QColor(96, 104, 118))
        painter.setBrush(base_grad)
        painter.drawEllipse(
            QRectF(pivot.x() - base_r, pivot.y() - base_r, base_r * 2, base_r * 2)
        )
        painter.setBrush(QColor(58, 63, 74))
        inner = base_r * 0.42
        painter.drawEllipse(
            QRectF(pivot.x() - inner, pivot.y() - inner, inner * 2, inner * 2)
        )
        painter.restore()

    def _draw_depth_classic(self, painter, cx, cy, cover, colors, albummid) -> None:
        """经典样式：正面方块 + 后方旋转 45° 的淡化方块（只露四个小三角）。"""
        reach = cover * 0.70711
        half = cover / 2.0
        base = half * 0.41421

        triangles = [
            [(cx - base, cy - half), (cx + base, cy - half), (cx, cy - reach)],
            [(cx + half, cy - base), (cx + half, cy + base), (cx + reach, cy)],
            [(cx - base, cy + half), (cx + base, cy + half), (cx, cy + reach)],
            [(cx - half, cy - base), (cx - half, cy + base), (cx - reach, cy)],
        ]

        style = self.settings.raise_style
        accent = QColor(colors["glow"])
        ambient = self._cover_color(albummid) or accent
        ko = max(0.0, min(1.5, float(self.settings.raise_opacity)))

        def scaled(color: QColor) -> QColor:
            return QColor(
                color.red(), color.green(), color.blue(),
                int(max(0, min(255, color.alpha() * ko))),
            )

        for points in triangles:
            path = QPainterPath()
            path.moveTo(*points[0])
            path.lineTo(*points[1])
            path.lineTo(*points[2])
            path.closeSubpath()

            painter.save()
            painter.setClipPath(path)
            if style == "outline":
                painter.fillPath(path, scaled(QColor(255, 255, 255, 12)))
            elif style == "ambient":
                glow = QRadialGradient(cx, cy, max(1.0, reach))
                glow.setColorAt(0.0, QColor(ambient.red(), ambient.green(), ambient.blue(), 0))
                glow.setColorAt(0.70, scaled(QColor(ambient.red(), ambient.green(), ambient.blue(), 12)))
                glow.setColorAt(0.90, scaled(QColor(ambient.red(), ambient.green(), ambient.blue(), 78)))
                glow.setColorAt(1.0, scaled(QColor(ambient.red(), ambient.green(), ambient.blue(), 140)))
                painter.fillPath(path, glow)
                painter.fillPath(path, scaled(QColor(255, 255, 255, 20)))
            else:
                frosted = QRadialGradient(cx, cy, max(1.0, reach))
                frosted.setColorAt(0.0, scaled(QColor(255, 255, 255, 0)))
                frosted.setColorAt(0.68, scaled(QColor(255, 255, 255, 4)))
                frosted.setColorAt(0.80, scaled(QColor(255, 255, 255, 24)))
                frosted.setColorAt(0.92, scaled(QColor(255, 255, 255, 64)))
                frosted.setColorAt(1.0, scaled(QColor(255, 255, 255, 108)))
                painter.fillPath(path, frosted)
                tint = QLinearGradient(cx, cy - reach, cx, cy + reach)
                tint.setColorAt(0.0, scaled(QColor(accent.red(), accent.green(), accent.blue(), 30)))
                tint.setColorAt(0.5, scaled(QColor(accent.red(), accent.green(), accent.blue(), 6)))
                tint.setColorAt(1.0, scaled(QColor(accent.red(), accent.green(), accent.blue(), 30)))
                painter.fillPath(path, tint)
            painter.restore()

            pen = painter.pen()
            pen.setColor(scaled(QColor(255, 255, 255, 110 if style == "outline" else 78)))
            pen.setWidthF(1.2)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(pen)
            painter.drawPath(path)

            # 贴着方块的那条边压暗，做出「抬高一层」的台阶感
            pen.setColor(QColor(0, 0, 0, 78))
            pen.setWidthF(2.6)
            painter.setPen(pen)
            painter.drawLine(QPointF(points[0][0], points[0][1]), QPointF(points[1][0], points[1][1]))

        diamond = QPainterPath()
        diamond.moveTo(cx, cy - reach)
        diamond.lineTo(cx + reach, cy)
        diamond.lineTo(cx, cy + reach)
        diamond.lineTo(cx - reach, cy)
        diamond.closeSubpath()
        pen = painter.pen()
        pen.setColor(QColor(255, 255, 255, 40))
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.drawPath(diamond)

        square = QRectF(cx - half, cy - half, cover, cover)
        radius = cover * 0.055

        painter.setPen(Qt.PenStyle.NoPen)
        for step in range(7, 0, -1):
            painter.setBrush(QColor(0, 0, 0, 9))
            grow = step * 0.9
            painter.drawRoundedRect(
                square.adjusted(-grow, -grow * 0.4, grow, grow * 1.3),
                radius + grow * 0.7,
                radius + grow * 0.7,
            )

        clip = QPainterPath()
        clip.addRoundedRect(square, radius, radius)
        scaled = self._cover_for(albummid, int(cover))

        painter.save()
        painter.setClipPath(clip)
        if scaled is not None:
            ratio = scaled.devicePixelRatio()
            painter.drawPixmap(
                int(square.center().x() - scaled.width() / (2 * ratio)),
                int(square.center().y() - scaled.height() / (2 * ratio)),
                scaled,
            )
        else:
            gradient = QLinearGradient(square.topLeft(), square.bottomRight())
            gradient.setColorAt(0.0, QColor(colors["c1"]))
            gradient.setColorAt(0.5, QColor(colors["c2"]))
            gradient.setColorAt(1.0, QColor(colors["c3"]))
            painter.fillPath(clip, gradient)
            glyph = make_sprite(
                "\u266a", self._icon_family, int(cover * 0.42), WEIGHT_MEDIUM
            )
            draw_sprite(
                painter, glyph, square.center().x(),
                square.center().y() + glyph.ascent / 2.0 - glyph.descent / 2.0,
                QColor(11, 16, 32), opacity=0.72, shadow=False,
            )
        painter.restore()

        painter.setBrush(Qt.BrushStyle.NoBrush)
        pen = painter.pen()
        pen.setColor(QColor(255, 255, 255, 110))
        pen.setWidthF(1.2)
        painter.setPen(pen)
        painter.drawRoundedRect(square, radius, radius)

        sheen = QLinearGradient(square.topLeft(), square.center())
        sheen.setColorAt(0.0, QColor(255, 255, 255, 70))
        sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(sheen)
        painter.drawRoundedRect(
            QRectF(square.left(), square.top(), square.width(), square.height() * 0.42),
            radius,
            radius,
        )

    def _visual_index_at(self, now: float) -> float:
        span = 0.42
        t = (now - self._scroll_t0) / span
        t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
        return self._scroll_from + (self._scroll_target - self._scroll_from) * ease_out_cubic(t)

    def _visual_index(self, now: float) -> float:
        target = float(self._display_idx)
        if not self._scroll_ready:
            self._scroll_ready = True
            self._scroll_from = target
            self._scroll_target = target
            self._scroll_t0 = now
            return target
        if target != self._scroll_target:
            self._scroll_from = self._visual_index_at(now)
            self._scroll_target = target
            self._scroll_t0 = now
        return self._visual_index_at(now)

    def _draw_lyric_list(
        self,
        painter,
        left,
        right,
        center_y,
        snapshot,
        lyrics,
        colors,
        now,
        transform=None,
        header=None,
    ) -> None:
        width = max(60.0, right - left)
        fm = self._metrics["list"]
        slot = self._list_slot
        count = self._list_count

        painter.save()
        if transform is None:
            transform = self._list_transform(left, right, center_y)
        if transform is not None:
            painter.setTransform(transform, True)

        def placeholder(message: str, opacity: float) -> None:
            family, size, weight = self._fonts["list"]
            fitted = fit_size(message, family, weight, size, width)
            sprite = make_sprite(message, family, fitted, weight)
            baseline = center_y + (sprite.ascent - sprite.descent) / 2.0
            draw_sprite(
                painter,
                sprite,
                self._align_center_x(left, right, sprite.advance),
                baseline,
                QColor(colors["dim"]), opacity=opacity,
                outline_width=max(2.0, fitted * 0.05),
                outline_color=QColor(0, 0, 0, 120),
            )

        try:
            if header is not None:
                # 头部和歌词在同一个倾斜平面里，倾斜 / 旋转效果完全一致
                header(painter, center_y - slot * count / 2.0)
            self._draw_list_body(
                painter, left, right, center_y, snapshot, lyrics, colors, now,
                width, fm, slot, count, placeholder,
            )
        finally:
            painter.restore()

    def _lyric_text_width(self, band: float) -> float:
        """当前歌词里最长一行的像素宽（用于决定透视平面的宽度）。

        透视的强弱跟「文字这块有多宽」走，而不是跟窗口有多宽走 ——
        否则同一个窗口拉到 1440 之后，同样一句歌词的变形会明显变轻。
        """
        fm = self._metrics.get("list")
        fm_cur = self._metrics.get("list_cur") or fm
        lyrics = getattr(self.engine, "lyrics", None)
        if fm is None or lyrics is None or not getattr(lyrics, "lines", None):
            return band
        key = (
            id(lyrics),
            len(lyrics.lines),
            round(fm.height(), 2),
            round(fm_cur.height(), 2),
            round(band, 1),
            round(float(self.settings.line_spacing), 3),
        )
        cached = getattr(self, "_text_w_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        widest = 0.0
        for line in lyrics.lines:
            if line.text:
                widest = max(
                    widest,
                    fm.horizontalAdvance(line.text),
                    fm_cur.horizontalAdvance(line.text),
                )
        value = max(60.0, min(band, widest))
        self._text_w_cache = (key, value)
        return value

    def _list_transform(self, left, right, center_y):
        """把歌词文字放在一个向内倾斜的平面上（上下 / 左右可同时生效）。"""
        tilt = float(self.settings.text_tilt)
        depth_v = float(self.settings.text_depth_v)
        depth_h = float(self.settings.text_depth_h)
        if self._effective_mode() == "depth3d":
            # 立体卡片只用正的景深（原来的方向就够用了），
            # 反向倾斜只对纯歌词 / 分离面板的歌词生效
            depth_v = abs(depth_v)
            depth_h = abs(depth_h)
        if abs(tilt) < 0.01 and abs(depth_v) < 0.001 and abs(depth_h) < 0.001:
            return None

        band = max(60.0, right - left)
        width = self._lyric_text_width(band)
        height = max(40.0, self._list_slot * self._list_count)
        # 按「歌词排版」决定这块文字贴在哪边：透视只作用在文字自己身上
        align = self.settings.lyric_align
        if align == "left":
            x0 = left
        elif align == "center":
            x0 = (left + right - width) / 2.0
        else:
            x0 = right - width
        x1 = x0 + width
        cx = (x0 + x1) / 2.0
        cy = center_y

        src = QPolygonF(
            [
                QPointF(x0, cy - height / 2.0),
                QPointF(x1, cy - height / 2.0),
                QPointF(x1, cy + height / 2.0),
                QPointF(x0, cy + height / 2.0),
            ]
        )

        # 真·透视：平面绕中心转两个轴，再用「虚拟相机 + 透视除法」投影。
        # 旧的「近边 ×(1+0.45d)、远边 ×(1−d)」是线性缩放，调大就会把字撑大，
        # 而且整块窗口一起缩，窗口越宽越夸张；这里换成真正的 3D 透视。
        theta_v = math.radians(depth_angle(depth_v))
        theta_h = math.radians(depth_angle(depth_h))
        corners = _project_points(
            ((-1, -1), (1, -1), (1, 1), (-1, 1)), width, height, theta_h, theta_v
        )
        angle = math.radians(tilt)
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        dst = QPolygonF()
        for dx, dy in corners:
            dst.append(
                QPointF(cx + dx * cos_a - dy * sin_a, cy + dx * sin_a + dy * cos_a)
            )

        return quad_transform(
            [(p.x(), p.y()) for p in src], [(p.x(), p.y()) for p in dst]
        )

    def _draw_list_body(
        self, painter, left, right, center_y, snapshot, lyrics, colors, now,
        width, fm, slot, count, placeholder,
    ) -> None:
        if snapshot is None:
            self._draw_no_player_hint(painter, left, right, center_y, colors)
            return
        if lyrics is None:
            placeholder("♪ 正在获取歌词…", 0.65)
            return
        if not lyrics.lines:
            placeholder("♪ 暂无歌词", 0.65)
            return

        anim, index, current, _next = self._resolve_lyrics(snapshot, lyrics, now)
        if index < 0 or current is None:
            # 还没到第一句歌词 = 还在前奏里。
            # 前奏通常有十几秒，干等着像卡住了，干脆把还要等多久写出来。
            position = snapshot.position + self._offset_ms() / 1000.0
            remaining = (lyrics.lines[0].time - position) if lyrics.lines else 0.0
            if remaining > 1.5:
                placeholder(f"♪ 前奏 · {remaining:.0f} 秒后开始", 0.5)
            else:
                placeholder("♪ 前奏…", 0.55)
            return

        visual = self._visual_index(now)
        first = index - count // 2

        for step in range(count):
            line_index = first + step
            if line_index < 0 or line_index >= len(lyrics.lines):
                continue
            line = lyrics.lines[line_index]
            if not line.text:
                continue
            y = center_y + (line_index - visual) * slot

            if line_index == index:
                family, size, weight = self._fonts["list_cur"]
                fitted = fit_size(line.text, family, weight, size, width)
                sprite = make_sprite(line.text, family, fitted, weight)
                baseline = (
                    y - slot / 2.0
                    + (slot - (sprite.ascent + sprite.descent)) / 2.0
                    + sprite.ascent
                )
                pop = ease_out_back(anim, 1.6)
                scale = 0.94 + 0.06 * pop
                draw_karaoke(
                    painter,
                    sprite,
                    self._align_center_x(left, right, sprite.advance * scale),
                    baseline,
                    QColor(255, 255, 255, 120),
                    (colors["c1"], colors["c2"], colors["c3"]),
                    self._lyric_progress(snapshot, line),
                    QColor(colors["glow"]),
                    scale=scale,
                    opacity=0.6 + 0.4 * ease_out_cubic(min(1.0, anim * 1.6)),
                    outline_width=max(2.0, fitted * 0.05),
                    outline_color=QColor(0, 0, 0, 150),
                )
            else:
                distance = abs(line_index - index)
                opacity = max(0.10, 0.50 - 0.14 * distance)
                fade = min(1.0, max(0.0, (y - (center_y - slot * (count / 2.0 + 1))) / slot))
                self._draw_elided(
                    painter, line.text, left, width, y - fm.height() / 2.0,
                    fm, self._fonts["list"], QColor(colors["base"]),
                    opacity * (0.35 + 0.65 * fade),
                    alignment=self.settings.lyric_align,
                )

    def _align_center_x(self, left, right, advance: float) -> float:
        """按「歌词排版」设置算出这一行文字的中心横坐标。"""
        alignment = self.settings.lyric_align
        if alignment == "left":
            return left + advance / 2.0
        if alignment == "center":
            return (left + right) / 2.0
        return right - advance / 2.0

    # ==================================================================
    # 唱片 / 专辑模式
    # ==================================================================

    def _paint_album(self, painter, card, snapshot, lyrics) -> None:
        settings = self.settings
        colors = settings.colors
        now = time.monotonic()

        disc = self._disc_size
        left = card.left() + PAD
        right = card.right() - PAD
        cy = card.center().y()
        albummid = getattr(lyrics, "albummid", "") if lyrics is not None else ""

        # 「显示封面」关掉时，整块封面/唱片都不画，文字用满整行宽度
        block_w = 0.0
        if settings.show_cover:
            box = QRectF(left, cy - disc / 2.0, disc, disc)
            if settings.album_shape == "square":
                side = disc * 0.82
                block_w = side * self.SQUARE_BLOCK_RATIO
                art_size = int(side)
            else:
                block_w = disc
                art_size = int(disc * 0.62)

            cover = self._cover_for(albummid, art_size)
            if settings.album_shape == "square":
                self._draw_album_square(
                    painter, box.left(), cy, side, cover, snapshot, colors
                )
            else:
                self._draw_vinyl(painter, box, cover, snapshot, colors)

        text_left = left if block_w <= 0.0 else left + block_w + TEXT_GAP
        text_w = max(120.0, right - text_left)

        fm_title = self._metrics["title"]
        fm_artist = self._metrics["artist"]
        fm_time = self._metrics["time"]
        text_h = self._album_text_h
        y = cy - text_h / 2.0

        # ---- 控制按钮（在标题行右侧）----
        reserved = 0.0
        if settings.show_controls:
            size = max(24.0, float(settings.font_size) * 0.82)
            controls_w = self._controls_width(size)
            reserved = controls_w + 14
            self._draw_controls(
                painter, right - controls_w, y, size,
                snapshot, colors,
                row_height=self._album_title_h,
            )

        title_text = snapshot.track.title if snapshot and snapshot.track else "未在播放"
        self._draw_elided(
            painter, title_text, text_left, max(40.0, text_w - reserved), y,
            fm_title, self._fonts["title"], QColor(colors["base"]), 1.0,
        )
        y += self._album_title_h + self._album_title_h * 0.18

        if snapshot is not None and snapshot.track is not None:
            parts = [p for p in (snapshot.track.artist, snapshot.track.album) if p]
            artist_text = "  ·  ".join(parts) if parts else "未知艺术家"
        else:
            artist_text = "打开任意播放器播放歌曲即可显示"
        self._draw_elided(
            painter, artist_text, text_left, text_w, y,
            fm_artist,
            self._fonts["artist"],
            QColor(colors["base"]) if self._no_card else QColor(colors["dim"]),
            0.88 if self._no_card else 0.95,
        )
        y += self._album_artist_h + self._album_title_h * 0.40

        # ---- 音频跳动波形 ----
        wave_rect = QRectF(text_left, y, text_w, self._wave_h)
        self._draw_wave(painter, wave_rect, colors, snapshot, now)
        y += self._wave_h + self._album_title_h * 0.42

        # ---- 进度条 + 时间 ----
        if settings.show_progress:
            self._draw_album_progress(painter, text_left, right, y, snapshot, colors)

    def _draw_wave(self, painter, rect, colors, snapshot, now) -> None:
        count = max(14, int(rect.width() / 9.0))
        gap = 3.0
        bar_w = max(2.0, (rect.width() - gap * (count - 1)) / count)
        playing = bool(snapshot is not None and snapshot.is_playing)
        position = snapshot.position if snapshot is not None else 0.0
        base = position * 2.4 if playing else now * 0.6

        gradient = QLinearGradient(rect.left(), 0.0, rect.right(), 0.0)
        gradient.setColorAt(0.0, QColor(colors["c1"]))
        gradient.setColorAt(0.5, QColor(colors["c2"]))
        gradient.setColorAt(1.0, QColor(colors["c3"]))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)

        center_y = rect.center().y()
        for index in range(count):
            phase = base + index * 0.55
            value = (
                math.sin(phase * 1.7) * 0.5
                + math.sin(phase * 3.1 + 1.3) * 0.3
                + math.sin(phase * 0.7 + 2.1) * 0.2
            )
            level = 0.5 + 0.5 * value
            shape = 0.42 + 0.58 * math.sin(math.pi * (index + 0.5) / count)
            height = max(0.10, min(1.0, level * shape)) * rect.height()
            if not playing:
                height *= 0.32 + 0.10 * math.sin(now * 1.6 + index * 0.4)
            x = rect.left() + index * (bar_w + gap)
            painter.drawRoundedRect(
                QRectF(x, center_y - height / 2.0, bar_w, height),
                bar_w / 2.0,
                bar_w / 2.0,
            )

    def _draw_vinyl(self, painter, box, cover, snapshot, colors) -> None:
        radius = box.width() / 2.0
        if radius <= 1:
            return
        painter.save()
        painter.translate(box.center())
        painter.rotate(self._spin_angle)
        painter.setPen(Qt.PenStyle.NoPen)

        disc = QRectF(-radius, -radius, radius * 2.0, radius * 2.0)
        body = QRadialGradient(-radius * 0.3, -radius * 0.35, radius * 1.7)
        body.setColorAt(0.0, QColor(48, 51, 62))
        body.setColorAt(0.55, QColor(24, 26, 33))
        body.setColorAt(1.0, QColor(12, 13, 18))
        painter.setBrush(body)
        painter.drawEllipse(disc)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        for index in range(11):
            ring = radius * (0.63 + 0.033 * index)
            if ring >= radius - 0.5:
                break
            pen = QPen(QColor(255, 255, 255, 10 + (index % 3) * 7))
            pen.setWidthF(1.0)
            painter.setPen(pen)
            painter.drawEllipse(QRectF(-ring, -ring, ring * 2.0, ring * 2.0))

        art_radius = radius * 0.60
        if cover is not None and not cover.isNull():
            path = QPainterPath()
            path.addEllipse(QRectF(-art_radius, -art_radius, art_radius * 2.0, art_radius * 2.0))
            painter.setClipPath(path)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPixmap(int(-art_radius), int(-art_radius), cover)
            painter.setClipping(False)

        hole = max(2.2, radius * 0.055)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(10, 11, 15))
        painter.drawEllipse(QRectF(-hole, -hole, hole * 2.0, hole * 2.0))

        sheen = QLinearGradient(-radius, -radius, radius, radius)
        sheen.setColorAt(0.0, QColor(255, 255, 255, 34))
        sheen.setColorAt(0.42, QColor(255, 255, 255, 0))
        sheen.setColorAt(0.62, QColor(255, 255, 255, 0))
        sheen.setColorAt(1.0, QColor(255, 255, 255, 20))
        painter.setBrush(sheen)
        painter.drawEllipse(disc)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        if snapshot is not None and snapshot.is_playing:
            pulse = 0.5 + 0.5 * math.sin(time.monotonic() * 2.1)
            accent = QColor(colors["glow"])
            pen = QPen(QColor(accent.red(), accent.green(), accent.blue(), int(55 + 85 * pulse)))
            pen.setWidthF(1.4 + 0.8 * pulse)
        else:
            pen = QPen(QColor(255, 255, 255, 30))
            pen.setWidthF(1.2)
        painter.setPen(pen)
        painter.drawEllipse(disc.adjusted(0.5, 0.5, -0.5, -0.5))
        painter.restore()

    # 方形封面 + 唱片的整体比例：封面边长 side，总宽 = side * BLOCK_RATIO
    SQUARE_BLOCK_RATIO = 1.78

    def _draw_album_square(self, painter, left, cy, side, cover, snapshot, colors) -> None:
        cover_rect = QRectF(left, cy - side / 2.0, side, side)
        vinyl_d = side * 1.30
        vinyl_rect = QRectF(
            cover_rect.right() - vinyl_d * 0.40,
            cy - vinyl_d / 2.0,
            vinyl_d,
            vinyl_d,
        )
        self._draw_vinyl(painter, vinyl_rect, cover, snapshot, colors)

        radius = side * 0.08
        painter.setPen(Qt.PenStyle.NoPen)
        for step in range(6, 0, -1):
            painter.setBrush(QColor(0, 0, 0, 12))
            grow = step * 0.9
            painter.drawRoundedRect(
                cover_rect.adjusted(-grow, -grow * 0.4, grow, grow * 1.2),
                radius + grow * 0.7,
                radius + grow * 0.7,
            )

        clip = QPainterPath()
        clip.addRoundedRect(cover_rect, radius, radius)
        painter.save()
        painter.setClipPath(clip)
        if cover is not None and not cover.isNull():
            painter.drawPixmap(int(cover_rect.left()), int(cover_rect.top()), cover)
        else:
            gradient = QLinearGradient(cover_rect.topLeft(), cover_rect.bottomRight())
            gradient.setColorAt(0.0, QColor(colors["c1"]))
            gradient.setColorAt(1.0, QColor(colors["c3"]))
            painter.setBrush(gradient)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(cover_rect)
        painter.restore()

        painter.setBrush(Qt.BrushStyle.NoBrush)
        pen = QPen(QColor(255, 255, 255, 110))
        pen.setWidthF(1.2)
        painter.setPen(pen)
        painter.drawRoundedRect(cover_rect, radius, radius)

    def _draw_album_progress(self, painter, left, right, top, snapshot, colors) -> None:
        width = max(40.0, right - left)
        bar_h = self._album_bar_h
        fm_time = self._metrics["time"]

        painter.setPen(Qt.PenStyle.NoPen)
        if self._no_card:
            # 无背景板时：先描一圈暗边，再铺半透明亮槽，深浅壁纸都看得见
            painter.setBrush(QColor(0, 0, 0, 80))
            painter.drawRoundedRect(
                QRectF(left - 1.0, top - 1.0, width + 2.0, bar_h + 2.0),
                (bar_h + 2.0) / 2,
                (bar_h + 2.0) / 2,
            )
            painter.setBrush(QColor(255, 255, 255, 90))
        else:
            painter.setBrush(QColor(255, 255, 255, 40))
        painter.drawRoundedRect(QRectF(left, top, width, bar_h), bar_h / 2, bar_h / 2)

        duration = snapshot.track.duration if snapshot is not None and snapshot.track else 0.0
        position = snapshot.position if snapshot is not None else 0.0
        fraction = max(0.0, min(1.0, position / duration)) if duration > 0 else 0.0

        self._hit_bar = QRectF(left - 8, top - 12, width + 16, bar_h + 24)

        if fraction > 0.001:
            gradient = QLinearGradient(left, 0.0, right, 0.0)
            gradient.setColorAt(0.0, QColor(colors["c1"]))
            gradient.setColorAt(0.6, QColor(colors["c2"]))
            gradient.setColorAt(1.0, QColor(colors["c3"]))
            painter.setBrush(gradient)
            painter.drawRoundedRect(
                QRectF(left, top, width * fraction, bar_h), bar_h / 2, bar_h / 2
            )
            knob = bar_h * 0.95 if self._hover == "bar" else bar_h * 0.72
            knob_x = left + width * fraction
            painter.setBrush(QColor(colors["c3"]))
            painter.drawEllipse(
                QRectF(knob_x - knob, top + bar_h / 2 - knob, knob * 2, knob * 2)
            )

        label_top = top + bar_h + 8
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QColor(colors["dim"]))
        painter.setFont(_qt_font(*self._fonts["time"]))
        rect_left = QRectF(left, label_top, width / 2, fm_time.height())
        rect_right = QRectF(left + width / 2, label_top, width / 2, fm_time.height())
        flag_left = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        flag_right = int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if self._no_card:
            painter.setPen(QColor(0, 0, 0, 150))
            painter.drawText(rect_left.translated(0, 1.2), flag_left, _format_time(position))
            painter.drawText(rect_right.translated(0, 1.2), flag_right, _format_time(duration))
            painter.setPen(QColor(colors["base"]))
        else:
            painter.setPen(QColor(colors["dim"]))
        painter.drawText(rect_left, flag_left, _format_time(position))
        painter.drawText(rect_right, flag_right, _format_time(duration))

    # ==================================================================
    # 播放器模式
    # ==================================================================

    def _paint_player(self, painter, card, snapshot, lyrics) -> None:
        settings = self.settings
        colors = settings.colors
        now = time.monotonic()

        top = card.top() + PAD
        main_h = self._main_h
        text_left = card.left() + PAD
        text_right = card.right() - PAD

        if settings.show_cover:
            cover_size = min(float(settings.cover_size), main_h)
            cover = QRectF(
                card.left() + PAD,
                top + (main_h - cover_size) / 2.0,
                cover_size,
                cover_size,
            )
            albummid = getattr(lyrics, "albummid", "") if lyrics is not None else ""
            self._draw_cover(painter, cover, albummid, snapshot, now, colors)
            text_left = cover.right() + TEXT_GAP

        text_w = max(80.0, text_right - text_left)

        fm_title = self._metrics["title"]
        fm_artist = self._metrics["artist"]
        fm_lyric = self._metrics["lyric"]
        fm_next = self._metrics["next"]

        block_h = fm_title.height() * 1.24 + fm_artist.height()
        block_h += fm_title.height() * 0.55 + fm_lyric.height()
        if settings.show_next:
            block_h += fm_next.height() * NEXT_GAP * settings.line_spacing + fm_next.height()
        y = top + (main_h - block_h) / 2.0

        # 控制按钮（右对齐在标题行）
        reserved = 0.0
        if settings.show_controls:
            size = max(24.0, float(settings.font_size) * 0.82)
            controls_w = self._controls_width(size)
            reserved = controls_w + 12
            self._draw_controls(
                painter, text_right - controls_w, y, size, snapshot, colors
            )

        title_text = snapshot.track.title if snapshot and snapshot.track else "未在播放"
        self._draw_elided(
            painter, title_text, text_left, max(40.0, text_w - reserved), y,
            fm_title, self._fonts["title"], QColor(colors["base"]), 0.95,
        )
        y += fm_title.height() * 1.24

        if snapshot is not None and snapshot.track is not None:
            parts = [p for p in (snapshot.track.artist, snapshot.track.album) if p]
            artist_text = "  ·  ".join(parts) if parts else "未知艺术家"
        else:
            artist_text = "打开任意播放器播放歌曲即可显示歌词"
        self._draw_elided(
            painter, artist_text, text_left, text_w, y,
            fm_artist, self._fonts["artist"], QColor(colors["dim"]), 0.9,
        )
        y += fm_artist.height() + fm_title.height() * 0.55

        anim, index, current, next_line = self._resolve_lyrics(snapshot, lyrics, now)
        lyric_rect = QRectF(text_left, y, text_w, fm_lyric.height())

        if current is None:
            if snapshot is None:
                placeholder = "♪ 等待播放器播放…"
            elif lyrics is None or not lyrics.lines:
                placeholder = "♪ 正在获取歌词…"
            else:
                placeholder = "♪ 前奏…"
            self._draw_elided(
                painter, placeholder, text_left, text_w, y,
                fm_lyric, self._fonts["lyric"], QColor(colors["dim"]), 0.72,
            )
        elif current.text:
            family, size, weight = self._fonts["lyric"]
            fitted = fit_size(current.text, family, weight, size, text_w)
            sprite = make_sprite(current.text, family, fitted, weight)

            pop = ease_out_back(anim, 1.7)
            wobble = math.exp(-6.0 * anim) * math.sin(anim * 20.0) * 0.028
            scale = 0.92 + 0.08 * pop + wobble
            offset = (1.0 - ease_out_cubic(anim)) * fm_lyric.height() * 0.26
            baseline = (
                lyric_rect.top()
                + offset
                + (fm_lyric.height() - (sprite.ascent + sprite.descent)) / 2.0
                + sprite.ascent
            )
            draw_karaoke(
                painter,
                sprite,
                text_left + sprite.advance / 2.0,
                baseline,
                QColor(255, 255, 255, 104),
                (colors["c1"], colors["c2"], colors["c3"]),
                self._lyric_progress(snapshot, current),
                QColor(colors["glow"]),
                scale=scale,
                opacity=0.55 + 0.45 * ease_out_cubic(min(1.0, anim * 1.5)),
                outline_width=max(2.0, fitted * 0.05),
                outline_color=QColor(0, 0, 0, 145),
            )
        else:
            pulse = 0.5 + 0.5 * math.sin(now * 3.2)
            self._draw_elided(
                painter, "♪", text_left, text_w, y,
                fm_lyric, self._fonts["lyric"], QColor(colors["glow"]),
                0.30 + 0.35 * pulse,
            )
        y += fm_lyric.height()

        if settings.show_next:
            y += fm_next.height() * NEXT_GAP * settings.line_spacing
            rise = (1.0 - ease_out_cubic(anim)) * fm_next.height() * 0.35
            self._draw_elided(
                painter,
                next_line.text if next_line is not None and next_line.text else "",
                text_left, text_w, y - rise,
                fm_next, self._fonts["next"], QColor(colors["dim"]),
                0.38 + 0.24 * anim,
            )

        if settings.show_progress:
            self._draw_progress(painter, card, snapshot, colors)

    def _resolve_lyrics(self, snapshot, lyrics, now):
        if lyrics is None or not lyrics.lines or snapshot is None:
            return 1.0, -1, None, None
        if getattr(lyrics, "source", "") == "miss":
            return 1.0, -1, None, None

        position = snapshot.position + self._offset_ms() / 1000.0
        index = lyrics.index_at(position)
        if index != self._display_idx:
            self._display_idx = index
            self._anim_t0 = now
        anim = min(1.0, max(0.0, (now - self._anim_t0) / ANIM_DURATION))
        if index < 0:
            return anim, -1, None, None
        current = lyrics.lines[index]
        next_line = lyrics.lines[index + 1] if index + 1 < len(lyrics.lines) else None
        return anim, index, current, next_line

    def _lyric_progress(self, snapshot, current) -> float:
        if snapshot is None or not snapshot.is_playing or not current.text:
            return 0.0
        position = snapshot.position + self._offset_ms() / 1000.0
        span = max(0.05, current.end - current.time)
        duration = min(span, max(0.9, 0.185 * len(current.text) + 0.4))
        return max(0.0, min(1.0, (position - current.time) / duration))

    # ==================================================================
    # 纯歌词模式
    # ==================================================================

    def _paint_compact(self, painter, card, snapshot, lyrics) -> None:
        """纯歌词面板：只有歌词列表（和立体卡片右侧一致），没有专辑。"""
        self._paint_lyrics_panel(painter, card, snapshot, lyrics)

    def _paint_lyrics_panel(self, painter, card, snapshot, lyrics) -> None:
        settings = self.settings
        colors = settings.colors
        now = time.monotonic()
        left = card.left() + PAD
        right = card.right() - PAD

        show_info = bool(
            self._want_song_info()
            and snapshot is not None
            and snapshot.track is not None
        )
        head_h = self._head_h if show_info else 0.0
        head_sub_h = self._head_sub_h if show_info else 0.0
        head_gap = self._head_gap if show_info else 0.0
        block = head_h + 6.0 + head_sub_h + head_gap if show_info else 0.0

        # 歌名 + 歌词当成一整块，整体居中的话列表要往下挪半个头部高度
        center_y = card.center().y() + block / 2.0
        transform = self._list_transform(left, right, center_y)

        def header(painter_, list_top: float) -> None:
            self._draw_song_header(
                painter_,
                snapshot,
                left,
                right,
                list_top - head_gap - head_sub_h - 6.0 - head_h,
                colors,
            )

        if show_info:
            self._ensure_heat(snapshot)

        self._draw_lyric_list(
            painter,
            left,
            right,
            center_y,
            snapshot,
            lyrics,
            colors,
            now,
            transform=transform,
            header=header if show_info else None,
        )

    def _draw_song_header(self, painter, snapshot, left, right, top, colors) -> None:
        """纯歌词面板顶上的：歌名 + 作者（+ 右上角的播放热度）。"""
        track = snapshot.track
        fm_head = self._metrics["head"]
        fm_sub = self._metrics["head_sub"]
        full = max(60.0, right - left)
        align = self.settings.lyric_align

        # 歌名和热度当成一整行，按「歌词排版」的设置在窗口里对齐
        heat_text = ""
        heat_w = 0.0
        if self._heat_value is not None:
            heat_text = f"\u2665 {self._heat_value:.0f}"
            heat_w = fm_sub.horizontalAdvance(heat_text)

        title = track.title or "未知歌曲"
        gap = 14.0 if heat_text else 0.0
        avail = max(60.0, full - heat_w - gap)
        title_w = min(fm_head.horizontalAdvance(title), avail)
        block = title_w + gap + heat_w
        if align == "left":
            start = left
        elif align == "center":
            start = left + (full - block) / 2.0
        else:
            start = right - block

        self._draw_elided(
            painter,
            title,
            start,
            title_w,
            top,
            fm_head,
            self._fonts["head"],
            QColor(colors["base"]),
            1.0,
            alignment="left",
        )

        parts = [p for p in (track.artist, track.album) if p]
        self._draw_elided(
            painter,
            "  ·  ".join(parts) if parts else "未知艺术家",
            left,
            full,
            top + fm_head.height() + 6.0,
            fm_sub,
            self._fonts["head_sub"],
            QColor(colors["base"]),
            0.62,
            alignment=align,
        )

        if heat_text:
            self._draw_elided(
                painter,
                heat_text,
                start + title_w + gap,
                max(heat_w, fm_sub.horizontalAdvance(heat_text)) + 4.0,
                top + (fm_head.height() - fm_sub.height()) / 2.0,
                fm_sub,
                self._fonts["head_sub"],
                QColor(colors["c3"]),
                0.95,
                alignment="left",
            )

    def _ensure_heat(self, snapshot) -> None:
        """换歌了就后台查一次热度（查不到就不显示爱心）。"""
        track = snapshot.track
        key = heat_lookup.key_for(track.title or "", track.artist or "")
        if key == self._heat_key:
            return
        self._heat_key = key
        self._heat_value = heat_lookup.cached(key)
        if self._heat_value is None:
            heat_lookup.lookup(
                key,
                track.title or "",
                track.artist or "",
                lambda k, value: self.heatReady.emit(k, value),
            )

    def _on_heat_ready(self, key: str, value) -> None:
        if key == self._heat_key and value is not None:
            self._heat_value = float(value)
            self.update()

    def _draw_no_player_hint(self, painter, left, right, center_y, colors) -> None:
        """没检测到播放器时的提示。

        不少音乐软件的「系统播放控件 / 媒体控制」默认是关的，
        关了以后系统里就没有任何播放会话，程序自然识别不到。
        """
        width = max(80.0, right - left)
        family, base_size, weight = self._fonts["next"]
        texts = (
            "\u266a 未检测到正在播放的歌曲",
            "如果你正在放歌：请在音乐软件的设置里开启「系统播放控件 / 媒体控制」",
        )
        sprites = []
        for index, text in enumerate(texts):
            size = base_size if index == 0 else max(11, int(base_size * 0.72))
            fitted = fit_size(text, family, weight, size, width)
            sprites.append(make_sprite(text, family, fitted, weight))

        gap = 8.0
        total = sum(sprite.height for sprite in sprites) + gap * (len(sprites) - 1)
        y = center_y - total / 2.0
        for index, sprite in enumerate(sprites):
            draw_sprite(
                painter,
                sprite,
                right - sprite.advance / 2.0,
                y + sprite.ascent,
                QColor(colors["base"] if index == 0 else colors["dim"]),
                opacity=0.78 if index == 0 else 0.6,
                outline_width=max(2.0, sprite.size * 0.05),
                outline_color=QColor(0, 0, 0, 130),
            )
            y += sprite.height + gap

    # ==================================================================
    # 子绘制
    # ==================================================================

    def _draw_cover(self, painter, rect, albummid, snapshot, now, colors) -> None:
        radius = rect.width() * 0.16
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)

        target = self._cover_for(albummid, int(rect.width()))
        if target is not None:
            painter.save()
            painter.setClipPath(path)
            ratio = target.devicePixelRatio()
            dx = rect.center().x() - target.width() / (2 * ratio)
            dy = rect.center().y() - target.height() / (2 * ratio)
            painter.drawPixmap(int(dx), int(dy), target)
            painter.restore()
        else:
            gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
            gradient.setColorAt(0.0, QColor(colors["c1"]))
            gradient.setColorAt(0.5, QColor(colors["c2"]))
            gradient.setColorAt(1.0, QColor(colors["c3"]))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(gradient)
            painter.drawPath(path)
            glyph = make_sprite(
                "\u266a", self._icon_family, int(rect.width() * 0.42), WEIGHT_MEDIUM
            )
            draw_sprite(
                painter, glyph, rect.center().x(),
                rect.center().y() + glyph.ascent / 2.0 - glyph.descent / 2.0,
                QColor(11, 16, 32), opacity=0.72, shadow=False,
            )

        painter.setBrush(Qt.BrushStyle.NoBrush)
        if snapshot is not None and snapshot.is_playing:
            pulse = 0.5 + 0.5 * math.sin(now * 2.1)
            accent = QColor(colors["glow"])
            pen = painter.pen()
            pen.setColor(
                QColor(accent.red(), accent.green(), accent.blue(), int(60 + 90 * pulse))
            )
            pen.setWidthF(1.4 + 0.9 * pulse)
            painter.setPen(pen)
            painter.drawRoundedRect(
                rect.adjusted(-1.4, -1.4, 1.4, 1.4), radius + 1.4, radius + 1.4
            )
        else:
            painter.setPen(QColor(255, 255, 255, 30))
            painter.drawRoundedRect(rect, radius, radius)

    def _draw_progress(self, painter, card, snapshot, colors) -> None:
        fm_time = self._metrics["time"]
        bar_h = 6.0
        label_h = fm_time.height()
        bottom = card.bottom() - PAD
        label_top = bottom - label_h
        bar_top = label_top - 10.0 - bar_h

        left = card.left() + PAD
        right = card.right() - PAD
        width = right - left

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 40))
        painter.drawRoundedRect(QRectF(left, bar_top, width, bar_h), bar_h / 2, bar_h / 2)

        duration = snapshot.track.duration if snapshot is not None and snapshot.track else 0.0
        position = snapshot.position if snapshot is not None else 0.0
        fraction = max(0.0, min(1.0, position / duration)) if duration > 0 else 0.0

        self._hit_bar = QRectF(left - 8, bar_top - 12, width + 16, bar_h + 26)

        if fraction > 0.001:
            gradient = QLinearGradient(left, 0.0, right, 0.0)
            gradient.setColorAt(0.0, QColor(colors["c1"]))
            gradient.setColorAt(0.6, QColor(colors["c2"]))
            gradient.setColorAt(1.0, QColor(colors["c3"]))
            painter.setBrush(gradient)
            painter.drawRoundedRect(
                QRectF(left, bar_top, width * fraction, bar_h), bar_h / 2, bar_h / 2
            )
            knob_r = bar_h * 0.95 if self._hover == "bar" else bar_h * 0.72
            knob_x = left + width * fraction
            painter.setBrush(QColor(colors["c3"]))
            painter.drawEllipse(
                QRectF(knob_x - knob_r, bar_top + bar_h / 2 - knob_r, knob_r * 2, knob_r * 2)
            )

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QColor(colors["dim"]))
        painter.setFont(_qt_font(*self._fonts["time"]))
        painter.drawText(
            QRectF(left, label_top, width / 2, label_h),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            _format_time(position),
        )
        painter.drawText(
            QRectF(left + width / 2, label_top, width / 2, label_h),
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
            _format_time(duration),
        )

    def _draw_controls(
        self, painter, x, y, size, snapshot, colors, row_height: float | None = None
    ) -> None:
        gap = CONTROLS_GAP
        cy = y + (row_height if row_height else self._metrics["title"].height()) / 2.0
        playing = bool(snapshot is not None and snapshot.is_playing)
        live = snapshot is not None

        specs = [
            ("prev", "\uE892", live),
            ("play", "\uE769" if playing else "\uE768", live),
            ("next", "\uE893", live),
        ]
        for key, glyph, enabled in specs:
            rect = QRectF(x, cy - size / 2.0, size, size)
            # 命中区比图标大一圈，避免点偏一点就被当成拖动窗口
            hit = max(size, 42.0)
            hit_rect = QRectF(
                rect.center().x() - hit / 2.0,
                rect.center().y() - hit / 2.0,
                hit,
                hit,
            )
            if key == "prev":
                self._hit_prev = hit_rect
            elif key == "play":
                self._hit_play = hit_rect
            else:
                self._hit_next = hit_rect

            hovered = self._hover == key and enabled
            if key == "play" and enabled:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(255, 255, 255, 34 if hovered else 22))
                painter.drawEllipse(rect)

            if hovered:
                colour = QColor(colors["base"])
            elif self._no_card:
                # 没有背景板时按钮也提亮，否则深色壁纸上会看不清
                colour = QColor(colors["base"])
                colour.setAlpha(int(255 * 0.78))
            else:
                colour = QColor(colors["dim"])
            self._draw_elided(
                painter, glyph, rect.left(), rect.width(),
                rect.top() + (rect.height() - self._metrics["icon"].height()) / 2.0,
                self._metrics["icon"], self._fonts["icon"], colour,
                0.95 if enabled else 0.30, alignment="center",
            )
            x += size + gap

    @staticmethod
    def _controls_width(size: float) -> float:
        return size * 3.0 + CONTROLS_GAP * 2.0

    def _draw_elided(
        self, painter, text, left, width, top, fm, font_spec,
        color, opacity, alignment="left",
    ) -> None:
        if not text or width <= 4:
            return
        family, size, weight = font_spec
        font = _qt_font(family, size, weight)
        # 字间距只作用于歌词行（歌名 / 作者 / 时间不跟着散开）
        lyric_specs = {
            self._fonts.get(key) for key in ("list", "list_cur", "prev", "next")
        }
        spacing = render_mod.letter_spacing() if font_spec in lyric_specs else 0.0
        if spacing:
            font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
            fm = QFontMetricsF(font)
        display = text
        if fm.horizontalAdvance(display) > width:
            display = fm.elidedText(text, Qt.TextElideMode.ElideRight, width)

        painter.save()
        painter.setOpacity(max(0.0, min(1.0, opacity)))
        painter.setFont(font)
        if alignment == "center":
            flag = Qt.AlignmentFlag.AlignHCenter
        elif alignment == "right":
            flag = Qt.AlignmentFlag.AlignRight
        else:
            flag = Qt.AlignmentFlag.AlignLeft
        flag |= Qt.AlignmentFlag.AlignVCenter

        rect = QRectF(left, top, width, fm.height())
        # 轻描边，保证在任意壁纸上都能看清
        painter.setPen(QColor(0, 0, 0, 120))
        painter.drawText(rect.translated(0.0, 1.3), int(flag), display)
        painter.setPen(color)
        painter.drawText(rect, int(flag), display)
        painter.restore()

    def _scale_cover(self, pixmap: QPixmap, key, size: int) -> QPixmap:
        cache_key = (key, int(size))
        cached = self._cover_cache.get(cache_key)
        if cached is not None:
            return cached
        ratio = self.devicePixelRatioF()
        scaled = pixmap.scaled(
            int(size * ratio),
            int(size * ratio),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        scaled.setDevicePixelRatio(ratio)
        if len(self._cover_cache) > 16:
            self._cover_cache.clear()
        self._cover_cache[cache_key] = scaled
        return scaled

    def _cover_for(self, albummid: str, size: int) -> QPixmap | None:
        """优先用曲库给的专辑封面；没有就用系统媒体接口给的（任何播放器通用）。"""
        if albummid:
            pixmap = self._covers.get(albummid)
            if pixmap is not None:
                return self._scale_cover(pixmap, ("album", albummid), size)
        return self._thumbnail_for(size)

    def _thumbnail_for(self, size: int) -> QPixmap | None:
        getter = getattr(self.engine, "thumbnail", None)
        if getter is None:
            return None
        snapshot = self.engine.snapshot()
        key = snapshot.track.key if snapshot is not None and snapshot.track else ""
        if not key:
            return None
        try:
            data = getter()
        except Exception:
            data = None
        if not data:
            return None
        if self._thumb_key != key:
            pixmap = QPixmap()
            if pixmap.loadFromData(data):
                self._thumb_pixmap = pixmap
            else:
                self._thumb_pixmap = None
            self._thumb_key = key
        if self._thumb_pixmap is None:
            return None
        return self._scale_cover(self._thumb_pixmap, ("thumb", key), size)

    def _cover_color(self, albummid: str):
        """取封面主色调，用于「环境光」突起样式。"""
        key = albummid or (self._thumb_key or "")
        if not key:
            return None
        cached = self._cover_tints.get(key)
        if cached is not None:
            return cached
        pixmap = self._covers.get(albummid) if albummid else self._thumb_pixmap
        if pixmap is None:
            return None
        try:
            tiny = pixmap.scaled(
                1,
                1,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ).toImage()
            color = tiny.pixelColor(0, 0)
        except Exception:
            return None
        color = color.lighter(130)
        self._cover_tints[key] = color
        return color

    def _draw_line(self, painter, slot, text, font_spec, max_width, color, opacity, scale) -> None:
        family, size, weight = font_spec
        fitted = fit_size(text, family, weight, size, max_width)
        sprite = make_sprite(text, family, fitted, weight)
        baseline = (
            slot.top() + (slot.height() - (sprite.ascent + sprite.descent)) / 2.0 + sprite.ascent
        )
        draw_sprite(
            painter, sprite, slot.center().x(), baseline, color,
            scale=scale, opacity=opacity,
            outline_width=max(2.0, fitted * 0.05),
            outline_color=QColor(0, 0, 0, 130),
        )

    def _draw_placeholder(self, painter, card, text, colors, opacity) -> None:
        family, size, weight = self._fonts["next"]
        fitted = fit_size(text, family, weight, size, card.width() - PAD * 2)
        sprite = make_sprite(text, family, fitted, weight)
        baseline = card.center().y() + (sprite.ascent - sprite.descent) / 2.0
        draw_sprite(
            painter, sprite, card.center().x(), baseline, QColor(colors["dim"]),
            opacity=opacity,
            outline_width=max(2.0, fitted * 0.05),
            outline_color=QColor(0, 0, 0, 120),
        )

    def _on_cover(self, albummid: str, data: bytes) -> None:
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            self._covers[albummid] = pixmap
            if len(self._covers) > 20:
                self._covers.pop(next(iter(self._covers)))
            self._cover_cache.clear()
            self.update()

    # ==================================================================
    # 交互
    # ==================================================================

    def _controls_active(self) -> bool:
        return self._effective_mode() in ("player", "album")

    @property
    def _no_card(self) -> bool:
        """没有背景板时，次要元素需要额外提高对比度。"""
        return (
            self._effective_mode() in _NO_BOARD_MODES
            or not self.settings.background
        )

    def _want_song_info(self) -> bool:
        """要不要在歌词上方显示歌名 / 作者 / 热度。

        只有独立的「纯歌词面板」显示；分离面板里的那条歌词列不加，
        保持它单纯只是歌词。
        """
        return bool(self.settings.show_song_info) and self.role != "lyrics"

    def _song_key(self) -> str:
        """当前这首歌的标识（用来记这首歌单独的偏移）。

        用「播放器 + 歌名 + 歌手 + 时长」做键：

        · 只按歌名记的话，同名的不同人翻唱会互相影响 —— 加上歌手就不串了
        · 同一首歌的不同版本（专辑版 / Live / 剪辑版）时长通常不一样，
          带上时长就把它们分开了
        · 不同播放器各记一份：同一首歌在 QQ音乐 和 Spotify 上的时长、
          歌词版本都可能不同，分开记反而更不容易出错
        """
        snapshot = self.engine.snapshot()
        if snapshot is None or snapshot.track is None:
            return ""
        track = snapshot.track
        title = normalize(track.title or "")
        artist = normalize(track.artist or "")
        if not title:
            return ""
        player = (snapshot.source or "").replace("\\", "/").split("/")[-1]
        if player.lower().endswith(".exe"):
            player = player[:-4]
        player = normalize(player)
        seconds = int(round(float(track.duration or 0.0)))
        return f"{player}|{title}|{artist}|{seconds}"

    def _offset_ms(self) -> int:
        """当前这首歌实际使用的偏移。"""
        return self.settings.offset_for(self._song_key())

    def _hit_test(self, pos) -> str:
        if self._controls_active() and self.settings.show_controls:
            if self._hit_play.contains(pos):
                return "play"
            if self._hit_next.contains(pos):
                return "next"
            if self._hit_prev.contains(pos):
                return "prev"
        if self._controls_active() and self.settings.show_progress:
            snapshot = self.engine.snapshot()
            if (
                snapshot is not None
                and getattr(snapshot, "can_seek", True)
                and self._hit_bar.contains(pos)
            ):
                return "bar"
        return ""

    def _update_cursor(self) -> None:
        if self.settings.locked or self.settings.click_through:
            self.unsetCursor()
            return
        self.setCursor(
            Qt.CursorShape.PointingHandCursor if self._hover else Qt.CursorShape.SizeAllCursor
        )

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        pos = event.position()
        target = self._hit_test(pos)
        if target in ("play", "next", "prev"):
            self._send(target)
            event.accept()
            return
        if target == "bar":
            self._seek_to(pos.x())
            event.accept()
            return
        if not self.settings.locked:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._press_global = event.globalPosition().toPoint()
            self._dragging = False
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            current = event.globalPosition().toPoint()
            if not self._dragging:
                # 先走够 5 像素才算拖动，避免手抖把"点按钮"变成"移动窗口"
                if (current - self._press_global).manhattanLength() < 5:
                    return
                self._dragging = True
            self.move(current - self._drag_offset)
            self._bg_key = None
            event.accept()
            return
        hover = self._hit_test(event.position())
        if hover != self._hover:
            self._hover = hover
            self._update_cursor()
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._drag_offset is not None:
            self._drag_offset = None
            self._dragging = False
            self.keep_on_screen()
            self._remember_position()
            self.settings.save()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if self._hit_test(event.position()):
            return
        self.settings.locked = not self.settings.locked
        self.settings.save()
        self._update_cursor()
        event.accept()

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self._hover:
            self._hover = ""
            self._update_cursor()

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        menu = self.build_menu()
        menu.exec(event.globalPos())
        menu.deleteLater()

    def _send(self, action: str) -> None:
        # 按钮标识是 "play"，但播放器接口的指令叫 "toggle"
        command = "toggle" if action == "play" else action
        sender = getattr(self.engine, "send_control", None)
        if sender is not None:
            sender(command)

    def _seek_to(self, x: float) -> None:
        snapshot = self.engine.snapshot()
        if snapshot is None or snapshot.track is None or snapshot.track.duration <= 0:
            return
        bar_left = self._hit_bar.left() + 8
        bar_width = max(1.0, self._hit_bar.width() - 16)
        fraction = max(0.0, min(1.0, (x - bar_left) / bar_width))
        self._send(f"seek:{fraction * snapshot.track.duration}")

    # ==================================================================
    # 菜单
    # ==================================================================

    def build_menu(self) -> QMenu:
        menu = QMenu()
        self.populate_menu(menu)
        return menu

    def open_settings(self) -> None:
        """打开设置窗口（同一时间只留一个，重复点就把它拿到最前面）。"""
        dialog = getattr(self, "_settings_dialog", None)
        if dialog is not None:
            try:
                # 兜底：设置窗口还在（比如刚被别人关掉又点开），保证歌词窗是挂起置顶的
                set_all_topmost_suspended(True)
                dialog.show()
                dialog.raise_()
                dialog.activateWindow()
                return
            except RuntimeError:
                # 底层的 C++ 对象已经没了（窗口被销毁），当成没打开过
                self._settings_dialog = None

        # 设置窗口开着的时候，把所有歌词窗的置顶摘掉 ——
        # 否则它们（置顶）会画在设置窗口（不置顶）上面，挡着看不清也点不动
        set_all_topmost_suspended(True)

        # 放在函数里导入：settings_dialog 要用到窗口的方法，模块级互相 import 会成环
        from .settings_dialog import SettingsDialog

        # 不挂父窗口：有 owner 的窗口 Windows 不会给任务栏按钮，
        # 设置窗口需要在任务栏 / Alt+Tab 里出现（逻辑上仍用 self 当宿主）
        dialog = SettingsDialog(self, None)
        self._settings_dialog = dialog
        dialog.finished.connect(self._on_settings_closed)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _on_settings_closed(self, _result: int = 0) -> None:
        # 关掉之后要把引用清掉，否则下次再点会去操作已释放的窗口
        self._settings_dialog = None
        # 设置窗口关了，歌词窗恢复原来的置顶状态
        set_all_topmost_suspended(False)

    def raise_settings(self) -> None:
        """设置窗口开着就把它重新提到最前（切模式时两扇面板会盖住它）。"""
        dialog = getattr(self, "_settings_dialog", None)
        if dialog is None:
            return
        try:
            if dialog.isVisible():
                dialog.raise_()
        except RuntimeError:
            self._settings_dialog = None

    def transfer_settings_dialog(self, other: "LyricWindow") -> None:
        """本窗口要被销毁时，把设置窗口交给另一个窗口接着用。

        分离面板的窗口在切回单窗口模式时会被 deleteLater 掉，
        而设置窗口是挂在它身上的 —— 不转交的话，用户手里的设置窗口
        会指向一个已经释放的窗口，点一下就崩。
        """
        dialog = getattr(self, "_settings_dialog", None)
        if dialog is None:
            return
        self._settings_dialog = None
        try:
            dialog.detach_from(self)
            dialog.attach_to(other)
        except RuntimeError:
            return
        other._settings_dialog = dialog

    def populate_menu(self, menu: QMenu) -> None:
        """把菜单项填进给定菜单（复用同一个菜单对象，避免反复创建销毁）。"""
        menu.clear()
        settings = self.settings
        mode = self._effective_mode()
        mode_menu = menu.addMenu("界面模式")
        for label, value in (
            ("唱片播放器（无歌词）", "album"),
            ("纯歌词面板", "lyrics"),
            ("立体卡片（封面+歌词列表）", "depth3d"),
            ("分离面板（唱片 + 歌词，各自可移动）", "split"),
        ):
            action = mode_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(settings.mode == value)
            action.triggered.connect(lambda _c, v=value: self._set_mode(v))

        # 跟随哪个播放器（只在检测到多个时才有必要显示）
        players: list[dict] = []
        getter = getattr(self.engine, "players", None)
        if getter is not None:
            try:
                players = getter() or []
            except Exception:
                players = []
        if players:
            player_menu = menu.addMenu("跟随播放器")
            auto_action = player_menu.addAction("自动（正在播放的那个）")
            auto_action.setCheckable(True)
            auto_action.setChecked(not settings.preferred_player)
            auto_action.triggered.connect(lambda: self._set_player(""))
            player_menu.addSeparator()
            for item in players:
                app_id = item.get("app_id", "")
                if not app_id:
                    continue
                label = friendly_player_name(app_id)
                if item.get("playing"):
                    label += "（播放中）"
                action = player_menu.addAction(label)
                action.setCheckable(True)
                action.setChecked(settings.preferred_player == app_id)
                action.triggered.connect(lambda _c, a=app_id: self._set_player(a))

        if mode in ("depth3d", "lyrics"):
            lines_menu = menu.addMenu("歌词列表行数")
            for value in (1, 3, 5, 7, 9, 11):
                action = lines_menu.addAction(f"{value} 行")
                action.setCheckable(True)
                action.setChecked(settings.lyric_lines == value)
                action.triggered.connect(lambda _c, v=value: self._set_lines(v))

        # 只有独立的纯歌词面板才需要这个开关（分离面板里的歌词列不带头部）
        if mode == "lyrics" and self.role != "lyrics":
            self._toggle(
                menu,
                "显示歌名歌手和热度",
                settings.show_song_info,
                self._toggle_song_info,
            )

        if mode == "depth3d":
            depth_style_menu = menu.addMenu("专辑样式")
            for label, value in (
                ("经典（方块 + 菱形）", "classic"),
                ("黑胶唱片（带唱臂）", "vinyl"),
                ("封面 + 唱片", "cover_vinyl"),
            ):
                action = depth_style_menu.addAction(label)
                action.setCheckable(True)
                action.setChecked(
                    getattr(settings, "depth_album_style", "classic") == value
                )
                action.triggered.connect(
                    lambda _c, v=value: self._set_depth_style(v)
                )

        font_menu = menu.addMenu("歌词字体")
        families = set(QFontDatabase.families())
        recommended = {family for _label, family in RECOMMENDED}
        # 内置字体和自备字体的族名要排除掉，
        # 否则当前用的是它们时，菜单顶上会多出一条重复的「（当前）」
        named_elsewhere = {family for _file, _label, family in BUNDLED_FONTS}
        named_elsewhere |= {item.family for item in ONLINE_FONTS}
        listed: set[str] = set()
        mine = imported_fonts()
        mine_families = {family for family, _filename in mine}
        # 当前用的字体如果不在推荐列表里（比如被精简掉的常见字体），
        # 单独放在最前面，保证菜单里总能看到自己现在用的是哪个
        current = settings.font_family
        if (
            current
            and current in families
            and current not in recommended
            and current not in mine_families
            and current not in named_elsewhere
        ):
            self._font_action(font_menu, f"{current}（当前）", current)
            listed.add(current)
            font_menu.addSeparator()
        for label, family in RECOMMENDED:
            if family not in families or family in listed:
                continue
            self._font_action(font_menu, label, family)
            listed.add(family)
        bundled = [
            (label, family)
            for _filename, label, family in BUNDLED_FONTS
            if family in families
        ]
        if bundled:
            font_menu.addSeparator()
            for label, family in bundled:
                self._font_action(font_menu, label, family)
        if mine:
            font_menu.addSeparator()
            listed_mine: set[str] = set()
            for family, _filename in mine:
                if family in listed_mine:
                    continue
                listed_mine.add(family)
                suffix = "（当前）" if family == current else "（我导入的）"
                self._font_action(font_menu, f"{family}{suffix}", family)
        if ONLINE_FONTS:
            font_menu.addSeparator()
            for item in ONLINE_FONTS:
                family = family_for(item)
                if family:
                    self._font_action(font_menu, f"{item.label}（已下载）", family)
                else:
                    action = font_menu.addAction(
                        f"下载 {item.label}（{item.size_mb:.0f} MB）"
                    )
                    action.triggered.connect(
                        lambda _c, k=item.key: self._download_font(k)
                    )
        font_menu.addSeparator()
        font_menu.addAction("导入字体文件…", self._import_font_dialog)
        font_menu.addAction("打开字体文件夹", self._open_font_folder)
        font_menu.addAction("从系统字体中选择…", self._pick_font_dialog)

        # 极简播放控制：**一行**三个图标按钮，点一下直接控制当前播放器。
        # 桌面上不显示任何播放控件，适合把「显示播放控制」关掉、只想用菜单的人。
        # 用 QWidgetAction 塞一个横排进去 —— 普通 QAction 在菜单里只能一行一个。
        menu.addSeparator()
        snapshot = self.engine.snapshot()
        track = getattr(snapshot, "track", None)
        playing = bool(snapshot is not None and getattr(snapshot, "is_playing", False))
        glyphs = _play_glyphs(self._icon_family)
        icon_font = QFont(self._icon_family)
        icon_font.setPixelSize(15)
        controls = QWidgetAction(menu)
        holder = QWidget(menu)
        holder.setObjectName("playControls")
        # 背景跟着菜单走，不然菜单里会多出一块灰底
        holder.setStyleSheet("QWidget#playControls { background: transparent; }")
        row = QHBoxLayout(holder)
        row.setContentsMargins(10, 2, 10, 2)
        row.setSpacing(6)

        def fire(command: str) -> None:
            self._send(command)
            # 菜单本来就该点完就关（普通菜单项也是这个行为）
            menu.close()

        for glyph, command, tip in (
            (glyphs["prev"], "prev", "上一首"),
            (glyphs["pause"] if playing else glyphs["play"], "toggle", "播放 / 暂停"),
            (glyphs["next"], "next", "下一首"),
        ):
            button = QToolButton(holder)
            button.setText(glyph)
            button.setFont(icon_font)
            button.setToolTip(tip)
            button.setAutoRaise(True)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            # 没在播歌的时候别摆三个点了没反应的图标
            button.setEnabled(track is not None)
            button.clicked.connect(lambda _checked=False, c=command: fire(c))
            row.addWidget(button)
        row.addStretch(1)
        controls.setDefaultWidget(holder)
        menu.addAction(controls)
        menu.addSeparator()

        song_key = self._song_key()
        current_offset = self._offset_ms()
        if song_key:
            parts = song_key.split("|")
            label = parts[1][:12] if len(parts) > 1 else "本歌"
            offset_menu = menu.addMenu(f"歌词同步（《{label}》{current_offset:+d} ms）")
        else:
            offset_menu = menu.addMenu(f"歌词同步（默认 {current_offset:+d} ms）")
        current_lyrics = self.engine.lyrics
        source_label = getattr(current_lyrics, "source", "") if current_lyrics else ""
        if source_label:
            info_item = offset_menu.addAction(f"当前歌词来自：{source_label}")
            info_item.setEnabled(False)
            offset_menu.addSeparator()
        offset_menu.addAction("提前 1 秒", lambda: self._nudge_offset(-1000))
        offset_menu.addAction("提前 0.5 秒", lambda: self._nudge_offset(-500))
        offset_menu.addAction("提前 0.1 秒", lambda: self._nudge_offset(-100))
        offset_menu.addAction("延后 0.1 秒", lambda: self._nudge_offset(100))
        offset_menu.addAction("延后 0.5 秒", lambda: self._nudge_offset(500))
        offset_menu.addAction("延后 1 秒", lambda: self._nudge_offset(1000))
        offset_menu.addSeparator()
        offset_menu.addAction("自定义偏移…", self._ask_offset)
        if song_key:
            has_own = song_key in settings.song_offsets
            label = "恢复默认（本歌）" if has_own else "重置（本歌）"
            offset_menu.addAction(label, lambda: self._set_offset(0))
        else:
            offset_menu.addAction("重置", lambda: self._set_offset(0))
        offset_menu.addSeparator()
        offset_menu.addAction("所有歌曲的默认偏移…", self._ask_default_offset)

        menu.addSeparator()
        self._toggle(menu, "锁定位置", settings.locked, self._toggle_locked)
        self._toggle(menu, "鼠标穿透", settings.click_through, self._toggle_click_through)
        self._toggle(menu, "置顶显示", settings.always_on_top, self._toggle_always_on_top)

        menu.addSeparator()
        menu.addAction("最小化到托盘（隐藏歌词）", self._minimize_to_tray)
        menu.addAction("重新获取歌词", self.requestReload.emit)
        menu.addAction("回到默认位置", self._reset_position)

        # 「设置…」放在菜单靠下的位置（跟「检查更新…」挨着），常用操作在上面
        menu.addSeparator()
        settings_action = menu.addAction(tr("menu.settings", "设置…"))
        settings_action.setShortcut(QKeySequence("Ctrl+,"))
        settings_action.triggered.connect(self.open_settings)
        menu.addSeparator()
        menu.addAction("检查更新…", self._check_update)
        version_item = menu.addAction(f"桌面歌词  v{__version__}")
        version_item.setEnabled(False)
        menu.addSeparator()
        menu.addAction("退出", self.requestQuit.emit)

    @staticmethod
    def _toggle(menu: QMenu, label: str, checked: bool, callback, enabled: bool = True) -> QAction:
        action = QAction(label, menu, checkable=True)
        action.setChecked(checked)
        action.setEnabled(enabled)
        action.triggered.connect(callback)
        menu.addAction(action)
        return action

    # ------------------------------------------------------------------

    def _set_mode(self, value: str) -> None:
        self.settings.mode = value
        self._display_idx = -1
        self._scroll_ready = False
        if value in ("depth3d", "lyrics"):
            self.settings.show_progress = False
            self.settings.show_controls = False
            self.settings.show_next = False
        elif value in ("player", "album"):
            self.settings.show_progress = True
            self.settings.show_controls = True
            self.settings.show_next = True
        self._commit(resize=True)

    def _set_album_shape(self, value: str) -> None:
        self.settings.album_shape = value
        self._commit(resize=True)

    def _set_depth_style(self, value: str) -> None:
        self.settings.depth_album_style = value
        self._commit(resize=True)

    def _set_player(self, app_id: str) -> None:
        setter = getattr(self.engine, "set_preferred_player", None)
        if setter is not None:
            setter(app_id)
        else:
            self.settings.preferred_player = app_id
        self._lyrics_ref = None
        self._display_idx = -1
        self._scroll_ready = False
        self.settings.save()
        self.settingsChanged.emit()
        self.update()

    def _set_lines(self, value: int) -> None:
        self.settings.lyric_lines = value
        self._commit(resize=True)

    def _set_depth(self, v: float | None = None, h: float | None = None) -> None:
        if v is not None:
            self.settings.text_depth_v = v
        if h is not None:
            self.settings.text_depth_h = h
        self._commit()

    def _set_spin(self, angle: float) -> None:
        self.settings.text_tilt = angle
        self._commit()

    def _set_raise_style(self, value: str) -> None:
        self.settings.raise_style = value
        self._commit()

    def _set_raise_opacity(self, value: float) -> None:
        self.settings.raise_opacity = value
        self._commit()

    def _set_ui_opacity(self, value: float) -> None:
        self.settings.ui_opacity = value
        self._commit()

    def _set_spacing(self, value: float) -> None:
        self.settings.line_spacing = value
        self._commit(resize=True)

    def _nudge_spacing(self, delta: float) -> None:
        self.settings.line_spacing += delta
        self._commit(resize=True)

    def _set_theme(self, key: str) -> None:
        self.settings.theme = key
        self._commit(background=True)

    def _set_font_size(self, value: int) -> None:
        self.settings.font_size = value
        self._commit(resize=True)

    def _font_action(self, menu: QMenu, label: str, family: str) -> None:
        action = menu.addAction(label)
        action.setCheckable(True)
        action.setChecked(self.settings.font_family == family)
        action.triggered.connect(lambda _c, f=family: self._set_font_family(f))

    def _set_font_family(self, family: str) -> None:
        self.settings.font_family = family
        self._commit(resize=True)

    def _pick_font_dialog(self) -> None:
        from PySide6.QtWidgets import QFontDialog

        current = QFont(self.settings.font_family)
        current.setPixelSize(int(self.settings.font_size))
        # PySide6 各版本这个静态方法的返回顺序不一样（6.11 是 (ok, font)，
        # 老版本是 (font, ok)），按类型认人 —— 不然选完字体要么没反应、
        # 要么直接 AttributeError: 'bool' object has no attribute 'family'
        first, second = QFontDialog.getFont(current, self, "选择歌词字体")
        chosen, ok = (first, second) if isinstance(first, QFont) else (second, first)
        ok = bool(ok)
        if ok and chosen.family():
            self._set_font_family(chosen.family())

    # ------------------------------------------------------------------
    # 导入自己的字体
    # ------------------------------------------------------------------

    def _import_font_dialog(self) -> None:
        """选几个字体文件导进来，之后一直出现在「歌词字体」菜单里。"""
        from PySide6.QtWidgets import QFileDialog, QMessageBox

        paths, _filter = QFileDialog.getOpenFileNames(
            self,
            "导入字体文件（可多选）",
            str(Path.home()),
            "字体文件 (*.ttf *.otf *.ttc *.otc);;所有文件 (*.*)",
        )
        if not paths:
            return

        ok_names: list[str] = []
        problems: list[str] = []
        for raw in paths:
            ok, message = import_font_file(Path(raw))
            if ok:
                ok_names.append(message)
            else:
                problems.append(message)

        if ok_names:
            # 只导入了一个就直接切过去，省一步
            if len(ok_names) == 1 and not problems:
                self.settings.font_family = ok_names[0]
            self._commit(resize=True)

        box = QMessageBox(self)
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        box.setWindowTitle("导入字体")
        if ok_names and not problems:
            box.setIcon(QMessageBox.Icon.Information)
            box.setText(f"已导入 {len(ok_names)} 个字体")
            detail = "、".join(ok_names)
            if len(ok_names) == 1:
                detail += "\n\n已经帮你切换成这个字体了。"
            box.setInformativeText(detail)
        elif ok_names and problems:
            box.setIcon(QMessageBox.Icon.Warning)
            box.setText(f"导入了 {len(ok_names)} 个，{len(problems)} 个没成功")
            box.setInformativeText(
                "成功：" + "、".join(ok_names) + "\n\n失败：\n" + "\n".join(problems)
            )
        else:
            box.setIcon(QMessageBox.Icon.Warning)
            box.setText("导入失败")
            box.setInformativeText("\n".join(problems))
        box.addButton("好", QMessageBox.ButtonRole.AcceptRole)
        box.exec()

        # 菜单里要立刻出现新字体，托盘菜单也一起刷新
        self.settingsChanged.emit()
        self.update()

    def _open_font_folder(self) -> None:
        """打开字体文件夹 —— 想删掉导入的字体，直接删文件即可。"""
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(user_font_dir())))

    def _download_font(self, key: str) -> None:
        item = next((f for f in ONLINE_FONTS if f.key == key), None)
        if item is None:
            return
        self.requestNotify.emit(
            "开始下载字体",
            f"正在下载 {item.label}（约 {item.size_mb:.0f} MB，{item.license}）…\n"
            "下载完成后会再通知你。",
        )

        def done(ok: bool, message: str) -> None:
            self.requestNotify.emit("歌词字体" if ok else "字体下载失败", message)
            if ok:
                # 让托盘菜单也跟着刷新（新字体已经能用，去字体菜单里选即可）
                self.settingsChanged.emit()

        download(item, done)

    def _nudge_font(self, delta: int) -> None:
        self.settings.font_size += delta
        self._commit(resize=True)

    def _set_cover(self, value: int) -> None:
        self.settings.cover_size = value
        self._commit(resize=True)

    def _set_width(self, value: int) -> None:
        """改歌词宽度。按歌词对齐方式保持锚点，避免窗口"滑来滑去"。"""
        align = self.settings.lyric_align
        before = QRect(self.geometry())
        self.settings.width = int(value)
        self._apply_new_width(before, align)

    def _set_player_width(self, value: int) -> None:
        """唱片/播放器面板宽度；0 = 自动（跟随封面）。"""
        self.settings.player_width = 0 if int(value) <= 0 else int(value)
        before = QRect(self.geometry())
        # 唱片面板一般靠右上，按"右边缘不动"处理
        self._apply_new_width(before, "right")

    def _set_letter_spacing(self, value: float) -> None:
        """歌词字间距（px）。改完重算：字变宽 → 自动宽度跟着变。"""
        self.settings.letter_spacing = float(value)
        self._commit(resize=True)

    def _apply_new_width(self, before: QRect, anchor: str) -> None:
        """按锚点重算窗口（右对齐钉右边缘 / 居中钉中心 / 左对齐钉左边）。"""
        self.settings.clamp()
        self.settings.save()
        self.recalculate()
        if anchor == "right":
            self.move(before.right() - self.width() + 1, self.y())
        elif anchor == "center":
            self.move(before.center().x() - self.width() // 2, self.y())
        else:
            self.move(before.x(), self.y())
        self.keep_on_screen()
        self._remember_position()
        self.settings.save()
        self.update()
        self.settingsChanged.emit()

    def _nudge_width(self, delta: int) -> None:
        self.settings.width += delta
        self._commit(resize=True)

    def _set_opacity(self, value: float) -> None:
        self.settings.opacity = value
        self._commit(background=True)

    def _set_offset(self, value: int) -> None:
        # 按歌记：这首歌调好的偏移不会影响下一首
        self.settings.set_offset_for(self._song_key(), value)
        self._commit()

    def _nudge_offset(self, delta: int) -> None:
        self._set_offset(self._offset_ms() + delta)

    def _ask_offset(self) -> None:
        """直接填毫秒数 —— 只作用在当前这首歌上。"""
        from PySide6.QtWidgets import QInputDialog

        song_key = self._song_key()
        title = "歌词同步"
        if song_key:
            parts = song_key.split("|")
            name = parts[1] if len(parts) > 1 else ""
            player = parts[0] if parts else ""
            title = f"《{name}》的歌词偏移（{player}）"
        value, ok = QInputDialog.getInt(
            self,
            title,
            "输入偏移毫秒数（只对这首歌生效，会一直记住）：\n"
            "负数 = 歌词提前（歌词比声音快）\n"
            "正数 = 歌词延后（歌词比声音慢）\n"
            "范围 -30000 ~ 30000（也就是 ±30 秒）",
            int(self._offset_ms()),
            -30000,
            30000,
            100,
        )
        if ok:
            self._set_offset(int(value))

    def _ask_default_offset(self) -> None:
        """给「没单独调过的歌」设一个默认偏移。"""
        from PySide6.QtWidgets import QInputDialog

        value, ok = QInputDialog.getInt(
            self,
            "所有歌曲的默认偏移",
            "输入默认偏移毫秒数：\n"
            "只影响还没单独调过的歌；单独调过的歌保持自己的数值。\n"
            "负数 = 歌词提前，正数 = 歌词延后。",
            int(self.settings.offset_ms),
            -30000,
            30000,
            100,
        )
        if ok:
            self.settings.offset_ms = int(value)
            self._commit()

    def _toggle_cover(self) -> None:
        self.settings.show_cover = not self.settings.show_cover
        self._commit(resize=True)

    def _toggle_progress(self) -> None:
        self.settings.show_progress = not self.settings.show_progress
        self._commit(resize=True)

    def _toggle_controls(self) -> None:
        self.settings.show_controls = not self.settings.show_controls
        self._commit()

    def _toggle_prev(self) -> None:
        self.settings.show_prev = not self.settings.show_prev
        self._commit(resize=True)

    def _toggle_next(self) -> None:
        self.settings.show_next = not self.settings.show_next
        self._commit(resize=True)

    def _toggle_background(self) -> None:
        self.settings.background = not self.settings.background
        self._commit(background=True)

    def _toggle_song_info(self) -> None:
        self.settings.show_song_info = not self.settings.show_song_info
        self._commit(resize=True)

    def _toggle_auto_show(self) -> None:
        self.settings.auto_show_on_music = not self.settings.auto_show_on_music
        self._commit()

    def _set_align(self, value: str) -> None:
        self.settings.lyric_align = value
        self._commit()

    def _toggle_locked(self) -> None:
        self.settings.locked = not self.settings.locked
        self._commit()

    def _toggle_click_through(self) -> None:
        self.set_click_through(not self.settings.click_through)

    def set_click_through(self, enabled: bool) -> None:
        """开启鼠标穿透。穿透之后窗口收不到鼠标事件，等于顺手把位置锁了。"""
        if enabled == self.settings.click_through:
            return
        self.settings.click_through = enabled
        if enabled:
            self.settings.locked = True
            self._hover = ""
            self.requestNotify.emit(
                "已开启鼠标穿透",
                f"{APP_TITLE} 现在不响应鼠标了（位置也已锁定）。\n\n"
                "想改回来：\n"
                "· 按 Ctrl + Alt + L，或\n"
                "· 右键任务栏托盘里的音符图标 → 鼠标穿透\n\n"
                "（Windows 11 可能把托盘图标收在「^」溢出区里）",
            )
        else:
            self.settings.locked = False
        self._commit(flags=True)

    # ------------------------------------------------------------------

    def _check_hotkey(self) -> None:
        """全局热键 Ctrl+Alt+L：切换鼠标穿透。

        穿透之后窗口点不了，这个热键是唯一的「后门」，
        即使托盘图标被系统折叠起来也能救回来。
        """
        try:
            import ctypes

            user32 = ctypes.windll.user32
            pressed = bool(
                user32.GetAsyncKeyState(0x11) & 0x8000  # Ctrl
                and user32.GetAsyncKeyState(0x12) & 0x8000  # Alt
                and user32.GetAsyncKeyState(0x4C) & 0x8000  # L
            )
        except Exception:
            return
        if pressed and not _HOTKEY_STATE["prev"]:
            self.set_click_through(not self.settings.click_through)
        _HOTKEY_STATE["prev"] = pressed

    def _toggle_always_on_top(self) -> None:
        self.settings.always_on_top = not self.settings.always_on_top
        self.settings.save()
        # 只改 Z 序：不走 _commit(flags=True)，否则 setWindowFlags 会重建窗口、闪一下
        if not set_native_topmost(self, self.settings.always_on_top):
            self._commit(flags=True)
        self.update()

    def _toggle_bili_mode(self) -> None:
        """B 站客户端字幕开关。

        打开时自动准备 B 站：端口在就什么都不做；B 站没跑就带端口启动；
        B 站正在跑（不带端口）→ 问一次再重启（会中断当前播放）。
        """
        if self.settings.bili_mode:
            self.settings.bili_mode = False
            self._commit()
            return

        if not self.ensure_bili_ready():
            self._commit()  # 没准备好就让设置窗口把勾去掉
            return
        self.settings.bili_mode = True
        self._commit()

    def ensure_bili_ready(self) -> bool:
        """确保 B 站以「能读字幕」的方式开着；需要重启时先问用户。"""
        from PySide6.QtWidgets import QMessageBox

        from . import bili_launcher

        if bili_launcher.debug_ready():
            return True

        exe = bili_launcher.find_exe()
        if exe is None:
            box = self._update_box(
                QMessageBox.Icon.Warning,
                "B 站字幕",
                "没找到 B 站客户端",
                "需要先安装「哔哩哔哩」电脑版；装好后再勾选这个开关。",
            )
            box.addButton("知道了", QMessageBox.ButtonRole.AcceptRole)
            box.exec()
            return False

        if bili_launcher.is_running(exe):
            box = self._update_box(
                QMessageBox.Icon.Question,
                "B 站字幕",
                "读取字幕需要重启 B 站",
                "当前正在播放的视频会中断。重启后会自动用「可读取字幕」的方式打开 B 站，要继续吗？",
            )
            go = box.addButton("继续", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is not go:
                return False
            bili_launcher.restart_with_debug(exe)
        else:
            bili_launcher.launch_with_debug(exe)

        ready = bili_launcher.wait_ready(8.0)
        if not ready:
            self.requestNotify.emit(
                "B 站字幕",
                "调试端口还没就绪。等 B 站完全打开后，点设置里的「重启 B 站并读取字幕」。",
            )
        return ready

    def _ask_restart_bili(self) -> None:
        """设置里/启动时的「重启 B 站并读取字幕」：问一句，然后重启并等端口。"""
        from PySide6.QtWidgets import QMessageBox

        from . import bili_launcher

        if bili_launcher.debug_ready():
            self.requestNotify.emit("B 站字幕", "B 站已经是「歌词模式」，可以直接看字幕。")
            return
        exe = bili_launcher.find_exe()
        if exe is None:
            self.requestNotify.emit("B 站字幕", "没找到 B 站客户端，先安装「哔哩哔哩」电脑版。")
            return
        box = self._update_box(
            QMessageBox.Icon.Question,
            "B 站字幕",
            "重启 B 站以读取字幕？",
            "当前正在播放的视频会中断；重启后会自动用「可读取字幕」的方式打开。",
        )
        go = box.addButton("重启 B 站", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("暂不", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not go:
            return
        bili_launcher.restart_with_debug(exe)
        if bili_launcher.wait_ready(8.0):
            self.requestNotify.emit("B 站字幕", "B 站已重启，字幕模式就绪。")
        else:
            self.requestNotify.emit("B 站字幕", "端口还没就绪，等 B 站完全打开后再试一次。")

    def _reset_position(self) -> None:
        if self.role == "player":
            self.settings.player_pos = [-1, -1]
        elif self.role == "lyrics":
            self.settings.lyrics_pos = [-1, -1]
        else:
            self.settings.x = -1
            self.settings.y = -1
        self._apply_initial_position()
        self.keep_on_screen()
        self.settings.save()
        self.update()

    def _minimize_to_tray(self) -> None:
        self.hide()
        # 分离面板模式下要把两扇面板一起收起来
        self.requestHide.emit()
        self.requestNotify.emit(
            "已最小化到托盘",
            f"{APP_TITLE} 已隐藏，仍在后台运行。\n"
            "右键任务栏托盘里的音符图标可以重新显示或退出。",
        )

    # ------------------------------------------------------------------
    # 检查更新
    # ------------------------------------------------------------------

    def _update_source(self) -> str:
        """设置里填的优先，其次是程序目录里的 update.json。"""
        return (self.settings.update_source or "").strip() or bundled_source() or UPDATE_DEFAULT_SOURCE

    def _update_box(self, icon, title: str, text: str, detail: str = ""):
        from PySide6.QtWidgets import QMessageBox

        box = QMessageBox(self)
        # 歌词窗是置顶的，弹窗必须跟着置顶，否则会被盖住看不见
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        box.setWindowTitle(title)
        box.setIcon(icon)
        box.setText(text)
        if detail:
            box.setInformativeText(detail)
        return box

    def _ask_update_source(self) -> bool:
        from PySide6.QtWidgets import QInputDialog

        current = self._update_source()
        tip = (
            "填一个「更新源」，程序会去那里读取最新版本号。支持四种写法：\n\n"
            "·  GitHub 仓库：someone/LyricDesk\n"
            "   读该仓库 Releases 里的最新版本\n"
            "·  码云 Gitee 仓库：gitee:someone/LyricDesk\n"
            "   国内直连可用，推荐\n"
            "·  任意 JSON 链接：https://例子.com/update.json\n"
            "   内容形如 {\"version\":\"1.6.0\",\"notes\":\"改了什么\","
            "\"url\":\"下载页\"}\n"
            "·  本地文件：D:\\LyricDesk\\update.json\n\n"
            "想清空就留空后确定。"
        )
        text, ok = QInputDialog.getText(
            self, "设置更新源", tip, text=current
        )
        if not ok:
            return False
        self.settings.update_source = text.strip()
        self.settings.save()
        self.settingsChanged.emit()
        return bool(self.settings.update_source)

    def _check_update(self) -> None:
        if getattr(self, "_update_busy", False):
            return
        source = self._update_source()
        if not source:
            if not self._ask_update_source():
                return
            source = self._update_source()
        self._update_busy = True
        self._update_silent = False
        self.requestNotify.emit(
            "正在检查更新",
            f"当前版本 v{__version__}，正在读取更新源…\n{describe_source(source)}",
        )
        self.update()

        def done(info) -> None:
            # 这里还在后台线程，别直接碰窗口，交给信号切回主线程
            self.updateChecked.emit(info)

        check_update(source, done)

    def auto_check_update(self) -> None:
        """启动时静默自查：24 小时内只查一次，且只在配了更新源之后。

        联网失败、或者没有更新，都安静处理，不打扰用户；
        只有真的发现新版本才发一条托盘通知。
        """
        source = self._update_source()
        if not source or self._update_busy:
            return
        now = time.time()
        try:
            last = float(self.settings.update_last_check or 0.0)
        except (TypeError, ValueError):
            last = 0.0
        if now - last < 24 * 3600:
            return
        self.settings.update_last_check = now
        self.settings.save()
        self._update_busy = True
        self._update_silent = True
        check_update(source, lambda info: self.updateChecked.emit(info))

    def _on_update_result(self, info) -> None:
        from PySide6.QtWidgets import QMessageBox

        self._update_busy = False
        if self._update_silent:
            self._update_silent = False
            if info.ok and is_newer(info.latest, __version__):
                self.requestNotify.emit(
                    "发现新版本",
                    f"桌面歌词 v{info.latest} 已经发布（你当前是 v{__version__}）。\n"
                    "右键托盘里的音符图标 → 检查更新…，可以打开下载页。",
                )
            return

        if not info.ok:
            box = self._update_box(
                QMessageBox.Icon.Warning,
                "检查更新",
                "没能读到版本信息",
                f"更新源：{describe_source(info.source)}\n"
                f"原因：{info.error}\n\n"
                "如果更新源是 GitHub，国内大多需要开代理；"
                "也可以改用 gitee:用户/仓库 或者一个 JSON 链接。",
            )
            again = box.addButton("重新设置更新源", QMessageBox.ButtonRole.ActionRole)
            box.addButton("知道了", QMessageBox.ButtonRole.AcceptRole)
            box.exec()
            if box.clickedButton() is again:
                self._ask_update_source()
            return

        if not is_newer(info.latest, __version__):
            box = self._update_box(
                QMessageBox.Icon.Information,
                "检查更新",
                f"已经是最新版本  v{__version__}",
                f"更新源里的最新版本：{info.latest}\n"
                f"来源：{describe_source(info.source)}",
            )
            box.addButton("好", QMessageBox.ButtonRole.AcceptRole)
            box.exec()
            return

        notes = (info.notes or "").strip()
        if len(notes) > 900:
            notes = notes[:900] + "…"
        detail = f"你现在是 v{__version__}，最新版是 {info.latest}。"
        if notes:
            detail += f"\n\n更新内容：\n{notes}"
        box = self._update_box(
            QMessageBox.Icon.Information,
            "发现新版本",
            f"有新版本可用：{info.latest}",
            detail,
        )
        update_button = None
        if info.installer:
            update_button = box.addButton(
                "立即更新", QMessageBox.ButtonRole.AcceptRole
            )
        open_button = None
        if info.url.lower().startswith("http"):
            open_button = box.addButton("打开下载页", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("稍后再说", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if update_button is not None and clicked is update_button:
            self._start_self_update(info)
            return
        if open_button is not None and clicked is open_button:
            from PySide6.QtGui import QDesktopServices
            from PySide6.QtCore import QUrl

            QDesktopServices.openUrl(QUrl(info.url))

    # ------------------------------------------------------------------
    # 一键更新：下载安装程序 → 关闭自己 → 静默安装 → 重新打开
    # ------------------------------------------------------------------

    _UNINSTALL_KEY = (
        r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
        r"\{8F3A2C7E-5B41-4D9A-9E27-1C6D4B0A7F33}_is1"
    )

    @classmethod
    def _installed_exe(cls) -> Path | None:
        """已安装版本的主程序路径（先读注册表，再退到默认安装目录）。"""
        import winreg

        location = ""
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, cls._UNINSTALL_KEY) as handle:
                location = str(winreg.QueryValueEx(handle, "InstallLocation")[0])
        except OSError:
            location = ""
        candidates = []
        if location:
            candidates.append(Path(location) / "LyricDesk.exe")
        base = os.environ.get("LOCALAPPDATA") or ""
        if base:
            candidates.append(Path(base) / "Programs" / "LyricDesk" / "LyricDesk.exe")
        for path in candidates:
            if path.exists():
                return path
        return None

    def _start_self_update(self, info) -> None:
        from PySide6.QtWidgets import QMessageBox

        box = self._update_box(
            QMessageBox.Icon.Question,
            "立即更新",
            f"要更新到 {info.latest} 吗？",
            "会先下载安装程序，下载完成后自动关闭本程序、静默安装，然后重新打开。\n"
            "你的设置、字体、窗口位置都会保留。\n\n"
            "下载期间可以继续用，不会卡。",
        )
        go = box.addButton("下载并安装", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not go:
            return

        self._update_busy = True
        stop = threading.Event()
        self._update_cancel = stop

        from PySide6.QtWidgets import QProgressDialog

        box = QProgressDialog(f"正在下载更新 {info.latest}…", "取消", 0, 100, self)
        box.setWindowTitle(f"更新到 {info.latest}")
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        box.setWindowModality(Qt.WindowModality.NonModal)
        box.setMinimumDuration(0)
        box.setAutoClose(False)
        box.setAutoReset(False)
        box.setValue(0)
        box.canceled.connect(stop.set)
        box.show()
        box.raise_()
        self._update_progress = box

        self.requestNotify.emit(
            "正在下载更新",
            f"正在下载 v{info.latest} 的安装程序…\n"
            "下载完成后会自动安装并重新打开，期间可以继续用。",
        )
        target = Path(tempfile.gettempdir()) / f"LyricDesk-Setup-{info.latest}.exe"

        def done(ok: bool, message: str) -> None:
            self.updateDownloaded.emit(ok, message, info)

        download_update(
            info.installer,
            target,
            done,
            on_progress=lambda done_bytes, total, speed: self.updateProgress.emit(
                int(done_bytes), int(total), float(speed)
            ),
            should_stop=stop.is_set,
        )

    def _on_update_progress(self, done: int, total: int, speed: float) -> None:
        box = getattr(self, "_update_progress", None)
        if box is None:
            return
        mb = 1048576.0
        if total > 0:
            box.setMaximum(int(total))
            box.setValue(min(int(done), int(total)))
            percent = int(done * 100 / total)
            text = (
                f"正在下载更新 {percent}%　{done / mb:.1f} / {total / mb:.1f} MB\n"
                f"速度 {speed / mb:.2f} MB/s"
            )
            if speed > 0 and total > done:
                text += f"　预计还剩 {int((total - done) / speed)} 秒"
        else:
            box.setMaximum(0)  # 服务器没给总大小，用忙碌指示
            text = f"正在下载更新… 已下载 {done / mb:.1f} MB\n速度 {speed / mb:.2f} MB/s"
        box.setLabelText(text)

    def _on_update_downloaded(self, ok: bool, message: str, info) -> None:
        from PySide6.QtWidgets import QMessageBox

        self._update_busy = False
        progress = getattr(self, "_update_progress", None)
        self._update_progress = None
        self._update_cancel = None
        if progress is not None:
            progress.close()
            progress.deleteLater()

        if not ok:
            if message == "已取消":
                self.requestNotify.emit("已取消更新", "没有安装任何东西，程序保持原样。")
                return
            box = self._update_box(
                QMessageBox.Icon.Warning,
                "立即更新",
                "更新包下载失败",
                f"{message}\n\n可以去发布页手动下载安装。",
            )
            target = info.url if info.url.lower().startswith("http") else info.installer
            open_button = box.addButton("打开下载页", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("知道了", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is open_button and target:
                from PySide6.QtGui import QDesktopServices
                from PySide6.QtCore import QUrl

                QDesktopServices.openUrl(QUrl(target))
            return

        setup = Path(message)
        exe = self._installed_exe()
        script = self._write_update_script(setup, exe)
        if script is None:
            QMessageBox.warning(
                self,
                "立即更新",
                f"更新脚本写入失败，请手动安装：\n{setup}",
            )
            return

        flags = 0
        if hasattr(subprocess, "DETACHED_PROCESS"):
            flags |= subprocess.DETACHED_PROCESS
        if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            flags |= subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            subprocess.Popen(
                ["cmd", "/c", str(script)],
                creationflags=flags,
                close_fds=True,
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(
                self,
                "立即更新",
                f"启动安装失败：{type(exc).__name__}\n请手动安装：\n{setup}",
            )
            return

        self.requestNotify.emit(
            "正在安装更新",
            f"桌面歌词即将关闭并安装 v{info.latest}，装好后会自动重新打开。",
        )
        QTimer.singleShot(1200, self.requestQuit.emit)

    def _write_update_script(self, setup: Path, exe: Path | None) -> Path | None:
        """写一个脱离本进程运行的 cmd：等一会儿 → 静默装 → 重新打开程序。

        装成功才删安装包；装失败（杀软拦截、系统版本不够……）保留安装包，并在
        temp 里留一个标记 —— 程序重新打开后会提示用户「安装包还在，可以手动装」。
        """
        relaunch = f'start "" "{exe}"' if exe is not None else ""
        temp_dir = Path(tempfile.gettempdir())
        # 脚本里尽量别出现中文路径：cmd 按控制台代码页解析批处理，
        # 「用户名带中文 + 代码页不是 936」时写死的绝对路径会变乱码。
        # 用 %TEMP% 让 cmd 自己展开就没这个问题。
        if setup.parent == temp_dir:
            setup_arg = f"%TEMP%\\{setup.name}"
            marker_arg = f"%TEMP%\\{FAILED_MARKER}"
        else:
            setup_arg = str(setup)
            marker_arg = str(temp_dir / FAILED_MARKER)
        lines = [
            "@echo off",
            # 等程序自己退干净（约 3 秒）。ping 不需要控制台，timeout 在无控制台时会直接报错
            "ping -n 4 127.0.0.1 >nul",
            f'"{setup_arg}" /SILENT /SUPPRESSMSGBOXES /NORESTART /SP-',
            "if errorlevel 1 goto failed",
            f'del /q "{setup_arg}"',
            f'del /q "{marker_arg}"',
            relaunch,
            'del "%~f0"',
            "exit /b 0",
            ":failed",
            f'>"{marker_arg}" echo {setup.name}',
            relaunch,
            'del "%~f0"',
        ]
        try:
            path = Path(tempfile.gettempdir()) / "lyricdesk-update.cmd"
            # cmd.exe 按系统 ANSI 代码页解析批处理，所以用 mbcs 写（中文路径才不会乱）
            path.write_text(
                "\r\n".join(lines) + "\r\n", encoding="mbcs", errors="replace"
            )
            return path
        except Exception:  # noqa: BLE001
            return None

    def _commit(self, resize: bool = False, flags: bool = False, background: bool = False) -> None:
        self.settings.clamp()
        self.settings.save()
        if resize:
            self.recalculate()
            self.keep_on_screen()
            self._remember_position()
            self.settings.save()
        if background:
            self._bg_key = None
        if flags:
            self.apply_flags()
        self._update_cursor()
        self.update()
        self.settingsChanged.emit()
