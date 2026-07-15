"""Write verifiable provenance for final and candidate slide images."""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
from typing import Any, Iterable

from artifact_fingerprint import sha256_bytes, sha256_file
from project_storage import planning_path, slide_dir


PROVENANCE_SCHEMA_VERSION = "visual_provenance_v2"
DEFAULT_RENDER_ALLOWED_PROVIDERS = ("codex_image_gen", "openai_compatible", "manual_upload")


def provenance_path(run_dir: str | Path, slide_id: str, *, candidate: bool = False) -> Path:
    filename = "visual_candidate.provenance.json" if candidate else "visual_provenance.json"
    return slide_dir(run_dir, slide_id) / filename


def render_allowed_providers() -> set[str]:
    configured = {
        value.strip()
        for value in os.environ.get("PPT_STUDIO_RENDER_IMAGE_PROVIDERS", "").split(",")
        if value.strip()
    }
    return configured or set(DEFAULT_RENDER_ALLOWED_PROVIDERS)


def visual_provenance_status(
    run_dir: str | Path,
    slide_id: str,
    *,
    allowed_providers: set[str] | None = None,
) -> dict[str, Any]:
    path = provenance_path(run_dir, slide_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {"valid": False, "reason": "missing_provenance", "slide_id": slide_id}
    except (OSError, json.JSONDecodeError):
        return {"valid": False, "reason": "invalid_provenance", "slide_id": slide_id}
    if not isinstance(payload, dict):
        return {"valid": False, "reason": "invalid_provenance", "slide_id": slide_id}
    provider = str(payload.get("provider") or "").strip()
    allowed = allowed_providers or render_allowed_providers()
    if not provider or provider not in allowed:
        return {"valid": False, "reason": "provider_not_allowed", "slide_id": slide_id, "provider": provider}
    if not str(payload.get("copied_to") or "").replace("\\", "/").endswith("visual_draft.png"):
        return {"valid": False, "reason": "invalid_destination", "slide_id": slide_id}
    if payload.get("schema_version") == PROVENANCE_SCHEMA_VERSION:
        image = slide_dir(run_dir, slide_id) / "visual_draft.png"
        if not payload.get("output_sha256") or payload.get("output_sha256") != sha256_file(image):
            return {"valid": False, "reason": "image_hash_changed", "slide_id": slide_id}
        contract = planning_path(run_dir, "visual_contract.json")
        if not payload.get("contract_sha256") or payload.get("contract_sha256") != sha256_file(contract):
            return {"valid": False, "reason": "contract_hash_changed", "slide_id": slide_id}
    return {"valid": True, "reason": "valid", "slide_id": slide_id, "provider": provider}


def validate_visual_provenance_set(
    run_dir: str | Path,
    slide_ids: Iterable[str],
    *,
    allowed_providers: set[str] | None = None,
) -> list[dict[str, Any]]:
    return [
        status
        for slide_id in slide_ids
        if not (
            status := visual_provenance_status(
                run_dir,
                str(slide_id),
                allowed_providers=allowed_providers,
            )
        )["valid"]
    ]


def build_visual_provenance(
    run_dir: str | Path,
    slide_id: str,
    *,
    image_path: str | Path,
    provider: str,
    source_type: str,
    model: str = "",
    prompt: str = "",
    reference_paths: Iterable[str | Path] = (),
    source_bytes: bytes | None = None,
    source_filename: str = "",
    candidate: bool = False,
) -> dict[str, Any]:
    root = Path(run_dir)
    image = Path(image_path)
    contract = planning_path(root, "visual_contract.json")
    references = [Path(path) for path in reference_paths]
    copied_name = "visual_candidate.png" if candidate else "visual_draft.png"
    return {
        "schema_version": PROVENANCE_SCHEMA_VERSION,
        "provider": str(provider or "").strip(),
        "source_type": str(source_type or "").strip(),
        "model": str(model or "").strip(),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "slide_id": str(slide_id),
        "prompt_sha256": sha256_bytes(str(prompt or "").encode("utf-8")) if prompt else None,
        "contract_sha256": sha256_file(contract),
        "reference_sha256s": [digest for digest in (sha256_file(path) for path in references) if digest],
        "source_sha256": sha256_bytes(source_bytes) if source_bytes is not None else None,
        "source_filename": Path(str(source_filename or "")).name,
        "output_sha256": sha256_file(image),
        "copied_to": f"slides/{slide_id}/{copied_name}",
    }


def write_visual_provenance(
    run_dir: str | Path,
    slide_id: str,
    *,
    image_path: str | Path,
    provider: str,
    source_type: str,
    model: str = "",
    prompt: str = "",
    reference_paths: Iterable[str | Path] = (),
    source_bytes: bytes | None = None,
    source_filename: str = "",
    candidate: bool = False,
) -> dict[str, Any]:
    from pipeline_lifecycle import write_json_atomic

    payload = build_visual_provenance(
        run_dir,
        slide_id,
        image_path=image_path,
        provider=provider,
        source_type=source_type,
        model=model,
        prompt=prompt,
        reference_paths=reference_paths,
        source_bytes=source_bytes,
        source_filename=source_filename,
        candidate=candidate,
    )
    write_json_atomic(provenance_path(run_dir, slide_id, candidate=candidate), payload)
    return payload


def promote_candidate_provenance(run_dir: str | Path, slide_id: str) -> dict[str, Any] | None:
    from pipeline_lifecycle import read_json_file, remove_file, write_json_atomic

    candidate_path = provenance_path(run_dir, slide_id, candidate=True)
    payload = read_json_file(candidate_path)
    if not isinstance(payload, dict):
        return None
    payload["copied_to"] = f"slides/{slide_id}/visual_draft.png"
    payload["promoted_at"] = datetime.now().isoformat(timespec="seconds")
    payload["output_sha256"] = sha256_file(slide_dir(run_dir, slide_id) / "visual_draft.png")
    write_json_atomic(provenance_path(run_dir, slide_id), payload)
    remove_file(candidate_path)
    return payload


def refresh_provenance_contract_hashes(run_dir: str | Path, slide_ids: Iterable[str]) -> int:
    """Refresh only the contract hash after a pure slide-order change."""
    from pipeline_lifecycle import read_json_file, write_json_atomic

    contract_hash = sha256_file(planning_path(run_dir, "visual_contract.json"))
    changed = 0
    for slide_id in slide_ids:
        path = provenance_path(run_dir, str(slide_id))
        payload = read_json_file(path)
        if not isinstance(payload, dict) or payload.get("schema_version") != PROVENANCE_SCHEMA_VERSION:
            continue
        image_path = slide_dir(run_dir, str(slide_id)) / "visual_draft.png"
        if payload.get("output_sha256") != sha256_file(image_path):
            continue
        payload["contract_sha256"] = contract_hash
        write_json_atomic(path, payload)
        changed += 1
    return changed
