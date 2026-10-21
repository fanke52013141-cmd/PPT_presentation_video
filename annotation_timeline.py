# -*- coding: utf-8 -*-
"""勾画标注时间轴构建器(W4):纯函数,确定性输出。

对应交接文档 7.2:

- 每个事件包含 annotation_id、目标引用、受限笔迹(首期由覆盖层按几何
  实时绘制,timeline 记录锚点时间与样式,路径细节数据由 W5 路径生成器
  补充进 strokes 字段)、start/draw_end/hold_end/exit_end、时间来源。
- 边界约束:``0 <= start < draw_end <= hold_end <= exit_end <= slide_duration``;
  时间不足返回 needs_review,不产生负 duration,不静默延长视频。
- 页面事件时间 = 锚点音频内时间 + 用户 offset(offset 只加一次)。
- 同一时刻默认一个主要绘制动作:冲突在容忍窗口(默认 0.2s)内延后,
  超窗口或超出语块结束时间进入 needs_review。显式 manual 定时不重排。
- 静态页/无锚点条目:temporal=manual 时必须带 manual_start_sec。
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from annotation_contracts import DEFAULT_CANVAS

__all__ = [
    "TIMELINE_SCHEMA_VERSION",
    "ANNOTATION_TIMELINE_FILE",
    "RESOLVER_VERSION",
    "CONFLICT_TOLERANCE_SEC",
    "TimelineEvent",
    "build_annotation_timeline",
    "timeline_hash",
]

TIMELINE_SCHEMA_VERSION = 2
ANNOTATION_TIMELINE_FILE = "annotation_timeline.json"
RESOLVER_VERSION = "annotation_timeline_v2"
CONFLICT_TOLERANCE_SEC = 0.2
_MIN_DRAW = 0.05
_MIN_EXIT = 0.0


@dataclass(frozen=True)
class TimelineEvent:
    annotation_id: str
    beat_id: Optional[str]
    target_kind: str
    token_ids: Tuple[str, ...]
    style_type: str
    color: str
    opacity: float
    width: int
    padding: int
    seed: int
    start_sec: float
    draw_end_sec: float
    hold_end_sec: float
    exit_end_sec: float
    timing_source: str  # anchor|manual
    scheduling_note: str  # "" | delayed | needs_review 原因
    needs_review: bool
    strokes: Tuple[Dict[str, Any], ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "annotation_id": self.annotation_id,
            "beat_id": self.beat_id,
            "target": {"kind": self.target_kind, "token_ids": list(self.token_ids)},
            "style": {
                "type": self.style_type, "color": self.color, "opacity": self.opacity,
                "width": self.width, "padding": self.padding, "seed": self.seed,
            },
            "strokes": [dict(s) for s in self.strokes],
            "start_sec": self.start_sec,
            "draw_end_sec": self.draw_end_sec,
            "hold_end_sec": round(self.hold_end_sec, 4),
            "exit_end_sec": round(self.exit_end_sec, 4),
            "timing_source": self.timing_source,
            "scheduling_note": self.scheduling_note,
            "needs_review": self.needs_review,
        }


def _resolve_start(item: Any, beat_times: Dict[str, Tuple[float, float]]) -> Tuple[Optional[float], str, bool]:
    """返回 (锚点起笔时间, 时间来源, needs_review)。"""
    timing = item.timing
    if timing.trigger_mode == "manual":
        if timing.manual_start_sec is None:
            return None, "manual", True
        return float(timing.manual_start_sec), "manual", False
    if item.anchor is None:
        return None, "anchor", True
    beat = beat_times.get(item.anchor.beat_id)
    if beat is None:
        return None, "anchor", True
    return beat[0] + timing.offset_sec, "anchor", False


def _resolve_hold_end(hold_mode: str, hold_duration: Optional[float], beat_end: Optional[float], slide_duration: float, draw_end: float, exit_duration: float) -> Tuple[Optional[float], Optional[float]]:
    """返回 (hold_end, exit_end);非法窗口返回 (None, None)。

    slide_end 语义:笔迹保留到页尾,退出动画收敛在页尾之内
    (hold_end = 页长 - exit),否则 exit_end 必然越过页长边界。
    """
    if hold_mode == "beat_end":
        return beat_end, (beat_end + exit_duration) if beat_end is not None else None
    if hold_mode == "slide_end":
        hold = slide_duration - exit_duration
        if hold < draw_end:
            return None, None
        return hold, slide_duration
    if hold_mode == "duration":
        if hold_duration is None:
            return None, None
        hold = draw_end + hold_duration
        return hold, hold + exit_duration
    return None, None


def schedule_strokes(strokes, draw_duration, fps=30):
    """Freeze each stroke's local window, weighted by arc length and pen lifts."""
    if not strokes:
        return ()
    lengths = [max(1.0, sum(math.dist(a, b) for a, b in zip(
        stroke.get("points", []), stroke.get("points", [])[1:]))) for stroke in strokes]
    gaps = [math.ceil(max(0.0, float(stroke.get("start_offset_sec", 0))) * fps) / fps for stroke in strokes]
    available = max(0.001, draw_duration - sum(gaps))
    cursor = 0.0
    result = []
    for stroke, length, gap in zip(strokes, lengths, gaps):
        cursor += gap
        duration = 2 / fps + max(0.0, available - len(strokes) * 2 / fps) * length / sum(lengths)
        result.append({**stroke, "draw_start_offset_sec": round(cursor, 6),
                       "draw_end_offset_sec": round(cursor + duration, 6)})
        cursor += duration
    return tuple(result)


