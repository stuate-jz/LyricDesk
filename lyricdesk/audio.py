"""WASAPI 回环音波：只读系统正在播放的声音，不做注入或录音落盘。"""

from __future__ import annotations

import cmath
import math
import threading
import time
from array import array
from collections import deque

try:
    import pyaudiowpatch as pyaudio

    IMPORT_AVAILABLE = True
except Exception:  # noqa: BLE001
    pyaudio = None
    IMPORT_AVAILABLE = False

FFT_SIZE = 1024
BAND_COUNT = 24
HISTORY_FRAMES = 48
FRAME_SECONDS = 0.025


def _fft(values: list[complex]) -> list[complex]:
    """原地基 2 FFT；只用于固定 1024 点的频谱，避免引入 numpy。"""
    count = len(values)
    j = 0
    for i in range(1, count):
        bit = count >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j ^= bit
        if i < j:
            values[i], values[j] = values[j], values[i]
    length = 2
    while length <= count:
        root = cmath.exp(-2j * math.pi / length)
        half = length // 2
        for start in range(0, count, length):
            factor = 1.0 + 0.0j
            for offset in range(half):
                even = values[start + offset]
                odd = values[start + offset + half] * factor
                values[start + offset] = even + odd
                values[start + offset + half] = even - odd
                factor *= root
        length <<= 1
    return values


