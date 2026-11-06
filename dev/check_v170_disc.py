"""v1.7.0 圆盘排版、逐字进度与拖动预览的无头回归。"""

from __future__ import annotations

import io
import os
import sys
import tempfile
from contextlib import redirect_stderr
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lyricdesk import config  # noqa: E402

config.SETTINGS_PATH = Path(tempfile.mkdtemp(prefix="lyricdesk-v170-")) / "settings.json"

from lyricdesk.config import Settings  # noqa: E402
from lyricdesk.fonts import register_all  # noqa: E402
from lyricdesk.lyricdoc import LyricWord  # noqa: E402
from lyricdesk.lyrics import LyricLine, Lyrics  # noqa: E402
from lyricdesk.smtc import Snapshot, Track  # noqa: E402
from lyricdesk.window import LyricWindow  # noqa: E402

OUT = Path(__file__).resolve().parent / "v170_disc_shots"


class FakeEngine:
    def __init__(self) -> None:
        self._snapshot = Snapshot(
            track=Track(
                title="很长的圆盘歌词测试歌曲",
                artist="测试歌手",
                album="测试专辑",
                duration=240.0,
            ),
            position=41.0,
            is_playing=True,
            status=4,
            source="QQMusic.exe",
        )
        texts = [
            "短句",
            "四字歌词",
            "这是一行长度为六字的歌词",
            "这一行故意写得非常非常长用来测试圆盘边界",
            "夜色落在透明的桌面上",
            "让每一个字都沿着半径发光",
            "当前这一句应该最亮并且略微向外",
            "下一句仍然保持清晰的阅读方向",
            "左侧和右侧都不能倒着写字",
            "角度变化时也不要跑出窗口",
            "十四行歌词的边缘情况",
            "第四行",
            "第五行",
            "最后一行",
        ]
        lines = []
        for index, text in enumerate(texts):
            start = float(index * 5)
            words = []
            cursor = start
            for char in text:
                words.append(LyricWord(cursor, 0.35, char))
                cursor += 0.35
            lines.append(
                LyricLine(
                    time=start,
                    text=text,
                    end=start + 4.8,
                    words=words,
                    trans=f"translation {index}",
                )
            )
        self._lyrics = Lyrics(
            lines=lines,
            source="测试逐字",
            title="很长的圆盘歌词测试歌曲",
            artist="测试歌手",
            provider="test",
        )
        self._lyrics.to_doc()

    @property
    def lyrics(self):
        return self._lyrics

    def snapshot(self):
        return self._snapshot

    def players(self):
        return []

    def send_control(self, _command):
        return None


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    register_all()
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  {'OK  ' if ok else 'FAIL'} {name}" + (f"  —— {detail}" if detail else ""))
        if not ok:
            failures.append(name)

    OUT.mkdir(exist_ok=True)
    settings = Settings()
    settings.font_family = "Smiley Sans"
    settings.show_song_info = False
    settings.background = False
    settings.lyric_layout = "disc"
    settings.lyric_lines = 7
    engine = FakeEngine()
    window = LyricWindow(settings, engine)
    window.show()
    app.processEvents()

    check("圆盘默认在右侧", settings.lyric_align == "right")
    check("圆盘窗口尺寸受宽度上限约束", window.width() <= config.WIDTH_MAX + 120)
    check("圆盘窗口高度可容纳径向排布", window.height() >= 240)

    noise = ""
    current = engine.lyrics.lines[8]
    for length in (4, 6, 14):
        text = ("短句随光向前" * 10)[:length]
        current.text = text
        current.words = [
            LyricWord(current.time + index * 0.3, 0.27, char)
            for index, char in enumerate(text)
        ]
        for side in ("left", "right"):
            settings.lyric_align = side
            for angle in (-90, -45, 0, 45, 90):
                settings.disc_angle = angle
                window._commit(resize=True)
                layer = QPixmap(window.size())
                stderr = io.StringIO()
                try:
                    with redirect_stderr(stderr):
                        window.render(layer)
                    suffix = "left" if side == "left" else "right"
                    layer.save(
                        str(OUT / f"disc-{length}char-{suffix}-{angle:+d}.png")
                    )
                except Exception as exc:  # noqa: BLE001
                    stderr.write(f"{type(exc).__name__}: {exc}\n")
                noise += stderr.getvalue()
                check(
                    f"{length} 字 / {side} / {angle:+d}° 可绘制",
                    not stderr.getvalue(),
                    stderr.getvalue().strip().splitlines()[-1][:100]
                    if stderr.getvalue().strip()
                    else "",
                )
    check("整组圆盘绘制没有异常", not noise)

    covered_size = (window.width(), window.height())
    settings.show_cover = False
    window._commit(resize=True)
    empty_size = (window.width(), window.height())
    check("取消封面后歌词半径不变", empty_size == covered_size)
    settings.show_cover = True

    for _ in range(10):
        window._set_lyric_layout("list")
        window._set_lyric_layout("disc")
    app.processEvents()
    stderr = io.StringIO()
    try:
        with redirect_stderr(stderr):
            window.render(QPixmap(window.size()))
    except Exception as exc:  # noqa: BLE001
        stderr.write(f"{type(exc).__name__}: {exc}\n")
    check("列表与圆盘往返 10 次无残留异常", not stderr.getvalue())

    for effect in ("off", "word", "bounce", "sweep"):
        settings.lyric_effect = effect
        window._commit()
        stderr = io.StringIO()
        try:
            with redirect_stderr(stderr):
                window.render(QPixmap(window.size()))
        except Exception as exc:  # noqa: BLE001
            stderr.write(f"{type(exc).__name__}: {exc}\n")
        check(f"歌词动效 {effect} 可绘制", not stderr.getvalue())
    settings.lyric_effect = "off"

    fake = window.engine
    window._set_lyric_layout("list")
    current = fake.lyrics.lines[8]
    fake._snapshot.position = current.time + 1.05
    progress = window._lyric_progress(
        fake.snapshot(), current, fake.lyrics.lines[9]
    )
    check("逐字进度按字边界推进", 0.0 < progress < 1.0, f"{progress:.3f}")
    fake._snapshot.position = current.time + 20.0
    window._scrub_pos = current.time + 0.7
    preview = window._lyric_progress(fake.snapshot(), current, fake.lyrics.lines[9])
    check("拖动预览覆盖外部播放位置", abs(preview - progress) > 0.01)
    window._scrub_pos = None

    window.hide()
    window.deleteLater()
    app.processEvents()
    if failures:
        print("\n失败：", ", ".join(failures))
        return 1
    print(f"\n全部通过；截图目录：{OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
