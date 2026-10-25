"""配置读写与主题定义。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import ClassVar

APP_NAME = "LyricDesk"


def app_dir() -> Path:
    """%APPDATA%\\LyricDesk"""
    import os

    base = os.environ.get("APPDATA") or str(Path.home())
    path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_dir() -> Path:
    path = app_dir() / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


SETTINGS_PATH = app_dir() / "settings.json"

# name -> (标签, 主色, 弱化色, 渐变起点, 渐变中点, 渐变终点)
THEMES: dict[str, dict[str, str]] = {
    "aurora": {
        "label": "极光",
        "base": "#ffffff",
        "dim": "#9aa4b8",
        "c1": "#7dd3fc",
        "c2": "#a78bfa",
        "c3": "#f0abfc",
        "glow": "#38bdf8",
    },
    "sakura": {
        "label": "樱花",
        "base": "#ffffff",
        "dim": "#b8a3ad",
        "c1": "#fecdd3",
        "c2": "#fb7185",
        "c3": "#f472b6",
        "glow": "#fb7185",
    },
    "sunset": {
        "label": "落日",
        "base": "#ffffff",
        "dim": "#b3a394",
        "c1": "#fde68a",
        "c2": "#fbbf24",
        "c3": "#fb7185",
        "glow": "#fbbf24",
    },
    "jade": {
        "label": "青竹",
        "base": "#ffffff",
        "dim": "#93a89f",
        "c1": "#6ee7b7",
        "c2": "#34d399",
        "c3": "#22d3ee",
        "glow": "#34d399",
    },
    "ink": {
        "label": "素白",
        "base": "#ffffff",
        "dim": "#a8adba",
        "c1": "#e5e7eb",
        "c2": "#ffffff",
        "c3": "#ffffff",
        "glow": "#cbd5e1",
    },
}

THEME_ORDER = ["aurora", "sakura", "sunset", "jade", "ink"]

# 歌词宽度的可调范围：clamp()、「自定义宽度…」对话框、设置窗口的滑动条
# 都从这里取，避免以后三处对不上。
# 语义：width = 歌词**实际能画文字**的像素宽（不含 MARGIN / PAD / 倾斜余量）。
WIDTH_MIN, WIDTH_MAX = 240, 1440
# 唱片/播放器面板的宽度（分离面板里那半边），单独一套；0 = 自动（跟随封面）
PLAYER_WIDTH_MIN, PLAYER_WIDTH_MAX = 240, 1440
# 歌词字间距（px）：正数拉开、负数收紧
LETTER_SPACING_MIN, LETTER_SPACING_MAX = -2.0, 12.0
# 旧版 width 是「窗口宽」口径，迁移到新口径时减掉左右两个 PAD。
# （window.PAD = 20；这里不 import window 是为了避免 config → window 循环依赖）
LEGACY_WIDTH_SHIFT = 40

# 界面语言："" 跟随系统 / zh_CN 中文 / en English
LANGUAGES = ("", "zh_CN", "en")

# 设置窗口自己的外观：auto 跟随歌词主题 / dark 深色 / light 浅色
DIALOG_THEMES = ("auto", "dark", "light")


@dataclass
class Settings:
    """所有可调参数。保存为 JSON。"""

    theme: str = "aurora"
    # 1.6.8 起桌面显示由下面两个开关派生，mode 只用于老配置迁移
    show_lyrics: bool = True
    show_player: bool = False
    show_title: bool = True
    show_wave: bool = True
    font_family: str = "Microsoft YaHei UI"
    font_size: int = 38
    opacity: float = 0.90
    background: bool = True
    cover_size: int = 88
    show_cover: bool = True
    show_progress: bool = True
    show_controls: bool = True
    lyric_lines: int = 5
    album_shape: str = "disc"
    # 1.6.8 起合并进 album_shape，字段仅为老配置反序列化保留
    depth_album_style: str = "classic"
    # 分离面板模式下的两套位置（-1 表示用默认位置：右上一个、右上下方一个）
    player_pos: list = field(default_factory=lambda: [-1, -1])
    lyrics_pos: list = field(default_factory=lambda: [-1, -1])
    raise_style: str = "frost"
    raise_opacity: float = 1.0
    text_tilt: float = 0.0
    text_depth_v: float = 0.0
    text_depth_h: float = 0.32
    ui_opacity: float = 1.0
    line_spacing: float = 1.0
    # 纯歌词面板：顶部显示歌名 / 作者 / 热度
    show_song_info: bool = True
    # 歌词排版：left 左对齐 / center 居中 / right 右对齐（默认和以前一样靠右）
    lyric_align: str = "right"
    # 打开音乐软件时自动把歌词显示出来
    auto_show_on_music: bool = True
    # B 站客户端字幕（需要先用「启动B站歌词模式」脚本带调试端口打开 B 站）
    bili_mode: bool = False
    tray_hint_shown: bool = False
    # 已不对外暴露（设置窗口里删掉了「显示上一首/下一首按钮」两个开关，
    # 统一由 show_controls 控制整条播放控制）。字段保留是为了老 settings.json
    # 反序列化不出缺口，渲染端仍会读它们。
    show_prev: bool = False
    show_next: bool = True
    width: int = 380
    # 歌词字间距（px）：正数拉开、负数收紧。0 = 默认
    letter_spacing: float = 0.0
    # 唱片/播放器面板宽度：0 = 自动（按封面尺寸算），>= PLAYER_WIDTH_MIN 才生效
    player_width: int = 0
    # 设置窗口的语言与外观（只影响设置窗口本身）
    language: str = ""
    dialog_theme: str = "auto"
    x: int = -1
    y: int = -1
    locked: bool = False
    click_through: bool = False
    always_on_top: bool = False
    offset_ms: int = 0
    # 每首歌单独记的偏移：{"歌名|歌手": 毫秒}。
    # 有的歌歌词是另一个版本的（整体差几秒），调好之后不该影响别的歌，
    # 所以按歌记；没记过的歌用上面的 offset_ms 当默认值。
    song_offsets: dict = field(default_factory=dict)
    # 设置文件的格式版本：2 起偏移才是「一歌一记」。
    # 老文件没有这个字段，用来判断要不要把遗留的全局偏移清掉。
    settings_version: int = 4
    preferred_player: str = ""
    # 检查更新的来源：owner/repo、gitee:owner/repo、http(s) 链接或本地 json 路径
    update_source: str = ""
    # 上次静默自查更新的时间戳（秒），24 小时内不重复查
    update_last_check: float = 0.0
    # 已发现但尚未安装的新版本；持久化后重启也不会丢提示
    update_pending_version: str = ""
    update_pending_notes: str = ""
    update_pending_url: str = ""
    update_pending_installer: str = ""

    # ---------- 持久化 ----------

    # 「恢复默认」时要保留下来的字段：都是用户自己的数据，不是外观设置。
    # 尤其是 song_offsets —— 漏掉它会把用户逐首调好的歌词偏移全清掉。
    # 用 ClassVar 标注：它不是 dataclass 字段，不会被写进 settings.json，
    # 也就不会因为配置文件里有同名键而把保留名单冲掉。
    KEEP_ON_RESET: ClassVar[tuple[str, ...]] = (
        "x",
        "y",
        "player_pos",
        "lyrics_pos",
        "song_offsets",
        "tray_hint_shown",
        "settings_version",
        "update_source",
        "update_last_check",
        "update_pending_version",
        "update_pending_notes",
        "update_pending_url",
        "update_pending_installer",
        "preferred_player",
    )

    @classmethod
    def load(cls) -> "Settings":
        obj = cls()
        try:
            raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return obj
        known = {f.name for f in fields(cls)}
        for key, value in raw.items():
            if key in known:
                setattr(obj, key, value)
        # 旧版本用 text_axis 表示单一方向，迁移成两个独立景深
        axis = raw.get("text_axis")
        if axis and "text_depth_v" not in raw and "text_depth_h" not in raw:
            legacy = float(raw.get("text_depth", 0.18) or 0.0)
            if axis == "vertical":
                obj.text_depth_v = legacy
                obj.text_depth_h = 0.0
            else:
                obj.text_depth_h = legacy
                obj.text_depth_v = 0.0
        # 老版本的偏移是「全局」的，用户多半只是为了修某一首歌临时调的。
        # 升级到「一歌一记」之后，这个残留值会悄悄套到每一首歌上
        # （实测有人留下 -6100 ms，结果所有歌的歌词都提前 6 秒），
        # 所以老设置文件里的这个值直接清零，从默认 0 重新开始。
        # 判断依据是「有没有 settings_version」—— 新版本保存时会写上，
        # 所以只有从旧版升级上来的文件会被清一次，之后用户自己设的
        # 默认值不会被误清。
        if "settings_version" not in raw and obj.offset_ms and not obj.song_offsets:
            obj.offset_ms = 0
        # 版本 3：width 的含义从「窗口宽」改成「歌词可用宽」。
        # 老用户按 2×PAD 减一下，歌词的视觉宽度不变（窗口总宽也不变）。
        try:
            version = int(raw.get("settings_version", 2))
        except (TypeError, ValueError):
            version = 2
        if version < 3:
            obj.width = max(WIDTH_MIN, int(raw.get("width", obj.width)) - LEGACY_WIDTH_SHIFT)
        # 版本 4：界面模式拆成两个显示开关，旧立体卡片样式并入 album_shape
        if version < 4:
            mode = str(raw.get("mode", "lyrics"))
            obj.show_lyrics = mode in ("lyrics", "split", "depth3d", "compact")
            obj.show_player = mode in ("album", "split", "depth3d", "player")
            if mode == "depth3d":
                obj.album_shape = {
                    "classic": "classic",
                    "vinyl": "vinyl",
                    "cover_vinyl": "square",
                }.get(str(raw.get("depth_album_style", "classic")), "classic")
        # 迁移完之后写回当前格式号，否则每次启动都会再迁移一次
        obj.settings_version = 4
        obj.clamp()
        return obj

    def save(self) -> None:
        self.clamp()
        try:
            SETTINGS_PATH.write_text(
                json.dumps(asdict(self), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def clamp(self) -> None:
        # 这些范围要和「设置」窗口里的滑动条一一对应（见 settings_dialog.py），
        # 两边不一致就会出现「拖到头了但值没变」的怪现象。
        self.show_lyrics = bool(self.show_lyrics)
        self.show_player = bool(self.show_player)
        self.show_title = bool(self.show_title)
        self.show_wave = bool(self.show_wave)
        self.font_size = max(12, min(200, int(self.font_size)))
        self.width = max(WIDTH_MIN, min(WIDTH_MAX, int(self.width)))
        self.letter_spacing = max(
            LETTER_SPACING_MIN, min(LETTER_SPACING_MAX, float(self.letter_spacing))
        )
        player = int(self.player_width)
        self.player_width = (
            0 if player <= 0 else max(PLAYER_WIDTH_MIN, min(PLAYER_WIDTH_MAX, player))
        )
        if self.language not in LANGUAGES:
            self.language = ""
        if self.dialog_theme not in DIALOG_THEMES:
            self.dialog_theme = "auto"
        self.opacity = max(0.25, min(1.0, float(self.opacity)))
        # 允许 ±30 秒：不同版本的歌，开头/结尾长度差几秒是常有的事
        self.offset_ms = max(-30000, min(30000, int(self.offset_ms)))
        if not isinstance(self.song_offsets, dict):
            self.song_offsets = {}
        cleaned: dict[str, int] = {}
        for key, value in self.song_offsets.items():
            try:
                millis = max(-30000, min(30000, int(value)))
            except (TypeError, ValueError):
                continue
            if millis:
                cleaned[str(key)[:200]] = millis
        # 记太多没意义，只留最近的 300 首
        while len(cleaned) > 300:
            cleaned.pop(next(iter(cleaned)))
        self.song_offsets = cleaned
        self.cover_size = max(40, min(320, int(self.cover_size)))
        if self.theme not in THEMES:
            self.theme = "aurora"
        self.lyric_lines = max(1, min(15, int(self.lyric_lines)))
        for name in ("player_pos", "lyrics_pos"):
            value = getattr(self, name)
            if not isinstance(value, (list, tuple)) or len(value) != 2:
                setattr(self, name, [-1, -1])
        self.text_tilt = max(-90.0, min(90.0, float(self.text_tilt)))
        # 允许负值 —— 负号代表反方向（右窄左宽 / 下窄上宽）
        self.text_depth_v = max(-0.80, min(0.80, float(self.text_depth_v)))
        self.text_depth_h = max(-0.80, min(0.80, float(self.text_depth_h)))
        self.raise_opacity = max(0.0, min(1.5, float(self.raise_opacity)))
        self.ui_opacity = max(0.05, min(1.0, float(self.ui_opacity)))
        self.line_spacing = max(0.50, min(3.00, float(self.line_spacing)))
        if self.lyric_align not in ("left", "center", "right"):
            self.lyric_align = "right"
        if self.raise_style not in ("frost", "ambient", "outline"):
            self.raise_style = "frost"
        if self.album_shape not in ("disc", "square", "vinyl", "classic"):
            self.album_shape = "disc"
        self.update_source = str(self.update_source or "").strip()

    def reset(self) -> None:
        """把外观类设置恢复成出厂默认，用户自己的数据原样保留。

        保留的是位置、每首歌的歌词偏移、更新源这些「用出来的东西」，
        其余（主题、模式、字号、倾斜……）全部回到 Settings() 的默认值。
        """
        defaults = asdict(Settings())
        for name, value in defaults.items():
            if name in self.KEEP_ON_RESET:
                continue
            setattr(self, name, value)
        self.clamp()

    # ---------- 便捷访问 ----------

    def offset_for(self, key: str) -> int:
        """这首歌的偏移（没单独设过就用全局默认值）。"""
        if key and key in self.song_offsets:
            return int(self.song_offsets[key])
        return int(self.offset_ms)

    def set_offset_for(self, key: str, value: int) -> None:
        """给这首歌单独设偏移；value 归零就等于恢复默认。"""
        millis = max(-30000, min(30000, int(value)))
        if not key:
            self.offset_ms = millis
            return
        if millis:
            self.song_offsets[key] = millis
        else:
            self.song_offsets.pop(key, None)

    @property
    def colors(self) -> dict[str, str]:
        return THEMES.get(self.theme, THEMES["aurora"])

    @property
    def theme_label(self) -> str:
        return self.colors["label"]
