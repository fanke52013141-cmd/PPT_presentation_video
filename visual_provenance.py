"""Write verifiable provenance for final and candidate slide images."""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
from typing import Any, Iterable

from artifact_fingerprint import sha256_bytes, sha256_file
from project_storage import planning_path, slide_dir
from storyboard_contract_diff import visual_slide_input


PROVENANCE_SCHEMA_VERSION = "visual_provenance_v3"
LEGACY_CONTRACT_HASH_SCHEMA_VERSION = "visual_provenance_v2"
# Keep the provider identifiers emitted by the configured image adapters in
# the production allow-list.  ``codex2api`` is the provider used by the
# Codex2API OpenAI-compatible gateway and is a valid generated-image source.
# ``xiaoxinai`` and ``toapis`` are configured OpenAI-compatible image gateways.
DEFAULT_RENDER_ALLOWED_PROVIDERS = (
    "codex_image_gen",
    "codex2api",
    "openai_compatible",
    "toapis",
    "xiaoxinai",
    "manual_upload",
)


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


def _canonical_slide_entry(slide: Any) -> str:
    return json.dumps(
        slide, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _canonical_visual_entry(slide: Any) -> str:
    return json.dumps(
        visual_slide_input(slide) if isinstance(slide, dict) else slide,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _entry_hashes(slides: Iterable[Any], canonical) -> dict[str, str]:
    return {
        str(slide.get("slide_id")): sha256_bytes(canonical(slide).encode("utf-8"))
        for slide in slides
        if isinstance(slide, dict) and slide.get("slide_id") is not None
    }


def slide_entry_hashes(slides: Iterable[Any]) -> dict[str, str]:
    """Map slide_id -> content hash of that single contract slide entry.

    Whole-entry semantics kept for legacy stored payloads; new writes use
    :func:`visual_slide_entry_hashes` so narration-only edits cannot break
    an approved image's provenance.
    """
    return _entry_hashes(slides, _canonical_slide_entry)


def visual_slide_entry_hashes(slides: Iterable[Any]) -> dict[str, str]:
    """Map slide_id -> hash of the slide's *visual* projection.

    The projection matches ``storyboard_contract_diff.visual_slide_input``:
    beat narration text is excluded (it feeds TTS, not the image), while the
    beat group/anchor mapping stays (it owns reveal semantics).
    """
    return _entry_hashes(slides, _canonical_visual_entry)


def _contract_slide_entries(run_dir: str | Path) -> list[Any] | None:
    try:
        contract = json.loads(
            planning_path(run_dir, "visual_contract.json").read_text(encoding="utf-8-sig")
        )
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(contract, dict) or not isinstance(contract.get("slides"), list):
        return None
    return contract["slides"]


def slide_contract_hash(run_dir: str | Path, slide_id: str) -> str:
    """Hash of only this slide's whole contract entry ('' when missing/unreadable).

    Whole-file hashing made an edit on any other slide invalidate every
    slide's provenance; per-slide entries only change when that slide changes.
    """
    slides = _contract_slide_entries(run_dir)
    if slides is None:
        return ""
    return slide_entry_hashes(slides).get(str(slide_id), "")


def visual_slide_contract_hash(run_dir: str | Path, slide_id: str) -> str:
    """Hash of this slide's visual projection ('' when missing/unreadable).

    Identical to :func:`slide_contract_hash` unless the slide's narration
    text changed: narration-only edits keep this hash stable, aligning the
    provenance gate with the invalidation classifier.
    """
    slides = _contract_slide_entries(run_dir)
    if slides is None:
        return ""
    return visual_slide_entry_hashes(slides).get(str(slide_id), "")


def contract_slide_hash_matches(stored: Any, run_dir: str | Path, slide_id: str) -> bool:
    """Whether a payload's stored per-slide hash still matches the contract.

    Accepts either hash semantics: new payloads store the visual projection,
    legacy v3 payloads stored the whole entry (a strictly stronger match).
    Any other value — including a hash of an entry that has since changed
    visually — fails.
    """
    if not stored:
        return False
    return stored in (
        slide_contract_hash(run_dir, slide_id),
        visual_slide_contract_hash(run_dir, slide_id),
    )


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
        # 双口径:新写入存视觉投影哈希(narration-only 编辑不失效),
        # 旧写入存整条目哈希(更严格)。两者之外一律拒绝。
        if not contract_slide_hash_matches(payload.get("contract_slide_sha256"), run_dir, slide_id):
            return {"valid": False, "reason": "contract_hash_changed", "slide_id": slide_id}
    elif payload.get("schema_version") == LEGACY_CONTRACT_HASH_SCHEMA_VERSION:
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
    reference_policy: str = "",
    reference_status: str = "",
    requested_reference_count: int = 0,
    submitted_reference_count: int = 0,
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
        # 视觉投影哈希:narration-only 编辑(改讲稿文本)不失效已批准图片;
        # 视觉字段或语块-画面映射变化会改变该哈希。
        "contract_slide_sha256": visual_slide_contract_hash(root, slide_id),
        "reference_sha256s": [digest for digest in (sha256_file(path) for path in references) if digest],
        "reference_policy": str(reference_policy or "").strip() or None,
        "reference_status": str(reference_status or "").strip() or None,
        "requested_reference_count": max(0, int(requested_reference_count or 0)),
        "submitted_reference_count": max(0, int(submitted_reference_count or 0)),
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
    reference_policy: str = "",
    reference_status: str = "",
    requested_reference_count: int = 0,
    submitted_reference_count: int = 0,
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
        reference_policy=reference_policy,
        reference_status=reference_status,
        requested_reference_count=requested_reference_count,
        submitted_reference_count=submitted_reference_count,
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


def refresh_provenance_contract_hashes(
    run_dir: str | Path,
    slide_ids: Iterable[str],
    *,
    previous_contract_text: str | None = None,
) -> int:
    """Refresh the whole-file contract hash after a pure topic/order change.

    A v3 payload may only be refreshed while its stored per-slide entry hash
    still matches the current entry, so real per-slide edits can never be
    whitewashed.  Legacy v2 payloads have no per-slide hash and are refreshed
    only when the caller proves the entry text is byte-identical to the
    previous contract via ``previous_contract_text``.
    """
    from pipeline_lifecycle import read_json_file, write_json_atomic

    contract_hash = sha256_file(planning_path(run_dir, "visual_contract.json"))
    previous_entry_hashes: dict[str, str] | None = None
    if previous_contract_text is not None:
        try:
            previous = json.loads(previous_contract_text)
        except json.JSONDecodeError:
            previous = None
        slides = previous.get("slides") if isinstance(previous, dict) else None
        if not isinstance(slides, list):
            return 0
        previous_entry_hashes = slide_entry_hashes(slides)
    changed = 0
    for slide_id in slide_ids:
        path = provenance_path(run_dir, str(slide_id))
        payload = read_json_file(path)
        if not isinstance(payload, dict):
            continue
        image_path = slide_dir(run_dir, str(slide_id)) / "visual_draft.png"
        if payload.get("output_sha256") != sha256_file(image_path):
            continue
        schema = payload.get("schema_version")
        if schema == PROVENANCE_SCHEMA_VERSION:
            # 双口径接受(新=投影哈希,旧=整条目哈希),再整体刷新 whole-file 哈希;
            # 逐页哈希不匹配(真实编辑)仍拒绝刷新。
            if not contract_slide_hash_matches(payload.get("contract_slide_sha256"), run_dir, str(slide_id)):
                continue
        elif schema == LEGACY_CONTRACT_HASH_SCHEMA_VERSION:
            if previous_entry_hashes is None:
                continue
            if previous_entry_hashes.get(str(slide_id)) != slide_contract_hash(run_dir, str(slide_id)):
                continue
        else:
            continue
        payload["contract_sha256"] = contract_hash
        write_json_atomic(path, payload)
        changed += 1
    return changed


def _contract_slides_from_payload(contract: Any) -> dict[str, dict]:
    slides = contract.get("slides") if isinstance(contract, dict) else None
    if not isinstance(slides, list):
        return {}
    return {
        str(slide.get("slide_id")): slide
        for slide in slides
        if isinstance(slide, dict) and slide.get("slide_id") is not None
    }


def refresh_provenance_for_contract_impact(
    run_dir: str | Path,
    previous_contract: Any,
    *,
    visual_slide_ids: Iterable[str],
    narration_slide_ids: Iterable[str],
    added_slide_ids: Iterable[str] = (),
) -> int:
    """Impact-aware entry point for the contract save paths.

    Narrows :func:`refresh_provenance_for_narration_only_changes` to slides
    that only changed narration (visual/added slides legitimately invalidate
    their images and must not be migrated).
    """
    visual = {str(value).strip() for value in visual_slide_ids if str(value).strip()}
    added = {str(value).strip() for value in added_slide_ids if str(value).strip()}
    narration_only = tuple(
        str(value).strip()
        for value in narration_slide_ids
        if str(value).strip() and str(value).strip() not in visual and str(value).strip() not in added
    )
    if not narration_only:
        return 0
    return refresh_provenance_for_narration_only_changes(
        run_dir, narration_only, previous_contract=previous_contract
    )


def refresh_provenance_for_narration_only_changes(
    run_dir: str | Path,
    slide_ids: Iterable[str],
    *,
    previous_contract: Any,
) -> int:
    """Migrate per-slide provenance hashes after a narration-only Step 2 edit.

    Called from the contract save paths with the exact ``previous_contract``
    they diffed against.  All three evidences must hold before a payload's
    ``contract_slide_sha256`` is rewritten to the current visual projection:

    1. the stored hash equals the *previous* whole-entry hash (nothing else
       edited the slide entry since image confirmation);
    2. the visual projection is byte-identical between the previous and the
       current entry (proving this edit truly only changed narration text);
    3. the current image bytes still match ``output_sha256``.

    A real visual edit changes evidence 2 and can never be whitewashed; a
    payload edited elsewhere fails evidence 1.
    """
    from pipeline_lifecycle import read_json_file, write_json_atomic

    previous_by_id = _contract_slides_from_payload(previous_contract)
    if not previous_by_id:
        return 0
    previous_entry = slide_entry_hashes(previous_by_id.values())
    previous_visual = visual_slide_entry_hashes(previous_by_id.values())
    current_by_id = {
        str(slide_id): visual_slide_contract_hash(run_dir, str(slide_id))
        for slide_id in slide_ids
    }
    changed = 0
    for slide_id in slide_ids:
        slide_key = str(slide_id)
        path = provenance_path(run_dir, slide_key)
        payload = read_json_file(path)
        if not isinstance(payload, dict) or payload.get("schema_version") != PROVENANCE_SCHEMA_VERSION:
            continue
        if payload.get("contract_slide_sha256") != previous_entry.get(slide_key):
            continue
        if not previous_visual.get(slide_key) or previous_visual[slide_key] != current_by_id.get(slide_key):
            continue
        image_path = slide_dir(run_dir, slide_key) / "visual_draft.png"
        if not payload.get("output_sha256") or payload.get("output_sha256") != sha256_file(image_path):
            continue
        payload["contract_slide_sha256"] = current_by_id[slide_key]
        payload["contract_sha256"] = sha256_file(planning_path(run_dir, "visual_contract.json"))
        write_json_atomic(path, payload)
        changed += 1
    return changed


def confirm_reused_slide_image(run_dir: str | Path, slide_id: str) -> bool:
    """Align per-slide provenance with the current contract after a reuse decision.

    The reuse decision is the user's explicit confirmation that the existing
    image still represents the current slide; once the image bytes are
    unchanged, the per-slide hash is realigned to the current visual
    projection so the render gate stops rejecting it.
    """
    from pipeline_lifecycle import read_json_file, write_json_atomic

    path = provenance_path(run_dir, str(slide_id))
    payload = read_json_file(path)
    if not isinstance(payload, dict) or payload.get("schema_version") != PROVENANCE_SCHEMA_VERSION:
        return False
    image_path = slide_dir(run_dir, str(slide_id)) / "visual_draft.png"
    if not payload.get("output_sha256") or payload.get("output_sha256") != sha256_file(image_path):
        return False
    projected = visual_slide_contract_hash(run_dir, str(slide_id))
    if not projected:
        return False
    payload["contract_slide_sha256"] = projected
    payload["contract_sha256"] = sha256_file(planning_path(run_dir, "visual_contract.json"))
    write_json_atomic(path, payload)
    return True
