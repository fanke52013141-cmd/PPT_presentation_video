"""Stable fingerprints for artifacts consumed by the final video render."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


FINGERPRINT_SCHEMA_VERSION = 1


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_json(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256_bytes(encoded)


def sha256_file(path: str | Path) -> str | None:
    target = Path(path)
    try:
        digest = hashlib.sha256()
        with target.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except (FileNotFoundError, IsADirectoryError, OSError):
        return None


def _read_contract_slide_ids(run_dir: Path) -> list[str]:
    contract_path = run_dir / "planning" / "visual_contract.json"
    try:
        payload = json.loads(contract_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []
    slides = payload.get("slides") if isinstance(payload, dict) else None
    if not isinstance(slides, list):
        return []
    return [
        str(slide.get("slide_id") or "").strip()
        for slide in slides
        if isinstance(slide, dict) and str(slide.get("slide_id") or "").strip()
    ]


def _component_hashes(run_dir: Path, relative_paths: Iterable[Path]) -> dict[str, str | None]:
    return {
        path.as_posix(): sha256_file(run_dir / path)
        for path in relative_paths
    }


def render_input_fingerprint(
    run_dir: str | Path,
    *,
    visual_settings: Mapping[str, Any],
    pipeline_version: str,
) -> dict[str, Any]:
    """Fingerprint every source that can materially change an MP4 render."""
    root = Path(run_dir)
    slide_ids = _read_contract_slide_ids(root)
    relative_paths = [
        Path("planning/visual_contract.json"),
        Path("planning/narration_beats.json"),
        Path("reveal_manifest.json"),
        Path("remotion_props.json"),
    ]
    for slide_id in slide_ids:
        base = Path("slides") / slide_id
        relative_paths.extend(
            base / filename
            for filename in (
                "visual_draft.png",
                "visual_provenance.json",
                "scene.json",
                "animation_timeline.json",
                "tts_text.txt",
                "voice.mp3",
                "tts_metadata.json",
                "subtitles.srt",
                "audio_timeline.json",
            )
        )

    payload: dict[str, Any] = {
        "schema_version": FINGERPRINT_SCHEMA_VERSION,
        "pipeline_version": str(pipeline_version or ""),
        "slide_ids": slide_ids,
        "visual_settings": dict(visual_settings or {}),
        "components": _component_hashes(root, relative_paths),
    }
    payload["digest"] = sha256_json(payload)
    return payload
