"""回归检查：绘制时不会因为缺排版属性而抛 AttributeError。

背景：`_disc_size / _list_slot / _main_h` 这一组是各模式分支在 `recalculate()`
里各自算出来的。模式刚改、还没重算就来一次重绘时，paintEvent 会去读一个
根本不存在的属性 —— Qt 会把异常吞掉只往 stderr 打一行，界面直接花掉/不更新。

这个脚本做两件事：
1. 负面对照：手动删掉属性再重绘，确认**这种异常确实会被捕获到**（保证检测手段有效）；
2. 正面检查：四种模式 × 三种窗口角色随便切、切完不重算就重绘，全部不出异常。

    python dev\\check_paint_attrs.py
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
from contextlib import redirect_stderr
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lyricdesk import config  # noqa: E402

config.SETTINGS_PATH = Path(tempfile.mkdtemp(prefix="lyricdesk-paint-")) / "settings.json"

from lyricdesk.config import Settings  # noqa: E402
from lyricdesk.lyrics import LyricLine, Lyrics  # noqa: E402
from lyricdesk.smtc import Snapshot, Track  # noqa: E402
from lyricdesk.window import LyricWindow  # noqa: E402

MODES = ("album", "lyrics", "player", "depth3d")
ROLES = ("main", "player", "lyrics")


class FakeEngine:
    def __init__(self) -> None:
        self._snapshot = Snapshot(
            track=Track(title="海屿你", artist="马也_Crabbit", album="海屿你", duration=219.0),
            position=10.0,
            is_playing=True,
            status=4,
            source="QQMusic.exe",
        )
        self._lyrics = Lyrics(
            lines=[
                LyricLine(time=0.0, text="他们说爱过就可以伤和别离", end=4.0),
                LyricLine(time=4.0, text="像放在手心就能够发光美丽", end=8.0),
                LyricLine(time=8.0, text="像放在脑海就能够翻云覆雨", end=12.0),
            ],
            source="QQ音乐",
            title="海屿你",
            artist="马也_Crabbit",
            albummid="",
            album="海屿你",
        )

    @property
    def lyrics(self):
        return self._lyrics

    def snapshot(self):
        return self._snapshot

    def players(self):
        return []


def paint(window: LyricWindow) -> str:
    """重绘一次，返回这段时间里 Qt 吐到 stderr 的内容。

    render() 会把 paintEvent 里的异常直接抛上来，repaint() 只往 stderr 打一行，
    所以两种都要接住，返回的字符串里带 "AttributeError" 就算没画成。
    """
    buffer = io.StringIO()
    layer = QPixmap(window.size())
    try:
        with redirect_stderr(buffer):
            window.render(layer)
            window.repaint()
    except Exception as exc:  # noqa: BLE001
        buffer.write(f"{type(exc).__name__}: {exc}\n")
    return buffer.getvalue()


def main() -> int:
    app = QApplication(sys.argv)
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  {'OK  ' if ok else 'FAIL'} {name}" + (f"  —— {detail}" if detail else ""))
        if not ok:
            failures.append(name)

    print("负面对照（确认检测手段抓得到这种异常）：")
    settings = Settings()
    window = LyricWindow(settings, FakeEngine())
    window.show()
    app.processEvents()
    saved = window._disc_size
    del window._disc_size
    settings.mode = "album"  # 不重算，直接画
    noise = paint(window)
    check(
        "删掉属性后确实报 AttributeError",
        "AttributeError" in noise or "_disc_size" in noise,
        noise.strip().splitlines()[-1][:90] if noise.strip() else "（没有输出）",
    )
    window._disc_size = saved
    noise = paint(window)
    check("补回属性后就不再报错", "_disc_size" not in noise)

    print("\n四种模式 × 三种角色：切完不重算直接重绘：")
    for role in ROLES:
        settings = Settings()
        win = LyricWindow(settings, FakeEngine(), role=role)
        win.show()
        app.processEvents()
        noise = ""
        for mode in MODES:
            settings.mode = mode
            noise += paint(win)
        check(f"role={role} 四种模式都不缺属性", "AttributeError" not in noise)
        win.hide()
        win.deleteLater()

    print("\n恢复默认之后立刻重绘：")
    settings = Settings()
    win = LyricWindow(settings, FakeEngine())
    win.show()
    app.processEvents()
    settings.reset()
    win._commit(resize=True, flags=True, background=True)
    noise = paint(win)
    check("reset() + _commit() 后重绘正常", "AttributeError" not in noise)

    print("\n构造后每个模式至少重绘一次（不经过 recalculate）：")
    for mode in MODES:
        settings = Settings()
        settings.mode = mode
        win = LyricWindow(settings, FakeEngine())
        noise = paint(win)
        check(f"mode={mode}", "AttributeError" not in noise)
        win.deleteLater()

    app.processEvents()
    if failures:
        print("\n失败：", ", ".join(failures))
        return 1
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
