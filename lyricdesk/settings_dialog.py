"""设置窗口：左边分类、右边内容的一份正经设置界面。

以前所有开关都挤在右键菜单里，档位又少（「歌词字号」只有 5 档），
这里把全部可调项收进来，倾斜 / 尺寸这类改成能自由拖动的滑动条，
拖着就能看到桌面歌词实时变化。

这个模块**不 import window.py**：宿主窗口用鸭子类型传进来（提供 `.settings`
和一堆 `_set_xxx` 方法），否则两边互相 import 会成环。窗口那边也是在
方法内部才 import 本模块。

本文件里的界面文案全部走 `i18n.tr()`，切换语言时用 `retranslate()` 把已经
建好的控件重刷一遍（不重建窗口，免得丢掉滚动位置和选中项）。
"""

from __future__ import annotations

import re
import sys

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .autostart import is_enabled
from .config import (
    THEMES,
    THEME_ORDER,
    WIDTH_MAX,
    WIDTH_MIN,
    Settings,
    app_dir,
    cache_dir,
)
from .fonts import BUNDLED_FONTS, ONLINE_FONTS, RECOMMENDED, family_for, imported_fonts
from .i18n import set_language, tr
from .smtc import friendly_player_name
from .update import homepage_url, releases_url

# 每个歌词主题一套「设置窗口个性」配色（深浅各一份）。
# 为什么不按主题自动算色：极光和樱花都靠 c1/c2 混色的话，出来是一堆"淡蓝淡粉"，
# 差别很小；手写一遍反而更稳、更好看，也能照顾对比度。
#
# 字段含义（每个主题两套都要给全）：
#   bg          窗口背景            panel     列表 / 输入框底
#   card        分组卡片底          text      正文        text_dim  次要文字
#   line        分隔线 / 边框       accent    强调色      accent2   渐变终点
#   accent_soft 强调色淡底（选中 / 悬停）        on_accent 压在 accent 上的文字色
_DIALOG_PALETTE: dict[str, dict[str, dict[str, str]]] = {
    # 极光：冷调、青 → 紫
    "aurora": {
        "dark": {
            "bg": "#161b26", "panel": "#10141d", "card": "#1d2331",
            "text": "#d6e2f5", "text_dim": "#8b9ab5", "line": "#2b3547",
            "accent": "#38bdf8", "accent2": "#a78bfa", "accent_soft": "#22314a",
        },
        "light": {
            "bg": "#f2f6fd", "panel": "#ffffff", "card": "#ffffff",
            "text": "#1f2b40", "text_dim": "#66748c", "line": "#d6dded",
            "accent": "#0f8fcd", "accent2": "#7a5af5", "accent_soft": "#e2eefb",
        },
    },
    # 樱花：暖粉、柔
    "sakura": {
        "dark": {
            "bg": "#221a20", "panel": "#1a1319", "card": "#2b2029",
            "text": "#f6e2ea", "text_dim": "#b39aa6", "line": "#402e39",
            "accent": "#fb7185", "accent2": "#f472b6", "accent_soft": "#3a2433",
        },
        "light": {
            "bg": "#fdf4f6", "panel": "#ffffff", "card": "#ffffff",
            "text": "#3a2630", "text_dim": "#8a6b78", "line": "#f0d7de",
            "accent": "#d94460", "accent2": "#c33f8f", "accent_soft": "#fbe3ea",
        },
    },
    # 落日：琥珀橙
    "sunset": {
        "dark": {
            "bg": "#241d16", "panel": "#1b1510", "card": "#2d241b",
            "text": "#f7e8d5", "text_dim": "#b7a186", "line": "#43362a",
            "accent": "#fbbf24", "accent2": "#fb7185", "accent_soft": "#3d2f1e",
        },
        "light": {
            "bg": "#fdf7ee", "panel": "#ffffff", "card": "#ffffff",
            "text": "#3b2f1f", "text_dim": "#8b7a63", "line": "#efdfc9",
            "accent": "#b8791a", "accent2": "#c9553f", "accent_soft": "#fbeed6",
        },
    },
    # 青竹：青绿
    "jade": {
        "dark": {
            "bg": "#141d1b", "panel": "#0f1614", "card": "#1b2624",
            "text": "#d8ece6", "text_dim": "#8bada4", "line": "#273a35",
            "accent": "#34d399", "accent2": "#22d3ee", "accent_soft": "#1d3a33",
        },
        "light": {
            "bg": "#f1f8f5", "panel": "#ffffff", "card": "#ffffff",
            "text": "#1e332c", "text_dim": "#657f76", "line": "#d3e6de",
            "accent": "#0f9c6d", "accent2": "#0e8f9e", "accent_soft": "#ddf1e8",
        },
    },
    # 素白：极简、几乎无色相，靠留白和细线做质感（不要加彩色）
    "ink": {
        "dark": {
            "bg": "#17181b", "panel": "#121316", "card": "#1e2024",
            "text": "#e7e8ec", "text_dim": "#9a9ca4", "line": "#2c2e34",
            "accent": "#8a93a6", "accent2": "#c8ccd6", "accent_soft": "#26282e",
        },
        "light": {
            "bg": "#f6f7f9", "panel": "#ffffff", "card": "#ffffff",
            "text": "#2b3140", "text_dim": "#7a8397", "line": "#dcdfe6",
            "accent": "#6f798c", "accent2": "#aeb4c0", "accent_soft": "#eceef2",
        },
    },
}

_DEFAULT_THEME = "aurora"


def _relative_luminance(color: QColor) -> float:
    """WCAG 相对亮度（sRGB 先转线性再按 0.2126/0.7152/0.0722 加权）。"""

    def channel(value: int) -> float:
        s = value / 255.0
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    return (
        0.2126 * channel(color.red())
        + 0.7152 * channel(color.green())
        + 0.0722 * channel(color.blue())
    )


def _readable_on(color: QColor) -> QColor:
    """压在该颜色上的文字用黑还是白：两种都算一遍，用对比度高的那个。

    （不用「亮度阈值」那种近似：浅蓝、浅粉这类颜色用阈值判断经常选错，
    直接比对比度最稳，也顺带保证浅色主题上不会出现白字压浅底。）
    """
    dark = QColor("#0b1020")
    light = QColor("#ffffff")
    base = _relative_luminance(color)

    def ratio(other: QColor) -> float:
        lo, hi = sorted((base, _relative_luminance(other)))
        return (hi + 0.05) / (lo + 0.05)

    return dark if ratio(dark) >= ratio(light) else light


def palette_for(theme: str, mode: str) -> dict[str, str]:
    """取该主题的调色板；缺项用默认主题补齐（不要 KeyError）。

    `on_accent` 不手写，按 accent 的亮度算出来，避免"浅色主题上白字看不清"。
    """
    mode = "light" if str(mode).strip().lower() == "light" else "dark"
    palettes = _DIALOG_PALETTE.get(str(theme or "").strip()) or _DIALOG_PALETTE[_DEFAULT_THEME]
    palette = dict(palettes.get(mode) or palettes.get("dark") or {})
    for key, value in _DIALOG_PALETTE[_DEFAULT_THEME][mode].items():
        palette.setdefault(key, value)
    palette["on_accent"] = _readable_on(QColor(palette["accent"])).name()
    return palette


def _style_context(theme: str, mode: str) -> dict[str, str]:
    """调色板 + 几个按深浅推出来的值，供模板替换用。"""
    palette = palette_for(theme, mode)
    disabled = QColor(palette["text_dim"])
    disabled.setAlpha(150)
    # 素白不要彩色标题带（纯白渐变看不见），用一条淡灰细线代替
    if str(theme or "").strip() == "ink":
        titlebar = f"background: {palette['line']};"
    else:
        titlebar = (
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
            f"stop:0 {palette['accent']}, stop:1 {palette['accent2']});"
        )
    context = {key.upper(): value for key, value in palette.items()}
    context["TITLEBAR"] = titlebar
    context["WARN"] = "#fbbf24" if mode == "dark" else "#b45309"
    context["DISABLED"] = (
        f"rgba({disabled.red()}, {disabled.green()}, {disabled.blue()}, {disabled.alpha()})"
    )
    # 滑块圆钮：深色皮肤上要够亮，浅色皮肤上用白钮 + 彩色描边
    context["HANDLE"] = palette["text"] if mode == "dark" else "#ffffff"
    context["HANDLE_HOVER"] = "#ffffff" if mode == "dark" else "#f2f5fb"
    return context