def build_annotation_timeline(
    *, slide_id, items, canvas=DEFAULT_CANVAS, beat_times, slide_duration,
    image_hash, narration_hash, audio_hash, confirmed_input_hashes,
    audio_start_sec=0.0, anchor_times=None, target_ready_times=None,
    require_precise=False, fps=30, max_concurrent_draws=2,
):
    """Compile audio-relative anchors into a deterministic slide clock.

    The production caller requires measured anchors. Legacy sentence timing is
    available only to explicit offline callers and is labelled sentence_fallback.
    Manual starts default to the legacy slide clock; new audio calibration
    declares its reference. Fade/hold may shrink, but strokes are never cut off.
    """
    events, issues = [], []
    anchor_times, target_ready_times = anchor_times or {}, target_ready_times or {}
    delay = max(0.0, float(audio_start_sec))
    fps = max(1, int(fps))
    slide_duration = math.floor(float(slide_duration) * fps + 1e-7) / fps
    minimum_hold = max(0.2, 2 / fps)

    def start_for(item):
        timing = item.timing
        if timing.trigger_mode == "manual":
            value = timing.manual_start_sec
            if value is None:
                return None, "manual", False
            reference = getattr(timing, "time_reference", "slide")
            return float(value) + (delay if reference == "audio" else 0), "manual", False
        precise = anchor_times.get(item.annotation_id)
        if precise:
            return float(precise["start"]) + delay + timing.offset_sec, precise["source"], False
        if require_precise:
            return None, "anchor", True
        start, _, review = _resolve_start(item, beat_times)
        return (start + delay if start is not None else None), "sentence_fallback", review

    ordered = sorted(items, key=lambda item: (start_for(item)[0] if start_for(item)[0] is not None
                                              else float("inf"), item.annotation_id))
    for item in ordered:
        if item.status.content == "disabled":
            continue
        if item.timing.trigger_mode == "manual" and item.timing.calibration_stale:
            issues.append({"annotation_id": item.annotation_id, "reason": "manual_calibration_stale"})
            continue
        start, source, review = start_for(item)
        if start is None:
            issues.append({"annotation_id": item.annotation_id, "reason":
                           "anchor_unresolved" if require_precise and source == "anchor" else
                           "missing_manual_start" if source == "manual" else "missing_anchor_time"})
            continue
        nominal_start = max(0.0, start)
        ready = target_ready_times.get(item.annotation_id, 0.0)
        if ready is None:
            issues.append({"annotation_id": item.annotation_id, "reason": "target_visibility_unresolved"})
            continue
        if ready - nominal_start > 0.15 + 1e-7:
            issues.append({"annotation_id": item.annotation_id, "reason": "target_not_ready",
                           "phrase_start_sec": nominal_start, "target_ready_sec": ready,
                           "delay_sec": ready - nominal_start})
            continue
        start = math.ceil(max(nominal_start, ready) * fps - 1e-7) / fps
        strokes = tuple(getattr(item, "strokes", ()) or ())
        gaps = sum(math.ceil(max(0, float(s.get("start_offset_sec", 0))) * fps) / fps for s in strokes)
        minimum_draw = max(2 / fps, len(strokes) * 2 / fps + gaps)
        available = slide_duration - start - minimum_hold
        if available + 1e-7 < minimum_draw:
            issues.append({"annotation_id": item.annotation_id, "reason": "insufficient_draw_window"})
            continue
        requested_draw = max(minimum_draw, float(item.timing.draw_duration_sec))
        draw_frames = min(math.ceil(requested_draw * fps - 1e-7),
                          math.floor(available * fps + 1e-7))
        draw_end = start + draw_frames / fps
        timing = item.timing
        beat_end = beat_times.get(item.anchor.beat_id, (None, None))[1] if item.anchor else None
        if timing.hold_mode == "beat_end":
            if beat_end is None:
                issues.append({"annotation_id": item.annotation_id, "reason": "missing_hold_reference"})
                continue
            hold_end = max(draw_end + minimum_hold, float(beat_end) + delay)
        elif timing.hold_mode == "slide_end":
            hold_end = max(draw_end + minimum_hold, slide_duration - max(0.0, timing.exit_duration_sec))
        else:
            if timing.hold_duration_sec is None:
                issues.append({"annotation_id": item.annotation_id, "reason": "missing_hold_reference"})
                continue
            hold_end = draw_end + max(minimum_hold, timing.hold_duration_sec)
        hold_end = min(slide_duration, hold_end)
        exit_end = min(slide_duration, hold_end + max(0.0, timing.exit_duration_sec))
        active = [event for event in events if event.draw_end_sec > start + 1e-7]
        if source != "manual" and len(active) >= max_concurrent_draws:
            issues.append({"annotation_id": item.annotation_id, "reason": "drawing_concurrency_exceeded"})
            continue
        note = "compressed" if draw_frames / fps + 1e-7 < requested_draw else ""
        event = TimelineEvent(
            annotation_id=item.annotation_id, beat_id=item.anchor.beat_id if item.anchor else None,
            target_kind=item.target.kind, token_ids=tuple(item.target.token_ids),
            style_type=item.style.type, color=item.style.color, opacity=item.style.opacity,
            width=item.style.width, padding=item.style.padding, seed=item.style.seed,
            start_sec=start, draw_end_sec=draw_end, hold_end_sec=hold_end, exit_end_sec=exit_end,
            timing_source=source, scheduling_note=note, needs_review=review,
            strokes=schedule_strokes(strokes, draw_frames / fps, fps),
        )
        events.append(event)
    payload = {
        "schema_version": TIMELINE_SCHEMA_VERSION, "resolver_version": RESOLVER_VERSION,
        "time_reference": "slide", "fps": fps, "slide_id": slide_id, "canvas": list(canvas),
        "inputs": {"image_hash": image_hash, "narration_hash": narration_hash,
                   "audio_hash": audio_hash, "audio_start_sec": delay,
                   "confirmed_input_hashes": dict(confirmed_input_hashes or {})},
        "page_state": "ready" if events else "no_annotations",
        "slide_duration_frames": round(slide_duration * fps),
        "slide_duration_sec": round(slide_duration, 6), "events": [event.to_dict() for event in events],
        "needs_review": issues,
    }
    for event in payload["events"]:
        event["start_frame"] = math.ceil(event["start_sec"] * fps - 0.001)
        event["draw_end_frame"] = round(event["draw_end_sec"] * fps)
        precise = anchor_times.get(event["annotation_id"], {})
        event["anchor_audio_start_sec"] = precise.get("start")
        event["anchor_audio_end_sec"] = precise.get("end")
        event["target_ready_sec"] = target_ready_times.get(event["annotation_id"], 0.0)
    return payload, issues


def timeline_hash(payload: Dict[str, Any]) -> str:
    """规范化哈希:同输入两次构建必须一致(确定性门)。"""
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
