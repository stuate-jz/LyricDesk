"""第三批（v1.6.5）的回归检查。

覆盖：
1. `update.releases_url()` / `homepage_url()` 的换算（Gitee / GitHub / http / 空 / 本地文件）；
2. 设置窗口「更新与关于」里的发布页链接：可点、跟着更新源变；
3. 「播放」分类里删掉了「显示上一首按钮 / 显示下一首按钮」，其余三项还在；
4. 五个主题 × 深浅两套调色板：字段齐、占位符全替换、对比度达标、素白无色相；
5. 顶部主题色标题带；
6. 老 settings.json（还带 show_prev/show_next）能正常加载；
7. 唱片模式下「显示播放控制」开着时三个按钮的命中区都在，关掉就都没有。

    python dev\\check_v165.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

import re  # noqa: E402

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QCheckBox, QFrame, QLabel  # noqa: E402

from lyricdesk import config  # noqa: E402

config.SETTINGS_PATH = Path(tempfile.mkdtemp(prefix="lyricdesk-v165-")) / "settings.json"

from lyricdesk.config import THEME_ORDER, Settings  # noqa: E402
from lyricdesk.lyrics import LyricLine, Lyrics  # noqa: E402
from lyricdesk.settings_dialog import (  # noqa: E402
    SettingsDialog,
    build_style,
    palette_for,
)
from lyricdesk.smtc import Snapshot, Track  # noqa: E402
from lyricdesk.update import (  # noqa: E402
    DEFAULT_HOMEPAGE_URL,
    DEFAULT_RELEASES_URL,
    homepage_url,
    releases_url,
)
from lyricdesk.window import LyricWindow  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'OK  ' if ok else 'FAIL'} {name}" + (f"  —— {detail}" if detail else ""))
    if not ok:
        FAILED.append(name)


def _lum(color: str) -> float:
    c = QColor(color)

    def channel(value: int) -> float:
        v = value / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    return (
        0.2126 * channel(c.red())
        + 0.7152 * channel(c.green())
        + 0.0722 * channel(c.blue())
    )


def contrast(a: str, b: str) -> float:
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


class FakeEngine:
    def __init__(self, playing: bool = True) -> None:
        track = Track(title="海屿你", artist="马也_Crabbit", album="海屿你", duration=219.0)
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


def main() -> int:
    app = QApplication(sys.argv)

    print("1) 发布页 / 主页地址换算")
    cases = [
        ("gitee:pursue-studies/LyricDesk", "https://gitee.com/pursue-studies/LyricDesk/releases"),
        ("foo/bar", "https://github.com/foo/bar/releases"),
        ("https://example.com/upd.json", "https://example.com/upd.json"),
        ("", DEFAULT_RELEASES_URL),
        ("D:\\some\\local\\update.json", DEFAULT_RELEASES_URL),
    ]
    for source, want in cases:
        got = releases_url(source)
        check(f"releases_url({source!r})", got == want, f"{got}")
    check(
        "homepage_url 是发布页去掉 /releases",
        homepage_url("gitee:pursue-studies/LyricDesk")
        == "https://gitee.com/pursue-studies/LyricDesk",
        homepage_url("gitee:pursue-studies/LyricDesk"),
    )
    check(
        "认不出来时回退项目主页常量",
        homepage_url("") == DEFAULT_HOMEPAGE_URL == "https://gitee.com/pursue-studies/LyricDesk",
    )

    settings = Settings()
    window = LyricWindow(settings, FakeEngine())
    dialog = SettingsDialog(window)
    dialog.show()
    app.processEvents()

    print("\n2) 「更新与关于」里的发布页链接")
    link = dialog._releases_link
    check("有发布页链接标签", link is not None)
    check("链接可以直接点开（openExternalLinks）", link.openExternalLinks())
    check(
        "文字交互标志允许浏览器交互",
        bool(link.textInteractionFlags() & Qt.TextInteractionFlag.LinksAccessibleByMouse),
    )
    text = link.text()
    check(
        "默认指向内置 Gitee 发布页",
        f'href="{DEFAULT_RELEASES_URL}"' in text and DEFAULT_RELEASES_URL in text,
        text[:80],
    )
    settings.update_source = "foo/bar"
    dialog._refresh()
    check(
        "改成 GitHub 形式的更新源后链接跟着变",
        'href="https://github.com/foo/bar/releases"' in link.text(),
        link.text()[:80],
    )
    settings.update_source = ""
    dialog._refresh()
    check("清空更新源后回到内置发布页", DEFAULT_RELEASES_URL in link.text())
    check(
        "关于里也有一行可点的项目主页",
        dialog._homepage_link is not None
        and dialog._homepage_link.openExternalLinks()
        and "gitee.com/pursue-studies/LyricDesk" in dialog._homepage_link.text(),
        dialog._homepage_link.text()[:80] if dialog._homepage_link else "无",
    )
    # 英文界面下这两行也要是英文（验收第 4 条）
    dialog._set_language("en")
    app.processEvents()
    check(
        "英文界面下发布页那行是英文",
        link.text().startswith("Release page") and DEFAULT_RELEASES_URL in link.text(),
        link.text()[:60],
    )
    check(
        "英文界面下项目主页那行是英文",
        dialog._homepage_link.text().startswith("Homepage"),
        dialog._homepage_link.text()[:40],
    )
    dialog._set_language("zh_CN")
    app.processEvents()
    check("切回中文恢复", link.text().startswith("发布页"), link.text()[:20])
    # 这两行纯靠字符串换算，永远不会发网络请求
    source_text = (ROOT / "lyricdesk" / "update.py").read_text(encoding="utf-8")
    block = source_text[source_text.index("def releases_url"):source_text.index("def homepage_url")]
    check("地址换算里没有网络请求", "requests" not in block and "urlopen" not in block)

    print("\n3) 「播放」分类里两个开关已删除")
    texts = [c.text() for c in dialog.findChildren(QCheckBox)]
    check("没有「显示上一首按钮」", not any("上一首" in t for t in texts), str(texts))
    check("没有「显示下一首按钮」", not any("下一首" in t for t in texts))
    for keep in ("显示封面", "显示进度条", "显示播放控制"):
        check(f"仍有「{keep}」", any(keep == t for t in texts))

    print("\n4) 主题调色板（5 主题 × 深浅）")
    fields = (
        "bg", "panel", "card", "text", "text_dim", "line",
        "accent", "accent2", "accent_soft", "on_accent",
    )
    contrast_problems: list[str] = []
    leftover_problems: list[str] = []
    for theme in THEME_ORDER:
        for mode in ("dark", "light"):
            palette = palette_for(theme, mode)
            missing = [f for f in fields if not palette.get(f)]
            check(f"{theme}/{mode} 字段齐", not missing, str(missing))
            style = build_style(mode, theme)
            left = sorted(set(re.findall(r"%[A-Z_0-9]+%", style)))
            if left:
                leftover_problems.append(f"{theme}/{mode}:{left}")
            pairs = (
                ("正文/背景", palette["text"], palette["bg"], 4.5),
                ("正文/卡片", palette["text"], palette["card"], 4.5),
                ("次要文字/背景", palette["text_dim"], palette["bg"], 3.0),
                ("强调色/背景", palette["accent"], palette["bg"], 3.0),
                ("强调色上文字/强调色", palette["on_accent"], palette["accent"], 4.0),
            )
            for label, fg, bg, need in pairs:
                ratio = contrast(fg, bg)
                if ratio < need:
                    contrast_problems.append(
                        f"{theme}/{mode} {label} {ratio:.2f}<{need}"
                    )
    check("10 套样式都没有残留占位符", not leftover_problems, "; ".join(leftover_problems))
    check(
        "10 套配色的对比度都达标",
        not contrast_problems,
        "; ".join(contrast_problems) or "全部达标",
    )
    ink_problems: list[str] = []
    for mode in ("dark", "light"):
        palette = palette_for("ink", mode)
        for key in fields:
            if key == "on_accent":
                continue
            c = QColor(palette[key])
            spread = max(c.red(), c.green(), c.blue()) - min(c.red(), c.green(), c.blue())
            # 32 是「几乎无色相」的宽容度：素白的灰带一点点冷调不碍事，
            # 但不能跑出某个主题的色相（比如青、粉）
            if spread > 32:
                ink_problems.append(f"{mode}.{key}={palette[key]} 色差{spread}")
    check("素白主题不带彩色（各通道差 ≤32）", not ink_problems, "; ".join(ink_problems))

    print("\n5) 顶部主题色标题带")
    band = dialog.findChild(QFrame, "titlebar")
    check("标题带控件存在", band is not None and band.height() == 4)
    aurora_style = build_style("dark", "aurora")
    check(
        "极光的标题带是渐变",
        "QFrame#titlebar" in aurora_style
        and palette_for("aurora", "dark")["accent"] in aurora_style
        and "qlineargradient" in aurora_style,
    )
    ink_style = build_style("light", "ink")
    check(
        "素白的标题带是淡灰细线（不用纯白渐变）",
        "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6f798c" not in ink_style,
    )

    print("\n6) 老 settings.json 兼容")
    config.SETTINGS_PATH.write_text(
        json.dumps({"show_prev": True, "show_next": False, "width": 500}), encoding="utf-8"
    )
    old = Settings.load()
    check(
        "带 show_prev/show_next 的老配置能加载",
        old.show_prev is True and old.show_next is False and old.width == 500,
        f"{old.show_prev}/{old.show_next}/{old.width}",
    )
    check(
        "渲染用的字段没被删",
        hasattr(old, "show_prev") and hasattr(old, "show_next")
        and hasattr(window, "_toggle_prev") and hasattr(window, "_toggle_next"),
    )

    print("\n7) 唱片模式：显示播放控制 = 三个按钮一起开关")
    from PySide6.QtCore import QPointF

    album = LyricWindow(Settings(), FakeEngine())
    album.settings.mode = "album"
    album.settings.show_controls = True
    album.recalculate()
    album.render(QPixmap(album.size()))
    spots = {
        "prev": album._hit_prev.center(),
        "play": album._hit_play.center(),
        "next": album._hit_next.center(),
    }
    check(
        "开着时三个按钮命中区都在",
        not album._hit_prev.isEmpty() and not album._hit_play.isEmpty() and not album._hit_next.isEmpty(),
        f"{album._hit_prev.isEmpty()} {album._hit_play.isEmpty()} {album._hit_next.isEmpty()}",
    )
    hits_on = {key: album._hit_test(QPointF(pos)) for key, pos in spots.items()}
    check("三个按钮都能点中", hits_on == {"prev": "prev", "play": "play", "next": "next"}, str(hits_on))
    album.settings.show_controls = False
    album.recalculate()
    album.render(QPixmap(album.size()))
    hits_off = {key: album._hit_test(QPointF(pos)) for key, pos in spots.items()}
    check(
        "关掉后三处都点不动了（按钮不再响应）",
        all(value == "" for value in hits_off.values()),
        str(hits_off),
    )
    # 说明：唱片模式下这三个按钮画在「标题行右侧」，所以关掉它不会让窗口变矮
    print(f"      （唱片模式下窗口高度：开 {album.height()}px —— 控件在标题行里，不占额外行）")

    dialog.close()
    app.processEvents()
    if FAILED:
        print("\n失败：", ", ".join(FAILED))
        return 1
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
