"""回归检查：设置窗口。

盯着几件很容易做错的事：
1. 滑动条的范围必须和 config.clamp() 完全一致（不然拖到头值也不变）；
2. 右键菜单里那 12 项要真的消失，而功能在设置窗口里都找得到；
3. 「恢复默认」不能把窗口位置 / 每首歌的偏移 / 更新源清掉；
4. 四种界面模式 + 没歌在播的时候，打开设置窗口都不能抛异常；
5. 倾斜范围放宽后，窗口留的透明余量要跟着变大（否则文字会被裁掉）。

用的是假引擎（不起 SMTC 后台线程），跑的是 offscreen 平台，不需要真的开窗口。
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:  # 无控制台/老代码页下也能打出中文
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QValidator  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lyricdesk import config  # noqa: E402

# 存档往返测试绝不能碰用户真正的 settings.json
config.SETTINGS_PATH = Path(tempfile.mkdtemp(prefix="lyricdesk-dialog-")) / "settings.json"

from lyricdesk.config import Settings  # noqa: E402
from lyricdesk.settings_dialog import SettingsDialog, SliderRow  # noqa: E402
from lyricdesk.window import LyricWindow  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'OK  ' if ok else 'FAIL'} {name}" + (f"  —— {detail}" if detail else ""))
    if not ok:
        FAILED.append(name)


class FakeEngine:
    """LyricWindow 只要这么多接口就够跑起来了；不起后台线程。"""

    def __init__(self) -> None:
        self.lyrics = None

    def snapshot(self):
        return None

    def players(self):
        return []

    def send_control(self, _action):
        return None

    def reload(self):
        return None


def main() -> int:
    app = QApplication(sys.argv)

    settings = Settings()
    window = LyricWindow(settings, FakeEngine())
    dialog = SettingsDialog(window)
    dialog.show()
    app.processEvents()

    print("滑动条（界面分类）：")
    rows: list[SliderRow] = list(dialog._slider_rows)
    for row in rows:
        print(
            f"    {row.title_text}: {row.minimum:g} ~ {row.maximum:g}"
            f" 步长 {row._step:g}"
        )
    expected = [
        ("上下倾斜", -0.80, 0.80, 0.01),
        ("左右倾斜", -0.80, 0.80, 0.01),
        ("整体旋转", -90.0, 90.0, 1.0),
        ("封面大小", 40, 320, 2),
        ("歌词宽度（歌词实际能显示多宽）", 240, 1440, 10),
        ("播放器宽度", 0, 1440, 10),
        ("歌词字号", 12, 200, 1),
        ("歌词列表行数", 1, 15, 1),
        ("歌唱行间距", 0.50, 3.00, 0.05),
        ("整体不透明度", 5, 100, 1),
    ]
    check(
        "一共 10 条滑动条",
        len(rows) == 10,
        f"实际 {len(rows)} 条",
    )
    for row, (title, lo, hi, step) in zip(rows, expected):
        ok = (
            row.title_text == title
            and abs(row.minimum - lo) < 1e-9
            and abs(row.maximum - hi) < 1e-9
            and abs(row._step - step) < 1e-9
        )
        check(f"{title} 范围 {lo:g}~{hi:g}", ok)

    print("\n滑动条范围与 clamp() 一致（拖到两端，值不被改写）：")
    fields = {
        "上下倾斜": "text_depth_v",
        "左右倾斜": "text_depth_h",
        "整体旋转": "text_tilt",
        "封面大小": "cover_size",
        "歌词宽度（歌词实际能显示多宽）": "width",
        "播放器宽度": "player_width",
        "歌词字号": "font_size",
        "歌词列表行数": "lyric_lines",
        "歌唱行间距": "line_spacing",
    }
    for row in rows:
        field = fields.get(row.title_text)
        if field is None:
            # 整体不透明度在界面上是 5~100 的百分数，落到字段是 0.05~1.0
            row.set_value(row.minimum)
            row.flush()
            low = settings.ui_opacity
            row.set_value(row.maximum)
            row.flush()
            high = settings.ui_opacity
            check(
                "整体不透明度 5%~100% 对应 0.05~1.0",
                abs(low - 0.05) < 1e-6 and abs(high - 1.0) < 1e-6,
                f"{low} / {high}",
            )
            continue
        row.set_value(row.minimum)
        row.flush()
        low = getattr(settings, field)
        row.set_value(row.maximum)
        row.flush()
        high = getattr(settings, field)
        same = abs(float(low) - row.minimum) < 1e-6 and abs(float(high) - row.maximum) < 1e-6
        check(f"{row.title_text} 两端都不被 clamp 改写", same, f"{low} / {high}")

    print("\n右键菜单：")
    menu = window.build_menu()
    labels = [a.text() for a in menu.actions()]
    submenu_labels = [
        a.text() for a in menu.actions() if a.menu() is not None
    ]
    removed = [
        "歌词排版", "主题", "歌词字号", "封面大小", "窗口宽度", "歌词行间距",
        "整体不透明度", "开机自启", "打开音乐软件时自动显示歌词", "上下倾斜",
        "左右倾斜", "整体旋转",
    ]
    all_labels = labels + submenu_labels
    for name in removed:
        check(f"菜单里没有「{name}」", name not in all_labels)
    check("菜单里有「设置…」", "设置…" in labels)

    print("\n设置窗口里的替代入口：")
    for name in ("歌词排版", "整体不透明度", "上下倾斜", "左右倾斜", "整体旋转", "歌词宽度", "播放器宽度"):
        found = any(
            name in child.text()
            for child in dialog.findChildren(type(dialog._click_warn))
        ) or any(
            name in row.title_text for row in dialog._slider_rows
        ) or any(
            name in combo.currentText() or any(name in combo.itemText(i) for i in range(combo.count()))
            for combo in dialog.findChildren(type(dialog._player_combo))
        )
        check(f"设置窗口里有「{name}」入口", found)

    print("\n恢复默认：")
    settings.width = 1800
    settings.text_tilt = 42.0
    settings.x, settings.y = 111, 222
    settings.song_offsets = {"QQMusic.exe|歌|人|200": -1500}
    settings.update_source = "gitee:someone/Repo"
    settings.preferred_player = "Spotify.exe"
    settings.save()
    settings.reset()
    check("窗口位置保留", (settings.x, settings.y) == (111, 222))
    check("每首歌的偏移保留", settings.song_offsets == {"QQMusic.exe|歌|人|200": -1500})
    check("更新源保留", settings.update_source == "gitee:someone/Repo")
    check("偏好播放器保留", settings.preferred_player == "Spotify.exe")
    check("宽度恢复默认", settings.width == Settings().width, str(settings.width))
    check("旋转恢复默认", settings.text_tilt == Settings().text_tilt)
    check("仅左右倾斜默认强", abs(Settings().text_depth_h - 0.32) < 1e-9)

    print("\n四种模式 + 没歌在播时打开设置窗口：")
    for mode in ("depth3d", "lyrics", "album", "split", "player", "compact"):
        try:
            settings.mode = mode
            settings.clamp()
            dialog._refresh()
            window.recalculate()
            ok = True
            detail = settings.mode
        except Exception as exc:  # noqa: BLE001
            ok = False
            detail = f"{type(exc).__name__}: {exc}"
        check(f"模式 {mode}", ok, detail)
    settings.mode = "depth3d"
    settings.clamp()

    print("\n文字倾斜的透明余量（真透视后按包围盒现算）：")
    settings.text_depth_v = 0.0
    settings.text_depth_h = 0.32
    settings.text_tilt = 0.0
    window.recalculate()
    base = (window._overscan, window._overscan_v)
    check("默认倾斜不需要额外余量（透视只会往小里缩）", base == (0, 0), str(base))
    settings.text_depth_v = 0.80
    settings.text_depth_h = 0.80
    settings.text_tilt = 0.0
    window.recalculate()
    wide = window._overscan
    check("两个方向拉满：横向不需要余量", wide == 0, str(wide))
    check("纵向余量按包围盒现算（不再是写死 76）", 0 <= window._overscan_v <= 80, str(window._overscan_v))
    prev_v = window._overscan_v
    settings.text_tilt = 60.0
    window.recalculate()
    check("再叠上旋转，余量跟着变大", window._overscan_v > prev_v, f"{prev_v} → {window._overscan_v}")

    print("\n数值框（正数带 + 号）：")
    spin = rows[0].spin
    spin.setValue(0.32)
    state, _text, _pos = spin.validate("+0.32", 0)
    check("+0.32 能被接受", state == QValidator.State.Acceptable, str(state))
    check("显示成 +0.32", spin.text() == "+0.32", spin.text())

    print("\n唱片封面二次上限：")
    settings.mode = "album"
    settings.clamp()
    settings.cover_size = 320
    window.recalculate()
    check("封面 320 时唱片大于旧的 240 上限", window._disc_size > 240, str(window._disc_size))

    print("\n分离面板切换时的设置窗口转交：")
    settings.mode = "split"
    settings.clamp()
    player = LyricWindow(settings, FakeEngine(), role="player")
    lyrics = LyricWindow(settings, FakeEngine(), role="lyrics")
    player.open_settings()
    moved = player._settings_dialog
    check("面板窗口能打开设置窗口", moved is not None)
    player.transfer_settings_dialog(lyrics)
    check("转交后旧窗口不再持有引用", getattr(player, "_settings_dialog", None) is None)
    check("转交后新窗口持有同一个窗口", lyrics._settings_dialog is moved)
    check("转交后宿主已换成新窗口", moved.window is lyrics)
    moved.close()
    app.processEvents()
    player.deleteLater()
    lyrics.deleteLater()
    settings.mode = "depth3d"
    settings.clamp()

    print("\n从菜单 / 托盘菜单打开设置窗口：")
    menu = window.build_menu()
    action = next((a for a in menu.actions() if a.text() == "设置…"), None)
    check("菜单里有可点击的「设置…」项", action is not None)
    if action is not None:
        action.trigger()
        app.processEvents()
        opened = getattr(window, "_settings_dialog", None)
        check("点菜单能打开设置窗口", opened is not None and opened.isVisible())
        action.trigger()
        app.processEvents()
        check(
            "重复点击不会再开一个（单实例）",
            getattr(window, "_settings_dialog", None) is opened,
        )
        window.raise_settings()
        opened.close()
        app.processEvents()
        check("关掉之后引用被清空", getattr(window, "_settings_dialog", None) is None)

    print("\n拖动滑动条 60 步时的刷新次数（去重）：")
    calls = {"n": 0}
    signals = {"n": 0}
    original_refresh = dialog._refresh

    def counting_refresh() -> None:
        calls["n"] += 1
        original_refresh()

    window.settingsChanged.connect(lambda: signals.__setitem__("n", signals["n"] + 1))
    dialog._refresh = counting_refresh  # type: ignore[method-assign]
    spin_row = rows[2]  # 整体旋转：不合并、一步一次提交
    ticks_min = spin_row.slider.minimum()
    for step in range(60):
        spin_row.slider.setValue(ticks_min + (step % 30) + 10)
        app.processEvents()
    dialog._refresh = original_refresh  # type: ignore[method-assign]
    print(
        f"  60 步 → settingsChanged {signals['n']} 次，_refresh {calls['n']} 次"
    )
    check(
        "刷新次数不超过步数（没有翻倍）",
        calls["n"] <= 60 and calls["n"] <= max(1, signals["n"]),
        f"{calls['n']} 次 / {signals['n']} 个通知",
    )
    check("刷新的确发生了", calls["n"] >= 1, f"{calls['n']} 次")

    merged = {"n": 0}

    def merge_refresh() -> None:
        merged["n"] += 1
        original_refresh()

    dialog._refresh = merge_refresh  # type: ignore[method-assign]
    for _ in range(3):
        dialog._on_settings_changed()  # 同一帧连着来 3 个通知
    app.processEvents()
    dialog._refresh = original_refresh  # type: ignore[method-assign]
    check("同一帧的 3 个通知只刷一次", merged["n"] == 1, f"{merged['n']} 次")
    # 去重不改变刷新内容：数值仍然和设置一致
    dialog._refresh()
    check(
        "去重后数值依旧同步",
        spin_row.spin.value() == settings.text_tilt,
        f"spin={spin_row.spin.value()} settings={settings.text_tilt}",
    )

    dialog.close()
    app.processEvents()

    if FAILED:
        print("\n失败：", ", ".join(FAILED))
        return 1
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
