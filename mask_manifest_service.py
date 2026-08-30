"""Step 5 Mask semantic blocks, Manifest lifecycle, and Reveal asset builds."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
import subprocess
from typing import Any, Callable, Dict, List, Optional

from canvas_profile_service import get_project_canvas
from runtime_support import run_subprocess_killable


logger = logging.getLogger("PPTStudio.MaskManifest")


class MaskManifestError(RuntimeError):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _not_configured(*_args: Any, **_kwargs: Any) -> Any:
    raise RuntimeError("Mask Manifest dependencies have not been configured")


@dataclass(frozen=True)
class MaskManifestDependencies:
    normalize_visual_type: Callable[..., str]
    reveal_lock_for: Callable[..., Any]
    read_contract_slide_ids: Callable[[str], List[str]]
    sync_reveal_manifest_to_contract: Callable[..., bool]
    storage_slide_file: Callable[..., Any]
    write_json_atomic: Callable[..., Any]
    handle_step_navigation: Callable[..., Any]
    sync_project_background_color: Callable[..., Any]
    write_project_log: Callable[..., Any]
    apply_storyboard_background: Callable[..., Any]
    repo_root: Path
    python_executable: str
    build_timeout_sec: float
    validation_timeout_sec: float = 120.0


_dependencies: MaskManifestDependencies | None = None


def configure_mask_manifest_dependencies(
    dependencies: MaskManifestDependencies,
) -> None:
    global _dependencies
    _dependencies = dependencies


def _deps() -> MaskManifestDependencies:
    # 未配置即快速失败（审查 L-08）：不再返回 repo_root="." 的静默默认值，
    # 避免配置遗漏表现为诡异的子进程失败。
    if _dependencies is None:
        raise RuntimeError("Mask Manifest dependencies have not been configured")
    return _dependencies


NARRATION_SPLIT_DELIMITERS = set("，,。.!！；;？?")
QUOTE_PAIRS = {
    "“": "”",
    "‘": "’",
    "《": "》",
    "「": "」",
    "『": "』",
    "（": "）",
    "(": ")",
    "[": "]",
    "【": "】",
    "{": "}",
}
INLINE_QUOTE_MARKS = {"`", '"'}

ROLE_LABELS = {
    "title": "主标题",
    "subtitle": "副标题",
    "summary": "总结区",
    "diagram": "图示",
    "annotation": "注释",
    "decoration": "装饰元素",
    "content_body": "正文内容",
}


def role_label(role: str) -> str:
    return ROLE_LABELS.get(str(role or "").strip(), "正文内容")


def split_narration_text(text: str) -> List[str]:
    value = str(text or "").strip()
    if not value:
        return []
    parts: List[str] = []
    stack: List[str] = []
    start = 0
    for index, character in enumerate(value):
        if character in INLINE_QUOTE_MARKS:
            if stack and stack[-1] == character:
                stack.pop()
            else:
                stack.append(character)
        elif character in QUOTE_PAIRS:
            stack.append(QUOTE_PAIRS[character])
        elif stack and character == stack[-1]:
            stack.pop()

        is_decimal_point = (
            character == "."
            and index > 0
            and index + 1 < len(value)
            and value[index - 1].isdigit()
            and value[index + 1].isdigit()
        )
        should_split = (
            character == "\n"
            or (
                character in NARRATION_SPLIT_DELIMITERS
                and not stack
                and not is_decimal_point
            )
        )
        if should_split:
            end = index + 1
            parts.append(value[start:end].strip())
            start = end
    if start < len(value):
        parts.append(value[start:].strip())
    return [part for part in parts if part]


def build_narration_fragments(
    contract_slide: Dict[str, Any],
) -> List[Dict[str, Any]]:
    fragments: List[Dict[str, Any]] = []
    for beat_index, beat in enumerate(
        contract_slide.get("narration_beats", []) or []
    ):
        if not isinstance(beat, dict):
            continue
        beat_id = str(beat.get("id") or f"beat_{beat_index + 1}").strip()
        group_id = str(beat.get("group_id") or "").strip()
        texts = split_narration_text(str(beat.get("spoken_text", "")))
        for fragment_index, text in enumerate(texts, start=1):
            fragments.append(
                {
                    "id": f"{beat_id}::{fragment_index}",
                    "beat_id": beat_id,
                    "group_id": group_id,
                    "beat_index": beat_index,
                    "fragment_index": fragment_index - 1,
                    "order": len(fragments) + 1,
                    "text": text,
                }
            )
    return fragments


def box_to_xyxy(box: Any) -> List[int]:
    if isinstance(box, dict):
        x = int(round(float(box.get("x", 860))))
        y = int(round(float(box.get("y", 460))))
        width = int(round(float(box.get("w", 200))))
        height = int(round(float(box.get("h", 160))))
        return [x, y, max(x + 1, x + width), max(y + 1, y + height)]
    if isinstance(box, list) and len(box) >= 4:
        return [int(round(float(value))) for value in box[:4]]
    return [860, 460, 1060, 620]


def group_has_paint(group: Dict[str, Any]) -> bool:
    manual_mask = group.get("manual_mask")
    if not isinstance(manual_mask, dict):
        return False
    rle = manual_mask.get("rle")
    if isinstance(rle, dict) and rle.get("encoding") == "row_runs_v1":
        runs = rle.get("runs")
        if isinstance(runs, list):
            for run in runs:
                if not isinstance(run, list) or len(run) < 3:
                    continue
                try:
                    if int(run[2]) > int(run[1]):
                        return True
                except (TypeError, ValueError):
                    continue
    strokes = manual_mask.get("strokes")
    if not isinstance(strokes, list):
        return False
    for stroke in strokes:
        if not isinstance(stroke, dict):
            continue
        mode = str(stroke.get("mode", "")).lower()
        if (
            not stroke.get("eraser")
            and mode != "erase"
            and stroke.get("points")
        ):
            return True
    return False


def semantic_block_payload(
    slide_id: str,
    index: int,
    fragment_ids: List[str],
    visual_group_id: str,
    group: Optional[Dict[str, Any]],
    fragments_by_id: Dict[str, Dict[str, Any]],
    existing_box: Any = None,
    ai_block: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    ai_block = ai_block or {}
    selected_fragments = [
        fragments_by_id[fragment_id]
        for fragment_id in fragment_ids
        if fragment_id in fragments_by_id
    ]
    beat_ids: List[str] = []
    narration_group_ids: List[str] = []
    for fragment in selected_fragments:
        beat_id = str(fragment.get("beat_id") or "")
        narration_group_id = str(fragment.get("group_id") or "")
        if beat_id and beat_id not in beat_ids:
            beat_ids.append(beat_id)
        if narration_group_id and narration_group_id not in narration_group_ids:
            narration_group_ids.append(narration_group_id)

    role = str((group or {}).get("role") or "content_body")
    visible_text = str(
        (group or {}).get("visible_text")
        or ai_block.get("text_label")
        or f"语块 {index}"
    ).strip()
    visual_anchor = str((group or {}).get("visual_anchor") or "").strip()
    visual_type = _deps().normalize_visual_type(
        (group or {}).get("visual_type") or ai_block.get("visual_type"),
        has_text=bool(str((group or {}).get("display_text") or "").strip()),
    )
    prefix = f"{slide_id}_" if slide_id else ""
    element_id = str((group or {}).get("element_id") or "").strip()
    if not element_id:
        element_id = (
            visual_group_id[len(prefix) :]
            if prefix and visual_group_id.startswith(prefix)
            else visual_group_id
        )
    semantic_type = str(
        ai_block.get("semantic_element_type") or role_label(role)
    ).strip()
    visual_description = str(
        ai_block.get("visual_description") or ""
    ).strip()
    if not visual_description:
        if visual_anchor and visible_text:
            visual_description = (
                f"{semantic_type}：画面中可见文字“{visible_text}”，"
                f"位置/形态为{visual_anchor}。"
            )
        elif visual_anchor:
            visual_description = f"{semantic_type}：{visual_anchor}。"
        else:
            visual_description = (
                f"{semantic_type}：请结合 visible_text 和当前页画面"
                "定位对应的可见元素。"
            )
    semantic_note = str(ai_block.get("semantic_note") or "").strip()
    if not semantic_note:
        semantic_note = (
            "建议只涂抹该语块对应的可见元素本体，避开相邻箭头、"
            "装饰线和底部字幕安全区。"
        )
    return {
        "group_id": f"semantic_{slide_id}_{index:02d}",
        "source": "ai_semantic",
        "visual_group_id": visual_group_id,
        "element_id": element_id,
        "role": role,
        "visual_type": visual_type,
        "text_label": visible_text or f"语块 {index}",
        "visual_anchor": visual_anchor,
        "semantic_element_type": semantic_type,
        "visual_description": visual_description,
        "semantic_note": semantic_note,
        "semantic_confidence": ai_block.get("confidence"),
        "narration_beat_id": beat_ids[0] if beat_ids else "",
        "narration_beat_ids": beat_ids,
        "narration_group_id": (
            narration_group_ids[0]
            if narration_group_ids
            else visual_group_id
        ),
        "narration_fragments": [
            {
                "id": fragment["id"],
                "beat_id": fragment.get("beat_id", ""),
                "group_id": fragment.get("group_id", ""),
                "text": fragment.get("text", ""),
            }
            for fragment in selected_fragments
        ],
        "spoken_text": "".join(
            str(fragment.get("text") or "")
            for fragment in selected_fragments
        ),
        "manual_mask": {"color": "", "strokes": []},
        "box": box_to_xyxy(existing_box),
    }


def deterministic_semantic_blocks(
    slide_id: str,
    contract_slide: Dict[str, Any],
    manifest_slide: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    groups = {
        str(group.get("id", "")).strip(): group
        for group in (contract_slide.get("visual_groups") or [])
        if isinstance(group, dict) and str(group.get("id", "")).strip()
    }
    existing_boxes: Dict[str, Any] = {}
    if manifest_slide:
        for field in ("semantic_blocks", "groups"):
            for group in manifest_slide.get(field, []) or []:
                if not isinstance(group, dict):
                    continue
                box = group.get("box")
                for identifier in (
                    group.get("visual_group_id"),
                    group.get("id"),
                    group.get("group_id"),
                ):
                    identifier_text = str(identifier or "").strip()
                    if (
                        identifier_text
                        and identifier_text not in existing_boxes
                    ):
                        existing_boxes[identifier_text] = box

    fragments = build_narration_fragments(contract_slide)
    fragments_by_id = {
        fragment["id"]: fragment for fragment in fragments
    }
    group_to_fragments: Dict[str, List[str]] = {}
    for fragment in fragments:
        group_to_fragments.setdefault(
            str(fragment.get("group_id") or ""), []
        ).append(str(fragment["id"]))

    blocks: List[Dict[str, Any]] = []
    for group_id, group in groups.items():
        if str(group.get("role") or "").strip().lower() == "decoration":
            continue
        fragment_ids = group_to_fragments.get(group_id) or []
        if not fragment_ids:
            continue
        blocks.append(
            semantic_block_payload(
                slide_id,
                len(blocks) + 1,
                fragment_ids,
                group_id,
                group,
                fragments_by_id,
                existing_boxes.get(group_id),
            )
        )
    return blocks


def refresh_reveal_semantic_blocks(
    project: Any,
    requested_slide_id: str = "",
) -> tuple[Dict[str, Any], int]:
    manifest_path = Path(project.run_dir) / "reveal_manifest.json"
    contract_path = (
        Path(project.run_dir) / "planning" / "visual_contract.json"
    )
    if not manifest_path.exists():
        raise MaskManifestError(
            400,
            "Mask 配置文件尚未生成，请先确认图片",
        )
    if not contract_path.exists():
        raise MaskManifestError(
            400,
            "分镜规划不存在，请先生成分镜",
        )

    # 锁内完成 读→改→写 完整临界区：避免与草稿保存并发时基于过期快照
    # 整体回写，静默覆盖用户刚保存的手动 Mask（审查 H-03）。
    with _deps().reveal_lock_for(project):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract_slides = {
            str(slide.get("slide_id", "")).strip(): slide
            for slide in contract.get("slides", [])
            if isinstance(slide, dict)
            and str(slide.get("slide_id", "")).strip()
        }
        target_slides = [
            slide
            for slide in manifest.get("slides", [])
            if isinstance(slide, dict)
            and (
                not requested_slide_id
                or str(slide.get("slide_id", "")).strip()
                == requested_slide_id
            )
            and str(slide.get("slide_id", "")).strip() in contract_slides
        ]
        if requested_slide_id and not target_slides:
            raise MaskManifestError(
                404,
                f"找不到当前页分镜：{requested_slide_id}",
            )

        for manifest_slide in target_slides:
            slide_id = str(manifest_slide.get("slide_id", "")).strip()
            semantic_blocks = deterministic_semantic_blocks(
                slide_id,
                contract_slides[slide_id],
                manifest_slide,
            )
            painted_groups = [
                group
                for group in manifest_slide.get("groups", []) or []
                if isinstance(group, dict) and group_has_paint(group)
            ]
            manifest_slide["semantic_blocks"] = semantic_blocks
            manifest_slide["groups"] = painted_groups
            if semantic_blocks or painted_groups:
                manifest_slide["status"] = (
                    manifest_slide.get("status") or "pending"
                )

        _deps().write_json_atomic(manifest_path, manifest)
    return manifest, len(target_slides)


def semantic_blocks_project(
    project: Any,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    requested_slide_id = str(
        (payload or {}).get("slide_id") or ""
    ).strip()
    manifest, processed_count = refresh_reveal_semantic_blocks(
        project,
        requested_slide_id,
    )
    return {
        "success": True,
        "vision_used": False,
        "processed": processed_count,
        "manifest": manifest,
        "message": "已根据分镜和旁白生成语块；自动 RLE Mask 可继续手动修正。",
    }


def get_step5_result(project: Any) -> Dict[str, Any]:
    manifest_path = Path(project.run_dir) / "reveal_manifest.json"
    if not manifest_path.exists():
        return {
            "success": False,
            "message": "尚未确认图片",
        }
    with _deps().reveal_lock_for(project):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_ids = _deps().read_contract_slide_ids(project.run_dir)
    actual_ids = [
        str(slide.get("slide_id") or "").strip()
        for slide in manifest.get("slides", [])
        if isinstance(slide, dict)
        and str(slide.get("slide_id") or "").strip()
    ]
    missing_ids = [
        slide_id for slide_id in expected_ids if slide_id not in actual_ids
    ]
    stale_ids = [
        slide_id for slide_id in actual_ids if slide_id not in expected_ids
    ]
    reasons: List[str] = []
    if missing_ids:
        reasons.append("missing_contract_slides")
    if stale_ids:
        reasons.append("unreferenced_manifest_slides")
    return {
        "success": True,
        "manifest": manifest,
        "repair": {
            "required": bool(reasons),
            "reasons": reasons,
            "missing_slide_ids": missing_ids,
            "stale_slide_ids": stale_ids,
            "endpoint": f"/api/projects/{project.id}/steps/5/repair",
        },
    }


def repair_step5_result(project: Any) -> Dict[str, Any]:
    manifest_path = Path(project.run_dir) / "reveal_manifest.json"
    if not manifest_path.exists():
        raise MaskManifestError(
            400,
            "尚未确认图片",
        )
    with _deps().reveal_lock_for(project):
        before = manifest_path.read_bytes()
        _deps().sync_reveal_manifest_to_contract(project)
        manifest, processed_count = refresh_reveal_semantic_blocks(project)
        changed = manifest_path.read_bytes() != before
    return {
        "success": True,
        "changed": changed,
        "processed": processed_count,
        "manifest": manifest,
    }


def prune_stale_mask_groups(
    project: Any,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    contract_path = (
        Path(project.run_dir) / "planning" / "visual_contract.json"
    )
    if (
        not contract_path.exists()
        or not isinstance(payload.get("slides"), list)
    ):
        return payload
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(
            "Failed to load visual contract while pruning Mask groups: %s",
            exc,
        )
        return payload

    visual_groups_by_slide = {
        str(slide.get("slide_id") or "").strip(): {
            str(group.get("id") or "").strip()
            for group in slide.get("visual_groups", []) or []
            if isinstance(group, dict)
            and str(group.get("id") or "").strip()
        }
        for slide in contract.get("slides", []) or []
        if isinstance(slide, dict)
    }

    def is_current(
        group: Dict[str, Any],
        visual_group_ids: set[str],
    ) -> bool:
        group_id = str(
            group.get("id") or group.get("group_id") or ""
        ).strip()
        visual_group_id = str(
            group.get("visual_group_id") or ""
        ).strip()
        if (
            group.get("is_static") is True
            or group.get("is_static_header") is True
            or str(group.get("source") or "") == "ai_static_header"
            or group_id == "__static_title_header__"
        ):
            return True
        if group_id.startswith("manual_group_"):
            return True
        if visual_group_id and visual_group_id in visual_group_ids:
            return True
        return group_id in visual_group_ids

    for slide in payload.get("slides", []):
        if not isinstance(slide, dict):
            continue
        slide_id = str(slide.get("slide_id") or "").strip()
        visual_group_ids = visual_groups_by_slide.get(slide_id, set())
        for field in ("semantic_blocks", "groups"):
            groups = slide.get(field)
            if not isinstance(groups, list):
                continue
            slide[field] = [
                group
                for group in groups
                if isinstance(group, dict)
                and is_current(group, visual_group_ids)
            ]
    return payload


def _prepare_manifest_for_save(
    project: Any,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    canvas = get_project_canvas(project)
    reveal_canvas = {
        "width": canvas["width"],
        "height": canvas["height"],
        "background": "#FEFDF9",
        "subtitle_safe_y": canvas["subtitle_safe_zone"]["top"],
    }
    payload["canvas"] = reveal_canvas
    current_slide_ids = _deps().read_contract_slide_ids(project.run_dir)
    if current_slide_ids and isinstance(payload.get("slides"), list):
        by_id = {
            str(slide.get("slide_id") or "").strip(): slide
            for slide in payload.get("slides", [])
            if isinstance(slide, dict)
            and str(slide.get("slide_id") or "").strip()
        }
        payload["slides"] = [
            by_id[slide_id]
            for slide_id in current_slide_ids
            if slide_id in by_id
        ]

    slides = (
        payload.get("slides", [])
        if isinstance(payload.get("slides"), list)
        else []
    )
    for slide in slides:
        if not isinstance(slide, dict):
            continue
        slide_id = str(slide.get("slide_id") or "").strip()
        if not slide_id:
            continue
        slide_path = _deps().storage_slide_file(
            project.run_dir,
            slide_id,
            "visual_draft.png",
        )
        slide["slide_dir"] = str(Path(slide_path).parent.as_posix())
        slide["master"] = "visual_draft.png"
        slide["canvas"] = dict(reveal_canvas)
    return prune_stale_mask_groups(project, payload)


def update_step5_draft(
    project: Any,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    with _deps().reveal_lock_for(project):
        prepared = _prepare_manifest_for_save(project, payload)
        manifest_path = Path(project.run_dir) / "reveal_manifest.json"
        _deps().write_json_atomic(manifest_path, prepared)
    return {"success": True}


def validate_current_reveal_assets(project: Any) -> None:
    dependencies = _deps()
    canvas = get_project_canvas(project)
    with dependencies.reveal_lock_for(project):
        validator = dependencies.repo_root / "scripts" / "validate_reveal_scene.py"
        command = [
            dependencies.python_executable,
            str(validator),
            "--run-dir",
            project.run_dir,
            "--repo-root",
            str(dependencies.repo_root),
            "--width",
            str(canvas["width"]),
            "--height",
            str(canvas["height"]),
        ]
        result = run_subprocess_killable(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout_sec=dependencies.validation_timeout_sec,
        )
        if result.returncode == 124:
            raise MaskManifestError(
                504,
                "Mask 产物校验超时，请重试",
            )
        if result.returncode != 0:
            logger.error(
                "Reveal asset validation failed: %s",
                result.stderr,
            )
            raise MaskManifestError(
                500,
                f"Mask 产物版本或内容校验失败: {result.stderr}",
            )


def build_current_reveal_assets(project: Any) -> None:
    dependencies = _deps()
    with dependencies.reveal_lock_for(project):
        manifest_path = Path(project.run_dir) / "reveal_manifest.json"
        if not manifest_path.exists():
            raise MaskManifestError(
                400,
                "Mask 配置文件不存在",
            )
        dependencies.sync_project_background_color(project)
        build_scene_script = (
            dependencies.repo_root / "scripts" / "build_reveal_scene.py"
        )
        command = [
            dependencies.python_executable,
            str(build_scene_script),
            "--manifest",
            str(manifest_path),
            "--repo-root",
            str(dependencies.repo_root),
        ]
        result = run_subprocess_killable(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout_sec=dependencies.build_timeout_sec,
        )
        if result.returncode == 124:
            dependencies.write_project_log(
                project,
                "step5_reveal_build_timeout",
                timeout_sec=dependencies.build_timeout_sec,
            )
            raise MaskManifestError(
                504,
                "构建 Mask 切层超时，已停止本次任务，请重试",
            )
        if result.returncode != 0:
            logger.error("Build reveal assets failed: %s", result.stderr)
            raise MaskManifestError(
                500,
                f"构建精确 Mask 素材失败: {result.stderr}",
            )
        dependencies.apply_storyboard_background(manifest_path.resolve())
        validate_current_reveal_assets(project)


def update_step5_result(
    project: Any,
    payload: Dict[str, Any],
    *,
    build_assets: bool,
    db: Any,
) -> Dict[str, Any]:
    dependencies = _deps()
    with dependencies.reveal_lock_for(project):
        prepared = _prepare_manifest_for_save(project, payload)
        manifest_path = Path(project.run_dir) / "reveal_manifest.json"
        dependencies.write_json_atomic(manifest_path, prepared)
        built_assets = False
        if build_assets:
            build_current_reveal_assets(project)
            built_assets = True

    dependencies.handle_step_navigation(project, 5, db)
    return {"success": True, "built_assets": built_assets}
