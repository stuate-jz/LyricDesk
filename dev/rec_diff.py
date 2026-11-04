r"""逐帧检查桌面歌词录屏：闪屏、区域卡顿、静音和音频断点。

用法：
    python dev\rec_diff.py <录屏.mp4>

判读规则：
    · 全空帧 > 0：闪屏未修好。
    · 歌词区域最长静止段 > 150ms 且不是换歌时刻：仍在卡顿。
    · 音频静音段可能来自换歌，需要结合播放器画面人工确认。
    · 音频跳变 > 0：可能有爆音、断点或解码损坏。

脚本只依赖 ffmpeg。默认从 PATH、FFMPEG_PATH / FFMPEG 或常见剪映安装目录查找。
视频按 30fps 解码成 320×180；左右两半分别比较，阈值为 5×5 采样块
最大平均亮度差 < 1.5。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

FRAME_W = 320
FRAME_H = 180
FRAME_BYTES = FRAME_W * FRAME_H * 3
ANALYSIS_FPS = 30
STATIC_DIFF_THRESHOLD = 1.5
EMPTY_DARK_RATIO = 0.985
EMPTY_MEAN_LUMA = 10.0
EMPTY_LOCAL_RATIO = 0.72
EMPTY_LOCAL_DARK_RATIO = 0.65
AUDIO_JUMP_THRESHOLD = 30000


def ffmpeg_path() -> Path | None:
    for key in ("FFMPEG_PATH", "FFMPEG"):
        value = os.environ.get(key, "").strip().strip('"')
        if value and Path(value).is_file():
            return Path(value)
    found = shutil.which("ffmpeg")
    if found:
        return Path(found)
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "JianyingPro" / "Apps",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Folia" / "resources" / "ffmpeg-audio",
        Path(r"C:\ffmpeg\bin"),
    ]
    for folder in candidates:
        if not folder.exists():
            continue
        direct = folder / "ffmpeg.exe"
        if direct.is_file():
            return direct
        try:
            nested = sorted(folder.rglob("ffmpeg.exe"))
        except OSError:
            nested = []
        if nested:
            return nested[-1]
    return None


def media_duration(ffmpeg: Path, source: Path) -> float:
    run = subprocess.run(
        [str(ffmpeg), "-hide_banner", "-i", str(source)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", run.stderr)
    if not match:
        return 0.0
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def region_samples(frame: bytes, left: int, right: int) -> list[int]:
    values: list[int] = []
    for y in range(0, FRAME_H, 2):
        row = y * FRAME_W * 3
        for x in range(left, right, 4):
            index = row + x * 3
            values.append(
                (frame[index] + frame[index + 1] + frame[index + 2]) // 3
            )
    return values


def region_diff(a: list[int], b: list[int]) -> float:
    if not a or not b:
        return 0.0
    # 左右半屏里真正变化的文字只占很小面积，整区平均会被背景稀释。
    # 按 5×5 采样块求差异，取变化最大的块，背景噪声仍保持在 0.x。
    columns = (FRAME_W // 2 + 3) // 4
    rows = (FRAME_H + 1) // 2
    if len(a) != len(b) or len(a) != columns * rows:
        return sum(abs(x - y) for x, y in zip(a, b)) / len(a)
    strongest = 0.0
    for block_y in range(0, rows, 5):
        for block_x in range(0, columns, 5):
            total = 0
            count = 0
            for y in range(block_y, min(block_y + 5, rows)):
                offset = y * columns
                for x in range(block_x, min(block_x + 5, columns)):
                    index = offset + x
                    total += abs(a[index] - b[index])
                    count += 1
            if count:
                strongest = max(strongest, total / count)
    return strongest


def frame_stats(values: list[int]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    mean = sum(values) / len(values)
    dark_ratio = sum(1 for value in values if value < 32) / len(values)
    return mean, dark_ratio


def empty_flags_from_stats(stats: list[tuple[float, float]]) -> list[bool]:
    """纯黑帧或相对前 15 帧亮度突然塌陷的空白帧。"""
    flags: list[bool] = []
    rolling: list[float] = []
    for mean, dark_ratio in stats:
        pure_dark = mean < EMPTY_MEAN_LUMA and dark_ratio > EMPTY_DARK_RATIO
        local_blank = False
        if rolling:
            reference = sorted(rolling)[len(rolling) // 2]
            local_blank = (
                mean < reference * EMPTY_LOCAL_RATIO
                and dark_ratio > EMPTY_LOCAL_DARK_RATIO
            )
        flags.append(pure_dark or local_blank)
        rolling.append(mean)
        if len(rolling) > 15:
            rolling.pop(0)
    return flags


def static_summary(deltas: list[float]) -> tuple[int, float]:
    segments = 0
    longest = 0
    run = 0
    for delta in deltas:
        if delta < STATIC_DIFF_THRESHOLD:
            run += 1
        else:
            if run >= 2:
                segments += 1
                longest = max(longest, run)
            run = 0
    if run >= 2:
        segments += 1
        longest = max(longest, run)
    return segments, longest * 1000.0 / ANALYSIS_FPS


def analyze_video(ffmpeg: Path, source: Path) -> dict:
    command = [
        str(ffmpeg),
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-an",
        "-vf",
        f"fps={ANALYSIS_FPS},scale={FRAME_W}:{FRAME_H}:flags=area,format=rgb24",
        "-f",
        "rawvideo",
        "-",
    ]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    assert process.stdout is not None
    previous_left: list[int] | None = None
    previous_right: list[int] | None = None
    left_deltas: list[float] = []
    right_deltas: list[float] = []
    frame_stats_list: list[tuple[float, float]] = []
    frames = 0
    while True:
        frame = process.stdout.read(FRAME_BYTES)
        if len(frame) < FRAME_BYTES:
            break
        frames += 1
        left = region_samples(frame, 0, FRAME_W // 2)
        right = region_samples(frame, FRAME_W // 2, FRAME_W)
        overall = left + right
        frame_stats_list.append(frame_stats(overall))
        if previous_left is not None:
            left_deltas.append(region_diff(previous_left, left))
            right_deltas.append(region_diff(previous_right or right, right))
        previous_left = left
        previous_right = right
    process.wait()

    empty_flags = empty_flags_from_stats(frame_stats_list)
    empty_segments = 0
    empty_frames = 0
    empty_starts: list[int] = []
    in_empty = False
    for frame_index, empty in enumerate(empty_flags):
        if empty:
            empty_frames += 1
            if not in_empty:
                empty_segments += 1
                empty_starts.append(frame_index)
            in_empty = True
        else:
            in_empty = False
    left_segments, left_longest = static_summary(left_deltas)
    right_segments, right_longest = static_summary(right_deltas)
    return {
        "frames": frames,
        "duration": frames / ANALYSIS_FPS,
        "empty_segments": empty_segments,
        "empty_frames": empty_frames,
        "empty_starts": empty_starts,
        "left_segments": left_segments,
        "left_longest_ms": left_longest,
        "right_segments": right_segments,
        "right_longest_ms": right_longest,
    }


def analyze_audio(ffmpeg: Path, source: Path) -> dict:
    silence_command = [
        str(ffmpeg),
        "-hide_banner",
        "-nostats",
        "-i",
        str(source),
        "-vn",
        "-af",
        "silencedetect=noise=-45dB:d=0.1",
        "-f",
        "null",
        "-",
    ]
    silence = subprocess.run(
        silence_command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    segments = []
    starts = re.findall(r"silence_start:\s*([0-9.]+)", silence.stderr)
    ends = re.findall(
        r"silence_end:\s*([0-9.]+)\s*\|\s*silence_duration:\s*([0-9.]+)",
        silence.stderr,
    )
    for index, start in enumerate(starts):
        if index < len(ends):
            segments.append((float(start), float(ends[index][1])))

    pcm_command = [
        str(ffmpeg),
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "8000",
        "-f",
        "s16le",
        "-",
    ]
    process = subprocess.Popen(
        pcm_command,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    assert process.stdout is not None
    jumps = 0
    previous = None
    sample_count = 0
    carry = b""
    while True:
        chunk = process.stdout.read(65536)
        if not chunk:
            break
        data = carry + chunk
        usable = len(data) - (len(data) % 2)
        carry = data[usable:]
        for index in range(0, usable, 2):
            value = int.from_bytes(data[index:index + 2], "little", signed=True)
            sample_count += 1
            if previous is not None and abs(value - previous) > AUDIO_JUMP_THRESHOLD:
                jumps += 1
            previous = value
    process.wait()
    return {
        "samples": sample_count,
        "silences": segments,
        "jumps": jumps,
    }


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    source = Path(sys.argv[1])
    if not source.is_file():
        print("找不到录屏：", source)
        return 2
    ffmpeg = ffmpeg_path()
    if ffmpeg is None:
        print("找不到 ffmpeg；请设置 FFMPEG_PATH 或把 ffmpeg.exe 放进 PATH。")
        return 2
    duration = media_duration(ffmpeg, source)
    print(f"文件：{source}")
    print(f"时长：{duration:.3f}s")
    video = analyze_video(ffmpeg, source)
    audio = analyze_audio(ffmpeg, source)

    print("\n1) 全空帧")
    print(
        f"  段数={video['empty_segments']}  帧数={video['empty_frames']}  "
        f"（期望 0）"
    )
    if video["empty_starts"]:
        print(
            "  起始帧：",
            ", ".join(
                f"#{index + 1} ({index / ANALYSIS_FPS:.2f}s)"
                for index in video["empty_starts"]
            ),
        )
    print("\n2) 区域静止段")
    print(
        f"  左半（网易云）：{video['left_segments']} 处 / "
        f"最长 {video['left_longest_ms']:.0f}ms"
    )
    print(
        f"  右半（歌词窗）：{video['right_segments']} 处 / "
        f"最长 {video['right_longest_ms']:.0f}ms"
    )
    print("  判读：歌词窗最长 > 150ms 且非换歌 = 仍在卡")
    print("\n3) 音频静音段")
    if not audio["silences"]:
        print("  0 处")
    else:
        print(f"  {len(audio['silences'])} 处")
        for start, length in audio["silences"]:
            print(f"  {start:.2f}s 起，持续 {length * 1000:.0f}ms")
    print("\n4) 音频跳变")
    print(f"  {audio['jumps']} 处（期望 0）")
    return 0 if video["empty_segments"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
