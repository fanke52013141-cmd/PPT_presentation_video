"""Narration text persistence and audio timeline alignment."""

from __future__ import annotations

import copy
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import re
from typing import Any, Callable, Dict, List, Optional

from fastapi import HTTPException
from project_storage import UnsafeProjectPath, slide_dir as storage_slide_dir


logger = logging.getLogger("PPTStudio.NarrationAudio")

MINIMAX_PAUSE_RE = re.compile(r"<#(\d+(?:\.\d{1,2})?)#>")
MINIMAX_EXPRESSION_RE = re.compile(r"\([A-Za-z-]+\)")
MINIMAX_ALLOWED_EXPRESSION_TAGS = {
    "(applause)",
    "(breath)",
    "(burps)",
    "(chuckle)",
    "(clear-throat)",
    "(coughs)",
    "(crying)",
    "(emm)",
    "(exhale)",
    "(gasps)",
    "(groans)",
    "(hissing)",
    "(humming)",
    "(inhale)",
    "(laughs)",
    "(lip-smacking)",
    "(pant)",
    "(sneezes)",
    "(sniffs)",
    "(snorts)",
    "(sighs)",
    "(whistles)",
}
MINIMAX_ALLOWED_EXPRESSION_RE = re.compile(
    "|".join(
        re.escape(tag)
        for tag in sorted(
            MINIMAX_ALLOWED_EXPRESSION_TAGS,
            key=len,
            reverse=True,
        )
    )
)
TTS_MARKUP_RE = re.compile(
    rf"(?:{MINIMAX_PAUSE_RE.pattern}|"
    rf"{MINIMAX_ALLOWED_EXPRESSION_RE.pattern})"
)
SUBTITLE_MAX_CHARS = 26
SUBTITLE_HARD_SPLIT_MARKS = "。！？；.!?;"
SUBTITLE_SOFT_SPLIT_MARKS = "，：、,:"
SUBTITLE_EDGE_PUNCTUATION = "，。！？；：、,.!?;: \t\r\n"
SUBTITLE_SPEECH_RE = re.compile(r"[\w\u4e00-\u9fff]")


@dataclass(frozen=True)
class NarrationAudioDependencies:
    dedupe_narration_beats: Callable[[Any], List[Dict[str, Any]]]
    probe_media_duration_sec: Callable[..., Optional[float]]
    read_contract_slide_ids: Callable[[str], List[str]]
    read_json_file: Callable[[str, Any], Any]
    write_json_atomic: Callable[[str, Any], Any]
    repo_root: Path


_dependencies: NarrationAudioDependencies | None = None


def configure_narration_audio_dependencies(
    dependencies: NarrationAudioDependencies,
) -> None:
    global _dependencies
    _dependencies = dependencies


def _deps() -> NarrationAudioDependencies:
    if _dependencies is None:
        raise RuntimeError(
            "Narration audio dependencies have not been configured"
        )
    return _dependencies


def clean_tts_text(text: str) -> str:
    value = TTS_MARKUP_RE.sub("", str(text or ""))
    return re.sub(r"\s+", " ", value).strip()


def beat_tts_text(beat: Dict[str, Any]) -> str:
    return str(
        beat.get("tts_text")
        or beat.get("spoken_text")
        or beat.get("source_text")
        or ""
    ).strip()


