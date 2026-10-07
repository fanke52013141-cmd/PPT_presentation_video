"""Shared annotation compilation and immutable ink builds, without app wiring."""
from __future__ import annotations

import hashlib
import json
import math
import threading
from pathlib import Path
from dataclasses import dataclass

from annotation_alignment import beat_times_from_alignment, resolve_anchor_times
from annotation_geometry import FragmentInput, GeometryInputV2, build_manual_path_stroke, build_strokes_v2
from annotation_ink import INK_VERSION, InkRequest, frames_needed, render_and_write
from annotation_target_resolver import resolve_phrase_target
from annotation_timeline import RESOLVER_VERSION, build_annotation_timeline


def ink_request(item, stroke, canvas, index):
    """Canonical ink inputs for editor stills and exported animation frames."""
    return InkRequest(
        points=tuple(map(tuple, stroke["points"])), width_profile=tuple(stroke["width_profile"]),
        speed_profile=tuple(stroke.get("speed_profile", [])), canvas=tuple(canvas),
        color=tuple(int(item.style.color[i:i + 2], 16) for i in (1, 3, 5)),
        base_width=float(stroke.get("brush_height") or item.style.width), opacity=1.0,
        seed=item.style.seed + index * 733, closed=stroke.get("closed", False),
    )


_INK_BUILD_GATE = threading.BoundedSemaphore(1)


class AnnotationBuildError(ValueError):
    def __init__(self, issues):
        self.issues = issues
        super().__init__(issues[0]["reason"] if issues else "annotation_build_failed")


def read_json(path, *, optional=False):
    path = Path(path)
    if optional and not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise AnnotationBuildError([{"reason": "artifact_missing_or_corrupt", "file": path.name}]) from exc
    if not isinstance(data, dict):
        raise AnnotationBuildError([{"reason": "artifact_corrupt", "file": path.name}])
    return data


def file_hash(path):
    path = Path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def content_hash(items):
    payload = [{key: value for key, value in item.to_dict().items()
                if key in ("annotation_id", "target", "anchor", "style", "timing")}
               for item in items if item.status.content != "disabled"]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def input_snapshot(slide_dir, items, canvas, fps=30):
    slide_dir = Path(slide_dir)
    return {
        **{name: file_hash(slide_dir / filename) for name, filename in (
            ("image_hash", "visual_draft.png"), ("narration_hash", "narration_beats.json"),
            ("audio_hash", "voice.mp3"), ("audio_timeline_hash", "audio_timeline.json"),
            ("animation_hash", "animation_timeline.json"), ("scene_hash", "scene.json"),
            ("layout_hash", "text_layout.json"), ("alignment_hash", "word_alignment.json"))},
        "content_hash": content_hash(items), "canvas": list(canvas), "fps": int(fps), "ink_version": INK_VERSION,
    }


def item_strokes(item, layout):
    paths = item.target.path_strokes or ((item.target.path_points,) if item.target.path_points else ())
    if paths:
        result = []
        for index, points in enumerate(paths):
            stroke = build_manual_path_stroke(points, style_type=item.style.type, width=item.style.width)
            stroke["start_offset_sec"] = 0.06 if index else 0.0
            result.append(stroke)
        return result
    if item.target.kind == "text":
        if layout is None:
            raise AnnotationBuildError([{"annotation_id": item.annotation_id, "reason": "text_layout_missing"}])
        resolved = resolve_phrase_target(layout=layout, token_ids=list(item.target.token_ids),
                                        expected_layout_revision=item.target.layout_revision)
        polygons = [fragment["polygons"] for fragment in resolved["fragments"]]
    else:
        polygons = [[polygon] for polygon in item.target.polygons]
    fragments = tuple(FragmentInput(
        polygons=tuple(tuple(map(tuple, polygon)) for polygon in group),
        style_type=item.style.type, width=item.style.width, padding=item.style.padding, seed=item.style.seed,
    ) for group in polygons)
    return list(build_strokes_v2(GeometryInputV2(fragments=fragments)))


