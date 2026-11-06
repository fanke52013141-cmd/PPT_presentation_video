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


def _digital_human_component_paths(run_dir: Path) -> list[Path]:
    """Return only digital-human inputs that affect the final MP4.

    A disabled presenter must remain invisible to the render fingerprint.  This
    keeps existing ordinary MP4 artifacts current, while changing the enabled
    flag, layout, mode, or active source video creates a different fingerprint.
    """
    config_path = run_dir / "planning" / "digital_human.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        # A corrupted saved config must make prior MP4s stale. Rendering will
        # then surface the actionable configuration error instead of reusing a
        # pre-digital-human artifact.
        return [Path("planning/digital_human.json")] if config_path.exists() else []
    if not isinstance(config, dict):
        return [Path("planning/digital_human.json")]
    if not config.get("enabled"):
        return []

    paths = [Path("planning/digital_human.json")]
    mode = str(config.get("mode") or "upload").strip().lower()
    source_name = "digi_upload.mp4" if mode == "upload" else "digi_full.mp4"
    paths.append(Path("planning") / "digital_human" / source_name)
    return paths


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
        Path("planning/annotation_settings.json"),
    ]
    relative_paths.extend(_digital_human_component_paths(root))
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
                "annotation_timeline.json",
            )
        )

    components = _component_hashes(root, relative_paths)
    digital_config_path = root / "planning" / "digital_human.json"
    digital_config_key = "planning/digital_human.json"
    if digital_config_key in components:
        try:
            digital_config = json.loads(digital_config_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            digital_config = None
        if isinstance(digital_config, dict) and digital_config.get("enabled"):
            from digital_human_contracts import digital_human_render_config
            components[digital_config_key] = sha256_json(digital_human_render_config(digital_config))

    payload: dict[str, Any] = {
        "schema_version": FINGERPRINT_SCHEMA_VERSION,
        "pipeline_version": str(pipeline_version or ""),
        "slide_ids": slide_ids,
        "visual_settings": dict(visual_settings or {}),
        "components": components,
    }
    payload["digest"] = sha256_json(payload)
    return payload


def presentation_input_fingerprint(run_dir: str | Path) -> dict[str, Any]:
    """Fingerprint the ordered, approved bitmap inputs used by a PPTX export."""
    root = Path(run_dir)
    slide_ids = _read_contract_slide_ids(root)
    # Reveal-mode exports reuse this fingerprint but additionally consume
    # reveal_manifest.json; without it, Mask edits would leave an exported
    # reveal deck reported as "current".
    relative_paths = [
        Path("planning/visual_contract.json"),
        Path("reveal_manifest.json"),
    ]
    for slide_id in slide_ids:
        base = Path("slides") / slide_id
        relative_paths.extend(
            (
                base / "visual_draft.png",
                base / "visual_provenance.json",
            )
        )
    payload: dict[str, Any] = {
        "schema_version": FINGERPRINT_SCHEMA_VERSION,
        "export_type": "image_only_pptx",
        "slide_ids": slide_ids,
        "components": _component_hashes(root, relative_paths),
    }
    payload["digest"] = sha256_json(payload)
    return payload