def _render(template: str, context: dict[str, str]) -> str:
    style = template
    for key, value in context.items():
        style = style.replace(f"%{key}%", value)
    return style


# 两个皮肤模板：所有颜色都是占位符，由主题调色板（+ 深浅）填。
# 深色是原来那套结构，浅色是同一套结构换底色。
_DARK_STYLE = """
QDialog { background: %BG%; }
QLabel { color: %TEXT%; }
QLabel#section {
    color: %TEXT_DIM%; font-size: 12px; font-weight: 600;
    padding-top: 8px; padding-bottom: 2px;
}
QLabel#hint { color: %TEXT_DIM%; font-size: 12px; }
QLabel#warn { color: %WARN%; font-size: 12px; font-weight: 600; }
QLabel#value { color: %TEXT_DIM%; font-size: 12px; }
QLabel#link { color: %ACCENT%; font-size: 12px; }
QLabel#hotkey {
    color: %TEXT%; font-size: 12px;
    font-family: Consolas, "Cascadia Mono", monospace;
}
/* 顶部主题色标题带：一眼看出现在用的是哪个主题 */
QFrame#titlebar { %TITLEBAR% border-radius: 2px; }
/* 分组卡片（快捷键表、鼠标穿透提示） */
QFrame#card { background: %CARD%; border: 1px solid %LINE%; border-radius: 10px; }
QListWidget {
    background: %PANEL%; border: 1px solid %LINE%; border-radius: 10px;
    padding: 6px; outline: none; color: %TEXT%; font-size: 13px;
}
QListWidget::item {
    padding: 9px 10px; border-radius: 8px;
    border-left: 4px solid transparent;
}
QListWidget::item:hover { background: %ACCENT_SOFT%; }
QListWidget::item:selected {
    background: %ACCENT_SOFT%; color: %ACCENT%;
    border-left: 4px solid %ACCENT%;
}
QScrollArea { background: transparent; border: none; }
QWidget#page { background: transparent; }
QSlider::groove:horizontal { height: 6px; background: %LINE%; border-radius: 3px; }
QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 %ACCENT%, stop:1 %ACCENT2%);
    border-radius: 3px;
}
QSlider::handle:horizontal {
    width: 15px; margin: -6px 0; border-radius: 8px;
    background: %HANDLE%; border: 1px solid %ACCENT%;
}
QSlider::handle:horizontal:hover { background: %HANDLE_HOVER%; }
QSlider:disabled::sub-page:horizontal { background: %LINE%; }
QPushButton {
    background: %CARD%; color: %TEXT%; border: 1px solid %LINE%;
    border-radius: 8px; padding: 6px 14px;
}
QPushButton:hover { background: %ACCENT_SOFT%; color: %ACCENT%; }
QPushButton:pressed { background: %PANEL%; }
QPushButton:disabled { color: %DISABLED%; border-color: %LINE%; background: %PANEL%; }
QPushButton#danger { border-color: %ACCENT2%; color: %ACCENT2%; }
QComboBox, QDoubleSpinBox {
    background: %CARD%; color: %TEXT%; border: 1px solid %LINE%;
    border-radius: 8px; padding: 4px 8px; min-height: 18px;
}
QComboBox:focus, QDoubleSpinBox:focus { border: 1px solid %ACCENT%; }
QComboBox:disabled, QDoubleSpinBox:disabled { color: %DISABLED%; }
QComboBox::drop-down { border: none; width: 20px; }
/* 数值框不要那两个小箭头按钮：滑块调、键盘方向键微调、直接输入都行，
   省下来的宽度留给数字本身（箭头按钮在这个 Qt 皮肤下画不好看） */
QDoubleSpinBox { padding-right: 6px; }
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    width: 0; border: none; background: transparent;
}
QComboBox QAbstractItemView {
    background: %CARD%; color: %TEXT%;
    selection-background-color: %ACCENT_SOFT%; border: 1px solid %LINE%;
}
QCheckBox { color: %TEXT%; spacing: 8px; }
QCheckBox:disabled { color: %DISABLED%; }
QCheckBox::indicator {
    width: 15px; height: 15px; border-radius: 4px;
    border: 1px solid %LINE%; background: %CARD%;
}
/* 勾选符号的颜色 Qt 不接受 QSS 设置，这里用 on_accent 描边保证"勾上了"看得出来 */
QCheckBox::indicator:checked { background: %ACCENT%; border: 1px solid %ON_ACCENT%; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: %ACCENT_SOFT%; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: %ACCENT%; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
"""

_LIGHT_STYLE = """
QDialog { background: %BG%; }
QLabel { color: %TEXT%; }
QLabel#section {
    color: %TEXT_DIM%; font-size: 12px; font-weight: 600;
    padding-top: 8px; padding-bottom: 2px;
}
QLabel#hint { color: %TEXT_DIM%; font-size: 12px; }
QLabel#warn { color: %WARN%; font-size: 12px; font-weight: 600; }
QLabel#value { color: %TEXT_DIM%; font-size: 12px; }
QLabel#link { color: %ACCENT%; font-size: 12px; }
QLabel#hotkey {
    color: %TEXT%; font-size: 12px;
    font-family: Consolas, "Cascadia Mono", monospace;
}
QFrame#titlebar { %TITLEBAR% border-radius: 2px; }
QFrame#card { background: %CARD%; border: 1px solid %LINE%; border-radius: 10px; }
QListWidget {
    background: %PANEL%; border: 1px solid %LINE%; border-radius: 10px;
    padding: 6px; outline: none; color: %TEXT%; font-size: 13px;
}
QListWidget::item {
    padding: 9px 10px; border-radius: 8px;
    border-left: 4px solid transparent;
}
QListWidget::item:hover { background: %ACCENT_SOFT%; }
QListWidget::item:selected {
    background: %ACCENT_SOFT%; color: %ACCENT%;
    border-left: 4px solid %ACCENT%;
}
QScrollArea { background: transparent; border: none; }
QWidget#page { background: transparent; }
QSlider::groove:horizontal { height: 6px; background: %LINE%; border-radius: 3px; }
QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 %ACCENT%, stop:1 %ACCENT2%);
    border-radius: 3px;
}
QSlider::handle:horizontal {
    width: 15px; margin: -6px 0; border-radius: 8px;
    background: %HANDLE%; border: 1px solid %ACCENT%;
}
QSlider::handle:horizontal:hover { background: %HANDLE_HOVER%; }
QSlider:disabled::sub-page:horizontal { background: %LINE%; }
QPushButton {
    background: %CARD%; color: %TEXT%; border: 1px solid %LINE%;
    border-radius: 8px; padding: 6px 14px;
}
QPushButton:hover { background: %ACCENT_SOFT%; color: %ACCENT%; }
QPushButton:pressed { background: %ACCENT_SOFT%; }
QPushButton:disabled { color: %DISABLED%; border-color: %LINE%; background: %BG%; }
QPushButton#danger { border-color: %ACCENT2%; color: %ACCENT2%; }
QComboBox, QDoubleSpinBox {
    background: %PANEL%; color: %TEXT%; border: 1px solid %LINE%;
    border-radius: 8px; padding: 4px 8px; min-height: 18px;
}
QComboBox:focus, QDoubleSpinBox:focus { border: 1px solid %ACCENT%; }
QComboBox:disabled, QDoubleSpinBox:disabled { color: %DISABLED%; }
QComboBox::drop-down { border: none; width: 20px; }
QDoubleSpinBox { padding-right: 6px; }
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    width: 0; border: none; background: transparent;
}
QComboBox QAbstractItemView {
    background: %PANEL%; color: %TEXT%;
    selection-background-color: %ACCENT_SOFT%; border: 1px solid %LINE%;
}
QCheckBox { color: %TEXT%; spacing: 8px; }
QCheckBox:disabled { color: %DISABLED%; }
QCheckBox::indicator {
    width: 15px; height: 15px; border-radius: 4px;
    border: 1px solid %LINE%; background: %PANEL%;
}
QCheckBox::indicator:checked { background: %ACCENT%; border: 1px solid %ON_ACCENT%; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: %ACCENT_SOFT%; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: %ACCENT%; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
"""

