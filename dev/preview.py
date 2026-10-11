"""离线把歌词窗口渲染成 PNG，用于快速检查视觉效果与定位绘制异常。"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lyricdesk.config import Settings  # noqa: E402
from lyricdesk.lyrics import LyricLine, Lyrics  # noqa: E402
from lyricdesk.smtc import Snapshot, Track  # noqa: E402
from lyricdesk.window import LyricWindow  # noqa: E402


class FakeEngine:
    def __init__(self) -> None:
        self._snapshot = Snapshot(
            track=Track(
                title="失忆 (温柔版)",
                artist="正在进行石女士",
                album="失忆（温柔版）",
                duration=219.3,
            ),
            position=0.0,
            is_playing=True,
            status=4,
            source="QQMusic.exe",
        )
        lines = [
            LyricLine(time=0.0, text="他们说爱过就可以伤和别离", end=4.0),
            LyricLine(time=4.0, text="像放在手心就能够发光美丽", end=8.0),
            LyricLine(time=8.0, text="像放在脑海就能够翻云覆雨", end=12.0),
            LyricLine(time=12.0, text="从陌生到熟悉爱你到恨你", end=16.0),
        ]
        self._lyrics = Lyrics(
            lines=lines,
            source="QQ音乐",
            title="失忆 (温柔版)",
            artist="正在进行石女士",
            albummid="0017EIWN0ujqJ6",
            album="失忆温柔女生版",
        )

    @property
    def lyrics(self):
        return self._lyrics

    def snapshot(self):
        return self._snapshot

    def set_position(self, value: float) -> None:
        self._snapshot.position = value


def render(window: LyricWindow, path: Path, background: str = "#ffffff") -> None:
    pixmap = QPixmap(window.size())
    pixmap.fill(QColor(background))
    window.render(pixmap)
    pixmap.save(str(path))


def main() -> int:
    app = QApplication(sys.argv)
    settings = Settings()
    engine = FakeEngine()
    window = LyricWindow(settings, engine)
    window.recalculate()

    out = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    out.mkdir(parents=True, exist_ok=True)

    # 先触发一次绘制，让窗口发起封面请求，再等待下载完成
    import time as _time

    render(window, out / "_warmup.png")
    deadline = _time.time() + 15
    while _time.time() < deadline:
        app.processEvents()
        _time.sleep(0.05)
        if window._covers:
            break
    print("covers loaded:", list(window._covers))

    cases = [
        ("10_player", 6.2, "aurora", True, True, "player"),
        ("11_player_sakura", 14.0, "sakura", True, True, "player"),
        ("12_player_nocover", 6.0, "sunset", True, False, "player"),
        ("13_lyrics", 6.0, "aurora", True, True, "lyrics"),
        ("14_player_nobg", 10.0, "ink", False, True, "player"),
        ("20_depth3d", 6.2, "aurora", True, True, "depth3d"),
        ("21_depth3d_sakura", 10.0, "sakura", True, True, "depth3d"),
        ("22_depth3d_jade", 14.0, "jade", True, True, "depth3d"),
    ]
    for name, position, theme, background, cover, mode in cases:
        combos = [("frost", 0.0, 0.32)]
        if mode == "depth3d":
            combos = [
                ("frost", 0.0, 0.32),
                ("frost", 0.20, 0.0),
                ("frost", 0.18, 0.18),
                ("ambient", 0.0, 0.32),
                ("outline", 0.0, 0.32),
            ]
        for style, depth_v, depth_h in combos:
            suffix = f"_{style}_v{depth_v}_h{depth_h}" if mode == "depth3d" else ""
            try:
                engine.set_position(position)
                settings.theme = theme
                settings.background = background
                settings.show_cover = cover
                settings.mode = mode
                settings.raise_style = style
                settings.show_progress = mode == "player"
                settings.show_controls = mode == "player"
                settings.show_next = mode != "depth3d"
                settings.show_prev = False
                settings.text_tilt = 0.0
                settings.text_depth_v = depth_v
                settings.text_depth_h = depth_h
                window._bg_key = None
                window.recalculate()
                window._anim_t0 = 0.0
                window._display_idx = -2
                render(
                    window,
                    out / f"{name}{suffix}.png",
                    "#2b3040" if mode == "depth3d" else "#ffffff",
                )
                print(f"rendered {name}{suffix}.png  size={window.width()}x{window.height()}")
            except Exception:
                print(f"FAILED {name}{suffix}")
                traceback.print_exc()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
