"""Build one standards-compliant SRT file from a project's per-slide subtitles.

This module intentionally has no HTTP or database dependency.  Callers supply the
already-validated project run directory and the current Visual Contract slide
order; that keeps the export tied to the same timeline used by the final video.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from project_storage import UnsafeProjectPath, safe_identifier, slide_file


_TIMESTAMP_RE = re.compile(
    r"^(?P<hours>\d{1,}):(?P<minutes>[0-5]\d):(?P<seconds>[0-5]\d)[,.](?P<milliseconds>\d{1,3})$"
)
_TIMING_LINE_RE = re.compile(r"^(?P<start>.+?)\s+-->\s+(?P<end>.+?)(?:\s+.*)?$")


class SubtitleExportError(ValueError):
    """A user-facing reason why the project does not currently have an SRT export."""


@dataclass(frozen=True)
class SubtitleCue:
    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True)
class SubtitleExport:
    content: str
    slide_count: int
    cue_count: int


def _fail(slide_id: str, message: str) -> SubtitleExportError:
    return SubtitleExportError(f"页面 {slide_id} 的字幕无法导出：{message}")


def _parse_timestamp(value: str, *, slide_id: str) -> int:
    match = _TIMESTAMP_RE.fullmatch(value.strip())
    if not match:
        raise _fail(slide_id, "SRT 时间格式无效，请重新生成该页音频。")
    milliseconds = match.group("milliseconds").ljust(3, "0")
    return (
        int(match.group("hours")) * 3_600_000
        + int(match.group("minutes")) * 60_000
        + int(match.group("seconds")) * 1_000
        + int(milliseconds)
    )


def parse_srt(content: str, *, slide_id: str) -> list[SubtitleCue]:
    """Parse the limited, standard SRT subset emitted by the TTS pipeline."""
    normalized = str(content or "").lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    blocks = [block for block in re.split(r"\n[\t ]*\n", normalized.strip()) if block.strip()]
    if not blocks:
        raise _fail(slide_id, "没有可用字幕内容，请先完成音频合成。")

    cues: list[SubtitleCue] = []
    for block in blocks:
        lines = block.split("\n")
        if len(lines) < 3 or not lines[0].strip().isdigit():
            raise _fail(slide_id, "SRT 字幕块格式无效，请重新生成该页音频。")
        timing = _TIMING_LINE_RE.fullmatch(lines[1].strip())
        if not timing:
            raise _fail(slide_id, "SRT 时间范围无效，请重新生成该页音频。")
        start_ms = _parse_timestamp(timing.group("start"), slide_id=slide_id)
        end_ms = _parse_timestamp(timing.group("end"), slide_id=slide_id)
        text = "\n".join(line.rstrip() for line in lines[2:]).strip()
        if end_ms <= start_ms or not text:
            raise _fail(slide_id, "SRT 字幕时间或文字为空，请重新生成该页音频。")
        cues.append(SubtitleCue(start_ms=start_ms, end_ms=end_ms, text=text))
    return cues


def _format_timestamp(milliseconds: int) -> str:
    safe_value = max(0, int(milliseconds))
    hours, remainder = divmod(safe_value, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def _positive_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _read_timeline(path: Path, *, slide_id: str) -> dict[str, Any]:
    if not path.is_file():
        raise _fail(slide_id, "缺少音频时间线，请先完成音频合成。")
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _fail(slide_id, "音频时间线无法读取，请重新生成该页音频。") from exc
    if not isinstance(payload, dict):
        raise _fail(slide_id, "音频时间线格式无效，请重新生成该页音频。")
    return payload


def _timeline_total_duration(
    timeline: dict[str, Any],
    cues: list[SubtitleCue],
    *,
    audio_start_sec: float,
    slide_id: str,
) -> float:
    candidates = [audio_start_sec + max(cue.end_ms for cue in cues) / 1_000]
    for key in ("duration_sec",):
        value = _positive_number(timeline.get(key))
        if value is not None:
            candidates.append(value)
    content_duration = _positive_number(timeline.get("audio_content_duration_sec"))
    if content_duration is not None:
        candidates.append(audio_start_sec + content_duration)
    segments = timeline.get("segments")
    if isinstance(segments, list):
        ends = [
            value
            for segment in segments
            if isinstance(segment, dict)
            for value in [_positive_number(segment.get("end"))]
            if value is not None
        ]
        if ends:
            candidates.append(audio_start_sec + max(ends))
    duration = max(candidates)
    if not math.isfinite(duration) or duration <= 0:
        raise _fail(slide_id, "音频时间线没有有效时长，请重新生成该页音频。")
    return duration


def build_subtitle_export(run_dir: str | Path, slide_ids: list[str]) -> SubtitleExport:
    """Merge page SRT files in Visual Contract order into final-video time."""
    root = Path(run_dir).expanduser().resolve()
    ordered_ids: list[str] = []
    seen: set[str] = set()
    for value in slide_ids:
        try:
            slide_id = safe_identifier(str(value or "").strip(), label="slide_id")
        except UnsafeProjectPath as exc:
            raise SubtitleExportError("分镜顺序包含无效页面，无法导出字幕。") from exc
        if slide_id in seen:
            raise SubtitleExportError("分镜顺序包含重复页面，无法导出字幕。")
        seen.add(slide_id)
        ordered_ids.append(slide_id)
    if not ordered_ids:
        raise SubtitleExportError("尚未生成分镜，无法导出字幕。")

    rendered_cues: list[SubtitleCue] = []
    project_cursor_sec = 0.0
    for slide_id in ordered_ids:
        try:
            srt_path = slide_file(root, slide_id, "subtitles.srt")
            timeline_path = slide_file(root, slide_id, "audio_timeline.json")
        except UnsafeProjectPath as exc:
            raise SubtitleExportError("字幕文件路径安全校验失败。") from exc
        if not srt_path.is_file():
            raise _fail(slide_id, "缺少字幕文件，请先完成音频合成。")
        try:
            cues = parse_srt(srt_path.read_text(encoding="utf-8-sig"), slide_id=slide_id)
        except OSError as exc:
            raise _fail(slide_id, "字幕文件无法读取，请重新生成该页音频。") from exc
        timeline = _read_timeline(timeline_path, slide_id=slide_id)
        # Older/generic TTS timelines omit this optional field.  Remotion also
        # treats an omitted value as zero, so the download must use the same
        # compatibility behavior rather than rejecting otherwise valid audio.
        raw_audio_start = timeline.get("audio_start_sec", 0)
        audio_start_sec = _positive_number(raw_audio_start)
        if audio_start_sec is None:
            raise _fail(slide_id, "音频起始时间无效，请重新生成该页音频。")
        offset_ms = int(round((project_cursor_sec + audio_start_sec) * 1_000))
        rendered_cues.extend(
            SubtitleCue(
                start_ms=cue.start_ms + offset_ms,
                end_ms=cue.end_ms + offset_ms,
                text=cue.text,
            )
            for cue in cues
        )
        project_cursor_sec += _timeline_total_duration(
            timeline,
            cues,
            audio_start_sec=audio_start_sec,
            slide_id=slide_id,
        )

    blocks = [
        "\n".join(
            (
                str(index),
                f"{_format_timestamp(cue.start_ms)} --> {_format_timestamp(cue.end_ms)}",
                cue.text,
            )
        )
        for index, cue in enumerate(rendered_cues, start=1)
    ]
    return SubtitleExport(
        content="\n\n".join(blocks) + "\n",
        slide_count=len(ordered_ids),
        cue_count=len(rendered_cues),
    )


def subtitle_export_readiness(run_dir: str | Path, slide_ids: list[str]) -> dict[str, Any]:
    """Return a UI-safe readiness payload without creating a persisted artifact."""
    try:
        result = build_subtitle_export(run_dir, slide_ids)
    except SubtitleExportError as exc:
        return {"ready": False, "message": str(exc)}
    return {
        "ready": True,
        "message": f"{result.slide_count} 页字幕已按最终视频时间轴合并，可下载 SRT。",
        "slide_count": result.slide_count,
        "cue_count": result.cue_count,
    }
