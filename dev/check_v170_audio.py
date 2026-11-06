"""v1.7.0 WASAPI 回环 spike：确认能取到非零频谱，并能把线程完全停掉。"""

from __future__ import annotations

import io
import math
import struct
import sys
import threading
import time
import wave

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from lyricdesk import audio  # noqa: E402


def tone_wave(seconds: float = 2.5, frequency: int = 440) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(48000)
        handle.writeframes(
            b"".join(
                struct.pack(
                    "<h",
                    int(18000 * math.sin(2 * math.pi * frequency * index / 48000)),
                )
                for index in range(int(48000 * seconds))
            )
        )
    return buffer.getvalue()


def main() -> int:
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  {'OK  ' if ok else 'FAIL'} {name}" + (f"  —— {detail}" if detail else ""))
        if not ok:
            failures.append(name)

    ok, detail = audio.available()
    check("找到 WASAPI 回环设备", ok, detail)
    if not ok:
        print("\n当前机器没有可用回环设备，结束。")
        return 1

    # 用系统内存 WAV 播放一段 440Hz 测试音，不依赖用户是否正在放歌，也不落盘。
    import winsound

    payload = tone_wave()
    audio.MONITOR.update_client(9001, True, True)
    threading.Thread(
        target=lambda: winsound.PlaySound(payload, winsound.SND_MEMORY),
        daemon=True,
    ).start()

    peak = 0.0
    for _ in range(10):
        time.sleep(0.2)
        peak = max(peak, max(audio.MONITOR.levels(24)))
    check("回环取得非零频谱", peak > 0.05, f"peak={peak:.3f}")
    check("采集线程已启动", audio.MONITOR.thread_count == 1, audio.MONITOR.status)

    audio.MONITOR.remove_client(9001)
    time.sleep(0.5)
    check("关闭后采集线程归零", audio.MONITOR.thread_count == 0)

    started = time.perf_counter()
    for _ in range(100):
        audio._spectrum([0] * audio.FFT_SIZE, 48000)
    elapsed = time.perf_counter() - started
    check("纯 Python 1024 点 FFT 足够实时", elapsed < 1.0, f"100 帧 {elapsed:.3f}s")

    if failures:
        print("\n失败：", ", ".join(failures))
        return 1
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
