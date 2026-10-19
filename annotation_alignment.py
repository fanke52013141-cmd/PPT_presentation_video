# -*- coding: utf-8 -*-
"""Audio alignment contracts and original-narration range resolution.

Sentence adapters remain available for diagnostics. Production anchor triggers
require measured provider/forced-alignment tokens; unavailable words require
explicit audio calibration. The isolated CPU worker owns model execution.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

__all__ = [
    "WORD_ALIGNMENT_FILE",
    "ALIGNMENT_SCHEMA_VERSION",
    "SENTENCE_ENGINE_VERSION",
    "AlignmentError",
    "build_sentence_alignment",
    "load_word_alignment",
    "word_alignment_cache_key",
]

WORD_ALIGNMENT_FILE = "word_alignment.json"
ALIGNMENT_SCHEMA_VERSION = 1
SENTENCE_ENGINE_VERSION = "sentence_timeline_v1"


class AlignmentError(ValueError):
    # 继承 ValueError:编译链路(如 annotation_build.compile_slide)以
    # ``except ValueError`` 兜底时间轴结构错误,独立 Exception 会穿透成裸 500。
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code  # missing_audio | bad_timeline | invalid_time
        self.message = message


@dataclass(frozen=True)
class BeatSpan:
    beat_id: str
    start_sec: float
    end_sec: float
    timing_source: str


def _finite_nonnegative(value: Any) -> Optional[float]:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    number = float(value)
    if number < 0 or number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def read_beat_spans(timeline_payload: Dict[str, Any]) -> Tuple[List[BeatSpan], Optional[float]]:
    """从既有 TTS 音频时间轴提取句级 beat 区间(纯函数)。

    区间必须有限、非负、start < end 且不超内容时长;非法段跳过。
    """
    if not isinstance(timeline_payload, dict):
        raise AlignmentError("bad_timeline", "audio_timeline.json 不是对象")
    duration = _finite_nonnegative(
        timeline_payload.get("audio_content_duration_sec")
        if timeline_payload.get("audio_content_duration_sec") is not None
        else timeline_payload.get("duration_sec")
    )
    segments = timeline_payload.get("segments")
    if not isinstance(segments, list):
        raise AlignmentError("bad_timeline", "audio_timeline.json 缺少 segments 数组")
    spans: List[BeatSpan] = []
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            continue
        beat_id = str(segment.get("beat_id") or segment.get("id") or "").strip()
        start = _finite_nonnegative(segment.get("start"))
        end = _finite_nonnegative(segment.get("end"))
        if not beat_id or start is None or end is None or end <= start:
            continue
        if duration is not None and start >= duration:
            continue
        end = min(end, duration) if duration is not None else end
        if end <= start:
            continue
        spans.append(
            BeatSpan(
                beat_id=beat_id,
                start_sec=start,
                end_sec=end,
                timing_source=str(segment.get("timing_source") or "unknown"),
            )
        )
    if not spans:
        raise AlignmentError("bad_timeline", "audio_timeline.json 没有可用的句级时间区间")
    return spans, duration


def build_sentence_alignment(
    *,
    slide_id: str,
    audio_bytes_hash: Optional[str],
    timeline_payload: Dict[str, Any],
    beats: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """句级对齐产物(缓存键命中前先算,产物落盘由调用方负责)。

    beats 为页面讲稿语块(beat_id + spoken_text);对齐范围覆盖整句,
    锚点时间 = 语块起点。精度如实标记 sentence_fallback。
    """
    spans, duration = read_beat_spans(timeline_payload)
    span_map: Dict[str, List[BeatSpan]] = {}
    for span in spans:
        span_map.setdefault(span.beat_id, []).append(span)

    beat_entries: List[Dict[str, Any]] = []
    missing: List[str] = []
    for beat in beats:
        beat_id = str(beat.get("beat_id"))
        spoken = str(beat.get("spoken_text") or "")
        spans_for_beat = span_map.get(beat_id) or []
        if spans_for_beat:
            start = min(span.start_sec for span in spans_for_beat)
            end = max(span.end_sec for span in spans_for_beat)
            beat_entries.append(
                {
                    "beat_id": beat_id,
                    "range": [start, end],
                    "precision": "sentence",
                    "timing_source": spans_for_beat[0].timing_source,
                    "codepoint_count": len(spoken),
                }
            )
        else:
            missing.append(beat_id)
            beat_entries.append(
                {
                    "beat_id": beat_id,
                    "range": None,
                    "precision": "unavailable",
                    "timing_source": None,
                    "codepoint_count": len(spoken),
                }
            )
    return {
        "schema_version": ALIGNMENT_SCHEMA_VERSION,
        "engine": {
            "engine_version": SENTENCE_ENGINE_VERSION,
            "adapter": "sentence_timeline",
            "granularity": "sentence",
        },
        "slide_id": slide_id,
        "audio_hash": audio_bytes_hash,
        "audio_duration_sec": duration,
        "beats": beat_entries,
        "unavailable_beats": missing,
        "precision": "sentence_fallback",
    }


def word_alignment_cache_key(
    audio_bytes: Optional[bytes],
    *,
    engine_version: str,
    spoken_text_hash: Optional[str],
) -> str:
    digest = hashlib.sha256()
    digest.update(b"annotation-alignment-v1\n")
    digest.update(engine_version.encode("utf-8") + b"\n")
    digest.update((spoken_text_hash or "none").encode("utf-8") + b"\n")
    digest.update(hashlib.sha256(audio_bytes).digest() if audio_bytes else b"no-audio")
    return digest.hexdigest()


def load_word_alignment(run_dir: str, slide_id: str) -> Optional[Dict[str, Any]]:
    from project_storage import slide_file

    path = Path(slide_file(run_dir, slide_id, WORD_ALIGNMENT_FILE))
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("schema_version") != ALIGNMENT_SCHEMA_VERSION:
        return None
    return payload


def beat_times_from_alignment(
    alignment_payload: Optional[Dict[str, Any]],
    timeline_payload: Optional[Dict[str, Any]],
) -> Tuple[Dict[str, Tuple[float, float]], str]:
    """为时间轴构建器提供 beat 区间与诚实的时间来源标记。

    优先读已落盘的 word_alignment;缺文件时直接用句级时间轴。
    返回 (beat_times, temporal_status):sentence → sentence_fallback。
    """
    spans, _duration = read_beat_spans(timeline_payload or {})
    beat_times = {}
    for span in spans:
        previous = beat_times.get(span.beat_id, (span.start_sec, span.end_sec))
        beat_times[span.beat_id] = (min(previous[0], span.start_sec), max(previous[1], span.end_sec))
    return beat_times, "sentence_fallback"


def _credible_anchor_tokens(tokens):
    """Reject visibly weak forced alignment; scores are not accuracy guarantees."""
    forced = [token for token in tokens if token['source'] == 'forced_alignment']
    scores = [_finite_nonnegative(token.get('score')) for token in forced]
    if forced and (any(score is None or score < .5 or score > 1 for score in scores)
                   or sum(scores) / len(scores) < .75):
        return False
    ordered = sorted(tokens, key=lambda token: (token['range'][0], token['start']))
    for token in ordered:
        if token['source'] == 'qwen_alignment' and token['precision'] == 'character':
            if not .015 <= token['end'] - token['start'] <= 1.0:
                return False
        if token['source'] == 'forced_alignment' and token['precision'] == 'character':
            if not .015 <= token['end'] - token['start'] <= 1.0:
                return False
    for previous, current in zip(ordered, ordered[1:]):
        # Expanded percentages legitimately share an original-text range.
        if current['range'] == previous['range']:
            continue
        if current['start'] < previous['start'] or current['start'] < previous['end'] - .04:
            return False
    return True


def resolve_anchor_times(items, alignment, *, audio_hash=None, narration_hash=None):
    """Resolve selected codepoint ranges using measured tokens, never interpolation.

    Tokens use beat-local original narration ranges. Overlapping normalized tokens
    (e.g. 20% -> 百分之二十) may share a range. Every spoken codepoint must be
    covered; punctuation alone cannot create a timestamp.
    """
    if not isinstance(alignment, dict):
        return {}
    engine = alignment.get('engine') or {}
    if isinstance(engine, dict) and str(engine.get('engine_version', '')).startswith('whisperx_'):
        # Historical measurements remain on disk, but cannot silently survive
        # the selected engine migration. Manual calibration is independent.
        return {}
    if alignment.get("time_reference", "audio") != "audio":
        return {}
    for key, expected in (("audio_hash", audio_hash), ("narration_hash", narration_hash)):
        if expected and alignment.get(key) != expected:
            return {}
    tokens = alignment.get("tokens") or []
    resolved = {}
    for item in items:
        anchor = item.anchor
        if anchor is None:
            continue
        selected = []
        selected_tokens = []
        covered = set()
        for token in tokens:
            if not isinstance(token, dict) or token.get("beat_id") != anchor.beat_id:
                continue
            if token.get("precision") not in ("word", "character"):
                continue
            if token.get("source") not in ("provider_word", "forced_alignment", "qwen_alignment", "manual_verified"):
                continue
            bounds = token.get("range")
            start, end = _finite_nonnegative(token.get("start")), _finite_nonnegative(token.get("end"))
            if (not isinstance(bounds, list) or len(bounds) != 2
                    or any(not isinstance(v, int) or isinstance(v, bool) for v in bounds)
                    or bounds[0] >= bounds[1] or start is None or end is None or end <= start):
                continue
            if bounds[0] < anchor.range_end and bounds[1] > anchor.range_start:
                # A measured multi-character word cannot locate a substring's
                # first sound without another character-level measurement.
                if token["source"] in ("provider_word", "qwen_alignment") and (bounds[0] < anchor.range_start or bounds[1] > anchor.range_end):
                    continue
                selected.append((start, end, token["source"]))
                selected_tokens.append(token)
                covered.update(range(max(bounds[0], anchor.range_start), min(bounds[1], anchor.range_end)))
        import unicodedata
        required = {anchor.range_start + i for i, char in enumerate(anchor.quote)
                    if not char.isspace() and not unicodedata.category(char).startswith("P")}
        if selected and required and required <= covered and _credible_anchor_tokens(selected_tokens):
            resolved[item.annotation_id] = {
                "start": min(entry[0] for entry in selected),
                "end": max(entry[1] for entry in selected),
                "source": selected[0][2],
            }
    return resolved


def calibration_audio_delay(timeline):
    if not isinstance(timeline, dict):
        return 0
    return _finite_nonnegative(timeline.get('audio_start_sec')) or 0


def calibration_locator(items, alignment, *, audio_hash, narration_hash):
    """Read-only listening cues from current measured audio, never stale timings."""
    if not audio_hash or not narration_hash:
        return {}
    anchors = resolve_anchor_times(items, alignment, audio_hash=audio_hash, narration_hash=narration_hash)
    for item in items:
        if item.annotation_id not in anchors:
            continue
        cue = anchors[item.annotation_id]
        cue['quote'] = item.anchor.quote
        cue['range'] = [item.anchor.range_start, item.anchor.range_end]
        cue['beat_id'] = item.anchor.beat_id
        cue['characters'] = []
        for token in alignment.get('tokens', []):
            if not isinstance(token, dict) or token.get('beat_id') != item.anchor.beat_id:
                continue
            bounds = token.get('range')
            if (not isinstance(bounds, list) or len(bounds) != 2
                    or any(not isinstance(v, int) or isinstance(v, bool) for v in bounds)
                    or bounds[0] >= bounds[1]):
                continue
            start, end = _finite_nonnegative(token.get('start')), _finite_nonnegative(token.get('end'))
            if (bounds[0] < item.anchor.range_end and bounds[1] > item.anchor.range_start
                    and isinstance(token.get('text'), str) and start is not None and end is not None
                    and end > start and token.get('source') in ('provider_word', 'forced_alignment', 'qwen_alignment', 'manual_verified')):
                cue['characters'].append({'text': token['text'], 'start': start, 'end': end})
    return anchors