# 「设置窗口外观」选 auto 时，哪些歌词主题算浅色 → 设置窗口也走浅色。
# 判断依据很简单：素白（ink）整套配色都是白/浅灰，用深色皮肤会跟歌词本身不搭。
# 若以后想让更多主题走浅色，往这个集合里加名字即可。
_LIGHT_LYRIC_THEMES = {"ink"}


def resolve_dialog_theme(setting: str, lyric_theme: str) -> str:
    """把设置里的 dialog_theme 解析成实际用的 dark / light。"""
    value = str(setting or "auto").strip().lower()
    if value in ("dark", "light"):
        return value
    return "light" if lyric_theme in _LIGHT_LYRIC_THEMES else "dark"


def build_style(mode: str, theme: str) -> str:
    """按主题生成设置窗口的样式表。

    mode: dark / light（深浅）；theme: 歌词主题名（色相与个性，见 _DIALOG_PALETTE）。
    两者组合共 5×2 = 10 套外观。
    """
    mode = "light" if str(mode).strip().lower() == "light" else "dark"
    template = _LIGHT_STYLE if mode == "light" else _DARK_STYLE
    style = _render(template, _style_context(theme, mode))

    leftovers = sorted(set(re.findall(r"%[A-Z_0-9]+%", style)))
    if leftovers:
        # 漏替换会让 Qt 整套样式解析失败（界面变回系统默认丑样式），
        # 所以这里兜底成默认主题的同一套皮肤，宁可少点个性也不能整段失效。
        print(
            f"[设置窗口] 样式表里有没替换的占位符：{leftovers}（已回退默认皮肤）",
            file=sys.stderr,
        )
        style = _render(_DARK_STYLE, _style_context(_DEFAULT_THEME, "dark"))
    return style


# 「窗口与交互」里的快捷键表：(左列 key, 左列原文, 右列 key, 右列原文)
# 这两段长文案当 tr() 的兜底原文（万一翻译表漏了也不会显示成空）
CLICK_WARN_DEFAULT = (
    "⚠ 鼠标穿透已开启：歌词窗口不响应鼠标，位置也已锁定。\n"
    "关掉它：点下面的按钮，或者按 Ctrl + Alt + L，"
    "或者右键任务栏托盘图标 → 鼠标穿透。"
)
ABOUT_DEFAULT = (
    "桌面歌词  v{version}\n"
    "把正在播放的歌词实时显示在桌面上，读取的是 Windows 系统媒体控制，不挑播放器。"
)

SHORTCUT_ROWS: tuple[tuple[str, str, str, str], ...] = (
    ("Ctrl + ,", "Ctrl + ,", "shortcut.open_settings.desc", "打开设置窗口"),
    (
        "Ctrl + Alt + L",
        "Ctrl + Alt + L",
        "shortcut.click_through.desc",
        "切换鼠标穿透（穿透后窗口点不动，这是唯一的救急键）",
    ),
    ("shortcut.drag", "左键拖动窗口", "shortcut.drag.desc", "移动窗口位置（自动记住）"),
    (
        "shortcut.double_click",
        "双击窗口空白处",
        "shortcut.double_click.desc",
        "锁定 / 解锁位置",
    ),
    (
        "shortcut.cover_drag",
        "单击封面左侧区域",
        "shortcut.cover_drag.desc",
        "直接拖动，不会误触按钮",
    ),
    ("shortcut.right_click", "右键", "shortcut.right_click.desc", "打开常用操作菜单"),
    (
        "shortcut.tray_double",
        "托盘图标双击",
        "shortcut.tray_double.desc",
        "显示 / 隐藏歌词",
    ),
    (
        "shortcut.tray_right",
        "托盘图标右键",
        "shortcut.tray_right.desc",
        "同右键菜单（含「隐藏/显示歌词」）",
    ),
)


class _NoWheelSlider(QSlider):
    """没聚焦时把滚轮让出去：鼠标划过不应该就把数值改了。"""

    def wheelEvent(self, event) -> None:  # noqa: N802
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class _NoWheelSpin(QDoubleSpinBox):
    """同上，数值框也不抢滚轮。"""

    def wheelEvent(self, event) -> None:  # noqa: N802
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class _ValueSpin(_NoWheelSpin):
    """正数带 + 号的数值框（倾斜看方向要靠它）。"""

    def __init__(self, *, signed: bool = False, decimals: int = 0, parent=None) -> None:
        super().__init__(parent)
        self._signed = signed
        self.setDecimals(int(decimals))
        self.setKeyboardTracking(False)
        self.setGroupSeparatorShown(False)

    def textFromValue(self, value: float) -> str:  # noqa: N802
        text = f"{value:.{self.decimals()}f}"
        if self._signed and value > 0:
            text = "+" + text
        return text