def _band_edges(sample_rate: int) -> list[int]:
    low, high = 40.0, min(16000.0, sample_rate / 2.0)
    edges = [0]
    for index in range(1, BAND_COUNT + 1):
        ratio = index / BAND_COUNT
        frequency = low * ((high / low) ** ratio)
        edges.append(max(1, min(FFT_SIZE // 2 - 1, int(frequency * FFT_SIZE / sample_rate))))
    for index in range(1, len(edges)):
        edges[index] = max(edges[index], edges[index - 1] + 1)
    return edges


def _spectrum(samples: list[float], sample_rate: int) -> list[float]:
    if len(samples) < FFT_SIZE:
        samples = [0.0] * (FFT_SIZE - len(samples)) + samples
    else:
        samples = samples[-FFT_SIZE:]
    windowed = [
        (samples[index] / 32768.0)
        * (0.5 - 0.5 * math.cos(2.0 * math.pi * index / (FFT_SIZE - 1)))
        for index in range(FFT_SIZE)
    ]
    values = [complex(value, 0.0) for value in windowed]
    transformed = _fft(values)
    edges = _band_edges(sample_rate)
    output: list[float] = []
    for index in range(BAND_COUNT):
        start = edges[index]
        end = max(start + 1, edges[index + 1])
        peak = max(
            abs(transformed[bin_index]) * 2.0 / FFT_SIZE
            for bin_index in range(start, min(end, FFT_SIZE // 2))
        )
        level = 20.0 * math.log10(max(peak, 1e-7))
        output.append(max(0.0, min(1.0, (level + 72.0) / 66.0)))
    return output


def _loopback_device(api) -> dict:
    host = api.get_host_api_info_by_type(pyaudio.paWASAPI)
    default_index = int(host.get("defaultOutputDevice", -1))
    if default_index >= 0:
        speaker = api.get_device_info_by_index(default_index)
        if speaker.get("isLoopbackDevice"):
            return speaker
        speaker_name = str(speaker.get("name") or "").lower()
        for item in api.get_loopback_device_info_generator():
            name = str(item.get("name") or "").lower()
            if speaker_name and speaker_name in name:
                return item
    for item in api.get_loopback_device_info_generator():
        return item
    raise RuntimeError("没有可用的 WASAPI 回环设备")


def available() -> tuple[bool, str]:
    if not IMPORT_AVAILABLE:
        return False, "未安装 pyaudiowpatch"
    api = None
    try:
        api = pyaudio.PyAudio()
        device = _loopback_device(api)
        return True, str(device.get("name") or "默认输出回环")
    except Exception as exc:  # noqa: BLE001
        return False, f"无回环设备：{exc}"
    finally:
        if api is not None:
            try:
                api.terminate()
            except Exception:  # noqa: BLE001
                pass


class AudioMonitor:
    """按窗口订阅启停；没有订阅者时线程完全退出。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._clients: dict[int, tuple[bool, bool]] = {}
        self._levels: deque[list[float]] = deque(
            ([0.0] * BAND_COUNT for _ in range(HISTORY_FRAMES)),
            maxlen=HISTORY_FRAMES,
        )
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._status = "未启动"
        self._has_data = False

    def update_client(self, client_id: int, enabled: bool, active: bool) -> None:
        with self._lock:
            self._clients[int(client_id)] = (bool(enabled), bool(active))
        self._reconcile()

    def remove_client(self, client_id: int) -> None:
        with self._lock:
            self._clients.pop(int(client_id), None)
        self._reconcile()

    def _wanted(self) -> bool:
        with self._lock:
            return any(enabled and active for enabled, active in self._clients.values())

    def _reconcile(self) -> None:
        wanted = self._wanted()
        running = self._thread is not None and self._thread.is_alive()
        if wanted and not running:
            self._stop = threading.Event()
            self._status = "正在打开回环设备"
            with self._lock:
                self._has_data = False
            self._thread = threading.Thread(
                target=self._run,
                name="wasapi-loopback",
                daemon=True,
            )
            self._thread.start()
        elif not wanted and running:
            self._stop.set()
            self._status = "已暂停"

    def _run(self) -> None:
        api = None
        stream = None
        try:
            api = pyaudio.PyAudio()
            device = _loopback_device(api)
            sample_rate = int(float(device.get("defaultSampleRate") or 48000))
            channels = max(1, int(device.get("maxInputChannels") or 2))
            chunk = max(FFT_SIZE, int(sample_rate * FRAME_SECONDS))
            stream = api.open(
                format=pyaudio.paInt16,
                channels=channels,
                rate=sample_rate,
                input=True,
                input_device_index=int(device["index"]),
                frames_per_buffer=chunk,
            )
            self._status = f"{device.get('name') or '默认输出'} · {sample_rate} Hz"
            while not self._stop.is_set():
                raw = stream.read(chunk, exception_on_overflow=False)
                samples = array("h")
                samples.frombytes(raw)
                if channels > 1:
                    mono = [
                        sum(samples[index:index + channels]) / channels
                        for index in range(0, len(samples) - channels + 1, channels)
                    ]
                else:
                    mono = list(samples)
                levels = _spectrum(mono, sample_rate)
                with self._lock:
                    self._levels.append(levels)
                    self._has_data = True
        except Exception as exc:  # noqa: BLE001
            self._status = f"回环不可用：{exc}"
        finally:
            if stream is not None:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:  # noqa: BLE001
                    pass
            if api is not None:
                try:
                    api.terminate()
                except Exception:  # noqa: BLE001
                    pass
            with self._lock:
                self._thread = None

    def levels(self, count: int) -> list[float]:
        count = max(1, int(count))
        with self._lock:
            frames = list(self._levels)
        if not frames:
            return [0.0] * count
        newest = frames[-1]
        if count <= len(newest):
            return [
                newest[min(len(newest) - 1, int(index * len(newest) / count))]
                for index in range(count)
            ]
        return [
            newest[min(len(newest) - 1, int(index * len(newest) / count))]
            for index in range(count)
        ]

    def history(self, band: int) -> list[float]:
        with self._lock:
            frames = list(self._levels)
        band = max(0, min(BAND_COUNT - 1, int(band)))
        return [frame[band] for frame in frames]

    @property
    def status(self) -> str:
        return self._status

    @property
    def thread_count(self) -> int:
        thread = self._thread
        return int(thread is not None and thread.is_alive())

    @property
    def has_data(self) -> bool:
        with self._lock:
            return self._has_data


MONITOR = AudioMonitor()
