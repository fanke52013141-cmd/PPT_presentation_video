"""Read-only workflow observations using source-owned artifact and decision checks."""

import json
import os
from typing import Any

from artifact_fingerprint import sha256_file, sha256_json
from one_click_resume_policy import inspect_stage_artifacts, slide_ids
from project_impact_service import list_impacts
from project_storage import safe_child, safe_identifier
from tts_artifacts import artifact_hashes
from agent_contract.domains.workflow import ProjectStateResult


# Visible positions are stable; API/internal artifact stages retain their IDs.
VISIBLE_STAGES = (
    ("article", (1,), ("preflight",)),
    ("storyboard", (2,), ("storyboard",)),
    ("images", (3, 4), ("images", "confirm_images")),
    ("mask", (5,), ("ai_mask",)),
    ("audio", (6, 7), ("narration", "tts")),
    ("annotations", (10,), ()),
    ("digital_human", (9,), ()),
    ("output", (8,), ()),
)


def inspect_project_state(project: Any, *, annotation: dict, digital_human_enabled: bool,
                          render_submission: dict, active_jobs: list[str], authorized_capabilities: set[str]) -> dict:
    """No transitions, repairs, generation, commits or persistence on reads."""
    root = project.run_dir
    identities = slide_ids(project)
    for identity in identities:
        safe_identifier(identity, label="slide_id")
    statuses = project.get_step_status()
    mask_enabled = getattr(project, "presentation_mode", "full_frame") == "reveal"
    stages = []
    for number, (identity, internal, validators) in enumerate(VISIBLE_STAGES, 1):
        skipped = (identity == "mask" and not mask_enabled) or (identity == "digital_human" and not digital_human_enabled)
        checks = {stage: inspect_stage_artifacts(project, stage) for stage in validators} if not skipped else {}
        stage = {"id": identity, "visible_step": number, "internal_steps": list(internal),
                 "required": identity != "digital_human" and not (identity == "mask" and skipped), "skipped": skipped,
                 "recorded_status": {str(key): statuses.get(str(key), "pending") for key in internal},
                 "checks": checks}
        if identity == "annotations":
            stage["module_state"] = annotation["module_state"]
            stage["skipped"] = annotation["module_state"] == "no_annotations"
        stages.append(stage)
    versions = {}
    for relative in (
        "inputs/article.md", "planning/visual_contract.json", "planning/slide_script_plan.json",
        "planning/narration_beats.json", "planning/audio_confirmed.json", "reveal_manifest.json",
        "planning/annotation_settings.json", "planning/digital_human.json",
    ):
        versions[relative] = sha256_file(safe_child(root, relative))
    for identity in identities:
        for filename in ("visual_draft.png", "annotations.json", "annotation_timeline.json"):
            relative = f"slides/{identity}/{filename}"
            versions[relative] = sha256_file(safe_child(root, relative))
        for key, digest in artifact_hashes(root, identity).items():
            versions[f"audio:{identity}:{key}"] = digest
    revision = int(getattr(project, "revision", 0) or 0)
    arguments = {"project_id": project.id}
    actions = [{"capability_id": identity, "arguments": arguments} for identity in (
        "project.get", "artifacts.list", "operation.list",
    )]
    actions.extend([
        {"capability_id": "project.update", "arguments": {**arguments, "expected_revision": revision}, "requires_input": True},
        {"capability_id": "source.set", "arguments": arguments, "requires_input": True},
    ])
    if not active_jobs:
        actions.append({"capability_id": "project.delete", "arguments": {**arguments, "expected_revision": revision}})
    if render_submission["can_submit"] and annotation["readiness"]["can_render"] and not active_jobs:
        actions.append({"capability_id": "video.render", "arguments": arguments})
    impacts = [{key: item[key] for key in ("id", "reason", "scope", "scope_id", "affected", "generation", "status", "decision", "policy") if key in item}
               for item in list_impacts(root)]
    result = {"project_id": project.id, "revision": revision, "resource_versions": versions,
              "stages": stages, "render_submission": {**render_submission, "annotation_readiness": annotation["readiness"],
                                                       "active_jobs": active_jobs},
              "pending_impacts": impacts, "allowed_actions": [action for action in actions if action["capability_id"] in authorized_capabilities]}
    result = ProjectStateResult(observation_revision="", **result).model_dump()
    result["observation_revision"] = sha256_json({key: value for key, value in result.items() if key != "observation_revision"})
    return result


def preview_storyboard_change(project: Any, *, proposed_contract: dict) -> dict:
    """Read-only what-if impact preview for a Step 2 contract edit.

    复用与提交路径完全相同的纯差分函数，不落盘、不登记影响、不提交；
    输出与 storyboard_contract_changed 实际会失效的范围一致。
    """
    from storyboard_contract_diff import diff_storyboard_contracts
    from visual_contract_service import (
        contract_canonical_sha256,
        normalize_visual_contract,
    )

    contract_path = os.path.join(project.run_dir, "planning", "visual_contract.json")
    stored = {}
    if os.path.exists(contract_path):
        with open(contract_path, "r", encoding="utf-8") as file:
            stored = json.load(file)
    if not stored:
        return {
            "success": False,
            "message": "尚未生成分镜合约，无可对比基线",
        }
    current = normalize_visual_contract(stored, None)
    proposed = normalize_visual_contract(proposed_contract, None)
    impact = diff_storyboard_contracts(current, proposed)
    unchanged = contract_canonical_sha256(current) == contract_canonical_sha256(proposed)
    return {
        "success": True,
        "changed": not unchanged,
        "current_contract_sha256": contract_canonical_sha256(current),
        "impact": {
            "visual_slide_ids": list(impact.visual_slide_ids),
            "narration_slide_ids": list(impact.narration_slide_ids),
            "added_slide_ids": list(impact.added_slide_ids),
            "removed_slide_ids": list(impact.removed_slide_ids),
            "reordered": impact.reordered,
        },
        "expected_invalidation": {
            "slide_images": sorted(set(impact.visual_slide_ids) | set(impact.added_slide_ids)),
            "narration_sources": sorted(set(impact.narration_slide_ids) | set(impact.added_slide_ids)),
            "masks_and_reveal_assets": not unchanged,
            "remotion_props": not unchanged,
        },
    }