def normalize_minimax_tts_markup(
    text: str,
    fallback: str = "",
) -> str:
    value = re.sub(
        r"\s+",
        " ",
        str(text or fallback or ""),
    ).strip()

    def normalize_pause(match: re.Match[str]) -> str:
        seconds = max(
            0.01,
            min(99.99, float(match.group(1))),
        )
        formatted = f"{seconds:.2f}".rstrip("0").rstrip(".")
        return f"<#{formatted}#>"

    value = MINIMAX_PAUSE_RE.sub(normalize_pause, value)
    value = re.sub(
        r"<#[^>]*#>",
        lambda match: (
            match.group(0)
            if MINIMAX_PAUSE_RE.fullmatch(match.group(0))
            else " "
        ),
        value,
    )

    def keep_expression(match: re.Match[str]) -> str:
        return match.group(0)

    value = MINIMAX_EXPRESSION_RE.sub(keep_expression, value)
    value = re.sub(
        r"(<#\d+(?:\.\d{1,2})?#>\s*){2,}",
        lambda match: (
            MINIMAX_PAUSE_RE.search(match.group(0)).group(0)
            + " "
            if MINIMAX_PAUSE_RE.search(match.group(0))
            else " "
        ),
        value,
    )
    value = re.sub(
        rf"^(?:\s*(?:{TTS_MARKUP_RE.pattern})\s*)+",
        "",
        value,
    ).strip()
    value = re.sub(
        rf"(?:\s*(?:{TTS_MARKUP_RE.pattern})\s*)+$",
        "",
        value,
    ).strip()
    return re.sub(r"\s+", " ", value).strip()


