"""回归检查：设置窗口的语言 / 皮肤 / 置顶开关 + 新的右键菜单布局。

覆盖本批第 1、3、4、5、6、7、8 项里能用脚本验证的部分：

* 宽度默认 380、旧 settings.json 里的 880 不被偷偷改掉、`_ask_width` 文案与常量一致；
* 中英切换（分类名 / 滑块标题 / 按钮 / 快捷键表）不报 KeyError，漏翻退回中文；
* 设置窗口外观 dark / light / auto（theme=ink 走浅色）；
* 设置窗口默认**不**置顶，勾上才置顶；
* 右键菜单里少了 唱片样式 / 显示封面 / 显示进度条 / 显示播放控制；
* 「设置…」紧挨在「检查更新…」上方，`Ctrl+,` 还在；
* 播放控制那一行三个图标：有歌时可用、没歌时置灰，点了会给播放器发指令。

    python dev\\check_settings_i18n.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

# 这里**不**强制 offscreen：最后一项要弹真的 QFontDialog 挑字体，
# offscreen 平台没有字体数据库（QFontDatabase.families() 是空的）。
# 想无头跑就自己设 QT_QPA_PLATFORM=offscreen，那一项会自动跳过。

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QCheckBox,
    QComboBox,
    QLabel,
    QPushButton,
    QToolButton,
    QWidgetAction,
)

from lyricdesk import config, i18n  # noqa: E402

config.SETTINGS_PATH = Path(tempfile.mkdtemp(prefix="lyricdesk-i18n-")) / "settings.json"

from lyricdesk.config import WIDTH_MAX, WIDTH_MIN, Settings  # noqa: E402
from lyricdesk.lyrics import LyricLine, Lyrics  # noqa: E402
from lyricdesk.settings_dialog import (  # noqa: E402
    SHORTCUT_ROWS,
    SettingsDialog,
    build_style,
    palette_for,
    resolve_dialog_theme,
)
from lyricdesk.smtc import Snapshot, Track  # noqa: E402
from lyricdesk.window import LyricWindow  # noqa: E402

FAILED: list[str] = []


class FakeEngine:
    """既能装成「在播歌」，也能装成「什么都没播」。"""

    def __init__(self, playing: bool = False) -> None:
        self.playing = playing
        self.commands: list[str] = []
        track = (
            Track(title="海屿你", artist="马也_Crabbit", album="海屿你", duration=219.0)
            if playing
            else None
        )
        self._snapshot = (
            Snapshot(track=track, position=10.0, is_playing=True, status=4, source="QQMusic.exe")
            if playing
            else None
        )
        self._lyrics = (
            Lyrics(
                lines=[LyricLine(time=0.0, text="他们说爱过就可以伤和别离", end=4.0)],
                source="QQ音乐",
                title="海屿你",
                artist="马也_Crabbit",
                albummid="",
                album="海屿你",
            )
            if playing
            else None
        )

    @property
    def lyrics(self):
        return self._lyrics

    def snapshot(self):
        return self._snapshot

    def players(self):
        return []

    def send_control(self, action):
        self.commands.append(action)


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'OK  ' if ok else 'FAIL'} {name}" + (f"  —— {detail}" if detail else ""))
    if not ok:
        FAILED.append(name)


def texts_of(dialog) -> list[str]:
    out = [dialog.nav.item(i).text() for i in range(dialog.nav.count())]
    out += [row.title_text for row in dialog._slider_rows]
    out += [b.text() for b in dialog.findChildren(QPushButton)]
    out += [c.text() for c in dialog.findChildren(QCheckBox)]
    for combo in dialog.findChildren(QComboBox):
        out += [combo.itemText(i) for i in range(combo.count())]
    out += [l.text() for l in dialog.findChildren(QLabel)]
    return out


def visible_actions(menu) -> list[str]:
    """菜单里可见的条目（跳过分隔线）——分隔线也是 QAction。"""
    return [a.text() for a in menu.actions() if not a.isSeparator()]


def menu_labels(window) -> list[str]:
    menu = window.build_menu()
    labels = [a.text() for a in menu.actions()]
    for action in menu.actions():
        if action.menu() is not None:
            labels.append(action.text())
    return labels


def main() -> int:
    app = QApplication(sys.argv)

    print("1) 宽度默认值 380 / 范围常量 / 不迁移老配置")
    check("Settings() 默认宽度是 380", Settings().width == 380, str(Settings().width))
    check("范围常量是 240 / 2560", (WIDTH_MIN, WIDTH_MAX) == (240, 2560))
    source = (ROOT / "lyricdesk" / "window.py").read_text(encoding="utf-8")
    check(
        "_ask_width 用的是范围常量而不是字面量",
        "f\"输入窗口宽度（像素，{WIDTH_MIN} ～ {WIDTH_MAX}）：" in source
        and "240 ～ 2560" not in source,
    )
    check(
        "clamp 也用同一对常量",
        "max(WIDTH_MIN, min(WIDTH_MAX" in (ROOT / "lyricdesk" / "config.py").read_text(encoding="utf-8"),
    )
    config.SETTINGS_PATH.write_text(json.dumps({"width": 880, "x": 10, "y": 20}), encoding="utf-8")
    old = Settings.load()
    check("老配置里的 880 原样保留（没被迁移成 380）", old.width == 880, str(old.width))
    check("「跟随系统」在本机解析成中文", i18n.resolve("") == "zh_CN", i18n.resolve(""))

    settings = Settings()
    engine = FakeEngine(playing=True)
    window = LyricWindow(settings, engine)
    window.show()
    app.processEvents()
    window.recalculate()
    from lyricdesk.window import MARGIN

    expected_px = 380 + (MARGIN + window._overscan) * 2
    check(
        "默认窗口像素宽 ≈ 380 + 2×(MARGIN+余量)",
        abs(window.width() - expected_px) <= 2,
        f"实际 {window.width()} / 预期 {expected_px}",
    )

    print("\n2) 语言切换")
    zh_keys, en_keys = i18n.count_keys()
    print(f"  文案表：中文 {zh_keys} 条 / 英文 {en_keys} 条")
    missing_en = sorted(set(i18n.STRINGS["zh_CN"]) - set(i18n.STRINGS["en"]))
    check(
        "中文表里的每条英文都有（除故意不翻的菜单项）",
        set(missing_en) <= {"menu.settings", "menu.check_update"},
        ", ".join(missing_en) or "无遗漏",
    )
    check("表里没有空文案", all(v.strip() for t in i18n.STRINGS.values() for v in t.values()))
    check("tr 遇到未知 key 退回原文", i18n.tr("no.such.key", "中文原文") == "中文原文")

    settings.language = "zh_CN"
    dialog = SettingsDialog(window)
    dialog.show()
    app.processEvents()
    zh_texts = texts_of(dialog)
    check("中文：分类名是中文", dialog.nav.item(0).text() == "界面", dialog.nav.item(0).text())
    check("中文：滑块标题是中文", dialog._slider_rows[0].title_text == "上下倾斜")
    check("中文：有「快捷键」小节", any("快捷键" in t for t in zh_texts))
    check("中文列表里没有英文残留", not any("Interface" == t for t in zh_texts))

    dialog._set_language("en")
    app.processEvents()
    en_texts = texts_of(dialog)
    check("英文：窗口标题变英文", dialog.windowTitle() == "Settings · Desktop Lyrics", dialog.windowTitle())
    check("英文：分类名变 Interface", dialog.nav.item(0).text() == "Interface", dialog.nav.item(0).text())
    check("英文：滑块标题变 Vertical tilt", dialog._slider_rows[0].title_text == "Vertical tilt")
    check("英文：按钮变 Close", any(b.text() == "Close" for b in dialog.findChildren(type(dialog._click_exit))))
    check("英文：语言下拉框里 中文/English 用自名", "English" in en_texts and "中文" in en_texts)
    check(
        "英文：没有漏翻的中文标题（关键词检查）",
        not any(t in en_texts for t in ("界面", "上下倾斜", "整体不透明度", "关闭")),
    )
    check("英文：拖滑块仍能改设置", _drag_test(dialog, settings))
    check("英文：没有抛 KeyError（能跑到这里就说明没有）", True)

    dialog._set_language("zh_CN")
    app.processEvents()
    check("切回中文：分类名恢复", dialog.nav.item(0).text() == "界面", dialog.nav.item(0).text())
    check("切回中文：滑块标题恢复", dialog._slider_rows[0].title_text == "上下倾斜")
    check("语言写进设置", settings.language == "zh_CN", settings.language)
    # 重启后保持：重新建一个设置窗口（等于程序重启时读 settings）
    dialog._set_language("en")
    app.processEvents()
    again = SettingsDialog(window)
    check(
        "重建设置窗口后语言仍然是英文（重启保持）",
        again.nav.item(0).text() == "Interface",
        again.nav.item(0).text(),
    )
    again.close()
    dialog._set_language("zh_CN")
    app.processEvents()

    print("\n3) 设置窗口外观（深色 / 浅色 / 跟随）")
    dark = build_style("dark", "aurora")
    light = build_style("light", "aurora")
    check(
        "深色/浅色两套样式不一样",
        dark != light and palette_for("aurora", "dark")["bg"] in dark
        and palette_for("aurora", "light")["bg"] in light,
    )
    check("auto + 素白 → 浅色", resolve_dialog_theme("auto", "ink") == "light")
    check("auto + 极光 → 深色", resolve_dialog_theme("auto", "aurora") == "dark")
    check("显式 dark 优先", resolve_dialog_theme("dark", "ink") == "dark")
    settings.dialog_theme = "light"
    dialog._apply_theme()
    check(
        "切浅色后样式表用的是当前主题的浅色调色板",
        palette_for(settings.theme, "light")["bg"] in dialog.styleSheet(),
    )
    settings.dialog_theme = "auto"
    settings.theme = "ink"
    dialog._refresh()
    check("跟随歌词主题：改成素白后自动转浅色", dialog._style_mode == "light", dialog._style_mode)
    settings.theme = "aurora"
    dialog._refresh()
    check("跟随歌词主题：改回极光后又变深色", dialog._style_mode == "dark", dialog._style_mode)

    print("\n4) 设置窗口默认不置顶，勾选才置顶")
    dialog.show()
    app.processEvents()
    check(
        "默认没有 WindowStaysOnTopHint",
        not bool(dialog.windowFlags() & Qt.WindowType.WindowStaysOnTopHint),
    )
    dialog._ontop_box.setChecked(True)
    app.processEvents()
    check(
        "勾上后有 WindowStaysOnTopHint",
        bool(dialog.windowFlags() & Qt.WindowType.WindowStaysOnTopHint),
    )
    check("勾上后窗口仍然可见（改标志没把它藏起来）", dialog.isVisible())
    dialog._ontop_box.setChecked(False)
    app.processEvents()
    check(
        "取消后又能被别的程序盖住",
        not bool(dialog.windowFlags() & Qt.WindowType.WindowStaysOnTopHint),
    )

    print("\n5) 快捷键表与真实行为对齐")
    check("表里一共 8 条", len(SHORTCUT_ROWS) == 8, str(len(SHORTCUT_ROWS)))
    menu = window.build_menu()
    action = next((a for a in menu.actions() if a.text() == "设置…"), None)
    check(
        "Ctrl+, 真的挂在「设置…」上",
        action is not None and action.shortcut().toString() == "Ctrl+,",
        action.shortcut().toString() if action else "没找到",
    )
    check(
        "Ctrl+Alt+L 的热键代码在（0x11 Ctrl / 0x12 Alt / 0x4C L）",
        all(chip in source for chip in ("GetAsyncKeyState(0x11)", "GetAsyncKeyState(0x12)", "GetAsyncKeyState(0x4C)")),
    )
    check("双击空白处锁定/解锁在代码里", "_toggle_locked" in source and "def mouseDoubleClickEvent" in source)
    check("托盘双击切换显示/隐藏在代码里", "ActivationReason.DoubleClick" in (ROOT / "lyricdesk" / "app.py").read_text(encoding="utf-8"))

    print("\n6) 右键菜单布局（第 5、6、8 项）")
    labels = menu_labels(window)
    for gone in ("唱片样式", "显示封面", "显示进度条", "显示播放控制"):
        check(f"菜单里没有「{gone}」", gone not in labels)
    order = visible_actions(menu)
    idx_settings = order.index("设置…")
    idx_check = order.index("检查更新…")
    check("「设置…」紧挨在「检查更新…」上方", idx_check - idx_settings == 1, f"{idx_settings} → {idx_check}")
    check("Ctrl+, 快捷键保留", action is not None and not action.shortcut().isEmpty())
    check("设置窗口「播放」分类里这几项还在", _player_page_has(dialog, "唱片样式", "显示封面", "显示进度条", "显示播放控制"))

    print("\n7) 播放控制那一行三个图标")
    buttons = play_buttons(menu)
    check("菜单里有一行三个图标按钮", len(buttons) == 3, [b.text() for b in buttons])
    holder = buttons[0].parentWidget() if buttons else None
    layout = holder.layout() if holder is not None else None
    check(
        "三个按钮横排在一个盒子里（同一个 QHBoxLayout，顺序不变）",
        len(buttons) == 3
        and layout is not None
        and layout.__class__.__name__ == "QHBoxLayout"
        and [layout.itemAt(i).widget() for i in range(3)] == buttons,
        f"{layout.__class__.__name__ if layout else '无布局'} / {[b.text() for b in buttons]}",
    )
    check("有歌在播：三个都可用", all(b.isEnabled() for b in buttons))
    for button in buttons:
        button.click()
    check(
        "点了会真的给播放器发指令",
        engine.commands == ["prev", "toggle", "next"],
        str(engine.commands),
    )
    idle_engine = FakeEngine(playing=False)
    idle_window = LyricWindow(Settings(), idle_engine)
    idle_menu = idle_window.build_menu()  # 得留着引用，不然菜单一回收 QAction 就没了
    idle_buttons = play_buttons(idle_menu)
    check(
        "没播放器时三个图标是灰的",
        len(idle_buttons) == 3 and not any(b.isEnabled() for b in idle_buttons),
    )

    print("\n8) 打开设置窗口时，歌词窗的置顶临时挂起")
    from lyricdesk.window import set_all_topmost_suspended

    check("默认没挂起", window._suspend_topmost is False)
    check(
        "默认是置顶的（settings.always_on_top=True）",
        bool(window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint),
    )
    window.open_settings()
    app.processEvents()
    check("开设置窗口后挂起", window._suspend_topmost is True)
    check(
        "挂起后不再置顶（设置窗口才不会被歌词压住）",
        not bool(window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint),
    )
    check("挂起期间设置没被改（关掉就能恢复）", settings.always_on_top is True)
    check("挂起时窗口仍然可见", window.isVisible())
    opened_dialog = window._settings_dialog
    opened_dialog.close()
    app.processEvents()
    check("关掉设置窗口后恢复置顶", bool(window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint))
    check("恢复后挂起标记清掉", window._suspend_topmost is False)
    # 分离面板那种「两扇窗口」的情况也要一起挂起
    extra = LyricWindow(settings, FakeEngine(playing=True), role="lyrics")
    set_all_topmost_suspended(True)
    check(
        "两扇歌词窗一起挂起",
        window._suspend_topmost and extra._suspend_topmost,
        f"{window._suspend_topmost} / {extra._suspend_topmost}",
    )
    set_all_topmost_suspended(False)
    check("一起恢复", not window._suspend_topmost and not extra._suspend_topmost)
    extra.deleteLater()

    print("\n9) 「从系统字体中选择…」能真的把字体换上")

    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QFontDialog

    families = sorted(QFontDatabase.families())
    target = "Microsoft YaHei UI" if "Microsoft YaHei UI" in families else (families[0] if families else "")
    start = next((f for f in families if f != target), target)
    if not target:
        print("  SKIP  当前平台没有字体数据库（offscreen），这一项需要在真实桌面下跑")
    settings.font_family = start

    def pick() -> None:
        modal = QApplication.activeModalWidget()
        if isinstance(modal, QFontDialog) and target:
            modal.setCurrentFont(QFont(target))
            modal.accept()

    def safety() -> None:  # 兜底：万一上面没抓到，别让模态框把脚本卡住
        modal = QApplication.activeModalWidget()
        if modal is not None:
            modal.reject()

    QTimer.singleShot(400, pick)
    QTimer.singleShot(2500, safety)
    error = ""
    if target:
        try:
            window._pick_font_dialog()
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
        check("调用不抛异常", not error, error)
        check(
            "选完字体真的换上了（不再是点了没反应）",
            settings.font_family == target,
            f"实际 {settings.font_family} / 期望 {target}",
        )

    dialog.close()
    app.processEvents()
    if FAILED:
        print("\n失败：", ", ".join(FAILED))
        return 1
    print("\n全部通过")
    return 0


def play_buttons(menu) -> list:
    """菜单里那一行播放控制按钮（QWidgetAction 里横排的三个 QToolButton）。"""
    buttons: list = []
    for action in menu.actions():
        if isinstance(action, QWidgetAction):
            holder = action.defaultWidget()
            if holder is not None:
                buttons += holder.findChildren(QToolButton)
    return buttons


def _drag_test(dialog, settings) -> bool:
    row = dialog._slider_rows[2]  # 整体旋转：不合并，立刻落地
    before = settings.text_tilt
    row.slider.setValue(row.slider.minimum() + 25)
    return settings.text_tilt != before


def _player_page_has(dialog, *needles: str) -> bool:
    texts = [l.text() for l in dialog.findChildren(QLabel)]
    texts += [c.text() for c in dialog.findChildren(QCheckBox)]
    texts += [c.itemText(i) for c in dialog.findChildren(QComboBox) for i in range(c.count())]
    texts += [b.text() for b in dialog.findChildren(QPushButton)]
    return all(any(n in t for t in texts) for n in needles)


if __name__ == "__main__":
    raise SystemExit(main())