def target_ready_times(slide_dir, items, canvas):
    """Use exact layer alpha under selected targets; never rematch Mask ownership."""
    scene = read_json(Path(slide_dir) / "scene.json", optional=True)
    animation = read_json(Path(slide_dir) / "animation_timeline.json", optional=True) or {}
    if not scene:
        return {item.annotation_id: 0.0 for item in items}
    dynamic = {str(event.get("target")): event for event in animation.get("events", [])
               if isinstance(event, dict) and event.get("action") != "hide"}
    if not dynamic:
        return {item.annotation_id: 0.0 for item in items}
    from PIL import Image, ImageChops, ImageDraw
    layers = [layer for layer in scene.get("layers", []) if str(layer.get("id")) in dynamic]
    result = {}
    for item in items:
        region = Image.new("L", tuple(canvas))
        draw = ImageDraw.Draw(region)
        for polygon in item.target.polygons:
            draw.polygon(list(map(tuple, polygon)), fill=255)
        found = []
        for layer in layers:
            selected = bool(item.target.mask_group_ids and layer.get("target_group_id") in item.target.mask_group_ids)
            if not item.target.mask_group_ids:
                asset = Path(slide_dir) / str(layer.get("asset") or "")
                if asset.is_file():
                    with Image.open(asset) as image:
                        alpha = image.convert("RGBA").getchannel("A")
                        if alpha.size == region.size:
                            selected = ImageChops.multiply(alpha, region).getbbox() is not None
            if selected:
                event = dynamic[str(layer["id"])]
                found.append(max(0.0, float(event.get("at", 0))) + max(0.0, float(event.get("duration", 0))))
        result[item.annotation_id] = max(found) if found else None
    return result


@dataclass(frozen=True)
class _WithStrokes:
    item: object
    strokes: tuple

    def __getattr__(self, name):
        return getattr(self.item, name)


def compile_slide(slide_dir, page, *, canvas, fps=30, alignment=None, cancel_event=None, progress=None):
    """Build complete assets without publishing confirmation or mutating a page."""
    slide_dir = Path(slide_dir)
    active = [item for item in page.items if item.status.content != "disabled"]
    snapshot = input_snapshot(slide_dir, page.items, canvas, fps)
    if not active:
        return {"resolver_version": RESOLVER_VERSION, "events": [], "needs_review": [],
                "inputs": snapshot, "slide_id": page.slide_id, "canvas": list(canvas), "fps": fps}
    audio = read_json(slide_dir / "audio_timeline.json", optional=True)
    if audio is None:
        raise AnnotationBuildError([{"reason": "audio_timeline_missing"}])
    try:
        beat_times, _ = beat_times_from_alignment(None, audio)
    except ValueError as exc:
        raise AnnotationBuildError([{"reason": "audio_timeline_invalid"}]) from exc
    alignment = alignment or read_json(slide_dir / "word_alignment.json", optional=True)
    if alignment is None and isinstance(audio.get("words"), list):
        alignment = {"tokens": audio["words"], "audio_hash": snapshot["audio_hash"],
                     "narration_hash": snapshot["narration_hash"], "time_reference": "audio"}
    anchors = resolve_anchor_times(active, alignment, audio_hash=snapshot["audio_hash"],
                                   narration_hash=snapshot["narration_hash"])
    layout = read_json(slide_dir / "text_layout.json", optional=True)
    wrapped = []
    for item in active:
        try:
            strokes = item_strokes(item, layout)
        except AnnotationBuildError:
            raise
        except Exception as exc:
            raise AnnotationBuildError([{"annotation_id": item.annotation_id, "reason": "strokes_invalid"}]) from exc
        if not strokes:
            raise AnnotationBuildError([{"annotation_id": item.annotation_id, "reason": "strokes_missing"}])
        wrapped.append(_WithStrokes(item, tuple(strokes)))
    from scripts.build_remotion_props import compute_slide_presentation_duration, align_audio_timeline_to_voice
    animation = read_json(slide_dir / "animation_timeline.json", optional=True) or {}
    delay = float(audio.get("audio_start_sec", 0) or 0)
    effective_audio = align_audio_timeline_to_voice(audio, slide_dir / "voice.mp3")
    if isinstance(effective_audio.get("audio_content_duration_sec"), (int, float)):
        effective_audio["duration_sec"] = float(effective_audio["audio_content_duration_sec"]) + delay
    payload, issues = build_annotation_timeline(
        slide_id=page.slide_id, items=wrapped, canvas=canvas, beat_times=beat_times,
        slide_duration=compute_slide_presentation_duration(effective_audio, animation),
        image_hash=snapshot["image_hash"], narration_hash=snapshot["narration_hash"],
        audio_hash=snapshot["audio_hash"], confirmed_input_hashes={}, audio_start_sec=delay,
        anchor_times=anchors, target_ready_times=target_ready_times(slide_dir, active, canvas),
        require_precise=True, fps=fps,
    )
    if issues:
        raise AnnotationBuildError(issues)
    payload["inputs"].update(snapshot)
    payload["build_id"] = timeline_build_id(payload)
    by_id = {item.annotation_id: item for item in active}
    total_strokes = sum(len(event["strokes"]) for event in payload["events"])
    completed_strokes = 0
    for event in payload["events"]:
        if cancel_event and cancel_event.is_set():
            raise AnnotationBuildError([{"reason": "cancelled"}])
        item = by_id[event["annotation_id"]]
        for index, stroke in enumerate(event["strokes"]):
            request = ink_request(item, stroke, canvas, index)
            relative = f"build_{payload['build_id']}_stroke_{index}"
            directory = slide_dir / "annotation_ink" / item.annotation_id / relative
            duration = stroke["draw_end_offset_sec"] - stroke["draw_start_offset_sec"]
            try:
                with _INK_BUILD_GATE:
                    metadata = read_json(directory / "meta.json", optional=True)
                    if not metadata or int(metadata.get("frame_count", 0)) < 2 or not all((directory / f"frame_{i:03d}.png").is_file()
                                               for i in range(int(metadata.get("frame_count", 0)))):
                        metadata = render_and_write(request, directory, draw_duration_sec=duration, fps=fps,
                                                    **({"cancel_event": cancel_event} if cancel_event else {}))
                stroke["ink"] = {"kind": "raster", "dir": relative,
                                 "frame_count": int(metadata["frame_count"]), "fps": fps,
                                 "canvas": list(canvas)}
                completed_strokes += 1
                if progress:
                    progress(30 + int(60 * completed_strokes / max(1, total_strokes)), "ink")
            except Exception as exc:
                raise AnnotationBuildError([{"annotation_id": item.annotation_id, "reason": "ink_build_failed"}]) from exc
    return json.loads(json.dumps(payload))


