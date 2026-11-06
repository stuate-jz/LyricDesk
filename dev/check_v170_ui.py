"""v1.7.0 播放器控制布局与进度条拖动回归。"""

from __future__ import annotations

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

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lyricdesk import config  # noqa: E402

config.SETTINGS_PATH = Path(tempfile.mkdtemp(prefix="lyricdesk-v170-ui-")) / "settings.json"

from lyricdesk.config import Settings  # noqa: E402
from lyricdesk.fonts import register_all  # noqa: E402
from lyricdesk.lyrics import LyricLine, Lyrics  # noqa: E402
from lyricdesk.smtc import Snapshot, Track  # noqa: E402
from lyricdesk.window import LyricWindow  # noqa: E402

OUT = Path(__file__).resolve().parent / "v170_control_shots"


class FakeEngine:
    def __init__(self) -> None:
        self.snapshot_value = Snapshot(
            track=Track(
                title="这是一首用于测试播放控制按钮和长歌名的歌曲",
                artist="测试歌手",
                album="测试专辑名称",
                duration=240.0,
            ),
            position=30.0,
            is_playing=True,
            status=4,
            source="QQMusic.exe",
        )
        self.lyrics = Lyrics(
            lines=[
                LyricLine(0.0, "第一行测试歌词", 10.0),
                LyricLine(10.0, "第二行测试歌词", 20.0),
                LyricLine(20.0, "第三行测试歌词", 30.0),
                LyricLine(30.0, "当前正在播放的测试歌词", 45.0),
                LyricLine(45.0, "下一行测试歌词", 60.0),
            ],
            source="测试",
            title="测试歌曲",
            artist="测试歌手",
        )
        self.commands: list[str] = []

    def snapshot(self):
        return self.snapshot_value

    def players(self):
        return []

    def send_control(self, command):
        self.commands.append(command)


def send_mouse(
    window: LyricWindow,
    event_type,
    local: QPointF,
    button,
    buttons,
) -> None:
    global_pos = QPointF(window.mapToGlobal(local.toPoint()))
    event = QMouseEvent(event_type, local, global_pos, button, buttons, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(window, event)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    register_all()
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  {'OK  ' if ok else 'FAIL'} {name}" + (f"  —— {detail}" if detail else ""))
        if not ok:
            failures.append(name)

    OUT.mkdir(exist_ok=True)
    sizes = (12, 38, 80)
    widths = (240, 380, 1000)
    for font_size in sizes:
        for width in widths:
            settings = Settings()
            settings.font_family = "Smiley Sans"
            settings.font_size = font_size
            settings.player_width = width
            settings.cover_size = 88
            player = LyricWindow(settings, FakeEngine(), role="player")
            player.show()
            app.processEvents()
            player.render(QPixmap(player.size()))
            image = player.grab()
            path = OUT / f"controls-{font_size}px-{width}w.png"
            image.save(str(path))
            row_h = player._album_title_h
            control = min(
                max(24.0, font_size * 0.82),
                max(18.0, row_h * 1.6),
            )
            controls_top = min(hit.top() for hit in (player._hit_prev, player._hit_play, player._hit_next))
            controls_bottom = max(hit.bottom() for hit in (player._hit_prev, player._hit_play, player._hit_next))
            check(
                f"{font_size}px / {width}px 控件尺寸受标题行约束",
                control <= max(18.0, row_h * 1.6) + 0.01
                and controls_top >= 0
                and controls_bottom <= player.height(),
                f"control={control:.1f} row={row_h:.1f}",
            )
            player.hide()
            player.deleteLater()
    app.processEvents()

    settings = Settings()
    settings.player_width = 600
    engine = FakeEngine()
    player = LyricWindow(settings, engine, role="player")
    player.show()
    app.processEvents()
    player.render(QPixmap(player.size()))
    bar = player._hit_bar
    start = bar.center()
    send_mouse(
        player,
        QEvent.Type.MouseButtonPress,
        start,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
    )
    check("按下进度条进入拖动模式", player._scrub_active and player._scrub_pos is not None)
    preview_before = player._scrub_pos
    engine.snapshot_value.position = 120.0
    moved = QPointF(bar.left() + bar.width() * 0.70, start.y())
    send_mouse(
        player,
        QEvent.Type.MouseMove,
        moved,
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
    )
    check("拖动期间外部进度不会覆盖预览", player._scrub_pos != preview_before)
    check("拖动期间不发 seek", not engine.commands, str(engine.commands))
    send_mouse(
        player,
        QEvent.Type.MouseButtonRelease,
        moved,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
    )
    check("松手只发送一次 seek", len(engine.commands) == 1 and engine.commands[0].startswith("seek:"), str(engine.commands))
    check("松手清除预览", not player._scrub_active and player._scrub_pos is None)

    player.render(QPixmap(player.size()))
    bar = player._hit_bar
    start = bar.center()
    send_mouse(
        player,
        QEvent.Type.MouseButtonPress,
        start,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
    )
    outside = QPointF(bar.right() + 120, bar.center().y())
    send_mouse(
        player,
        QEvent.Type.MouseMove,
        outside,
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
    )
    before_cancel = len(engine.commands)
    send_mouse(
        player,
        QEvent.Type.MouseButtonRelease,
        outside,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
    )
    check("拖出进度条后松手取消", len(engine.commands) == before_cancel)

    player.deleteLater()
    app.processEvents()
    if failures:
        print("\n失败：", ", ".join(failures))
        return 1
    print(f"\n全部通过；九种组合截图：{OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
