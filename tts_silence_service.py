"""Compress long TTS silences in staged artifacts before they become live.

No model calls or application wiring: cuts use measured PCM boundaries, and
all timestamps use the same piecewise translation (never a duration ratio).
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import wave
from typing import Any, Mapping

from scripts.media_tools import resolve_media_tool

MAX_SILENCE_SEC = 2.0
SILENCE_THRESHOLD_DB = -50
POLICY_VERSION = "long_silence_cap_2s_v1"


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def compressed_timeline_matches_audio(timeline: dict, audio: Path) -> bool:
    report = timeline.get("silence_compression")
    return bool(isinstance(report, dict) and report.get("version") == POLICY_VERSION
                and audio.is_file() and report.get("audio_sha256") == _sha256(audio))


def silence_cuts(log: str, duration: float, rate: int) -> list[tuple[int, int]]:
    """Keep half of the two-second allowance at each edge of a long pause."""
    cuts = []
    start = None
    for kind, value in re.findall(r"silence_(start|end):\s*([0-9.eE+\-]+)", log):
        point = float(value)
        if not math.isfinite(point):
            raise ValueError("Invalid silence timestamp")
        if kind == "start":
            start = max(0.0, point)
        elif start is not None:
            cuts.append((start, min(duration, point)))
            start = None
    if start is not None:
        cuts.append((start, duration))
    result = []
    for start, end in cuts:
        if end - start <= MAX_SILENCE_SEC:
            continue
        # ceil/floor protect speech at both ends, even with detector rounding.
        left = math.ceil((start + MAX_SILENCE_SEC / 2) * rate)
        right = math.floor((end - MAX_SILENCE_SEC / 2) * rate)
        if right > left:
            result.append((left, right))
    return result


def translate_time(value: float, cuts: list[tuple[float, float]]) -> float:
    return max(0.0, value - sum(max(0.0, min(value, end) - start)
                                for start, end in cuts))


def _translate_provider(value: Any, cuts: list[tuple[float, float]]) -> None:
    if isinstance(value, list):
        for child in value:
            _translate_provider(child, cuts)
    elif isinstance(value, dict):
        for key, child in value.items():
            if key in ("time_begin", "time_end") and isinstance(child, (int, float)):
                value[key] = round(1000 * translate_time(child / 1000, cuts))
            elif isinstance(child, (list, dict)):
                _translate_provider(child, cuts)


def _retime_segments(segments: list[dict], cuts: list[tuple[float, float]],
                     duration: float, *, measured: bool) -> None:
    for segment in segments:
        for key in ("start", "end"):
            value = float(segment[key])
            if not math.isfinite(value):
                raise ValueError("Invalid subtitle timestamp")
            segment[key] = round(min(duration, translate_time(value, cuts)), 3)
    if measured:
        if any(item["end"] <= item["start"] for item in segments):
            raise ValueError("Silence cuts would collapse a measured subtitle segment")
        return
    # Estimated splits can place a whole subtitle in a long silent region.
    # Keep its text and beat identity in a minimal display interval at the cut,
    # without claiming measured timing or dropping a narration/animation anchor.
    next_start = round(duration, 3)
    for segment in reversed(segments):
        segment["end"] = min(next_start, segment["end"])
        segment["start"] = round(min(segment["start"], segment["end"] - .001), 3)
        if segment["start"] < 0:
            raise ValueError("Not enough audio duration for subtitle segments")
        next_start = segment["start"]


def _srt(segments: list[dict]) -> str:
    def timestamp(seconds: float) -> str:
        milliseconds = round(max(0, seconds) * 1000)
        seconds, milliseconds = divmod(milliseconds, 1000)
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"

    return "\n\n".join(
        f"{index}\n{timestamp(item['start'])} --> {timestamp(item['end'])}\n{item['text']}"
        for index, item in enumerate(segments, 1)
    ) + "\n"


def _run(command: list[str]) -> subprocess.CompletedProcess:
    result = subprocess.run(command, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=300)
    if result.returncode:
        raise RuntimeError(f"静音压缩失败：{result.stderr[-1200:]}")
    return result


def compress_staged_tts_silence(paths: Mapping[str, str], *, repo_root: Path) -> dict:
    """Only accepts disposable staging paths; errors must prevent promotion.

    Unchanged audio is byte-for-byte preserved. When cuts exist, retain all
    original artifacts for recovery and update display and measured timings.
    """
    audio = Path(paths["audio"])
    timeline_path = Path(paths["timeline"])
    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    if compressed_timeline_matches_audio(timeline, audio):
        return timeline["silence_compression"]
    ffmpeg = resolve_media_tool("ffmpeg", repo_root)
    if not ffmpeg:
        raise RuntimeError("自动压缩长停顿需要 FFmpeg，请安装后重试。")
    original_hash = _sha256(audio)
    with tempfile.TemporaryDirectory(prefix="tts-silence-", dir=audio.parent) as directory:
        work = Path(directory)
        decoded, trimmed, encoded = work / "decoded.wav", work / "trimmed.wav", work / "voice.mp3"
        detection = _run([ffmpeg, "-hide_banner", "-nostdin", "-y", "-i", str(audio),
                          "-vn", "-af", f"silencedetect=noise={SILENCE_THRESHOLD_DB}dB:d={MAX_SILENCE_SEC}",
                          "-c:a", "pcm_s16le", str(decoded)])
        with wave.open(str(decoded), "rb") as source:
            rate, frames = source.getframerate(), source.getnframes()
            duration = frames / rate
            cuts = silence_cuts(detection.stderr, duration, rate)
            if not cuts:
                return {"version": POLICY_VERSION, "removed_sec": 0.0, "cuts": []}
            if sum(end - start for start, end in cuts) >= frames:
                raise ValueError("Silence compression would remove the whole audio")
            with wave.open(str(trimmed), "wb") as target:
                target.setparams(source.getparams())
                cursor = 0
                for start, end in [*cuts, (frames, frames)]:
                    source.setpos(cursor)
                    remaining = start - cursor
                    while remaining > 0:
                        count = min(remaining, 65536)
                        target.writeframesraw(source.readframes(count))
                        remaining -= count
                    cursor = end
        _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
              "-i", str(trimmed), "-c:a", "libmp3lame", "-b:a", "192k", str(encoded)])
        # Decode the result to verify it is playable and account for encoder
        # padding before committing new timeline duration metadata.
        verified = work / "verified.wav"
        _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
              "-i", str(encoded), "-c:a", "pcm_s16le", str(verified)])
        with wave.open(str(verified), "rb") as output:
            final_duration = output.getnframes() / output.getframerate()
        seconds = [(start / rate, end / rate) for start, end in cuts]
        expected_duration = duration - sum(end - start for start, end in seconds)
        if abs(final_duration - expected_duration) > 0.1:
            raise ValueError("Compressed audio duration does not match its cut map")
        segments = timeline.get("segments")
        if not isinstance(segments, list) or not segments:
            raise ValueError("Cannot compress audio without subtitle timing segments")
        _retime_segments(segments, seconds, final_duration,
                         measured=timeline.get("timing_source") == "provider_sentence_timestamps")
        processed_hash = _sha256(encoded)
        if timeline.get("provider_timestamps_audio_hash") == original_hash:
            _translate_provider(timeline.get("provider_timestamps"), seconds)
            timeline["provider_timestamps_audio_hash"] = processed_hash
        else:
            # Never relabel unverified provider words as measured against new audio.
            timeline.pop("provider_timestamps_audio_hash", None)
        report = {
            "version": POLICY_VERSION, "max_silence_sec": MAX_SILENCE_SEC,
            "threshold_db": SILENCE_THRESHOLD_DB,
            "original_duration_sec": round(duration, 6),
            "duration_sec": round(final_duration, 6),
            "removed_sec": round(duration - expected_duration, 6),
            "cuts": [{"start": start, "end": end} for start, end in seconds],
            "original_audio_sha256": original_hash, "audio_sha256": processed_hash,
        }
        timeline["silence_compression"] = report
        timeline["audio_content_duration_sec"] = round(final_duration, 3)
        timeline["duration_sec"] = round(final_duration + float(timeline.get("audio_start_sec") or 0), 3)
        timeline["duration_source"] = "local_audio_silence_compression"
        timeline.pop("probed_audio_duration_sec", None)
        metadata = json.loads(Path(paths["metadata"]).read_text(encoding="utf-8"))
        metadata["silence_compression"] = report
        metadata["duration"] = {**metadata.get("duration", {}), "sec": round(final_duration, 3),
                                "source": "local_audio_silence_compression"}
        # This directory is copied to project recovery before staged promotion.
        originals = audio.parent / "before_silence_compression"
        originals.mkdir(exist_ok=True)
        for key in ("audio", "timeline", "metadata", "srt"):
            shutil.copy2(paths[key], originals / Path(paths[key]).name)
        shutil.copy2(encoded, audio)
        timeline_path.write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8")
        Path(paths["metadata"]).write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        Path(paths["srt"]).write_text(_srt(segments), encoding="utf-8")
        return report
