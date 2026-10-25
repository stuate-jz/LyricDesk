"""界面文案的多语言表。

目前**只覆盖设置窗口**（右键菜单、托盘提示、通知气泡这些仍然是中文），
但接口按「以后逐条补 key 就能扩」来设计：新增语言只要往 `STRINGS` 里加一张表，
调用方统一用 `tr("语义化 key", "中文原文")`。

设计上刻意做得**不会因为漏一条就出事**：

- 当前语言查不到 → 退回中文表；
- 中文表也没有 → 用调用方传进来的中文原文；
- 再没有 → 才用 key 本身（绝不会抛 KeyError）。

只用标准库 + PySide6（QLocale），不引入任何新依赖。
"""

from __future__ import annotations

from PySide6.QtCore import QLocale

# 支持的语言：zh_CN 中文 / en English；设置里存 "" 表示跟随系统
SUPPORTED = ("zh_CN", "en")
DEFAULT_LANGUAGE = "zh_CN"


STRINGS: dict[str, dict[str, str]] = {
    "zh_CN": {
        # ---------- 外壳 ----------
        "app.title": "设置 · 桌面歌词",
        "dialog.title": "设置",
        "top.always_on_top": "置顶显示",
        "top.always_on_top.hint": "让设置窗口一直浮在其它程序上面",
        "btn.close": "关闭",
        "btn.reset": "恢复默认",
        "reset.title": "恢复默认",
        "reset.text": "把所有外观设置恢复成默认值？",
        "reset.info": "窗口位置、每首歌单独调过的歌词偏移、更新源会保留，其余全部回到出厂状态。",
        "slider.reset.tooltip": "双击恢复默认值",
        "unit.multiplier": "倍",
        "unit.lines": "行",
        # ---------- 分类 ----------
        "nav.general": "界面",
        "nav.lyrics": "歌词",
        "nav.player": "播放",
        "nav.window": "窗口与交互",
        "nav.update": "更新与关于",
        # ---------- 界面 ----------
        "general.section.appearance": "外观",
        "general.theme": "主题",
        "theme.aurora": "极光",
        "theme.sakura": "樱花",
        "theme.sunset": "落日",
        "theme.jade": "青竹",
        "theme.ink": "素白",
        "general.mode": "界面模式",
        "general.mode.depth3d": "立体卡片（封面 + 歌词列表）",
        "general.mode.lyrics": "纯歌词面板（只剩歌词）",
        "general.mode.album": "唱片播放器（无歌词）",
        "general.mode.split": "分离面板（唱片 + 歌词，各自可移动）",
        "general.album_style": "专辑样式",
        "general.album_style.classic": "经典（方块 + 菱形）",
        "general.album_style.vinyl": "黑胶唱片（带唱臂）",
        "general.album_style.cover_vinyl": "封面 + 唱片",
        "general.dialog_theme": "设置窗口外观",
        "general.dialog_theme.auto": "跟随歌词主题",
        "general.dialog_theme.dark": "深色",
        "general.dialog_theme.light": "浅色",
        "general.section.text3d": "文字立体（倾斜 / 旋转）",
        "general.tilt_v": "上下倾斜",
        "general.tilt_h": "左右倾斜",
        "general.tilt_rotate": "整体旋转",
        "general.text3d.hint": (
            "上下倾斜：正值「上窄下宽」、负值「下窄上宽」。\n"
            "左右倾斜：正值「左窄右宽」、负值「右窄左宽」。\n"
            "两个方向可以同时生效；立体卡片只用正值（原来的方向）。\n"
            "整体旋转：正值顺时针、负值逆时针，0 为不旋转。\n"
            "双击任意一项的标题可以恢复它的默认值。"
        ),
        "general.section.size": "尺寸",
        "general.cover_size": "封面大小",
        "general.width": "歌词宽度（歌词实际能显示多宽）",
        "general.player_width": "播放器宽度",
        "general.player_width.auto": "自动",
        "general.width.hint": "唱片播放器模式没有歌词列；要改播放器宽度请用下面的「播放器宽度」。",
        "general.font_size": "歌词字号",
        "general.lyric_lines": "歌词列表行数",
        "general.letter_spacing": "歌词字间距",
        "general.letter_spacing.hint": "正数拉开字距、负数收紧；窗口宽度会自动适应最长的一行。",
        "general.line_spacing": "歌词行间距",
        "general.size.hint": (
            "播放器宽度只影响唱片面板（分离面板里那半边），选「自动」就跟着封面大小走。\n"
            "歌词列表行数 / 行间距只在立体卡片、纯歌词面板、分离面板下有意义。"
        ),
        "general.section.overall": "整体",
        "general.ui_opacity": "整体不透明度",
        "general.ui_opacity.hint": "整体不透明度只作用于桌面歌词本身；设置窗口自己不受影响。",
        # ---------- 歌词 ----------
        "lyrics.section.font": "字体",
        "lyrics.current_font": "当前字体：{name}",
        "btn.import_font": "导入字体文件…",
        "btn.open_font_folder": "打开字体文件夹",
        "btn.pick_font": "从系统字体中选择…",
        "lyrics.font.hint": "带「（内置）」的是随程序打包的字体，装上就能用，不需要联网。",
        "font.tag.recommended": "（推荐）",
        "font.tag.bundled": "（内置）",
        "font.tag.current": "（当前）",
        "font.tag.mine": "（我导入的）",
        "font.tag.downloaded": "（已下载）",
        "font.download": "下载 {label}",
        "lyrics.section.layout": "排版",
        "lyrics.align": "歌词排版",
        "lyrics.align.left": "向左对齐",
        "lyrics.align.center": "居中",
        "lyrics.align.right": "向右对齐",
        "lyrics.show_info": "显示歌名、歌手和热度",
        "lyrics.show_info.hint": "只有独立的纯歌词面板显示它；分离面板里的歌词列不显示",
        "lyrics.section.size": "歌词尺寸",
        "lyrics.size.hint": "「歌词字号」和「歌词行间距」是滑动条，在左边「界面」分类的「尺寸」里。",
        "btn.goto_general": "去「界面」调字号 / 行间距",
        "lyrics.section.sync": "歌词同步（本歌偏移）",
        "sync.none": "当前没有正在播放的歌。默认偏移 {default:+d} ms。",
        "sync.now": "正在播放：{title}（本歌偏移 {current:+d} ms，默认 {default:+d} ms）",
        "btn.earlier.01": "提前 0.1 秒",
        "btn.earlier.05": "提前 0.5 秒",
        "btn.earlier.1": "提前 1 秒",
        "btn.later.01": "延后 0.1 秒",
        "btn.later.05": "延后 0.5 秒",
        "btn.later.1": "延后 1 秒",
        "btn.custom_offset": "自定义偏移…",
        "btn.reset_song": "重置本歌",
        "btn.default_offset": "所有歌曲的默认偏移…",
        "lyrics.sync.hint": (
            "偏移按「播放器 + 歌名 + 歌手 + 时长」分别记：调好一首不会影响别的歌，"
            "同名不同版本也不会串。"
        ),
        # ---------- 播放 ----------
        "player.section.follow": "跟随哪个播放器",
        "player.follow.hint": "多个音乐软件同时开着时，可以指定跟随哪一个；默认自动选正在播放的那个。",
        "player.auto": "自动（正在播放的那个）",
        "player.playing": "（播放中）",
        "player.section.album": "唱片播放器面板",
        "player.album_shape": "唱片样式",
        "player.album_shape.disc": "圆形唱片",
        "player.album_shape.square": "方形封面 + 唱片",
        "player.show_cover": "显示封面",
        "player.show_progress": "显示进度条",
        "player.show_controls": "显示播放控制",
        "player.hint": "这几项只在唱片播放器 / 分离面板的唱片那半边生效。",
        # ---------- 窗口与交互 ----------
        "window.click_warn": (
            "⚠ 鼠标穿透已开启：歌词窗口不响应鼠标，位置也已锁定。\n"
            "关掉它：点下面的按钮，或者按 Ctrl + Alt + L，"
            "或者右键任务栏托盘图标 → 鼠标穿透。"
        ),
        "btn.exit_click_through": "关闭鼠标穿透",
        "window.section.behaviour": "窗口行为",
        "window.locked": "锁定位置",
        "window.locked.hint": "锁定后不能拖动窗口",
        "window.click_through": "鼠标穿透",
        "window.click_through.hint": "开启后不响应鼠标，位置也一并锁定",
        "window.on_top": "置顶显示",
        "window.on_top.hint": "始终浮在其它窗口上面",
        "window.auto_show": "打开音乐软件时自动显示歌词",
        "window.auto_show.hint": "检测到音乐软件从未运行变成运行时，自动把歌词显示出来",
        "window.bili_mode": "B 站客户端字幕",
        "window.bili_mode.hint": (
            "不会主动打开 B 站；B 站没运行时会记住设置，之后由你打开时自动切换；"
            "如果勾选时 B 站已经开着，会自动重启一次以读取字幕。"
        ),
        "btn.default_position": "回到默认位置",
        "btn.minimize_tray": "最小化到托盘",
        "window.tray.hint": "「最小化到托盘」只是把歌词收起来，程序仍在后台运行。",
        "window.section.shortcut": "快捷键",
        "shortcut.drag": "左键拖动窗口",
        "shortcut.double_click": "双击窗口空白处",
        "shortcut.cover_drag": "单击封面左侧区域",
        "shortcut.right_click": "右键",
        "shortcut.tray_double": "托盘图标双击",
        "shortcut.tray_right": "托盘图标右键",
        "shortcut.open_settings.desc": "打开设置窗口",
        "shortcut.click_through.desc": "切换鼠标穿透（穿透后窗口点不动，这是唯一的救急键）",
        "shortcut.drag.desc": "移动窗口位置（自动记住）",
        "shortcut.double_click.desc": "锁定 / 解锁位置",
        "shortcut.cover_drag.desc": "直接拖动，不会误触按钮",
        "shortcut.right_click.desc": "打开常用操作菜单",
        "shortcut.tray_double.desc": "显示 / 隐藏歌词",
        "shortcut.tray_right.desc": "同右键菜单（含「隐藏/显示歌词」）",
        # ---------- 更新与关于 ----------
        "update.section.language": "界面语言",
        "update.language": "设置窗口的语言",
        "update.language.system": "跟随系统",
        "update.section.autostart": "开机自启",
        "update.autostart": "开机时自动启动桌面歌词",
        "update.autostart.hint": "写进当前用户的注册表启动项，不需要管理员权限",
        "update.section.update": "更新",
        "update.current_source": "当前更新源：{source}",
        "update.releases_link": "发布页（更新动态 / 更新日志）：",
        "update.homepage": "项目主页：",
        "btn.check_update": "检查更新…",
        "btn.set_source": "设置更新源…",
        "update.hint": "更新源已内置；以后仓库搬家了再用「设置更新源…」改。",
        "update.section.about": "关于",
        "about.text": (
            "桌面歌词  v{version}\n"
            "把正在播放的歌词实时显示在桌面上，读取的是 Windows 系统媒体控制，不挑播放器。"
        ),
        "btn.open_settings_dir": "打开设置文件夹",
        "btn.open_cache_dir": "打开歌词缓存文件夹",
        # ---------- 右键菜单（本批不翻译：英文表里故意不放，tr 会退回中文） ----------
        "menu.settings": "设置…",
        "menu.check_update": "检查更新…",
    },
    "en": {
        # ---------- shell ----------
        "app.title": "Settings · Desktop Lyrics",
        "dialog.title": "Settings",
        "top.always_on_top": "Always on top",
        "top.always_on_top.hint": "Keep this settings window above other apps",
        "btn.close": "Close",
        "btn.reset": "Restore defaults",
        "reset.title": "Restore defaults",
        "reset.text": "Restore all appearance settings to their defaults?",
        "reset.info": (
            "Window position, per-song lyric offsets and the update source are kept; "
            "everything else goes back to the factory values."
        ),
        "slider.reset.tooltip": "Double-click to restore the default value",
        "unit.multiplier": "×",
        "unit.lines": "lines",
        # ---------- categories ----------
        "nav.general": "Interface",
        "nav.lyrics": "Lyrics",
        "nav.player": "Playback",
        "nav.window": "Window & input",
        "nav.update": "Update & about",
        # ---------- interface ----------
        "general.section.appearance": "Appearance",
        "general.theme": "Theme",
        "theme.aurora": "Aurora",
        "theme.sakura": "Sakura",
        "theme.sunset": "Sunset",
        "theme.jade": "Jade",
        "theme.ink": "Ink",
        "general.mode": "Interface mode",
        "general.mode.depth3d": "3D card (cover + lyrics list)",
        "general.mode.lyrics": "Lyrics only",
        "general.mode.album": "Album player (no lyrics)",
        "general.mode.split": "Split panels (disc + lyrics, moveable)",
        "general.album_style": "Cover style",
        "general.album_style.classic": "Classic (square + diamond)",
        "general.album_style.vinyl": "Vinyl (with tonearm)",
        "general.album_style.cover_vinyl": "Cover + disc",
        "general.dialog_theme": "Settings window look",
        "general.dialog_theme.auto": "Match lyric theme",
        "general.dialog_theme.dark": "Dark",
        "general.dialog_theme.light": "Light",
        "general.section.text3d": "Text depth (tilt / rotate)",
        "general.tilt_v": "Vertical tilt",
        "general.tilt_h": "Horizontal tilt",
        "general.tilt_rotate": "Rotation",
        "general.text3d.hint": (
            "Vertical tilt: positive = narrower on top, negative = narrower at the bottom.\n"
            "Horizontal tilt: positive = narrower on the left, negative = narrower on the right.\n"
            "Both directions can be active at once; the 3D card only uses positive values.\n"
            "Rotation: positive = clockwise, negative = counter-clockwise, 0 = no rotation.\n"
            "Double-click a title to restore its default value."
        ),
        "general.section.size": "Size",
        "general.cover_size": "Cover size",
        "general.width": "Lyric width (usable text width)",
        "general.player_width": "Player width",
        "general.player_width.auto": "Auto",
        "general.width.hint": (
            "The disc player has no lyric column; use \"Player width\" below instead."
        ),
        "general.font_size": "Lyric font size",
        "general.lyric_lines": "Lyric list lines",
        "general.line_spacing": "Line spacing",
        "general.letter_spacing": "Letter spacing",
        "general.letter_spacing.hint": (
            "Positive spreads letters out, negative tightens them; "
            "the window width adapts to the longest line."
        ),
        "general.size.hint": (
            "Player width only affects the disc panel (the other half of split mode), "
            "and \"Auto\" follows the cover size.\n"
            "Lyric list lines / line spacing only matter in 3D card, lyrics-only and split mode."
        ),
        "general.section.overall": "Overall",
        "general.ui_opacity": "Overall opacity",
        "general.ui_opacity.hint": (
            "Overall opacity only affects the desktop lyrics, not this settings window."
        ),
        # ---------- lyrics ----------
        "lyrics.section.font": "Font",
        "lyrics.current_font": "Current font: {name}",
        "btn.import_font": "Import font file…",
        "btn.open_font_folder": "Open font folder",
        "btn.pick_font": "Choose from system fonts…",
        "lyrics.font.hint": "Fonts marked (built-in) ship with the app — no download needed.",
        "font.tag.recommended": " (recommended)",
        "font.tag.bundled": " (built-in)",
        "font.tag.current": " (current)",
        "font.tag.mine": " (imported)",
        "font.tag.downloaded": " (downloaded)",
        "font.download": "Download {label}",
        "lyrics.section.layout": "Layout",
        "lyrics.align": "Lyric alignment",
        "lyrics.align.left": "Left",
        "lyrics.align.center": "Center",
        "lyrics.align.right": "Right",
        "lyrics.show_info": "Show title, artist and popularity",
        "lyrics.show_info.hint": (
            "Only the standalone lyrics panel shows it; the lyric column in split mode does not."
        ),
        "lyrics.section.size": "Lyric size",
        "lyrics.size.hint": (
            "Lyric font size and line spacing are sliders under “Interface” → “Size”."
        ),
        "btn.goto_general": "Open “Interface” tab",
        "lyrics.section.sync": "Lyric sync (this song)",
        "sync.none": "No song is playing. Default offset {default:+d} ms.",
        "sync.now": "Now playing: {title} (offset {current:+d} ms, default {default:+d} ms)",
        "btn.earlier.01": "0.1 s earlier",
        "btn.earlier.05": "0.5 s earlier",
        "btn.earlier.1": "1 s earlier",
        "btn.later.01": "0.1 s later",
        "btn.later.05": "0.5 s later",
        "btn.later.1": "1 s later",
        "btn.custom_offset": "Custom offset…",
        "btn.reset_song": "Reset this song",
        "btn.default_offset": "Default offset for all songs…",
        "lyrics.sync.hint": (
            "Offsets are stored per “player + title + artist + duration”, so fixing one song "
            "never affects another — and two versions of the same title stay separate."
        ),
        # ---------- playback ----------
        "player.section.follow": "Which player to follow",
        "player.follow.hint": (
            "When several music apps are running you can pick one; by default the one that is "
            "currently playing wins."
        ),
        "player.auto": "Auto (the one playing)",
        "player.playing": " (playing)",
        "player.section.album": "Album player panel",
        "player.album_shape": "Disc style",
        "player.album_shape.disc": "Round disc",
        "player.album_shape.square": "Square cover + disc",
        "player.show_cover": "Show cover",
        "player.show_progress": "Show progress bar",
        "player.show_controls": "Show playback controls",
        "player.hint": "These only apply to album player mode / the disc half of split mode.",
        # ---------- window & input ----------
        "window.click_warn": (
            "⚠ Click-through is on: the lyrics window ignores the mouse and its position is locked.\n"
            "To turn it off use the button below, press Ctrl + Alt + L, "
            "or right-click the tray icon → Click-through."
        ),
        "btn.exit_click_through": "Turn off click-through",
        "window.section.behaviour": "Window behaviour",
        "window.locked": "Lock position",
        "window.locked.hint": "The window cannot be dragged while locked",
        "window.click_through": "Click-through",
        "window.click_through.hint": "The window ignores the mouse; its position is locked too",
        "window.on_top": "Always on top",
        "window.on_top.hint": "Stay above other windows",
        "window.auto_show": "Show lyrics when a music app opens",
        "window.auto_show.hint": "Shows the lyrics when a music app goes from not running to running",
        "window.bili_mode": "Bilibili client subtitles",
        "window.bili_mode.hint": (
            "Never opens Bilibili automatically. The setting is remembered while "
            "Bilibili is closed and applies when you open it. If Bilibili is already "
            "running when enabled, it is restarted once for subtitle access."
        ),
        "btn.default_position": "Move to default position",
        "btn.minimize_tray": "Minimize to tray",
        "window.tray.hint": "Minimizing to tray only hides the lyrics; the app keeps running.",
        "window.section.shortcut": "Shortcuts",
        "shortcut.drag": "Drag with the left button",
        "shortcut.double_click": "Double-click empty space",
        "shortcut.cover_drag": "Click-drag left of the cover",
        "shortcut.right_click": "Right-click",
        "shortcut.tray_double": "Double-click the tray icon",
        "shortcut.tray_right": "Right-click the tray icon",
        "shortcut.open_settings.desc": "Open this settings window",
        "shortcut.click_through.desc": "Toggle click-through (the only rescue key once it is on)",
        "shortcut.drag.desc": "Move the window (position is remembered)",
        "shortcut.double_click.desc": "Lock / unlock the position",
        "shortcut.cover_drag.desc": "Drag directly, without hitting the buttons by accident",
        "shortcut.right_click.desc": "Open the quick menu",
        "shortcut.tray_double.desc": "Show / hide the lyrics",
        "shortcut.tray_right.desc": "Same as the right-click menu (plus hide/show)",
        # ---------- update & about ----------
        "update.section.language": "Language",
        "update.language": "Language of this window",
        "update.language.system": "Follow system",
        "update.section.autostart": "Start with Windows",
        "update.autostart": "Launch desktop lyrics at startup",
        "update.autostart.hint": "Writes to the current user's Run key; no admin rights needed",
        "update.section.update": "Update",
        "update.current_source": "Update source: {source}",
        "update.releases_link": "Release page (changelog & news): ",
        "update.homepage": "Homepage: ",
        "btn.check_update": "Check for updates…",
        "btn.set_source": "Set update source…",
        "update.hint": "An update source is built in; change it only if the repo moves.",
        "update.section.about": "About",
        "about.text": (
            "Desktop Lyrics  v{version}\n"
            "Shows the lyrics of whatever is playing right now, straight from Windows media "
            "controls — works with any player."
        ),
        "btn.open_settings_dir": "Open settings folder",
        "btn.open_cache_dir": "Open lyrics cache folder",
    },
}


_current: str = DEFAULT_LANGUAGE


def resolve(value: str) -> str:
    """把设置里存的值解析成实际语言（空值 = 跟随系统）。"""
    text = str(value or "").strip()
    if text in SUPPORTED:
        return text
    name = QLocale.system().name()  # 例如 zh_CN / en_US
    return "zh_CN" if name.lower().startswith("zh") else "en"


def set_language(value: str) -> str:
    """切换当前语言，返回实际生效的语言代码。"""
    global _current
    _current = resolve(value)
    return _current


def current_language() -> str:
    return _current


def tr(key: str, default: str = "") -> str:
    """取文案：当前语言 → 中文表 → 调用方给的原文 → key 本身。绝不抛异常。"""
    table = STRINGS.get(_current) or {}
    text = table.get(key)
    if text:
        return text
    fallback = STRINGS[DEFAULT_LANGUAGE].get(key)
    if fallback:
        return fallback
    return default or key


def count_keys() -> tuple[int, int]:
    """（中文条数, 英文条数），给自检脚本用。"""
    return len(STRINGS["zh_CN"]), len(STRINGS["en"])