class _DblLabel(QLabel):
    """双击恢复该项默认值。"""

    def __init__(self, text: str, on_double_click, tooltip: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self._on_double_click = on_double_click
        if tooltip:
            self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self._on_double_click()
        event.accept()


class SliderRow(QWidget):
    """一条「标题 + 滑动条 + 数值框」的设置行。

    Qt 的滑块只有整数刻度，所以小数项统一按 `刻度 = 数值 / step` 换算，
    写回时再乘回去 —— 拖动滑块不会把 0.32 变成 0.3。

    `on_change` 收到的是**显示单位**的值（比如整体不透明度是 5~100 的百分数），
    换算成真实字段由调用方负责。
    """

    def __init__(
        self,
        title: str,
        *,
        minimum: float,
        maximum: float,
        step: float,
        value: float,
        default: float,
        on_change,
        unit: str = "",
        decimals: int = 0,
        signed: bool = False,
        coalesce_ms: int = 0,
        tooltip: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.title_text = title
        self.minimum = float(minimum)
        self.maximum = float(maximum)
        self._step = float(step)
        self._default = float(default)
        self._on_change = on_change
        self._pending: float | None = None
        self._silent = False

        ticks_min = int(round(float(minimum) / self._step))
        ticks_max = int(round(float(maximum) / self._step))

        self.label = _DblLabel(title, self.reset_default, tooltip)
        self.label.setFixedWidth(96)

        self.slider = _NoWheelSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(ticks_min, ticks_max)
        self.slider.setSingleStep(1)
        self.slider.setPageStep(max(1, (ticks_max - ticks_min) // 10))
        self.slider.setValue(self._to_ticks(value))
        self.slider.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.spin = _ValueSpin(signed=signed, decimals=decimals)
        self.spin.setRange(float(minimum), float(maximum))
        self.spin.setSingleStep(self._step)
        self.spin.setValue(float(max(minimum, min(maximum, value))))
        if unit:
            self.spin.setSuffix(f" {unit}")
        self.spin.setFixedWidth(100)
        self.spin.setAlignment(Qt.AlignmentFlag.AlignCenter)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        row.addWidget(self.label)
        row.addWidget(self.slider, 1)
        row.addWidget(self.spin)

        self._timer: QTimer | None = None
        if coalesce_ms:
            # 宽度 / 字号这类每次都要重算字体度量，拖动时先攒一下再落地
            self._timer = QTimer(self)
            self._timer.setSingleShot(True)
            self._timer.setInterval(int(coalesce_ms))
            self._timer.timeout.connect(self._flush)

        self.slider.valueChanged.connect(self._from_slider)
        self.slider.sliderReleased.connect(self._flush)
        self.spin.valueChanged.connect(self._from_spin)

    # ---------- 换算 ----------

    def _to_ticks(self, value: float) -> int:
        return int(round(float(value) / self._step))

    def _from_ticks(self, ticks: int) -> float:
        # 用 round 收一下浮点误差：0.05 × 7 = 0.35000000000000003
        return round(ticks * self._step, 6)

    # ---------- 交互 ----------

    def _from_slider(self, ticks: int) -> None:
        value = self._from_ticks(ticks)
        self._silent = True
        self.spin.setValue(value)
        self._silent = False
        self._send(value)

    def _from_spin(self, value: float) -> None:
        if self._silent:
            return
        self._silent = True
        self.slider.setValue(self._to_ticks(value))
        self._silent = False
        self._send(value)

    def _send(self, value: float) -> None:
        if self._timer is not None:
            self._pending = value
            self._timer.start()
        else:
            self._on_change(value)

    def flush(self) -> None:
        """把还没落地的那次改动立刻写回去（松手 / 关窗口时用）。"""
        if self._timer is not None:
            self._timer.stop()
        if self._pending is None:
            return
        value, self._pending = self._pending, None
        self._on_change(value)

    _flush = flush

    def reset_default(self) -> None:
        self.set_value(self._default)
        self._send(self._default)

    def set_value(self, value: float) -> None:
        """外部（比如「恢复默认」）改值，不回头再触发一次写回。"""
        self._silent = True
        self.slider.setValue(self._to_ticks(value))
        self.spin.setValue(float(value))
        self._silent = False

    def set_title(self, text: str) -> None:
        """换语言时重刷标题（双击还原默认值的行为不变）。"""
        self.title_text = text
        self.label.setText(text)

    def set_tooltip(self, text: str) -> None:
        self.label.setToolTip(text)

    def set_unit(self, unit: str) -> None:
        self.spin.setSuffix(f" {unit}" if unit else "")

    def set_dirty_enabled(self, enabled: bool) -> None:
        for widget in (self.label, self.slider, self.spin):
            widget.setEnabled(enabled)


class SettingsDialog(QDialog):
    """程序设置窗口（非模态，改动即时生效）。"""

    # 左侧分类：key 与中文原文
    NAV = (
        ("nav.general", "界面"),
        ("nav.lyrics", "歌词"),
        ("nav.player", "播放"),
        ("nav.window", "窗口与交互"),
        ("nav.update", "更新与关于"),
    )

    def __init__(self, window, parent=None) -> None:
        super().__init__(parent)
        # 宿主是 LyricWindow：这里只按鸭子类型用它，不反向 import
        self.window = window
        self._defaults = Settings()
        self._silent = False
        # 每一项都注册一个「从 settings 读回来刷新界面」的小函数
        self._refreshers: list = []
        # 切语言时要重刷的文案（登记的是「怎么刷」，不是文本本身）
        self._i18n_refresh: list = []
        # 语言一变，字体列表 / 播放器列表里的标签也要重建
        self._i18n_dirty = False
        # 所有滑动条：关窗口前要把没落地的那次改动补上
        self._slider_rows: list[SliderRow] = []
        # 去重用：同一次提交可能连着来好几个 settingsChanged，合并成一帧刷一次
        self._refresh_pending = False
        # 只在特定界面模式下才有意义的控件：[(控件, 允许的模式), ...]
        self._mode_bound: list[tuple[QWidget, tuple[str, ...]]] = []
        # 设置窗口自己是不是常驻置顶：默认**不**置顶，免得占着别的软件
        self._always_on_top = False
        self._style_mode = ""
        self._style_theme = ""

        # 语言：设置里存 "" 表示跟随系统
        set_language(getattr(window.settings, "language", ""))
        self.setWindowTitle(tr("app.title", "设置 · 桌面歌词"))
        self.resize(920, 660)
        self.setMinimumSize(720, 520)
        # 注意：这里**不**给设置窗口套用 settings.ui_opacity，
        # 否则用户把整体不透明度调低后连设置界面都看不清。
        self._build()
        self._apply_theme()
        self.window.settingsChanged.connect(self._on_settings_changed)
        self._refresh()

    # ==================================================================
    # 骨架
    # ==================================================================

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(10)

        # 顶部主题色标题带：五个主题的渐变不一样，一眼能看出现在用的是哪个
        self._titlebar = QFrame()
        self._titlebar.setObjectName("titlebar")
        self._titlebar.setFixedHeight(4)
        outer.addWidget(self._titlebar)

        # 顶部：设置窗口自己的置顶开关
        top = QHBoxLayout()
        top.setSpacing(10)
        self._ontop_box = QCheckBox(self._t("top.always_on_top", "置顶显示"))
        self._ontop_box.setToolTip(
            tr("top.always_on_top.hint", "让设置窗口一直浮在其它程序上面")
        )
        self._bind_text(
            self._ontop_box, "top.always_on_top", "置顶显示"
        )
        self._bind_text(
            self._ontop_box,
            "top.always_on_top.hint",
            "让设置窗口一直浮在其它程序上面",
            "setToolTip",
        )
        self._ontop_box.setChecked(self._always_on_top)
        self._ontop_box.toggled.connect(self._set_always_on_top)
        top.addStretch(1)
        top.addWidget(self._ontop_box)
        outer.addLayout(top)

        body = QHBoxLayout()
        body.setSpacing(12)
        self.nav = QListWidget()
        self.nav.setFixedWidth(150)
        self.nav.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.pages = QStackedWidget()
        body.addWidget(self.nav)
        body.addWidget(self.pages, 1)
        outer.addLayout(body, 1)

        bottom = QHBoxLayout()
        reset_btn = QPushButton(self._t("btn.reset", "恢复默认"))
        self._bind_text(reset_btn, "btn.reset", "恢复默认")
        reset_btn.clicked.connect(self._reset_defaults)
        close_btn = QPushButton(self._t("btn.close", "关闭"))
        self._bind_text(close_btn, "btn.close", "关闭")
        close_btn.clicked.connect(self.close)
        bottom.addWidget(reset_btn)
        bottom.addStretch(1)
        bottom.addWidget(close_btn)
        outer.addLayout(bottom)

        self._page_general()
        self._page_lyrics()
        self._page_player()
        self._page_window()
        self._page_update()

        for key, default in self.NAV:
            self.nav.addItem(tr(key, default))
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.setCurrentRow(0)

    def _page(self, name_key: str, name_default: str) -> QVBoxLayout:
        """新建一个分类页，返回可以往里塞控件的竖直布局。

        分类名统一在 `_build()` 里按 NAV 填（切语言时好重刷），这里不看参数。
        """
        inner = QWidget()
        inner.setObjectName("page")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(6, 4, 8, 4)
        layout.setSpacing(10)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(inner)
        self.pages.addWidget(scroll)
        return layout

    def _t(self, key: str, default: str) -> str:
        """取当前语言下的文案（不登记；要重刷请用 `_bind_text`）。"""
        return tr(key, default)

    def _bind_text(self, widget, key: str, default: str, setter: str = "setText") -> None:
        self._i18n_refresh.append(
            lambda w=widget, s=setter, k=key, d=default: getattr(w, s)(tr(k, d))
        )

    def _section(self, layout: QVBoxLayout, key: str, default: str) -> QLabel:
        label = QLabel(self._t(key, default))
        label.setObjectName("section")
        self._bind_text(label, key, default)
        layout.addSpacing(4)
        layout.addWidget(label)
        return label

    def _hint(self, layout: QVBoxLayout, key: str, default: str, name: str = "hint") -> QLabel:
        label = QLabel(self._t(key, default))
        label.setObjectName(name)
        label.setWordWrap(True)
        self._bind_text(label, key, default)
        layout.addWidget(label)
        return label

    def _card(self, layout: QVBoxLayout) -> QVBoxLayout:
        """一块分组卡片（底色来自主题调色板的 card），返回往卡片里塞控件的布局。"""
        frame = QFrame()
        frame.setObjectName("card")
        inner = QVBoxLayout(frame)
        inner.setContentsMargins(12, 10, 12, 10)
        inner.setSpacing(8)
        layout.addWidget(frame)
        return inner

    # ==================================================================
    # 通用控件
    # ==================================================================

    def _slider(
        self,
        layout: QVBoxLayout,
        key: str,
        default_text: str,
        *,
        getter,
        apply,
        minimum: float,
        maximum: float,
        step: float,
        default: float,
        unit_key: str = "",
        unit: str = "",
        decimals: int = 0,
        signed: bool = False,
        coalesce_ms: int = 0,
    ) -> SliderRow:
        row = SliderRow(
            self._t(key, default_text),
            minimum=minimum,
            maximum=maximum,
            step=step,
            value=getter(),
            default=default,
            on_change=apply,
            unit=tr(unit_key, unit) if unit_key else unit,
            decimals=decimals,
            signed=signed,
            coalesce_ms=coalesce_ms,
            tooltip=tr("slider.reset.tooltip", "双击恢复默认值"),
        )
        self._bind_text(row, key, default_text, "set_title")
        self._bind_text(row, "slider.reset.tooltip", "双击恢复默认值", "set_tooltip")
        if unit_key:
            self._i18n_refresh.append(
                lambda r=row, k=unit_key, d=unit: r.set_unit(tr(k, d))
            )
        layout.addWidget(row)
        self._refreshers.append(lambda r=row, g=getter: r.set_value(g()))
        self._slider_rows.append(row)
        return row

    def _combo(self, layout: QVBoxLayout, key: str, default_text: str, items, getter, apply) -> QComboBox:
        """一行「标题 + 下拉框」。items 是 (文案 key, 文案原文, 取值) 的列表。"""
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        label = QLabel(self._t(key, default_text))
        label.setFixedWidth(96)
        self._bind_text(label, key, default_text)
        combo = QComboBox()
        combo.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        for item_key, item_default, value in items:
            combo.addItem(tr(item_key, item_default), value)
        row.addWidget(label)
        row.addWidget(combo, 1)
        layout.addWidget(holder)

        def changed(_index: int) -> None:
            if self._silent:
                return
            value = combo.currentData()
            if value is not None:
                apply(value)

        combo.currentIndexChanged.connect(changed)

        def refresh_texts() -> None:
            for index, (item_key, item_default, _value) in enumerate(items):
                combo.setItemText(index, tr(item_key, item_default))

        self._i18n_refresh.append(refresh_texts)

        def refresh() -> None:
            self._silent = True
            target = getter()
            index = combo.findData(target)
            if index >= 0:
                combo.setCurrentIndex(index)
            self._silent = False

        self._refreshers.append(refresh)
        return combo

    def _check(
        self,
        layout: QVBoxLayout,
        key: str,
        default_text: str,
        *,
        getter,
        apply,
        hint_key: str = "",
        hint: str = "",
    ) -> QCheckBox:
        box = QCheckBox(self._t(key, default_text))
        box.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        if hint_key:
            box.setToolTip(tr(hint_key, hint))
            self._bind_text(box, hint_key, hint, "setToolTip")
        self._bind_text(box, key, default_text)
        layout.addWidget(box)

        def toggled(checked: bool) -> None:
            if self._silent:
                return
            apply(bool(checked))

        box.toggled.connect(toggled)
        self._refreshers.append(lambda b=box, g=getter: self._set_checked(b, g()))
        return box

    def _buttons(self, layout: QVBoxLayout, *specs) -> QHBoxLayout:
        """一行按钮。specs 里每项是 (文案 key, 文案原文, 回调, 是否危险色)。"""
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        for spec in specs:
            key, default_text, callback = spec[0], spec[1], spec[2]
            danger = len(spec) > 3 and spec[3]
            button = QPushButton(self._t(key, default_text))
            if danger:
                button.setObjectName("danger")
            button.clicked.connect(callback)
            self._bind_text(button, key, default_text)
            row.addWidget(button)
        row.addStretch(1)
        layout.addWidget(holder)
        return row

    def _set_checked(self, box: QCheckBox, value: bool) -> None:
        self._silent = True
        box.setChecked(bool(value))
        self._silent = False

    def _bind_mode(self, widget: QWidget, *modes: str) -> QWidget:
        """这个控件只在列出的界面模式下有意义，别的模式置灰。"""
        self._mode_bound.append((widget, tuple(modes)))
        return widget

    # ==================================================================
    # 分类 1：界面
    # ==================================================================

    def _page_general(self) -> None:
        settings = self.window.settings
        layout = self._page("nav.general", "界面")

        self._section(layout, "general.section.appearance", "外观")
        self._combo(
            layout,
            "general.theme",
            "主题",
            # 主题名做成可翻译的 key，查不到就退回 config 里的中文名
            [(f"theme.{key}", THEMES[key]["label"], key) for key in THEME_ORDER],
            lambda: settings.theme,
            self.window._set_theme,
        )
        self._combo(
            layout,
            "general.mode",
            "界面模式",
            [
                ("general.mode.depth3d", "立体卡片（封面 + 歌词列表）", "depth3d"),
                ("general.mode.lyrics", "纯歌词面板（只剩歌词）", "lyrics"),
                ("general.mode.album", "唱片播放器（无歌词）", "album"),
                ("general.mode.split", "分离面板（唱片 + 歌词，各自可移动）", "split"),
            ],
            lambda: settings.mode,
            self.window._set_mode,
        )
        style_combo = self._combo(
            layout,
            "general.album_style",
            "专辑样式",
            [
                ("general.album_style.classic", "经典（方块 + 菱形）", "classic"),
                ("general.album_style.vinyl", "黑胶唱片（带唱臂）", "vinyl"),
                ("general.album_style.cover_vinyl", "封面 + 唱片", "cover_vinyl"),
            ],
            lambda: settings.depth_album_style,
            self.window._set_depth_style,
        )
        self._bind_mode(style_combo.parentWidget() or style_combo, "depth3d")
        self._combo(
            layout,
            "general.dialog_theme",
            "设置窗口外观",
            [
                ("general.dialog_theme.auto", "跟随歌词主题", "auto"),
                ("general.dialog_theme.dark", "深色", "dark"),
                ("general.dialog_theme.light", "浅色", "light"),
            ],
            lambda: getattr(settings, "dialog_theme", "auto"),
            self._set_dialog_theme,
        )

        self._section(layout, "general.section.text3d", "文字立体（倾斜 / 旋转）")
        self._slider(
            layout,
            "general.tilt_v",
            "上下倾斜",
            getter=lambda: settings.text_depth_v,
            apply=lambda v: self.window._set_depth(v=v),
            minimum=-0.80, maximum=0.80, step=0.01, default=0.0,
            decimals=2, signed=True,
        )
        self._slider(
            layout,
            "general.tilt_h",
            "左右倾斜",
            getter=lambda: settings.text_depth_h,
            apply=lambda v: self.window._set_depth(h=v),
            minimum=-0.80, maximum=0.80, step=0.01, default=0.32,
            decimals=2, signed=True,
        )
        self._slider(
            layout,
            "general.tilt_rotate",
            "整体旋转",
            getter=lambda: settings.text_tilt,
            apply=self.window._set_spin,
            minimum=-90.0, maximum=90.0, step=1.0, default=0.0,
            unit="°", signed=True,
        )
        self._hint(
            layout,
            "general.text3d.hint",
            "上下倾斜：正值「上窄下宽」、负值「下窄上宽」。\n"
            "左右倾斜：正值「左窄右宽」、负值「右窄左宽」。\n"
            "两个方向可以同时生效；立体卡片只用正值（原来的方向）。\n"
            "整体旋转：正值顺时针、负值逆时针，0 为不旋转。\n"
            "双击任意一项的标题可以恢复它的默认值。",
        )

        self._section(layout, "general.section.size", "尺寸")
        self._slider(
            layout,
            "general.cover_size",
            "封面大小",
            getter=lambda: settings.cover_size,
            apply=lambda v: self.window._set_cover(int(round(v))),
            minimum=40, maximum=320, step=2, default=self._defaults.cover_size,
            unit="px", coalesce_ms=60,
        )
        self._slider(
            layout,
            "general.width",
            "窗口宽度",
            getter=lambda: settings.width,
            apply=lambda v: self.window._set_width(int(round(v))),
            minimum=WIDTH_MIN, maximum=WIDTH_MAX, step=10, default=self._defaults.width,
            unit="px", coalesce_ms=60,
        )
        self._slider(
            layout,
            "general.font_size",
            "歌词字号",
            getter=lambda: settings.font_size,
            apply=lambda v: self.window._set_font_size(int(round(v))),
            minimum=12, maximum=200, step=1, default=self._defaults.font_size,
            unit="px", coalesce_ms=60,
        )
        lines_row = self._slider(
            layout,
            "general.lyric_lines",
            "歌词列表行数",
            getter=lambda: settings.lyric_lines,
            apply=lambda v: self.window._set_lines(int(round(v))),
            minimum=1, maximum=15, step=1, default=self._defaults.lyric_lines,
            unit_key="unit.lines", unit="行", coalesce_ms=60,
        )
        self._bind_mode(lines_row, "depth3d", "lyrics", "split")
        spacing_row = self._slider(
            layout,
            "general.line_spacing",
            "歌唱行间距",
            getter=lambda: settings.line_spacing,
            apply=self.window._set_spacing,
            minimum=0.50, maximum=3.00, step=0.05, default=self._defaults.line_spacing,
            unit_key="unit.multiplier", unit="倍", decimals=2, coalesce_ms=60,
        )
        self._bind_mode(spacing_row, "depth3d", "lyrics", "split")
        self._hint(
            layout,
            "general.size.hint",
            "歌词列表行数 / 行间距只在立体卡片、纯歌词面板、分离面板下有意义。",
        )

        self._section(layout, "general.section.overall", "整体")
        self._slider(
            layout,
            "general.ui_opacity",
            "整体不透明度",
            getter=lambda: round(settings.ui_opacity * 100),
            apply=lambda v: self.window._set_ui_opacity(v / 100.0),
            minimum=5, maximum=100, step=1,
            default=round(self._defaults.ui_opacity * 100),
            unit="%",
        )
        self._hint(
            layout,
            "general.ui_opacity.hint",
            "整体不透明度只作用于桌面歌词本身；设置窗口自己不受影响。",
        )

        layout.addStretch(1)

    def _set_dialog_theme(self, value: str) -> None:
        self.window.settings.dialog_theme = value
        self.window._commit()
        self._apply_theme()

    # ==================================================================
    # 分类 2：歌词
    # ==================================================================

    def _page_lyrics(self) -> None:
        settings = self.window.settings
        layout = self._page("nav.lyrics", "歌词")

        self._section(layout, "lyrics.section.font", "字体")
        self._font_label = QLabel()
        self._font_label.setObjectName("value")
        layout.addWidget(self._font_label)
        self._font_combo = QComboBox()
        self._font_combo.setMaxVisibleItems(24)
        self._font_combo.currentIndexChanged.connect(self._on_font_picked)
        layout.addWidget(self._font_combo)
        self._buttons(
            layout,
            ("btn.import_font", "导入字体文件…", self.window._import_font_dialog),
            ("btn.open_font_folder", "打开字体文件夹", self.window._open_font_folder),
            ("btn.pick_font", "从系统字体中选择…", self.window._pick_font_dialog),
        )
        for item in ONLINE_FONTS:
            family = family_for(item)
            # key 只用来给「切语言重刷」占位：这里带上下载项自己的 key，
            # 表里查不到就会退回下面这段原文，不会把按钮文字刷成光秃秃一个标签
            key = f"online_font.{item.key}"
            text = (
                f"{item.label}{tr('font.tag.downloaded', '（已下载）')}"
                if family
                else tr("font.download", "下载 {label}").format(label=item.label)
            )
            self._buttons(
                layout,
                (key, text, lambda _c=False, k=item.key: self.window._download_font(k)),
            )
        self._hint(
            layout,
            "lyrics.font.hint",
            "带「（内置）」的是随程序打包的字体，装上就能用，不需要联网。",
        )

        self._section(layout, "lyrics.section.layout", "排版")
        self._combo(
            layout,
            "lyrics.align",
            "歌词排版",
            [
                ("lyrics.align.left", "向左对齐", "left"),
                ("lyrics.align.center", "居中", "center"),
                ("lyrics.align.right", "向右对齐", "right"),
            ],
            lambda: settings.lyric_align,
            self.window._set_align,
        )
        info_box = self._check(
            layout,
            "lyrics.show_info",
            "显示歌名、歌手和热度",
            getter=lambda: settings.show_song_info,
            apply=self._set_song_info,
            hint_key="lyrics.show_info.hint",
            hint="只有独立的纯歌词面板显示它；分离面板里的歌词列不显示",
        )
        self._bind_mode(info_box, "lyrics")

        self._section(layout, "lyrics.section.size", "歌词尺寸")
        self._hint(
            layout,
            "lyrics.size.hint",
            "「歌词字号」和「歌唱行间距」是滑动条，在左边「界面」分类的「尺寸」里。",
        )
        self._buttons(
            layout,
            ("btn.goto_general", "去「界面」调字号 / 行间距", lambda: self.nav.setCurrentRow(0)),
        )

        self._section(layout, "lyrics.section.sync", "歌词同步（本歌偏移）")
        self._offset_label = QLabel()
        self._offset_label.setWordWrap(True)
        layout.addWidget(self._offset_label)
        self._buttons(
            layout,
            ("btn.earlier.01", "提前 0.1 秒", lambda: self.window._nudge_offset(-100)),
            ("btn.earlier.05", "提前 0.5 秒", lambda: self.window._nudge_offset(-500)),
            ("btn.earlier.1", "提前 1 秒", lambda: self.window._nudge_offset(-1000)),
        )
        self._buttons(
            layout,
            ("btn.later.01", "延后 0.1 秒", lambda: self.window._nudge_offset(100)),
            ("btn.later.05", "延后 0.5 秒", lambda: self.window._nudge_offset(500)),
            ("btn.later.1", "延后 1 秒", lambda: self.window._nudge_offset(1000)),
        )
        self._buttons(
            layout,
            ("btn.custom_offset", "自定义偏移…", self.window._ask_offset),
            ("btn.reset_song", "重置本歌", lambda: self.window._set_offset(0)),
            ("btn.default_offset", "所有歌曲的默认偏移…", self.window._ask_default_offset),
        )
        self._hint(
            layout,
            "lyrics.sync.hint",
            "偏移按「播放器 + 歌名 + 歌手 + 时长」分别记：调好一首不会影响别的歌，"
            "同名不同版本也不会串。",
        )

        layout.addStretch(1)

    def _set_song_info(self, value: bool) -> None:
        if bool(self.window.settings.show_song_info) != bool(value):
            self.window._toggle_song_info()

    # ==================================================================
    # 分类 3：播放
    # ==================================================================

    def _page_player(self) -> None:
        settings = self.window.settings
        layout = self._page("nav.player", "播放")

        self._section(layout, "player.section.follow", "跟随哪个播放器")
        self._player_combo = QComboBox()
        self._player_combo.currentIndexChanged.connect(self._on_player_picked)
        layout.addWidget(self._player_combo)
        self._hint(
            layout,
            "player.follow.hint",
            "多个音乐软件同时开着时，可以指定跟随哪一个；默认自动选正在播放的那个。",
        )

        self._section(layout, "player.section.album", "唱片播放器面板")
        shape_combo = self._combo(
            layout,
            "player.album_shape",
            "唱片样式",
            [
                ("player.album_shape.disc", "圆形唱片", "disc"),
                ("player.album_shape.square", "方形封面 + 唱片", "square"),
            ],
            lambda: settings.album_shape,
            self.window._set_album_shape,
        )
        self._bind_mode(shape_combo.parentWidget() or shape_combo, "album", "split")
        for key, default_text, field, flipper in (
            ("player.show_cover", "显示封面", "show_cover", "_toggle_cover"),
            ("player.show_progress", "显示进度条", "show_progress", "_toggle_progress"),
            ("player.show_controls", "显示播放控制", "show_controls", "_toggle_controls"),
        ):
            box = self._check(
                layout,
                key,
                default_text,
                getter=lambda f=field: getattr(settings, f),
                apply=lambda value, f=field, m=flipper: self._flip(f, m, value),
            )
            self._bind_mode(box, "album", "split")
        self._hint(layout, "player.hint", "这几项只在唱片播放器 / 分离面板的唱片那半边生效。")

        layout.addStretch(1)

    def _flip(self, field: str, method: str, value: bool) -> None:
        """勾选类字段：值不一样才去调宿主的翻转方法，避免来回打架。"""
        if bool(getattr(self.window.settings, field)) != bool(value):
            getattr(self.window, method)()

    def _on_player_picked(self, _index: int) -> None:
        if self._silent:
            return
        app_id = self._player_combo.currentData()
        if app_id is not None:
            self.window._set_player(app_id)

    # ==================================================================
    # 分类 4：窗口与交互
    # ==================================================================

    def _page_window(self) -> None:
        settings = self.window.settings
        layout = self._page("nav.window", "窗口与交互")

        # 穿透状态下窗口点不动，这里给个明晃晃的出口
        warn_card = self._card(layout)
        self._click_warn = QLabel()
        self._click_warn.setObjectName("warn")
        self._click_warn.setWordWrap(True)
        warn_card.addWidget(self._click_warn)
        self._click_exit = QPushButton(self._t("btn.exit_click_through", "关闭鼠标穿透"))
        self._bind_text(self._click_exit, "btn.exit_click_through", "关闭鼠标穿透")
        self._click_exit.clicked.connect(lambda: self.window.set_click_through(False))
        warn_card.addWidget(self._click_exit)
        # 卡片的显示 / 隐藏跟着穿透状态走（_refresh 里控制）
        self._warn_card = warn_card.parentWidget()
        layout.addSpacing(6)

        self._section(layout, "window.section.behaviour", "窗口行为")
        for key, default_text, field, flipper, hint_key, hint in (
            (
                "window.locked", "锁定位置", "locked", "_toggle_locked",
                "window.locked.hint", "锁定后不能拖动窗口",
            ),
            (
                "window.click_through", "鼠标穿透", "click_through", None,
                "window.click_through.hint", "开启后不响应鼠标，位置也一并锁定",
            ),
            (
                "window.on_top", "置顶显示", "always_on_top", "_toggle_always_on_top",
                "window.on_top.hint", "始终浮在其它窗口上面",
            ),
        ):
            if field == "click_through":
                box = self._check(
                    layout,
                    key,
                    default_text,
                    getter=lambda: settings.click_through,
                    apply=self._set_click_through,
                    hint_key=hint_key,
                    hint=hint,
                )
            else:
                box = self._check(
                    layout,
                    key,
                    default_text,
                    getter=lambda f=field: getattr(settings, f),
                    apply=lambda value, f=field, m=flipper: self._flip(f, m, value),
                    hint_key=hint_key,
                    hint=hint,
                )
            box.setToolTip(tr(hint_key, hint))

        self._check(
            layout,
            "window.auto_show",
            "打开音乐软件时自动显示歌词",
            getter=lambda: settings.auto_show_on_music,
            apply=lambda value: self._flip(
                "auto_show_on_music", "_toggle_auto_show", value
            ),
            hint_key="window.auto_show.hint",
            hint="检测到音乐软件从未运行变成运行时，自动把歌词显示出来",
        )

        layout.addSpacing(6)
        self._buttons(
            layout,
            ("btn.default_position", "回到默认位置", self.window._reset_position),
            ("btn.minimize_tray", "最小化到托盘", self.window._minimize_to_tray),
        )
        self._hint(
            layout,
            "window.tray.hint",
            "「最小化到托盘」只是把歌词收起来，程序仍在后台运行。",
        )

        # 快捷键表：左列是按键 / 手势，右列是作用
        self._section(layout, "window.section.shortcut", "快捷键")
        shortcut_card = self._card(layout)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)
        for row_index, (left_key, left_text, right_key, right_text) in enumerate(SHORTCUT_ROWS):
            left = QLabel(tr(left_key, left_text))
            left.setObjectName("hotkey")
            right = QLabel(tr(right_key, right_text))
            right.setObjectName("hint")
            right.setWordWrap(True)
            self._bind_text(left, left_key, left_text)
            self._bind_text(right, right_key, right_text)
            grid.addWidget(left, row_index, 0)
            grid.addWidget(right, row_index, 1)
        shortcut_card.addLayout(grid)

        layout.addStretch(1)

    def _set_click_through(self, value: bool) -> None:
        if bool(self.window.settings.click_through) != bool(value):
            self.window.set_click_through(bool(value))

    # ==================================================================
    # 分类 5：更新与关于
    # ==================================================================

    def _page_update(self) -> None:
        layout = self._page("nav.update", "更新与关于")

        self._section(layout, "update.section.language", "界面语言")
        self._combo(
            layout,
            "update.language",
            "设置窗口的语言",
            [
                ("update.language.system", "跟随系统", ""),
                # 语言名用「自名」：中文永远显示 中文，英文永远显示 English，
                # 所以这两项在表里没有对应 key，tr() 会原样返回原文
                ("lang.zh", "中文", "zh_CN"),
                ("lang.en", "English", "en"),
            ],
            lambda: getattr(self.window.settings, "language", ""),
            self._set_language,
        )

        self._section(layout, "update.section.autostart", "开机自启")
        self._check(
            layout,
            "update.autostart",
            "开机时自动启动桌面歌词",
            getter=is_enabled,
            apply=lambda value: self.window.requestAutostart.emit(bool(value)),
            hint_key="update.autostart.hint",
            hint="写进当前用户的注册表启动项，不需要管理员权限",
        )

        self._section(layout, "update.section.update", "更新")
        self._source_label = QLabel()
        self._source_label.setObjectName("value")
        self._source_label.setWordWrap(True)
        layout.addWidget(self._source_label)
        # 发布页链接：点一下用默认浏览器打开（不联网校验，也不预加载）
        self._releases_link = QLabel()
        self._releases_link.setObjectName("link")
        self._releases_link.setOpenExternalLinks(True)
        self._releases_link.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
        )
        layout.addWidget(self._releases_link)
        self._buttons(
            layout,
            ("btn.check_update", "检查更新…", self.window._check_update),
            ("btn.set_source", "设置更新源…", self.window._ask_update_source),
        )
        self._hint(
            layout,
            "update.hint",
            "更新源已内置；以后仓库搬家了再用「设置更新源…」改。",
        )

        self._section(layout, "update.section.about", "关于")
        self._about = QLabel()
        self._about.setWordWrap(True)
        layout.addWidget(self._about)
        # 项目主页（同样是可点的，点不动也没关系，只是条信息）
        self._homepage_link = QLabel()
        self._homepage_link.setObjectName("link")
        self._homepage_link.setOpenExternalLinks(True)
        self._homepage_link.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
        )
        layout.addWidget(self._homepage_link)
        self._buttons(
            layout,
            ("btn.open_settings_dir", "打开设置文件夹", lambda: self._open_dir(app_dir())),
            ("btn.open_cache_dir", "打开歌词缓存文件夹", lambda: self._open_dir(cache_dir())),
        )

        layout.addStretch(1)

    def _set_language(self, value: str) -> None:
        self.window.settings.language = value
        self.window._commit()
        set_language(value)
        self._i18n_dirty = True
        self.retranslate()

    @staticmethod
    def _open_dir(path) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    # ==================================================================
    # 语言 / 皮肤
    # ==================================================================

    def retranslate(self) -> None:
        """语言切换后把已建好的控件文案重刷一遍（不重建窗口）。"""
        self.setWindowTitle(tr("app.title", "设置 · 桌面歌词"))
        for index, (key, default) in enumerate(self.NAV):
            item = self.nav.item(index)
            if item is not None:
                item.setText(tr(key, default))
        for refresh in self._i18n_refresh:
            try:
                refresh()
            except RuntimeError:
                # 控件已经没了（窗口关闭中），忽略
                pass
        self._refresh()

    def _apply_theme(self) -> None:
        settings = self.window.settings
        mode = resolve_dialog_theme(
            getattr(settings, "dialog_theme", "auto"), settings.theme
        )
        self._style_mode = mode
        self._style_theme = settings.theme
        self.setStyleSheet(build_style(mode, settings.theme))
        self.update()

    def _set_always_on_top(self, checked: bool) -> None:
        """设置窗口自己的置顶（默认关；开了才是以前的常驻置顶行为）。"""
        self._always_on_top = bool(checked)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self._always_on_top)
        # 改窗口标志会把窗口藏起来，必须再显示一次，否则看起来像「窗口消失了」
        self.show()
        self.raise_()
        self.activateWindow()

    # ==================================================================
    # 刷新 / 联动
    # ==================================================================

    def _on_settings_changed(self) -> None:
        # 一次改动会从好几个地方通知过来（宿主 _commit 一次、滑动条写回一次……），
        # 全都在同一个事件循环 tick 里，合并成一次刷新就够。
        # 只去重，不改刷新内容与顺序。
        if self._refresh_pending:
            return
        self._refresh_pending = True
        QTimer.singleShot(0, self._flush_refresh)

    def _flush_refresh(self) -> None:
        self._refresh_pending = False
        self._refresh()

    def detach_from(self, window) -> None:
        """换宿主前先断开旧宿主的信号。"""
        try:
            window.settingsChanged.disconnect(self._on_settings_changed)
        except (RuntimeError, TypeError):
            pass

    def attach_to(self, window) -> None:
        """接管到新的宿主窗口（分离面板切换时的转交）。"""
        self.window = window
        window.settingsChanged.connect(self._on_settings_changed)
        self._refresh()

    def _refresh(self) -> None:
        """把界面上的控件按当前设置重新对一遍。"""
        dirty = self._i18n_dirty
        self._i18n_dirty = False
        self._silent = True
        try:
            for refresh in self._refreshers:
                try:
                    refresh()
                except RuntimeError:
                    # 控件已经被销毁（窗口关闭中），忽略即可
                    pass
        finally:
            self._silent = False

        settings = self.window.settings
        mode = settings.mode
        for widget, modes in self._mode_bound:
            widget.setEnabled(mode in modes)

        self._click_warn.setText(tr("window.click_warn", CLICK_WARN_DEFAULT))
        clicking = bool(settings.click_through)
        self._click_warn.setVisible(clicking)
        self._click_exit.setVisible(clicking)
        self._warn_card.setVisible(clicking)
        self._offset_label.setText(self._offset_text())
        source = self.window._update_source()
        self._source_label.setText(
            tr("update.current_source", "当前更新源：{source}").format(source=source)
        )
        releases = releases_url(source)
        self._releases_link.setText(
            tr("update.releases_link", "发布页（更新动态 / 更新日志）：")
            + f'<a href="{releases}">{releases}</a>'
        )
        home = homepage_url(source)
        self._homepage_link.setText(
            tr("update.homepage", "项目主页：") + f'<a href="{home}">{home}</a>'
        )
        self._about.setText(
            tr("about.text", ABOUT_DEFAULT).format(version=__version__)
        )
        self._refresh_fonts(force=dirty)
        self._refresh_players(force=dirty)

        # 歌词主题一改（或深浅变了），设置窗口跟着换肤
        wanted = resolve_dialog_theme(
            getattr(settings, "dialog_theme", "auto"), settings.theme
        )
        if wanted != self._style_mode or settings.theme != self._style_theme:
            self._apply_theme()

    def _offset_text(self) -> str:
        key = self.window._song_key()
        current = self.window._offset_ms()
        default = int(self.window.settings.offset_ms)
        if not key:
            return tr("sync.none", "当前没有正在播放的歌。默认偏移 {default:+d} ms。").format(
                default=default
            )
        parts = key.split("|")
        title = parts[1] if len(parts) > 1 else "本歌"
        return tr(
            "sync.now",
            "正在播放：{title}（本歌偏移 {current:+d} ms，默认 {default:+d} ms）",
        ).format(title=title, current=current, default=default)

    def _refresh_fonts(self, force: bool = False) -> None:
        """字体列表：内置 / 推荐 / 我导入的 / 系统里的都列出来。"""
        current = self.window.settings.font_family
        families = set(QFontDatabase.families())
        entries: list[tuple[str, str]] = []
        listed: set[str] = set()

        for label, family in RECOMMENDED:
            if family in families and family not in listed:
                entries.append((f"{label}{tr('font.tag.recommended', '（推荐）')}", family))
                listed.add(family)
        for _filename, label, family in BUNDLED_FONTS:
            if family in families and family not in listed:
                # fonts.py 里的标签自带「（内置）」，这里换成当前语言的写法
                clean = label.replace("（内置）", "").strip()
                entries.append((f"{clean}{tr('font.tag.bundled', '（内置）')}", family))
                listed.add(family)
        for family, _filename in imported_fonts():
            if family not in listed:
                entries.append((f"{family}{tr('font.tag.mine', '（我导入的）')}", family))
                listed.add(family)
        for item in ONLINE_FONTS:
            family = family_for(item)
            if family and family not in listed:
                entries.append(
                    (f"{item.label}{tr('font.tag.downloaded', '（已下载）')}", family)
                )
                listed.add(family)

        rest = sorted(f for f in families if f not in listed)
        entries.extend((family, family) for family in rest)
        if current and current not in listed:
            entries.insert(0, (f"{current}{tr('font.tag.current', '（当前）')}", current))

        if not force and self._font_combo.count() == len(entries):
            # 列表没变就不重建，省得每次刷新都重置下拉框
            index = self._font_combo.findData(current)
            if index >= 0 and index == self._font_combo.currentIndex():
                self._font_label.setText(
                    tr("lyrics.current_font", "当前字体：{name}").format(name=current)
                )
                return

        self._silent = True
        self._font_combo.clear()
        for text, family in entries:
            self._font_combo.addItem(text, family)
        index = self._font_combo.findData(current)
        if index >= 0:
            self._font_combo.setCurrentIndex(index)
        self._silent = False
        self._font_label.setText(
            tr("lyrics.current_font", "当前字体：{name}").format(name=current)
        )

    def _on_font_picked(self, _index: int) -> None:
        if self._silent:
            return
        family = self._font_combo.currentData()
        if family and family != self.window.settings.font_family:
            self.window._set_font_family(family)
            self._refresh_fonts(force=True)

    def _refresh_players(self, force: bool = False) -> None:
        players: list[dict] = []
        getter = getattr(self.window.engine, "players", None)
        if getter is not None:
            try:
                players = getter() or []
            except Exception:
                players = []

        entries: list[tuple[str, str]] = [
            (tr("player.auto", "自动（正在播放的那个）"), "")
        ]
        for item in players:
            app_id = item.get("app_id", "")
            if not app_id:
                continue
            label = friendly_player_name(app_id)
            if item.get("playing"):
                label += tr("player.playing", "（播放中）")
            entries.append((label, app_id))

        if not force and self._player_combo.count() == len(entries):
            same = all(
                self._player_combo.itemData(i) == entries[i][1]
                for i in range(len(entries))
            )
            if same:
                return

        current = self.window.settings.preferred_player
        self._silent = True
        self._player_combo.clear()
        for text, value in entries:
            self._player_combo.addItem(text, value)
        index = self._player_combo.findData(current)
        if index >= 0:
            self._player_combo.setCurrentIndex(index)
        self._silent = False

    # ==================================================================
    # 底部
    # ==================================================================

    def _reset_defaults(self) -> None:
        box = QMessageBox(self)
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        box.setWindowTitle(tr("reset.title", "恢复默认"))
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(tr("reset.text", "把所有外观设置恢复成默认值？"))
        box.setInformativeText(
            tr(
                "reset.info",
                "窗口位置、每首歌单独调过的歌词偏移、更新源会保留，其余全部回到出厂状态。",
            )
        )
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        box.setDefaultButton(QMessageBox.StandardButton.No)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        self.window.settings.reset()
        # 位置、模式、窗口标志都可能变了，一次性全部重算
        self.window._commit(resize=True, flags=True, background=True)
        set_language(getattr(self.window.settings, "language", ""))
        self._i18n_dirty = True
        self.retranslate()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._refresh()

    def closeEvent(self, event) -> None:  # noqa: N802
        # 关之前把还没落地的那次滑动补上（拖着滑块顺手按关闭的边界情况）
        for row in self._slider_rows:
            row.flush()
        super().closeEvent(event)
