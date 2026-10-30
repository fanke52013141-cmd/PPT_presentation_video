"""Content versions for the inputs named by downstream impact rules."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from artifact_fingerprint import sha256_file, sha256_json


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def _slide(contract: Any, slide_id: str) -> dict[str, Any]:
    if not isinstance(contract, dict):
        return {}
    for item in contract.get("slides") or []:
        if isinstance(item, dict) and str(item.get("slide_id") or "") == slide_id:
            return item
    return {}


def _visual_input(slide: dict[str, Any]) -> dict[str, Any]:
    visual = {key: value for key, value in slide.items() if key not in {"slide_id", "narration_beats"}}
    beats = slide.get("narration_beats")
    if isinstance(beats, list):
        visual["narration_anchors"] = [
            {key: value for key, value in beat.items()
             if key not in {"spoken_text", "tts_text", "source_text"}}
            for beat in beats if isinstance(beat, dict)
        ]
    return visual


def _narration_input(slide: dict[str, Any]) -> list[str]:
    return [
        str(beat.get("spoken_text") or beat.get("tts_text") or beat.get("source_text") or "").strip()
        for beat in (slide.get("narration_beats") or []) if isinstance(beat, dict)
    ]


def impact_source_version(run_dir: str | Path, reason: str, scope_id: str) -> str:
    """Hash only inputs relevant to one reason and its project/page scope."""
    root = Path(run_dir)
    slide = root / "slides" / scope_id
    contract = _json(root / "planning" / "visual_contract.json")
    visual_settings = _json(root / "visual_settings.json")
    if reason == "article_changed":
        value = sha256_file(root / "inputs" / "article.md")
    elif reason in {"storyboard_changed", "storyboard_empty"}:
        value = contract
    elif reason == "storyboard_structure_changed":
        value = [str(item.get("slide_id") or "") for item in (contract or {}).get("slides", [])
                 if isinstance(item, dict)] if isinstance(contract, dict) else []
    elif reason == "storyboard_visual_changed":
        value = _visual_input(_slide(contract, scope_id))
    elif reason == "storyboard_narration_changed":
        value = _narration_input(_slide(contract, scope_id))
    elif reason == "slide_image_changed":
        value = [sha256_file(slide / name) for name in (
            "visual_draft.png", "visual_draft.raw.png", "visual_draft.raw.sha256")]
    elif reason == "mask_content_changed":
        value = _json(root / "reveal_manifest.json")
    elif reason == "annotation_changed":
        value = [sha256_file(slide / "annotations.json"),
                 sha256_file(slide / "annotation_timeline.json")]
    elif reason == "audio_artifacts_changed":
        value = [sha256_file(slide / name) for name in (
            "voice.mp3", "audio_timeline.json", "tts_metadata.json", "tts_text.txt")]
    elif reason == "narration_content_changed":
        value = _json(root / "planning" / "narration_beats.json")
    elif reason == "digital_human_changed":
        config = _json(root / "planning" / "digital_human.json")
        config = config if isinstance(config, dict) else {}
        value = {
            "config": {key: config.get(key) for key in (
                "enabled", "mode", "shape", "circle", "video", "position", "border")},
            "upload": sha256_file(root / "planning" / "digital_human" / "digi_upload.mp4"),
            "generated": sha256_file(root / "planning" / "digital_human" / "digi_full.mp4"),
        }
    elif reason == "digital_human_audio_changed":
        config = _json(root / "planning" / "digital_human.json")
        entries = config.get("slides") if isinstance(config, dict) else {}
        entry = entries.get(scope_id) if isinstance(entries, dict) else None
        if scope_id == "full":
            ids = [str(item.get("slide_id") or "") for item in (contract or {}).get("slides", [])
                   if isinstance(item, dict)] if isinstance(contract, dict) else []
            audio = [sha256_file(root / "slides" / slide_id / "voice.mp3") for slide_id in ids]
        else:
            audio = sha256_file(slide / "voice.mp3")
        value = {"audio": audio, "job_id": entry.get("job_id") if isinstance(entry, dict) else None}
        if scope_id == "full":
            value["full_audio_sha256"] = sha256_file(root / "planning/digital_human/audio_full.mp3")
    elif reason in {"subtitle_style_changed", "subtitle_visibility_changed", "video_background_changed"}:
        value = visual_settings
    else:
        value = {"reason": reason, "scope_id": scope_id}
    return sha256_json({"reason": reason, "scope_id": scope_id, "input": value})