def ensure_minimax_delivery_markup(text: str) -> str:
    value = normalize_minimax_tts_markup(text)
    if (
        not value
        or MINIMAX_PAUSE_RE.search(value)
        or len(clean_tts_text(value)) < 12
    ):
        return value

    punctuation_matches = [
        match
        for match in re.finditer(r"[，。！？；：、,.!?;:]", value)
        if match.end() < len(value)
    ]
    if punctuation_matches:
        midpoint = len(value) / 2
        match = min(
            punctuation_matches,
            key=lambda item: abs(item.end() - midpoint),
        )
        insert_at = match.end()
    else:
        insert_at = max(
            1,
            min(len(value) - 1, len(value) // 2),
        )

    pause = "<#0.35#>"
    annotated = (
        f"{value[:insert_at].rstrip()}"
        f"{pause}"
        f"{value[insert_at:].lstrip()}"
    )
    return normalize_minimax_tts_markup(annotated, value)


def split_subtitle_text(
    text: str,
    max_chars: int = SUBTITLE_MAX_CHARS,
) -> List[str]:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if not value:
        return []

    chunks: List[str] = []
    remaining = value
    while remaining:
        if len(remaining) <= max_chars:
            chunk = remaining
            remaining = ""
        else:
            window = remaining[: max_chars + 1]
            hard_cut = max(
                (
                    window.rfind(mark)
                    for mark in SUBTITLE_HARD_SPLIT_MARKS
                ),
                default=-1,
            )
            soft_cut = max(
                (
                    window.rfind(mark)
                    for mark in SUBTITLE_SOFT_SPLIT_MARKS
                ),
                default=-1,
            )
            cut_at = (
                hard_cut
                if hard_cut >= max(8, max_chars // 2)
                else soft_cut
            )
            if (
                cut_at < max(8, max_chars // 2)
                or cut_at >= max_chars
            ):
                cut_at = max_chars - 1
            chunk = remaining[: cut_at + 1]
            remaining = remaining[cut_at + 1 :].strip()
        chunk = chunk.strip(SUBTITLE_EDGE_PUNCTUATION)
        if chunk:
            chunks.append(chunk)
    return chunks


def subtitle_text_weight(text: str) -> int:
    compact = re.sub(r"\s+", "", str(text or ""))
    return max(1, len(compact))


def subtitle_chunks_for_timing(text: str) -> List[str]:
    chunks: List[str] = []
    for chunk in split_subtitle_text(clean_tts_text(text)):
        chunk = chunk.strip()
        if not chunk:
            continue
        if not SUBTITLE_SPEECH_RE.search(chunk):
            if chunks:
                chunks[-1] = f"{chunks[-1]}{chunk}".strip()
            continue
        chunks.append(chunk)
    return chunks


def tts_text_parts_with_pauses(
    text: str,
) -> List[Dict[str, Any]]:
    value = str(text or "")
    parts: List[Dict[str, Any]] = []
    cursor = 0
    for match in MINIMAX_PAUSE_RE.finditer(value):
        before = clean_tts_text(value[cursor : match.start()])
        if before:
            parts.append({"type": "text", "text": before})
        seconds = max(0.0, float(match.group(1)))
        if seconds > 0:
            parts.append(
                {"type": "pause", "duration": seconds}
            )
        cursor = match.end()
    after = clean_tts_text(value[cursor:])
    if after:
        parts.append({"type": "text", "text": after})
    return parts


def prepare_narration_payload(
    project: Any,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    dependencies = _deps()
    payload = dict(payload or {})
    slides = (
        payload.get("slides")
        if isinstance(payload.get("slides"), list)
        else []
    )
    current_slide_ids = dependencies.read_contract_slide_ids(
        project.run_dir
    )
    if current_slide_ids:
        by_id = {
            str(slide.get("slide_id") or "").strip(): slide
            for slide in slides
            if isinstance(slide, dict)
            and str(slide.get("slide_id") or "").strip()
        }
        slides = [
            by_id[slide_id]
            for slide_id in current_slide_ids
            if slide_id in by_id
        ]

    for slide_data in slides:
        if not isinstance(slide_data, dict):
            continue
        slide_beats = slide_data.get("beats", [])
        if not isinstance(slide_beats, list):
            slide_beats = []
            slide_data["beats"] = slide_beats
        for index, beat in enumerate(slide_beats, start=1):
            if not isinstance(beat, dict):
                continue
            beat.setdefault(
                "id",
                (
                    f"{slide_data.get('slide_id', 'slide')}"
                    f"_beat_{index:03d}"
                ),
            )
            source = str(
                beat.get("source_text")
                or beat.get("spoken_text")
                or ""
            ).strip()
            spoken = str(
                beat.get("spoken_text") or source
            ).strip()
            beat["source_text"] = source or spoken
            beat["spoken_text"] = spoken or source
            beat["tts_text"] = normalize_minimax_tts_markup(
                beat.get("tts_text"),
                beat["spoken_text"],
            )
        slide_data["beats"] = (
            dependencies.dedupe_narration_beats(slide_beats)
        )
    payload["slides"] = slides
    return payload


def _write_text_if_changed(path: str, content: str) -> bool:
    """幂等写入文本：内容一致时保留原文件与 mtime。

    Step 7 以 tts_text.txt 的 mtime 判定音频是否过期（晚于音频即删除
    重合成）。演讲稿内容没有变化时必须跳过重写，否则一次恢复重试会把
    全部已生成音频判为过期并从头重造。
    """
    try:
        with open(path, "r", encoding="utf-8") as file:
            if file.read() == content:
                return False
    except OSError:
        pass
    with open(path, "w", encoding="utf-8") as file:
        file.write(content)
    return True


def _write_json_if_changed(
    write_json_atomic: Callable[..., Any],
    path: str,
    payload: Dict[str, Any],
) -> bool:
    """幂等写入 JSON：语义内容一致时跳过原子重写。"""
    try:
        with open(path, "r", encoding="utf-8") as file:
            if json.load(file) == payload:
                return False
    except (OSError, json.JSONDecodeError):
        pass
    write_json_atomic(path, payload)
    return True


def persist_narration_beats(
    project: Any,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    dependencies = _deps()
    payload = prepare_narration_payload(project, payload)
    planning_dir = os.path.join(project.run_dir, "planning")
    beats_path = os.path.join(
        planning_dir,
        "narration_beats.json",
    )
    os.makedirs(os.path.dirname(beats_path), exist_ok=True)
    # planning/narration_beats.json 保持无条件写入：其 mtime 是
    # has_fresh_narration 判定演讲稿新鲜的依据，重写可让下一轮恢复直接
    # 复用演讲稿，避免重复执行 AI 标注。
    dependencies.write_json_atomic(beats_path, payload)

    narration_lines = []
    tts_text_lines = []

    for slide_data in payload.get("slides", []):
        if not isinstance(slide_data, dict):
            continue
        slide_id = str(
            slide_data.get("slide_id") or ""
        ).strip()
        if not slide_id:
            continue
        # 使用带 safe_identifier 校验的 slide_dir() 构造路径，防止路径穿越
        try:
            slide_dir = storage_slide_dir(
                project.run_dir,
                slide_id,
            )
        except UnsafeProjectPath as exc:
            raise HTTPException(
                status_code=400,
                detail=f"slide_id 含非法字符，已拒绝写入：{slide_id!r}",
            ) from exc
        os.makedirs(slide_dir, exist_ok=True)
        slide_beats = (
            slide_data.get("beats", [])
            if isinstance(slide_data.get("beats"), list)
            else []
        )
        slide_narration = "\n".join(
            clean_tts_text(beat_tts_text(beat))
            for beat in slide_beats
        )
        slide_tts_text = "\n".join(
            beat_tts_text(beat)
            for beat in slide_beats
        )

        _write_text_if_changed(
            os.path.join(slide_dir, "narration.txt"),
            slide_narration + "\n",
        )
        _write_text_if_changed(
            os.path.join(slide_dir, "tts_text.txt"),
            slide_tts_text + "\n",
        )
        _write_json_if_changed(
            dependencies.write_json_atomic,
            os.path.join(slide_dir, "narration_beats.json"),
            {"slide_id": slide_id, "beats": slide_beats},
        )

        narration_lines.append(f"=== {slide_id} ===")
        tts_text_lines.append(f"=== {slide_id} ===")
        for beat in slide_beats:
            if not isinstance(beat, dict):
                continue
            group_id = (
                beat.get("group_id")
                or beat.get("id")
                or "sentence"
            )
            text = clean_tts_text(beat_tts_text(beat))
            narration_lines.append(f"[{group_id}] {text}")
            tts_text_lines.append(beat_tts_text(beat))

    _write_text_if_changed(
        os.path.join(planning_dir, "narration.txt"),
        "\n".join(narration_lines) + "\n",
    )
    _write_text_if_changed(
        os.path.join(planning_dir, "tts_text.txt"),
        "\n".join(tts_text_lines) + "\n",
    )
    return payload


def sync_narration_beats_to_contract(
    project: Any,
    slide_ids: Optional[List[str]] = None,
) -> bool:
    dependencies = _deps()
    explicit_slide_ids = slide_ids is not None
    current_slide_ids = (
        slide_ids
        if explicit_slide_ids
        else dependencies.read_contract_slide_ids(
            project.run_dir
        )
    )
    if not current_slide_ids and not explicit_slide_ids:
        return False

    beats_path = os.path.join(
        project.run_dir,
        "planning",
        "narration_beats.json",
    )
    if not os.path.exists(beats_path):
        return False

    try:
        with open(beats_path, "r", encoding="utf-8") as file:
            payload = json.load(file)
    except Exception as exc:
        logger.warning(
            "Failed to read narration beats for slide sync: %s",
            exc,
        )
        return False

    slides = payload.get("slides", [])
    if not isinstance(slides, list):
        return False

    by_id = {
        str(slide.get("slide_id") or "").strip(): slide
        for slide in slides
        if isinstance(slide, dict)
        and str(slide.get("slide_id") or "").strip()
    }
    contract = dependencies.read_json_file(
        os.path.join(
            project.run_dir,
            "planning",
            "visual_contract.json",
        ),
        {},
    )
    contract_by_id = {
        str(slide.get("slide_id") or "").strip(): slide
        for slide in contract.get("slides", [])
        if isinstance(slide, dict)
        and str(slide.get("slide_id") or "").strip()
    }
    synced_slides = []
    for slide_id in current_slide_ids:
        existing = by_id.get(slide_id)
        if existing is not None:
            synced_slides.append(existing)
            continue
        contract_slide = contract_by_id.get(slide_id, {})
        synced_slides.append(
            {
                "slide_id": slide_id,
                "beats": copy.deepcopy(
                    contract_slide.get("narration_beats", [])
                ),
            }
        )
    normalized_slides = []
    for slide in synced_slides:
        normalized = dict(slide)
        normalized["beats"] = (
            dependencies.dedupe_narration_beats(
                slide.get("beats")
            )
        )
        normalized_slides.append(normalized)
    if normalized_slides == slides:
        return False

    payload["slides"] = normalized_slides
    dependencies.write_json_atomic(beats_path, payload)
    logger.info(
        "Synced narration beats to visual contract: "
        "kept %s of %s slides",
        len(synced_slides),
        len(slides),
    )
    return True


def sync_narration_sources_from_contract(
    project: Any,
    previous_contract: Dict[str, Any],
    current_contract: Dict[str, Any],
) -> bool:
    """Propagate source edits without replacing unchanged TTS markup."""
    dependencies = _deps()
    beats_path = os.path.join(
        project.run_dir,
        "planning",
        "narration_beats.json",
    )
    if not os.path.exists(beats_path):
        return False

    existing_payload = dependencies.read_json_file(beats_path, {})
    existing_slides = (
        existing_payload.get("slides")
        if isinstance(existing_payload, dict)
        else None
    )
    if not isinstance(existing_slides, list):
        return False

    def slide_map(
        contract: Dict[str, Any],
    ) -> Dict[str, Dict[str, Any]]:
        return {
            str(slide.get("slide_id") or "").strip(): slide
            for slide in contract.get("slides", [])
            if isinstance(slide, dict)
            and str(slide.get("slide_id") or "").strip()
        }

    def beat_map(
        slide: Dict[str, Any],
        field: str,
    ) -> Dict[str, Dict[str, Any]]:
        beats = slide.get(field)
        if not isinstance(beats, list):
            return {}
        return {
            str(beat.get("id") or "").strip(): beat
            for beat in beats
            if isinstance(beat, dict)
            and str(beat.get("id") or "").strip()
        }

    previous_slides = slide_map(
        previous_contract
        if isinstance(previous_contract, dict)
        else {}
    )
    current_slides = slide_map(
        current_contract
        if isinstance(current_contract, dict)
        else {}
    )
    existing_by_slide = {
        str(slide.get("slide_id") or "").strip(): slide
        for slide in existing_slides
        if isinstance(slide, dict)
        and str(slide.get("slide_id") or "").strip()
    }
    structural_fields = (
        "id",
        "group_id",
        "content_unit_id",
        "visible_anchor",
        "spoken_intent",
    )
    synced_slides: List[Dict[str, Any]] = []

    for slide_id, current_slide in current_slides.items():
        previous_beats = beat_map(
            previous_slides.get(slide_id, {}),
            "narration_beats",
        )
        existing_slide = existing_by_slide.get(slide_id, {})
        existing_beats = beat_map(existing_slide, "beats")
        merged_beats: List[Dict[str, Any]] = []
        current_beats = dependencies.dedupe_narration_beats(
            current_slide.get("narration_beats")
        )
        for current_beat in current_beats:
            beat_id = str(
                current_beat.get("id") or ""
            ).strip()
            if not beat_id:
                continue
            current_text = str(
                current_beat.get("spoken_text") or ""
            ).strip()
            previous_text = str(
                previous_beats.get(beat_id, {}).get(
                    "spoken_text"
                )
                or ""
            ).strip()
            existing_beat = existing_beats.get(beat_id)
            source_changed = (
                beat_id not in previous_beats
                or current_text != previous_text
            )

            if (
                existing_beat is not None
                and not source_changed
            ):
                merged = copy.deepcopy(existing_beat)
                for field in structural_fields:
                    if field in current_beat:
                        merged[field] = copy.deepcopy(
                            current_beat[field]
                        )
            else:
                merged = copy.deepcopy(current_beat)
                merged["source_text"] = current_text
                merged["spoken_text"] = current_text
                merged["tts_text"] = current_text
            merged_beats.append(merged)
        synced_slides.append(
            {
                "slide_id": slide_id,
                "beats": merged_beats,
            }
        )

    candidate = dict(existing_payload)
    candidate["slides"] = synced_slides
    if candidate == existing_payload:
        return False
    prepared = prepare_narration_payload(project, candidate)
    if prepared == existing_payload:
        return False
    persist_narration_beats(project, candidate)
    logger.info(
        "Synced Step 2 narration sources into Step 5 "
        "for %s slides",
        len(synced_slides),
    )
    return True


def rewrite_audio_timeline_by_beats(
    timeline_path: str,
    slide_id: str,
    beats: List[Dict[str, Any]],
) -> None:
    dependencies = _deps()
    if not os.path.exists(timeline_path):
        return
    with open(timeline_path, "r", encoding="utf-8") as file:
        timeline = json.load(file)
    previous_duration = float(
        timeline.get("audio_content_duration_sec")
        or timeline.get("duration_sec")
        or 0
    )
    voice_path = os.path.join(
        os.path.dirname(timeline_path),
        "voice.mp3",
    )
    probed_duration = dependencies.probe_media_duration_sec(
        voice_path,
        repo_root=dependencies.repo_root,
    )
    duration = float(probed_duration or previous_duration)
    if duration <= 0:
        return
    clean_beats: List[Dict[str, Any]] = []
    for index, beat in enumerate(beats):
        raw_text = beat_tts_text(beat)
        if not clean_tts_text(raw_text):
            continue
        parts = tts_text_parts_with_pauses(raw_text)
        if not any(
            part.get("type") == "text"
            for part in parts
        ):
            continue
        clean_beats.append(
            {
                "id": str(
                    beat.get("id")
                    or f"{slide_id}_beat_{index + 1:03d}"
                ),
                "parts": parts,
            }
        )
    if not clean_beats:
        return

    provider_segments = (
        timeline.get("segments")
        if timeline.get("timing_source")
        == "provider_sentence_timestamps"
        else None
    )
    if isinstance(provider_segments, list) and provider_segments:
        beat_signatures = [
            re.sub(
                r"[^0-9A-Za-z\u4e00-\u9fff]+",
                "",
                clean_tts_text(
                    "".join(
                        str(part.get("text") or "")
                        for part in beat.get("parts", [])
                        if part.get("type") == "text"
                    )
                ),
            )
            for beat in clean_beats
        ]
        beat_part_counts: Dict[str, int] = {}
        active_beat_index = 0
        for segment in provider_segments:
            if not isinstance(segment, dict):
                continue
            segment_signature = re.sub(
                r"[^0-9A-Za-z\u4e00-\u9fff]+",
                "",
                clean_tts_text(
                    str(segment.get("text") or "")
                ),
            )
            if segment_signature:
                for beat_index in range(
                    active_beat_index,
                    len(beat_signatures),
                ):
                    if (
                        segment_signature
                        in beat_signatures[beat_index]
                    ):
                        active_beat_index = beat_index
                        break
            beat_id = clean_beats[active_beat_index]["id"]
            part_number = beat_part_counts.get(beat_id, 0) + 1
            beat_part_counts[beat_id] = part_number
            segment["beat_id"] = beat_id
            segment["id"] = (
                beat_id
                if part_number == 1
                else f"{beat_id}__part_{part_number:02d}"
            )
            segment["timing_source"] = (
                "provider_sentence_timestamps"
            )
        timeline["segments"] = provider_segments
        timeline["audio_content_duration_sec"] = round(
            duration,
            3,
        )
        timeline["duration_sec"] = round(
            duration
            + float(timeline.get("audio_start_sec", 0.0) or 0.0),
            3,
        )
        timeline["duration_source"] = (
            "local_audio_ffprobe"
            if probed_duration
            else timeline.get("duration_source")
        )
        if probed_duration:
            timeline["probed_audio_duration_sec"] = round(
                probed_duration,
                3,
            )
        with open(
            timeline_path,
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                timeline,
                file,
                ensure_ascii=False,
                indent=2,
            )
        return

    total_pause = sum(
        float(part.get("duration", 0.0) or 0.0)
        for item in clean_beats
        for part in item["parts"]
        if part.get("type") == "pause"
    )
    pause_budget = min(total_pause, duration * 0.45)
    pause_scale = (
        pause_budget / total_pause
        if total_pause > 0
        else 0.0
    )
    speech_duration = max(0.001, duration - pause_budget)
    total_weight = 0
    chunked_parts: List[Dict[str, Any]] = []
    for item in clean_beats:
        beat_parts: List[Dict[str, Any]] = []
        for part in item["parts"]:
            if part.get("type") == "pause":
                beat_parts.append(part)
                continue
            chunks = subtitle_chunks_for_timing(
                str(part.get("text") or "")
            )
            chunk_weights = [
                subtitle_text_weight(chunk)
                for chunk in chunks
            ]
            total_weight += sum(chunk_weights)
            beat_parts.append(
                {
                    "type": "text",
                    "chunks": chunks,
                    "weights": chunk_weights,
                }
            )
        chunked_parts.append(
            {
                "id": item["id"],
                "parts": beat_parts,
            }
        )
    if total_weight <= 0:
        return

    cursor = 0.0
    segments: List[Dict[str, Any]] = []
    for item in chunked_parts:
        chunk_index = 0
        for part in item["parts"]:
            if part.get("type") == "pause":
                pause_duration = (
                    float(part.get("duration", 0.0) or 0.0)
                    * pause_scale
                )
                if pause_duration > 0:
                    if segments:
                        segments[-1]["_end"] = (
                            segments[-1]["_end"]
                            + pause_duration
                        )
                    cursor += pause_duration
                continue
            chunks = part.get("chunks", [])
            weights = part.get("weights", [])
            for chunk, weight in zip(chunks, weights):
                chunk_index += 1
                chunk_start = cursor
                chunk_end = (
                    cursor
                    + speech_duration
                    * float(weight)
                    / float(total_weight)
                )
                segment_id = (
                    item["id"]
                    if chunk_index == 1
                    else (
                        f"{item['id']}"
                        f"__part_{chunk_index:02d}"
                    )
                )
                segments.append(
                    {
                        "id": segment_id,
                        "beat_id": item["id"],
                        "_start": chunk_start,
                        "_end": chunk_end,
                        "text": chunk,
                        "timing_source": (
                            "beat_pause_aware_estimated_split"
                        ),
                        "max_cjk_chars": SUBTITLE_MAX_CHARS,
                        "max_lines": 1,
                    }
                )
                cursor = chunk_end
    if not segments:
        return
    if cursor < duration:
        segments[-1]["_end"] = (
            segments[-1]["_end"] + (duration - cursor)
        )
    normalized_segments: List[Dict[str, Any]] = []
    previous_end = 0.0
    for segment in segments:
        start = max(
            previous_end,
            min(duration, float(segment.pop("_start"))),
        )
        end = max(
            start,
            min(duration, float(segment.pop("_end"))),
        )
        if end <= start and start < duration:
            end = min(duration, start + 0.05)
        if end <= start:
            continue
        segment["start"] = round(start, 3)
        segment["end"] = round(end, 3)
        normalized_segments.append(segment)
        previous_end = end
    if not normalized_segments:
        return
    timeline["segments"] = normalized_segments
    timeline["timing_source"] = (
        "beat_pause_aware_estimated_split"
    )
    timeline["explicit_pause_sec"] = round(pause_budget, 3)
    timeline["subtitle_display"] = {
        "max_lines": 1,
        "max_cjk_chars": SUBTITLE_MAX_CHARS,
    }
    timeline["audio_content_duration_sec"] = round(duration, 3)
    timeline["duration_sec"] = round(
        duration
        + float(timeline.get("audio_start_sec", 0.0) or 0.0),
        3,
    )
    if probed_duration:
        timeline["duration_source"] = "local_audio_ffprobe"
        timeline["probed_audio_duration_sec"] = round(
            probed_duration,
            3,
        )
        if (
            previous_duration > 0
            and abs(previous_duration - probed_duration) > 0.05
        ):
            timeline[
                "previous_timeline_content_duration_sec"
            ] = round(previous_duration, 3)
    with open(timeline_path, "w", encoding="utf-8") as file:
        json.dump(
            timeline,
            file,
            ensure_ascii=False,
            indent=2,
        )
