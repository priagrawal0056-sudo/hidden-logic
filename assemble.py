"""FFmpeg renderer for Hidden Logic vertical shorts.

The editorial path maps five reviewed stock shots to five narration beats, respects each
reviewed source start and crop position, and keeps color treatment light. It deliberately
adds no loop-back, zoom punch, generated whoosh/impact, branding, hook overlay, or fade.
"""
from __future__ import annotations

import json
import os
import subprocess
from typing import Any

W, H = 1080, 1920
SCALE_W, SCALE_H = 1188, 2112


def _audio_duration(timings_path: str) -> float:
    with open(timings_path, encoding="utf-8") as fh:
        words = json.load(fh)
    if not words:
        raise ValueError("word timings are empty")
    return float(words[-1]["end"]) + 0.8


def _probe_duration(path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True, timeout=30,
    )
    duration = float(result.stdout.strip())
    if duration <= 0:
        raise ValueError(f"media has invalid duration: {path}")
    return duration


def _escape_filter_path(path: str) -> str:
    return os.path.abspath(path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def _crop_fractions(position: dict[str, Any] | None) -> tuple[float, float]:
    position = position or {}
    x_map = {"left": 0.0, "center": 0.5, "right": 1.0}
    y_map = {"top": 0.0, "center": 0.5, "bottom": 1.0}
    x, y = position.get("x", "center"), position.get("y", "center")
    if x not in x_map or y not in y_map:
        raise ValueError(f"invalid reviewed crop position: {position!r}")
    return x_map[x], y_map[y]


def _normalized_segments(duration: float, segment_durations: list[float] | None,
                         shot_count: int, strict_editorial: bool) -> list[float]:
    if strict_editorial:
        if shot_count != 5 or segment_durations is None or len(segment_durations) != 5:
            raise ValueError("editorial assembly requires five shots and five beat durations")
        durations = [float(value) for value in segment_durations]
        if any(value <= 0 for value in durations):
            raise ValueError("all narration beat durations must be positive")
        delta = duration - sum(durations)
        if abs(delta) > 0.5:
            raise ValueError(
                f"five beat durations differ from audio by {delta:.2f}s; refusing to shift reviewed cuts"
            )
        durations[-1] += delta
        if durations[-1] <= 0:
            raise ValueError("last narration beat duration became invalid")
        return durations
    if not shot_count:
        raise ValueError("no stock clips supplied")
    if segment_durations is not None:
        if len(segment_durations) != shot_count:
            raise ValueError("clip count and segment duration count differ")
        durations = [float(value) for value in segment_durations]
        if any(value <= 0 for value in durations):
            raise ValueError("all segment durations must be positive")
        delta = duration - sum(durations)
        if abs(delta) > 0.5:
            raise ValueError("segment durations do not align with narration duration")
        durations[-1] += delta
        return durations
    return [duration / shot_count] * shot_count


def build_video_filter_graph(bg_paths: list[str], segment_durations: list[float],
                             shot_records: list[dict], ass_path: str) -> str:
    """Build the visual FFmpeg graph and expose it for deterministic unit tests."""
    filters: list[str] = []
    labels: list[str] = []
    for index, (path, seconds, record) in enumerate(zip(bg_paths, segment_durations, shot_records)):
        start = float(record.get("source_start", 0.0))
        if start < 0:
            raise ValueError("reviewed source start cannot be negative")
        x_fraction, y_fraction = _crop_fractions(record.get("crop_position"))
        label = f"shot{index}"
        filters.append(
            f"[{index}:v]trim=start={start:.3f}:duration={seconds:.3f},setpts=PTS-STARTPTS,"
            f"scale={SCALE_W}:{SCALE_H}:force_original_aspect_ratio=increase,"
            f"crop={SCALE_W}:{SCALE_H}:x='(in_w-{SCALE_W})*{x_fraction:.3f}':"
            f"y='(in_h-{SCALE_H})*{y_fraction:.3f}',"
            f"scale={W}:{H},setsar=1,fps=30,format=yuv420p[{label}]"
        )
        labels.append(f"[{label}]")
    filters.append("".join(labels) + f"concat=n={len(labels)}:v=1:a=0[vcat]")
    ass_file = _escape_filter_path(ass_path)
    font_dir = _escape_filter_path(os.path.dirname(os.path.abspath(__file__)))
    # Light color only. Captions sit on the footage; no branding or decorative text layer.
    filters.append(
        f"[vcat]eq=contrast=1.02:saturation=1.02,"
        f"subtitles='{ass_file}':fontsdir='{font_dir}':original_size={W}x{H}[vout]"
    )
    return ";".join(filters)


def assemble(bg_paths: list[str], voice_path: str, timings_path: str,
             ass_path: str, out_path: str, music_path: str | None = None,
             music_volume: float = 0.10, seg_seconds: float | list[float] | None = None,
             emphasis_words=None, sfx_dir: str | None = None,
             brand_label: str | None = None, fast_pacing: bool = True,
             opening_hook_text: str | None = None, show_subscribe_cue: bool = False,
             show_follow_cue: bool = False, *, shot_records: list[dict] | None = None,
             strict_editorial: bool = False) -> str:
    """Render a vertical short while retaining the old call signature.

    `strict_editorial=True` is used by production generation and requires five unique reviewed
    shots. Legacy visual flags remain accepted for compatibility but are intentionally ignored.
    """
    del emphasis_words, sfx_dir, brand_label, fast_pacing, opening_hook_text
    del show_subscribe_cue, show_follow_cue
    duration = _audio_duration(timings_path)
    records = list(shot_records or [])
    if strict_editorial:
        if len(bg_paths) != 5 or len(records) != 5:
            raise ValueError("strict editorial render requires five reviewed stock-shot records")
        paths = [os.path.abspath(path) for path in bg_paths]
        if len(set(paths)) != 5:
            raise ValueError("strict editorial render rejects a reused clip path")
        ids = [str(record.get("clip_id", "")) for record in records]
        hashes = [str(record.get("sha256", "")) for record in records]
        if any(not value for value in ids + hashes) or len(set(ids)) != 5 or len(set(hashes)) != 5:
            raise ValueError("strict editorial render rejects missing or duplicate clip IDs/hashes")
        if [os.path.abspath(str(record.get("local_path", ""))) for record in records] != paths:
            raise ValueError("shot records do not match the supplied clip paths")
    else:
        if not records:
            records = [{"source_start": 0.0, "crop_position": {"x": "center", "y": "center"}}
                       for _ in bg_paths]
        if len(records) != len(bg_paths):
            raise ValueError("shot metadata count does not match clip count")

    if isinstance(seg_seconds, list):
        segment_durations = list(seg_seconds)
    elif seg_seconds is not None:
        segment_durations = [float(seg_seconds)] * len(bg_paths)
    else:
        segment_durations = None
    durations = _normalized_segments(duration, segment_durations, len(bg_paths), strict_editorial)

    for index, path in enumerate(bg_paths):
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            raise ValueError(f"missing or empty stock clip for beat {index+1}: {path}")
        clip_duration = _probe_duration(path)
        source_start = float(records[index].get("source_start", 0.0))
        if source_start + durations[index] > clip_duration + 0.05:
            raise ValueError(
                f"reviewed source window for beat {index+1} exceeds clip duration "
                f"({source_start:.2f}+{durations[index]:.2f}>{clip_duration:.2f})"
            )

    if not os.path.isfile(voice_path) or os.path.getsize(voice_path) == 0:
        raise ValueError("voice track is missing or empty")
    if not os.path.isfile(ass_path) or os.path.getsize(ass_path) == 0:
        raise ValueError("validated captions are missing or empty")

    command = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    for path in bg_paths:
        # No -stream_loop: every beat uses its own reviewed source window exactly once.
        command += ["-i", path]
    voice_index = len(bg_paths)
    command += ["-i", voice_path]
    has_music = bool(music_path and os.path.isfile(music_path))
    if has_music:
        command += ["-stream_loop", "-1", "-i", music_path]

    visual_graph = build_video_filter_graph(bg_paths, durations, records, ass_path)
    audio_filters = [
        f"[{voice_index}:a]highpass=f=85,acompressor=threshold=-18dB:ratio=3:attack=8:release=120[voice]"
    ]
    if has_music:
        music_index = voice_index + 1
        volume = min(max(float(music_volume), 0.0), 0.2)
        audio_filters.append(f"[{music_index}:a]volume={volume:.3f}[music]")
        audio_filters.append(
            "[voice][music]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
            "loudnorm=I=-14:TP=-1.5:LRA=9[aout]"
        )
    else:
        audio_filters.append("[voice]loudnorm=I=-14:TP=-1.5:LRA=9[aout]")

    command += [
        "-filter_complex", visual_graph + ";" + ";".join(audio_filters),
        "-map", "[vout]", "-map", "[aout]",
        "-t", f"{duration:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
        "-pix_fmt", "yuv420p", "-r", "30",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart", out_path,
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=900)
    if result.returncode != 0:
        raise RuntimeError("ffmpeg failed:\n" + result.stderr[-3000:])
    if not os.path.isfile(out_path) or os.path.getsize(out_path) < 10_000:
        raise RuntimeError("ffmpeg render is missing, empty, or truncated")
    return out_path