def timeline_build_id(payload):
    canonical = json.loads(json.dumps(payload))
    canonical.pop("build_id", None)
    for event in canonical.get("events", []):
        for stroke in event.get("strokes", []):
            stroke.pop("ink", None)
    return hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()[:24]


def validate_timeline(slide_dir, page, *, canvas, fps=30, timeline=None):
    active = [item for item in page.items if item.status.content != "disabled"] if page else []
    if not active:
        return None
    timeline = timeline or read_json(Path(slide_dir) / "annotation_timeline.json", optional=True)
    if not timeline:
        raise AnnotationBuildError([{"reason": "timeline_missing"}])
    if timeline.get("resolver_version") != RESOLVER_VERSION:
        raise AnnotationBuildError([{"reason": "timeline_version_stale"}])
    if any(event.get('timing_source') == 'forced_alignment' for event in timeline.get('events', [])):
        raise AnnotationBuildError([{"reason": "timeline_version_stale"}])
    if timeline.get("build_id") != timeline_build_id(timeline):
        raise AnnotationBuildError([{"reason": "timeline_content_corrupt"}])
    snapshot = input_snapshot(slide_dir, page.items, canvas, fps)
    if any(timeline.get("inputs", {}).get(key) != value for key, value in snapshot.items()):
        raise AnnotationBuildError([{"reason": "timeline_inputs_stale"}])
    ids = {event.get("annotation_id") for event in timeline.get("events", [])}
    if ids != {item.annotation_id for item in active} or timeline.get("needs_review"):
        raise AnnotationBuildError([{"reason": "timeline_incomplete"}])
    for item in active:
        if (item.confirmed_inputs or {}).get("build_id") != timeline.get("build_id"):
            raise AnnotationBuildError([{"annotation_id": item.annotation_id, "reason": "confirmation_stale"}])
        if item.status.content != "confirmed":
            raise AnnotationBuildError([{"annotation_id": item.annotation_id, "reason": "unconfirmed"}])
    for event in timeline["events"]:
        if not event.get("strokes"):
            raise AnnotationBuildError([{"annotation_id": event["annotation_id"], "reason": "strokes_missing"}])
        for index, stroke in enumerate(event["strokes"]):
            ink = stroke.get("ink") or {}
            if ink.get("dir") != f"build_{timeline['build_id']}_stroke_{index}":
                raise AnnotationBuildError([{"reason": "ink_build_mismatch"}])
            directory = Path(slide_dir) / "annotation_ink" / event["annotation_id"] / str(ink.get("dir", ""))
            if not directory.resolve().is_relative_to(Path(slide_dir).resolve()):
                raise AnnotationBuildError([{"reason": "ink_path_invalid"}])
            count = ink.get("frame_count", 0)
            expected_count = frames_needed(stroke["draw_end_offset_sec"] - stroke["draw_start_offset_sec"], fps)
            if (not isinstance(count, int) or isinstance(count, bool) or count != expected_count
                    or ink.get("fps") != fps or ink.get("canvas") != list(canvas)):
                raise AnnotationBuildError([{"reason": "ink_metadata_invalid"}])
            if ink.get("kind") != "raster" or count < 2 or count > 240 or not all(
                    (directory / f"frame_{i:03d}.png").is_file() for i in range(count)):
                raise AnnotationBuildError([{"annotation_id": event["annotation_id"], "reason": "ink_asset_missing"}])
    return timeline
