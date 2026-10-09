"""Step 3 prompt, generation, upload, ordering, and confirmation."""

from __future__ import annotations
from runtime_support import run_subprocess_killable

from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
import json
import logging
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import threading
import time
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote
import uuid
from zipfile import ZIP_DEFLATED, ZipFile
from PIL import Image, ImageDraw

from fastapi import HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from ai_mask_contracts import (
    mask_source_marker_path,
    mask_source_raw_path,
    remove_mask_source_pair,
    rename_mask_source_pair,
    resolve_mask_source_master,
    seal_mask_source_pair,
)
from ai_provider_service import (
    enforce_white_image_region,
    is_toapis_image_provider,
    normalize_image_size,
)
import image_generation_errors
from image_generation_errors import (
    CODE_GATEWAY_BUSY,
    CODE_SAVE_FAILED,
    ImageGenerationError,
    ImagePageFailure,
    PHASE_DOWNLOAD,
    classify_image_error,
)
from image_generation_retry import (
    ImageRetryPolicy,
    decide_download_retry,
    decide_retry,
)
from canvas_profile_service import get_canvas_profile, get_project_canvas
from artifact_fingerprint import sha256_file, sha256_json
from image_change_preview import preview_image_change
from config_store import get_setting
from database import ArtifactRecord, Project
from project_path_service import project_or_404
from global_image_style_service import (
    active_style_reference_paths,
    read_style_tokens_data,
    should_send_style_reference_images,
)
from ai_provider_service import ImagePayloadTooLarge
import invalidation_service
import generation_governor
from artifact_registry import record_artifact, remove_artifact_record
from pipeline_lifecycle import read_json_file as read_json_artifact, write_json_atomic
from project_storage import slide_file as storage_slide_file
from project_style_reference_service import (
    can_send_project_references,
    profile_style_prompt,
    project_generate_prompt_for_slide,
    project_reference_paths,
)
from storyboard_prompt_templates import read_prompt_template
from ip_character_service import (
    IP_PROMPT_MARKER,
    ip_character_reference_paths,
    render_ip_character_prompt,
)
from visual_contract_service import normalize_visual_type
from visual_provenance import (
    promote_candidate_provenance,
    provenance_path as visual_provenance_path,
    slide_contract_hash,
    validate_visual_provenance_set,
    visual_provenance_status,
    write_visual_provenance,
)
from repository_paths import (
    STEP3_IMAGE_PROMPT_TEMPLATE_PATH,
)
from repository_paths import REPO_ROOT as REPO_ROOT  # noqa: F401 - public path-registry compatibility export
from project_config_runtime import get_config_value

try:
    from project_config_runtime import project_subtitles_enabled
except ImportError:
    # Older portable editions predate the shared subtitle-switch helper. Keep
    # this one module safely replaceable in those editions: their saved
    # project_config.json / visual_settings.json already contain the same
    # ``subtitle.enabled`` contract.
    def project_subtitles_enabled(project: Any, default: bool = True) -> bool:
        package_value = get_config_value(project, "subtitle.enabled", default)
        enabled = bool(package_value) if isinstance(package_value, bool) else default
        run_dir = getattr(project, "run_dir", None)
        if not isinstance(run_dir, str) or not run_dir.strip():
            return enabled
        try:
            payload = json.loads(
                (Path(run_dir) / "visual_settings.json").read_text(
                    encoding="utf-8-sig"
                )
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return enabled
        style = payload.get("subtitle_style") if isinstance(payload, dict) else None
        if isinstance(style, dict) and isinstance(style.get("enabled"), bool):
            return style["enabled"]
        return enabled


logger = logging.getLogger("PPTStudio.ImageWorkflow")


def archive_current_slide_image(
    project: Any, slide_id: str, *, keep_derivatives: bool = True,
) -> Path | None:
    """Keep the current source image recoverable before replacement or deletion."""
    image_path = Path(storage_slide_file(project.run_dir, slide_id, "visual_draft.png"))
    if not image_path.is_file():
        return None
    archive_dir = (
        Path(project.run_dir) / "recovery" / "images" /
        f"{slide_id}-{uuid.uuid4().hex}"
    )
    archive_dir.mkdir(parents=True, exist_ok=False)
    for source in (
        image_path,
        mask_source_raw_path(image_path),
        mask_source_marker_path(image_path),
        visual_provenance_path(project.run_dir, slide_id),
    ):
        if source.is_file():
            shutil.copy2(source, archive_dir / source.name)
    manifest = read_json_artifact(Path(project.run_dir) / "reveal_manifest.json")
    if isinstance(manifest, dict):
        for entry in manifest.get("slides", []) or []:
            if isinstance(entry, dict) and str(entry.get("slide_id") or "") == slide_id:
                write_json_atomic(archive_dir / "mask_slide.json", entry)
                break
    if keep_derivatives:
        slide_dir = image_path.parent
        for name in (
            "annotations.json", "text_layout.json", "annotation_timeline.json",
            "scene.json", "animation_timeline.json", "reveal_report.json",
            "mask_preview.png",
        ):
            source = slide_dir / name
            if source.is_file():
                shutil.copy2(source, archive_dir / name)
        for name in ("assets", "auto_mask"):
            source = slide_dir / name
            if source.is_dir():
                shutil.copytree(source, archive_dir / name)
    write_json_atomic(archive_dir / "archive.json", {
        "slide_id": slide_id,
        "image_sha256": sha256_file(image_path),
        "keep_derivatives": keep_derivatives,
        "created_at": datetime.now().isoformat(),
    })
    return archive_dir


def get_slide_image_change_preview(project_id: str, slide_id: str, db: Session) -> dict[str, Any]:
    project = project_or_404(db, project_id)
    current_slide_file_or_404(project, slide_id, "visual_draft.png")
    return {"success": True, **preview_image_change(project.run_dir, slide_id)}


def _check_image_change_choice(
    project: Any, slide_id: str, disposition: str, expected_version: str | None,
) -> bool:
    if disposition not in {"keep", "cleanup"}:
        raise HTTPException(status_code=422, detail="图片变更处理方式无效")
    if expected_version and preview_image_change(project.run_dir, slide_id)["version"] != expected_version:
        raise HTTPException(status_code=409, detail="图片或关联素材已变化，请重新查看影响预览")
    return disposition == "keep"


def _image_recovery_dir(project: Any, slide_id: str, archive_id: str) -> Path:
    if not re.fullmatch(rf"{re.escape(slide_id)}-[0-9a-f]{{32}}", archive_id):
        raise HTTPException(status_code=400, detail="图片归档编号无效")
    archive = Path(project.run_dir) / "recovery" / "images" / archive_id
    if not archive.is_dir():
        raise HTTPException(status_code=404, detail="图片归档不存在")
    metadata = read_json_artifact(archive / "archive.json")
    if not isinstance(metadata, dict) or metadata.get("slide_id") != slide_id:
        raise HTTPException(status_code=409, detail="图片归档与当前页面不匹配")
    return archive


def list_slide_image_recovery(project_id: str, slide_id: str, db: Session) -> dict[str, Any]:
    project = project_or_404(db, project_id)
    image_path = Path(current_slide_file_or_404(project, slide_id, "visual_draft.png"))
    root = Path(project.run_dir) / "recovery" / "images"
    items = []
    if root.is_dir():
        for archive in sorted(root.glob(f"{slide_id}-*"), reverse=True):
            if not archive.is_dir() or not re.fullmatch(rf"{re.escape(slide_id)}-[0-9a-f]{{32}}", archive.name):
                continue
            metadata = read_json_artifact(archive / "archive.json")
            if not isinstance(metadata, dict) or metadata.get("slide_id") != slide_id:
                continue
            mask = read_json_artifact(archive / "mask_slide.json")
            annotations = read_json_artifact(archive / "annotations.json")
            items.append({
                "archive_id": archive.name,
                "created_at": metadata.get("created_at"),
                "image_sha256": metadata.get("image_sha256"),
                "mask_groups": len(mask.get("groups") or []) if isinstance(mask, dict) else 0,
                "annotation_items": len(annotations.get("items") or []) if isinstance(annotations, dict) else 0,
            })
    return {
        "success": True,
        "slide_id": slide_id,
        "current_image_sha256": sha256_file(image_path),
        "version": preview_image_change(project.run_dir, slide_id)["version"],
        "items": items,
    }


def image_recovery_overlay(project_id: str, slide_id: str, archive_id: str, db: Session) -> Response:
    project = project_or_404(db, project_id)
    archive = _image_recovery_dir(project, slide_id, archive_id)
    image_path = Path(current_slide_file_or_404(project, slide_id, "visual_draft.png"))
    if not image_path.is_file():
        raise HTTPException(status_code=404, detail="当前图片不存在")
    with Image.open(image_path) as source:
        canvas = source.convert("RGBA")
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    mask = read_json_artifact(archive / "mask_slide.json")
    if isinstance(mask, dict):
        for group in mask.get("groups") or []:
            if not isinstance(group, dict):
                continue
            rle = (group.get("manual_mask") or {}).get("rle") or {}
            if rle.get("encoding") != "row_runs_v1" or (
                int(rle.get("width", canvas.width)) != canvas.width
                or int(rle.get("height", canvas.height)) != canvas.height
            ):
                continue
            for run in rle.get("runs") or []:
                if isinstance(run, list) and len(run) >= 3:
                    y, x1, x2 = (int(run[0]), int(run[1]), int(run[2]))
                    if 0 <= y < canvas.height and x2 > x1:
                        draw.line((max(0, x1), y, min(canvas.width - 1, x2 - 1), y), fill=(244, 106, 56, 90))
    annotations = read_json_artifact(archive / "annotations.json")
    if isinstance(annotations, dict):
        for item in annotations.get("items") or []:
            target = item.get("target") if isinstance(item, dict) else None
            if not isinstance(target, dict):
                continue
            for polygon in target.get("polygons") or []:
                if isinstance(polygon, list) and len(polygon) >= 2:
                    points = [tuple(point[:2]) for point in polygon if isinstance(point, list) and len(point) >= 2]
                    if len(points) >= 2:
                        draw.line(points + [points[0]], fill=(26, 91, 224, 220), width=5)
    result = Image.alpha_composite(canvas, overlay).convert("RGB")
    buffer = BytesIO()
    result.save(buffer, format="PNG")
    return Response(content=buffer.getvalue(), media_type="image/png")


def reuse_slide_image_geometry(project_id: str, slide_id: str, payload: Dict[str, Any], db: Session) -> dict[str, Any]:
    project = project_or_404(db, project_id)
    archive = _image_recovery_dir(project, slide_id, str(payload.get("archive_id") or ""))
    image_path = Path(current_slide_file_or_404(project, slide_id, "visual_draft.png"))
    if not image_path.is_file():
        raise HTTPException(status_code=404, detail="当前图片不存在")
    expected_version = str(payload.get("expected_version") or "")
    if not expected_version:
        raise HTTPException(status_code=428, detail="请先查看当前图片上的复用预览")
    reuse_mask = payload.get("reuse_mask") is True
    reuse_annotations = payload.get("reuse_annotations") is True
    if not (reuse_mask or reuse_annotations):
        raise HTTPException(status_code=422, detail="请选择要复用的 Mask 或勾画")
    archived_mask = read_json_artifact(archive / "mask_slide.json") if reuse_mask else None
    archived_annotations = read_json_artifact(archive / "annotations.json") if reuse_annotations else None
    if reuse_mask and not isinstance(archived_mask, dict):
        raise HTTPException(status_code=404, detail="该归档没有 Mask 数据")
    if reuse_annotations and not isinstance(archived_annotations, dict):
        raise HTTPException(status_code=404, detail="该归档没有勾画数据")
    with Image.open(image_path) as current_image, Image.open(archive / "visual_draft.png") as old_image:
        current_size = current_image.size
        if current_size != old_image.size:
            raise HTTPException(status_code=409, detail="新旧图片尺寸不同，请重新绘制 Mask 和勾画")
    if reuse_mask:
        for group in archived_mask.get("groups") or []:
            if not isinstance(group, dict):
                raise HTTPException(status_code=422, detail="归档 Mask 数据无效")
            rle = (group.get("manual_mask") or {}).get("rle") or {}
            if rle.get("encoding") == "row_runs_v1" and (
                int(rle.get("width", 0)) != current_size[0]
                or int(rle.get("height", 0)) != current_size[1]
            ):
                raise HTTPException(status_code=409, detail="归档 Mask 尺寸与当前图片不匹配")
    with reveal_lock_for(project):
        if preview_image_change(project.run_dir, slide_id)["version"] != expected_version:
            raise HTTPException(status_code=409, detail="图片或关联素材已变化，请重新查看复用预览")
        annotation_path = image_path.parent / "annotations.json"
        parsed_page = None
        if reuse_annotations:
            current_page = read_json_artifact(annotation_path)
            restored = dict(archived_annotations)
            restored["revision"] = max(
                int(restored.get("revision") or 0),
                int(current_page.get("revision") or 0) if isinstance(current_page, dict) else 0,
            ) + 1
            for item in restored.get("items") or []:
                if not isinstance(item, dict):
                    continue
                item["confirmed_inputs"] = None
                status = item.get("status") or {}
                if status.get("content") != "disabled":
                    status["content"] = "draft"
                    status["spatial"] = "needs_review"
                item["status"] = status
                inputs = item.get("inputs") or {}
                inputs["image_hash"] = sha256_file(image_path)
                item["inputs"] = inputs
            from annotation_contracts import AnnotationPage

            issues: list[Any] = []
            parsed_page = AnnotationPage.from_payload(restored, issues, canvas=current_size)
            if issues or parsed_page is None:
                raise HTTPException(status_code=422, detail="归档勾画数据与当前画布不兼容，请手动调整")
        if reuse_mask:
            manifest_path = Path(project.run_dir) / "reveal_manifest.json"
            manifest = read_json_artifact(manifest_path)
            if not isinstance(manifest, dict):
                raise HTTPException(status_code=409, detail="当前 Mask 配置不存在，请先确认图片")
            slide = next((item for item in manifest.get("slides", []) or []
                          if isinstance(item, dict) and str(item.get("slide_id") or "") == slide_id), None)
            if slide is None:
                raise HTTPException(status_code=409, detail="当前 Mask 页面不存在")
            slide["groups"] = archived_mask.get("groups") or []
            slide["semantic_blocks"] = archived_mask.get("semantic_blocks") or []
            slide["status"] = "pending"
            write_json_atomic(manifest_path, manifest)
            invalidation_service.mask_content_changed(project)
        if parsed_page is not None:
            write_json_atomic(annotation_path, parsed_page.to_dict())
            invalidation_service.annotation_content_changed(project, (slide_id,))
        db.commit()
    return {"success": True, "slide_id": slide_id, "mask_draft_restored": reuse_mask,
            "annotation_draft_restored": reuse_annotations}


def _same_effective_slide_image(current_path: Path, candidate_path: Path) -> bool:
    """Compare the image bytes consumed by the static and Mask pipelines.

    A Step 3 upload is normalized to the project canvas before it becomes the
    static slide image.  The Mask pipeline may additionally consume the sealed
    raw sidecar, so a byte match of the PNG master alone is insufficient: a
    newly active (or changed) raw pair can alter the reveal result.
    """
    if sha256_file(current_path) != sha256_file(candidate_path):
        return False
    current_raw = resolve_mask_source_master(current_path)
    candidate_raw = resolve_mask_source_master(candidate_path)
    if (current_raw is None) != (candidate_raw is None):
        return False
    if current_raw is None:
        return True
    return sha256_file(current_raw) == sha256_file(candidate_raw)
STEP3_IMAGE_PROMPTS_FILE = "step3_image_prompts.json"
MAX_IMAGE_UPLOAD_BYTES = int(
    os.environ.get(
        "PPT_STUDIO_MAX_IMAGE_UPLOAD_BYTES",
        str(20 * 1024 * 1024),
    )
)

# This package reserves the subtitle band as part of its teaching-page layout,
# even when a legacy project-level subtitle switch is off.
XIAXIAOHUA_CREATION_CONFIG_PACKAGE_ID = "d086a3590bb34b8eb22a46d2e0ce2380"


def _not_configured(*_args: Any, **_kwargs: Any) -> Any:
    raise RuntimeError("Image workflow dependencies have not been configured")


all_current_slide_images_exist: Callable[..., Any] = _not_configured
current_slide_file_or_404: Callable[..., Any] = _not_configured
extract_image_bytes_from_response: Callable[..., Any] = _not_configured
generate_image_response: Callable[..., Any] = _not_configured
get_openai_client: Callable[..., Any] = _not_configured
handle_step_navigation: Callable[..., Any] = _not_configured
mark_slide_image_changed: Callable[..., Any] = _not_configured
process_and_save_image: Callable[..., Any] = _not_configured
read_current_slide_ids_or_404: Callable[..., Any] = _not_configured
read_json_file: Callable[..., Any] = _not_configured
refresh_reveal_semantic_blocks: Callable[..., Any] = _not_configured
reveal_lock_for: Callable[..., Any] = _not_configured
sync_reveal_manifest_to_contract: Callable[..., Any] = _not_configured
write_project_log: Callable[..., Any] = _not_configured
resolve_model_connection: Callable[..., Any] = _not_configured
get_credential: Callable[..., Any] = _not_configured


@dataclass(frozen=True)
class ImageWorkflowDependencies:
    all_current_slide_images_exist: Callable[..., Any]
    current_slide_file_or_404: Callable[..., Any]
    extract_image_bytes_from_response: Callable[..., Any]
    generate_image_response: Callable[..., Any]
    get_openai_client: Callable[..., Any]
    handle_step_navigation: Callable[..., Any]
    mark_slide_image_changed: Callable[..., Any]
    process_and_save_image: Callable[..., Any]
    read_current_slide_ids_or_404: Callable[..., Any]
    read_json_file: Callable[..., Any]
    refresh_reveal_semantic_blocks: Callable[..., Any]
    reveal_lock_for: Callable[..., Any]
    sync_reveal_manifest_to_contract: Callable[..., Any]
    write_project_log: Callable[..., Any]
    resolve_model_connection: Callable[..., Any] = _not_configured
    get_credential: Callable[..., Any] = _not_configured


def configure_image_workflow_dependencies(
    dependencies: ImageWorkflowDependencies,
) -> None:
    global all_current_slide_images_exist
    global current_slide_file_or_404
    global extract_image_bytes_from_response
    global generate_image_response
    global get_openai_client
    global handle_step_navigation
    global mark_slide_image_changed
    global process_and_save_image
    global read_current_slide_ids_or_404
    global read_json_file
    global refresh_reveal_semantic_blocks
    global reveal_lock_for
    global sync_reveal_manifest_to_contract
    global write_project_log
    global resolve_model_connection
    global get_credential
    all_current_slide_images_exist = dependencies.all_current_slide_images_exist
    current_slide_file_or_404 = dependencies.current_slide_file_or_404
    extract_image_bytes_from_response = dependencies.extract_image_bytes_from_response
    generate_image_response = dependencies.generate_image_response
    get_openai_client = dependencies.get_openai_client
    handle_step_navigation = dependencies.handle_step_navigation
    mark_slide_image_changed = dependencies.mark_slide_image_changed
    process_and_save_image = dependencies.process_and_save_image
    read_current_slide_ids_or_404 = dependencies.read_current_slide_ids_or_404
    read_json_file = dependencies.read_json_file
    refresh_reveal_semantic_blocks = dependencies.refresh_reveal_semantic_blocks
    reveal_lock_for = dependencies.reveal_lock_for
    sync_reveal_manifest_to_contract = dependencies.sync_reveal_manifest_to_contract
    write_project_log = dependencies.write_project_log
    resolve_model_connection = dependencies.resolve_model_connection
    get_credential = dependencies.get_credential


def _connection_value(connection: Any, name: str, default: Any = None) -> Any:
    if isinstance(connection, dict):
        return connection.get(name, default)
    return getattr(connection, name, default)


def _credential_value(values: Any, *names: str) -> str:
    if not isinstance(values, dict):
        return ""
    normalized = {
        str(key).replace("-", "_").lower(): value
        for key, value in values.items()
    }
    for name in names:
        value = normalized.get(name.replace("-", "_").lower())
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _redact_runtime_secrets(value: Any, secrets: Any) -> str:
    text = str(value)
    if isinstance(secrets, dict):
        for secret in secrets.values():
            if isinstance(secret, str) and secret:
                text = text.replace(secret, "[REDACTED]")
    return text


def _project_image_runtime(project: Project) -> Optional[Dict[str, Any]]:
    """Resolve a project-pinned image connection without exposing its secret."""
    binding = get_config_value(
        project,
        "model_bindings.image_generation",
        None,
    )
    if not isinstance(binding, dict):
        return None
    connection_id = str(binding.get("connection_id") or "").strip()
    if not connection_id:
        raise HTTPException(status_code=400, detail="项目图片模型连接配置无效。")
    try:
        connection = resolve_model_connection(connection_id, None)
    except Exception as exc:
        logger.warning("Project image connection cannot be resolved: %s", type(exc).__name__)
        raise HTTPException(status_code=400, detail="项目图片模型连接不可用。") from exc
    if _connection_value(connection, "kind") != "image":
        raise HTTPException(status_code=400, detail="项目图片模型连接类型不正确。")
    credential_ref = _connection_value(connection, "credential_ref")
    if not isinstance(credential_ref, str) or not credential_ref:
        raise HTTPException(status_code=400, detail="项目图片模型连接缺少凭据。")
    try:
        secrets = get_credential(credential_ref)
    except Exception as exc:
        logger.warning("Project image credential is unavailable: %s", type(exc).__name__)
        raise HTTPException(status_code=400, detail="项目图片模型凭据不可用。") from exc
    api_key = _credential_value(secrets, "api_key", "access_token", "token", "key")
    if not api_key:
        raise HTTPException(status_code=400, detail="项目图片模型凭据缺少 API Key。")
    public_config = _connection_value(connection, "public_config", {})
    public_config = public_config if isinstance(public_config, dict) else {}
    return {
        "api_key": api_key,
        "base_url": _connection_value(connection, "endpoint") or "",
        "model": str(_connection_value(connection, "model") or "").strip(),
        "provider": str(_connection_value(connection, "provider") or "openai_compatible"),
        "image_size": (
            public_config.get("image_size") or public_config.get("size")
        ),
        "public_config": public_config,
        "secrets": secrets,
    }


def _image_reference_policy(project: Project) -> dict[str, Any]:
    value = get_config_value(project, "image_style", {})
    value = value if isinstance(value, dict) else {}
    policy = str(value.get("reference_policy") or "preferred").strip().lower()
    if policy not in {"required", "preferred", "text_only"}:
        policy = "preferred"
    try:
        minimum = int(value.get("minimum_reference_images", 1))
    except (TypeError, ValueError):
        minimum = 1
    minimum = max(0, min(3, minimum))
    if policy == "required":
        minimum = max(1, minimum)
    elif policy == "text_only":
        minimum = 0
    return {"policy": policy, "minimum": minimum}


def _project_requires_subtitle_safe_zone(project: Any) -> bool:
    """Return whether this project's image pixels must leave the caption band blank.

    The 夏晓华 creation package treats the band as a fixed page-layout safety
    boundary. Preserve an explicit subtitle-off full-frame layout for every
    other package.
    """
    return project_subtitles_enabled(project) or (
        str(getattr(project, "creation_config_package_id", "") or "").strip()
        == XIAXIAOHUA_CREATION_CONFIG_PACKAGE_ID
    )


def _enforce_project_subtitle_safe_zone(
    project: Project,
    slide_id: str,
    image_path: str,
    *,
    source: str,
) -> None:
    """Deterministically clear the required caption band after image writes."""
    if not _project_requires_subtitle_safe_zone(project):
        logger.info(
            "Subtitle-safe zone is disabled for %s image: slide=%s; retaining the full PPT image.",
            source,
            slide_id,
        )
        return
    canvas = get_project_canvas(project)
    safe_zone = canvas.get("subtitle_safe_zone") or get_canvas_profile(
        getattr(project, "canvas_profile", None)
    )["subtitle_safe_zone"]
    subtitle_report = enforce_white_image_region(
        image_path,
        top=safe_zone["top"],
        bottom=safe_zone["bottom"],
    )
    # The raw sidecar must stay a pixel-exact superset of the master: keep the
    # locked caption band cleared in both files or the pair diverges.
    raw_path = mask_source_raw_path(Path(image_path))
    if raw_path.exists():
        enforce_white_image_region(
            str(raw_path),
            top=safe_zone["top"],
            bottom=safe_zone["bottom"],
        )
    if subtitle_report["nonwhite_ratio"] > 0.005:
        logger.warning(
            "%s image entered locked subtitle-safe zone: slide=%s ratio=%.4f; region was cleared",
            source.capitalize(),
            slide_id,
            subtitle_report["nonwhite_ratio"],
        )
    else:
        logger.info(
            "Subtitle-safe zone enforced for %s image: slide=%s ratio=%.4f",
            source,
            slide_id,
            subtitle_report["nonwhite_ratio"],
        )


def _image_reference_capability(
    model: str,
    base_url: str,
    public_config: dict[str, Any],
    reference_paths: List[str],
) -> tuple[bool, int]:
    explicit = public_config.get("supports_reference_images")
    if isinstance(explicit, bool):
        supported = explicit
    else:
        supported = can_send_project_references(model, base_url, reference_paths)
    try:
        maximum = int(public_config.get("max_reference_images", 3))
    except (TypeError, ValueError):
        maximum = 3
    return supported, max(1, min(6, maximum))


def step3_image_prompts_path(project: Project) -> str:
    return os.path.join(project.run_dir, "planning", STEP3_IMAGE_PROMPTS_FILE)


def default_step3_image_system_content() -> str:
    return read_prompt_template(STEP3_IMAGE_PROMPT_TEMPLATE_PATH)


def read_step3_image_system_content(project: Project) -> str:
    default_value = default_step3_image_system_content()
    stored = read_json_file(step3_image_prompts_path(project), {})
    if isinstance(stored, str):
        value = stored.strip()
    elif isinstance(stored, dict):
        value = str(stored.get("system_content") or "").strip()
    else:
        value = ""
    return value or default_value


def write_step3_image_system_content(project: Project, system_content: str) -> None:
    if read_step3_image_system_content(project) == system_content:
        return
    write_json_atomic(
        step3_image_prompts_path(project),
        {
            "version": "step3_image_prompt_settings_v1",
            "system_content": system_content,
        },
    )


def step3_image_input_contract() -> Dict[str, Any]:
    return {
        "slide_id": "仅用于区分任务，不会作为画面文字",
        "main_title": "唯一主标题，必须准确呈现",
        "body_elements": [
            {
                "type": "text 或 picture",
                "content": "必须呈现的正文文字，或必须落实的可视化描述",
            }
        ],
    }


def step3_image_input_example() -> Dict[str, Any]:
    return {
        "slide_id": "slide_003",
        "main_title": "为什么要拆分 Token？",
        "body_elements": [
            {"type": "picture", "content": "左侧展示一句中文被切分成彩色 Token 积木"},
            {"type": "text", "content": "模型按 Token 计算，而不是直接读取文字"},
        ],
    }


def step3_image_example_slide() -> Dict[str, Any]:
    example = step3_image_input_example()
    groups = []
    for item in example["body_elements"]:
        visual_type = str(item.get("type") or "picture")
        content = str(item.get("content") or "")
        groups.append(
            {
                "role": "content_body",
                "visual_type": visual_type,
                "display_text": content if visual_type == "text" else "",
                "visual_anchor": content,
            }
        )
    return {
        "slide_id": example["slide_id"],
        "main_title": example["main_title"],
        "visual_groups": groups,
    }


# 辅助生成某一页 PPT 生图的 Prompt。
def step3_slide_input_payload(slide: Dict[str, Any]) -> Dict[str, Any]:
    slide_id = str(slide.get("slide_id") or "").strip()
    main_title = str(slide.get("main_title") or "").strip()
    body_elements: List[Dict[str, str]] = []
    for group in slide.get("visual_groups", []) or []:
        if not isinstance(group, dict):
            continue
        role = str(group.get("role") or "content_body").strip().lower()
        if role == "title":
            continue
        visual_type = normalize_visual_type(
            group.get("visual_type"),
            has_text=bool(str(group.get("display_text") or "").strip()),
        )
        if visual_type == "text":
            content = str(
                group.get("display_text")
                or group.get("visible_text")
                or group.get("visual_anchor")
                or ""
            ).strip()
        else:
            content = str(
                group.get("visual_anchor")
                or group.get("mask_target")
                or group.get("visible_text")
                or ""
            ).strip()
        if content:
            body_elements.append({"type": visual_type, "content": content})
    return {
        "slide_id": slide_id,
        "main_title": main_title,
        "body_elements": body_elements,
    }


def compact_slide_element_lines(slide: Dict[str, Any]) -> List[str]:
    payload = step3_slide_input_payload(slide)
    return [
        f"- [{item['type']}] {item['content']}" for item in payload["body_elements"]
    ]


def _canvas_for_value(canvas_profile: Any = None) -> Dict[str, Any]:
    return (
        get_project_canvas(canvas_profile)
        if hasattr(canvas_profile, "canvas_profile")
        else get_canvas_profile(canvas_profile)
    )


def adapt_step3_system_content_for_canvas(
    system_content: str,
    canvas_profile: Any = None,
) -> str:
    """Adapt the built-in production-area wording without changing legacy prompts."""
    canvas = _canvas_for_value(canvas_profile)
    if canvas["orientation"] != "portrait":
        return str(system_content or "")
    subtitle = canvas["subtitle_safe_zone"]
    content = canvas["content_safe_area"]
    return (
        str(system_content or "")
        .replace("1920×1080、16:9", "1080×1920、9:16")
        .replace("1920×1080 画布", "1080×1920 画布")
        .replace("字幕安全区始终对应画布底部约 14% 的高度区域", "字幕安全区对应画布底部约 14% 的高度区域")
        .replace("`x=80..1840, y=60..210`", "`x=64..1016, y=72..170`")
        .replace("`x=80..1840, y=230..930`", f"`x={content['left']}..{content['right']}, y={content['top']}..{content['bottom']}`")
        .replace("`y=930..1080`", f"`y={subtitle['top']}..{subtitle['bottom']}`")
    )


def build_step3_global_image_prompt(
    style_prompt: str,
    system_content: Optional[str] = None,
    canvas_profile: Any = None,
) -> str:
    return (
        "=== 图片生成 System Content ===\n"
        f"{adapt_step3_system_content_for_canvas(str(system_content or default_step3_image_system_content()).strip(), canvas_profile)}\n\n"
        "=== 当前生效的图片风格 ===\n"
        f"{str(style_prompt or '').strip()}"
    )


def build_step3_slide_specific_prompt(slide: Dict[str, Any]) -> str:
    return "最小单页输入（不要把字段名、类型名或 slide_id 画进页面）：\n" + json.dumps(
        step3_slide_input_payload(slide), ensure_ascii=False, indent=2
    )


def compose_step3_single_slide_prompt(
    style_prompt: str,
    slide: Dict[str, Any],
    system_content: Optional[str] = None,
    ip_prompt_segment: str = "",
    canvas_profile: Any = None,
) -> str:
    prompt = f"{build_step3_global_image_prompt(style_prompt, system_content, canvas_profile)}"
    if ip_prompt_segment:
        prompt += f"\n\n{ip_prompt_segment}"
    prompt += f"\n\n=== 当前 Slide 输入 ===\n{build_step3_slide_specific_prompt(slide)}"
    return enforce_white_generation_background(prompt, canvas_profile)


def compose_step3_batch_copy_prompt(
    style_prompt: str,
    slides: List[Dict[str, Any]],
    system_content: Optional[str] = None,
    ip_prompt_segment: str = "",
    canvas_profile: Any = None,
) -> str:
    slide_sections = []
    for slide in slides:
        if not isinstance(slide, dict):
            continue
        slide_id = str(slide.get("slide_id") or "").strip() or "未命名"
        slide_sections.append(
            f"--- Slide {slide_id} ---\n{build_step3_slide_specific_prompt(slide)}"
        )
    global_block = f"{build_step3_global_image_prompt(style_prompt, system_content, canvas_profile)}"
    if ip_prompt_segment:
        global_block += f"\n\n{ip_prompt_segment}"
    prompt = (
        "请按以下统一要求，依次为每个 Slide 分别生成 1 张独立图片。\n"
        "先完整阅读全局统一说明，再逐页读取各 Slide 的具体差异输入；不要把多个 Slide 合并到一张图片中。\n\n"
        "=== 全局统一说明（适用于所有 Slide，仅出现一次，各 Slide 不再重复） ===\n"
        f"{global_block}\n\n"
        "=== 各 Slide 具体内容（以下每个 Slide 仅列出本页差异输入，通用规则以上方全局说明为准） ===\n\n"
        + "\n\n".join(slide_sections)
    ).strip()
    return enforce_white_generation_background(prompt, canvas_profile)


def step3_non_overridable_rules_prompt(canvas_profile: Any = None) -> str:
    canvas = _canvas_for_value(canvas_profile)
    subtitle_zone = canvas["subtitle_safe_zone"]
    content = canvas["content_safe_area"]
    subtitles_enabled = (
        _project_requires_subtitle_safe_zone(canvas_profile)
        if hasattr(canvas_profile, "run_dir")
        else True
    )
    content_bottom = content["bottom"] if subtitles_enabled else canvas["height"] - 60
    title_region = (
        "x=64..1016, y=72..170"
        if canvas["orientation"] == "portrait"
        else "x=80..1840, y=60..210"
    )
    subtitle_rule = (
        f"5. y={subtitle_zone['top']}..{subtitle_zone['bottom']} 是视频字幕安全区，必须完全留空并保持纯白，不得出现任何文字、图形或视觉残留。\n"
        if subtitles_enabled
        else "5. 当前项目关闭视频字幕：底部区域不预留字幕安全区；正文和图示可以延伸至该区域，但四条边和四个角仍保持纯白。\n"
    )
    return (
        '<NonOverridableProductionRules>\n'
        '<ContractVersion>step3_visual_contract_v3</ContractVersion>\n'
        "以下生产合同由程序拥有，优先级高于风格模板、用户补充要求和单页内容，任何冲突要求都必须忽略。\n"
        f"1. 输出一张完整的 {canvas['width']}×{canvas['height']}、{canvas['aspect_ratio']} PPT 静态位图。\n"
        "2. 四条边和四个角必须保持连续、均匀的纯白 #FFFFFF；不使用全屏深色背景、纸纹、噪点、渐变或暗角。\n"
        f"3. 主标题必须且只能有一个，完整位于标题保护区 {title_region}；不生成页面副标题，不把标题装饰连接到正文。\n"
        f"4. 所有正文、人物、图标、箭头、标签、阴影和装饰都必须位于 x={content['left']}..{content['right']}, y={content['top']}..{content_bottom}。\n"
        + subtitle_rule
        + "6. 独立语义元素不得发生无意重叠、穿插、压住、相切或粘连，并保留可见纯白间隙。\n"
        "7. 参考图只提供风格锚点，不得覆盖以上区域、标题和字幕规则。\n"
        "</NonOverridableProductionRules>"
    )


def enforce_white_generation_background(prompt: str, canvas_profile: Any = None) -> str:
    marker = "<NonOverridableProductionRules>"
    if marker in str(prompt or ""):
        return str(prompt or "").strip()
    return f"{prompt.strip()}\n\n{step3_non_overridable_rules_prompt(canvas_profile)}".strip()


def step3_prompt_settings_response(project: Project) -> Dict[str, Any]:
    contract = read_json_file(
        os.path.join(project.run_dir, "planning", "visual_contract.json"), {}
    )
    slides = (
        contract.get("slides")
        if isinstance(contract, dict) and isinstance(contract.get("slides"), list)
        else []
    )
    first_slide = next((slide for slide in slides if isinstance(slide, dict)), None)
    system_content = read_step3_image_system_content(project)
    style_prompt = profile_style_prompt(project)
    return {
        "success": True,
        "prompts": {
            "system_content": system_content,
            "default_system_content": default_step3_image_system_content(),
            "current_input": step3_slide_input_payload(first_slide)
            if first_slide
            else step3_image_input_example(),
            "input_contract": step3_image_input_contract(),
            "input_example": step3_image_input_example(),
            "output_description": f"一张完整的 {get_project_canvas(project)['width']}×{get_project_canvas(project)['height']}、{get_project_canvas(project)['aspect_ratio']} PPT 位图；无文字说明、JSON、Mask 或备选拼图。",
            "style_content": style_prompt,
            "protected_rules": step3_non_overridable_rules_prompt(project),
            "ip_prompt_segment": render_ip_character_prompt(project, None),
            "full_prompt_example": compose_step3_single_slide_prompt(
                style_prompt,
                first_slide or step3_image_example_slide(),
                system_content,
                render_ip_character_prompt(project, None),
                project,
            ),
        },
    }


def get_step3_prompt_settings(project_id: str, db: Session):
    project = project_or_404(db, project_id)
    return step3_prompt_settings_response(project)


def update_step3_prompt_settings(
    project_id: str,
    payload: Dict[str, Any],
    db: Session,
):
    project = project_or_404(db, project_id)
    prompts = (
        payload.get("prompts") if isinstance(payload.get("prompts"), dict) else payload
    )
    system_content = str(prompts.get("system_content") or "").strip()
    if not system_content:
        raise HTTPException(status_code=400, detail="图片生成 System Content 不能为空")
    if len(system_content) > 40000:
        raise HTTPException(
            status_code=400, detail="图片生成 System Content 不能超过 40000 个字符"
        )
    write_step3_image_system_content(project, system_content)
    return step3_prompt_settings_response(project)


def get_slide_prompts(project_id: str, db: Session):
    project = project_or_404(db, project_id)

    contract_path = os.path.join(project.run_dir, "planning", "visual_contract.json")
    if not os.path.exists(contract_path):
        raise HTTPException(status_code=400, detail="分镜规划尚未生成")

    with open(contract_path, "r", encoding="utf-8") as f:
        contract = json.load(f)

    # 单页生成仍返回完整 Prompt；网页端批量复制另用一份全局说明 + 每页差异内容。
    slide_prompts = []
    slides = [slide for slide in contract.get("slides", []) if isinstance(slide, dict)]
    topic = contract.get("topic") if isinstance(contract.get("topic"), dict) else {}
    topic_name = str(topic.get("topic_name") or project.name or "")
    style_prompt = profile_style_prompt(project)
    system_content = read_step3_image_system_content(project)
    for slide in slides:
        slide_id = slide["slide_id"]
        generated_prompt = project_generate_prompt_for_slide(
            project, slide, topic_name, ip_prompt_segment=render_ip_character_prompt(project, slide_id)
        )
        slide_prompts.append(
            {
                "slide_id": slide_id,
                "title": slide["main_title"],
                "prompt": generated_prompt,
                "slide_prompt": build_step3_slide_specific_prompt(slide),
            }
        )

    return {
        "success": True,
        "prompts": slide_prompts,
        "global_prompt": enforce_white_generation_background(
            build_step3_global_image_prompt(style_prompt, system_content, project), project
        ),
        "batch_prompt": compose_step3_batch_copy_prompt(
            style_prompt, slides, system_content, render_ip_character_prompt(project, None), project
        ),
        "prompt_settings": {
            "system_content": system_content,
            "input_contract": step3_image_input_contract(),
            "input_example": step3_image_input_example(),
            "output_description": f"一张完整的 {get_project_canvas(project)['width']}×{get_project_canvas(project)['height']}、{get_project_canvas(project)['aspect_ratio']} PPT 位图。",
        },
    }


# Per-(project, slide) in-flight guard.  A second request for the same slide
# would otherwise pay the provider twice and interleave writes into the same
# visual_draft.png/visual_candidate.png path (single-process deployment).
_IMAGE_GENERATION_GUARD_LOCK = threading.Lock()
_ACTIVE_IMAGE_GENERATIONS: set[tuple[str, str]] = set()


def claim_slide_image_generation(project_id: str, slide_id: str) -> bool:
    key = (str(project_id), str(slide_id))
    with _IMAGE_GENERATION_GUARD_LOCK:
        if key in _ACTIVE_IMAGE_GENERATIONS:
            return False
        _ACTIVE_IMAGE_GENERATIONS.add(key)
        return True


def release_slide_image_generation(project_id: str, slide_id: str) -> None:
    _ACTIVE_IMAGE_GENERATIONS.discard((str(project_id), str(slide_id)))


def active_slide_image_generation(project_id: str) -> List[str]:
    with _IMAGE_GENERATION_GUARD_LOCK:
        return sorted(
            slide_id
            for pid, slide_id in _ACTIVE_IMAGE_GENERATIONS
            if pid == str(project_id)
        )


# 治理器单次排队等待的上限：既避免一张慢页长期霸占队列，也保证等待
# 不超过该页剩余预算（调用侧取两者较小值）。
_IMAGE_QUEUE_WAIT_CAP_SEC = 120.0


def _governed_reference_edit(
    governor: Any,
    base_url: str,
    client: Any,
    *,
    model: str,
    reference_files: list,
    effective_prompt: str,
    image_size: str,
    queue_wait_seconds: float,
) -> Any:
    """在网关额度内执行一次参考图编辑请求（每次都占用额度）。"""
    with governor.request(
        generation_governor.RESOURCE_IMAGE,
        base_url,
        timeout_sec=queue_wait_seconds,
    ):
        return client.images.edit(
            model=model,
            image=reference_files,
            prompt=effective_prompt,
            size=image_size,
            n=1,
        )


def _extract_image_bytes_with_bounded_retries(
    response: Any,
    *,
    policy: ImageRetryPolicy,
    deadline_monotonic: float,
    slide_id: str,
) -> bytes:
    """提取图片字节：下载失败复用同一结果地址有界重试，不重新生图。

    只有"下载阶段"的可重试错误在此循环内消化；解码/空响应等需要重新生成
    的失败原样上抛，交给页级重试循环决策。
    """
    download_attempt = 0
    while True:
        download_attempt += 1
        try:
            return extract_image_bytes_from_response(response)
        except ImageGenerationError as exc:
            info = exc.info
            if info.phase != PHASE_DOWNLOAD or not info.retryable:
                raise
            verdict = decide_download_retry(
                info,
                attempt=download_attempt,
                policy=policy,
                remaining_sec=deadline_monotonic - time.monotonic(),
            )
            if not verdict.retry:
                raise image_generation_errors.ImageGenerationError(
                    image_generation_errors.ImageGenerationErrorInfo(
                        code=info.code,
                        phase=info.phase,
                        retryable=False,
                        status_code=info.status_code,
                        outcome_unknown=info.outcome_unknown,
                        safe_message=(
                            f"下载生成图片失败（已尝试 {download_attempt} 次下载，"
                            f"生成结果仍可恢复）: {info.safe_message}"
                        ),
                    ),
                    cause=exc,
                )
            logger.warning(
                "Image download for %s failed (download attempt %s/%s, code=%s); retrying in %.1fs",
                slide_id,
                download_attempt,
                policy.max_download_attempts,
                info.code,
                verdict.delay_sec,
            )
            time.sleep(verdict.delay_sec)


def generate_slide_image(
    project_id: str,
    slide_id: str,
    prompt: str,
    preview: bool,
    db: Session,
    *,
    defer_invalidation: bool = False,
    disposition: str = "keep",
    expected_version: str | None = None,
):
    if not claim_slide_image_generation(project_id, slide_id):
        raise HTTPException(
            status_code=409,
            detail=f"{slide_id} 正在生成图片，请等待当前任务完成后再触发。",
        )
    try:
        project = project_or_404(db, project_id)
        image_name = "visual_candidate.png" if preview else "visual_draft.png"
        live_path = Path(current_slide_file_or_404(project, slide_id, image_name))
        live_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="step3-generation-", dir=live_path.parent) as staging_dir:
            return _generate_slide_image_impl(
                project_id, slide_id, prompt, preview, db,
                defer_invalidation=defer_invalidation,
                staging_dir=staging_dir,
                disposition=disposition,
                expected_version=expected_version,
            )
    finally:
        release_slide_image_generation(project_id, slide_id)


def _generate_slide_image_impl(
    project_id: str,
    slide_id: str,
    prompt: str,
    preview: bool,
    db: Session,
    *,
    defer_invalidation: bool = False,
    staging_dir: str,
    disposition: str = "keep",
    expected_version: str | None = None,
):
    project = project_or_404(db, project_id)

    project_runtime = _project_image_runtime(project)
    if project_runtime is None:
        api_key = get_setting("image_api_key")
        base_url = get_setting("image_base_url")
        model = get_setting("image_model", "gpt-image-1")
        image_provider = "openai_compatible"
        runtime_secrets: Dict[str, Any] = {}
        image_public_config: Dict[str, Any] = {}
    else:
        api_key = project_runtime["api_key"]
        base_url = project_runtime["base_url"]
        model = project_runtime["model"]
        image_provider = project_runtime["provider"]
        runtime_secrets = project_runtime["secrets"]
        image_public_config = project_runtime["public_config"]
        if not model:
            raise HTTPException(status_code=400, detail="项目图片模型连接缺少模型名称。")
    image_filename = "visual_candidate.png" if preview else "visual_draft.png"
    live_path = Path(current_slide_file_or_404(project, slide_id, image_filename))
    save_path = str(Path(staging_dir) / image_filename)

    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="未配置生图 API 密钥，请在系统设置中配置，或使用下方本地上传图片功能。",
        )

    is_toapis = is_toapis_image_provider(image_provider, base_url)
    client = None if is_toapis else get_openai_client(api_key=api_key, base_url=base_url)
    canvas = get_project_canvas(project)
    image_size = normalize_image_size(f"{canvas['width']}x{canvas['height']}")
    effective_prompt = enforce_white_generation_background(prompt, project)
    ip_prompt_segment = render_ip_character_prompt(project, slide_id)
    if ip_prompt_segment and IP_PROMPT_MARKER not in effective_prompt:
        effective_prompt = effective_prompt + "\n\n" + ip_prompt_segment
    logger.info(
        f"Generating image for {slide_id} using {model}, size={image_size}, prompt: {effective_prompt[:80]}"
    )

    used_reference_paths: List[str] = []
    reference_policy = _image_reference_policy(project)
    reference_status = "not_requested"
    project_references = project_reference_paths(project)
    if reference_policy["policy"] == "text_only":
        style_reference_paths: List[str] = []
        reference_status = "text_only"
    elif project_references:
        style_reference_paths = list(project_references)
    else:
        style_tokens = read_style_tokens_data()
        style_reference_paths = active_style_reference_paths()
        legacy_style_supported = should_send_style_reference_images(
            model=model,
            base_url=base_url,
            reference_paths=style_reference_paths,
            style_tokens=style_tokens,
        )
        if not legacy_style_supported and reference_policy["policy"] == "preferred":
            style_reference_paths = []
            reference_status = "fallback_text_only"
    if (
        reference_policy["policy"] == "required"
        and len(style_reference_paths) < reference_policy["minimum"]
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "当前创作配置要求使用参考图，但项目参考图不足："
                f"至少 {reference_policy['minimum']} 张，当前 {len(style_reference_paths)} 张。"
            ),
        )
    ip_reference_paths = ip_character_reference_paths(project, slide_id)
    reference_paths = list(style_reference_paths) + list(ip_reference_paths)
    use_reference_images = False
    max_reference_images = 3
    if reference_paths:
        use_reference_images, max_reference_images = _image_reference_capability(
            model, base_url, image_public_config, reference_paths
        )
        if (
            reference_policy["policy"] == "required"
            and max_reference_images < reference_policy["minimum"]
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "当前图片模型最多支持 "
                    f"{max_reference_images} 张参考图，少于创作配置要求的 "
                    f"{reference_policy['minimum']} 张。"
                ),
            )
        reference_paths = reference_paths[:max_reference_images]
    if reference_policy["policy"] == "required" and not use_reference_images:
        raise HTTPException(
            status_code=409,
            detail="当前图片模型未启用参考图能力，请在模型设置中开启后再生成。",
        )
    if reference_paths and not use_reference_images:
        if reference_status == "not_requested":
            reference_status = "fallback_text_only"
        logger.info(
            "Skipping binary style reference images for %s: active references are not compatible with current model/style.",
            slide_id,
        )

    def current_input_version() -> str:
        current_prompt = enforce_white_generation_background(prompt, project)
        current_ip = render_ip_character_prompt(project, slide_id)
        if current_ip and IP_PROMPT_MARKER not in current_prompt:
            current_prompt += "\n\n" + current_ip
        runtime = _project_image_runtime(project)
        return sha256_json({
            "slide_contract": slide_contract_hash(project.run_dir, slide_id),
            "image_state": preview_image_change(project.run_dir, slide_id)["version"],
            "prompt": current_prompt,
            "canvas": get_project_canvas(project),
            "runtime": runtime,
            "references": [sha256_file(path) for path in reference_paths],
        })

    input_version = current_input_version()

    # ── 有界自动重试：只针对单页的"提交/轮询/下载"短暂故障 ──
    # 成功写盘的图片立即保留；配置类错误（HTTPException）不重试；
    # 未知程序错误默认不重试。所有重试共享同一份单页预算。
    retry_policy = ImageRetryPolicy.from_environment()
    page_started_at = time.monotonic()
    page_deadline = page_started_at + retry_policy.total_budget_sec
    attempts = 0
    resume_task_id = ""
    failure: Optional[ImagePageFailure] = None
    while True:
        attempts += 1
        info: Optional[image_generation_errors.ImageGenerationErrorInfo] = None
        try:
            response = None
            if use_reference_images and not is_toapis:
                governor = generation_governor.get_generation_governor()
                remaining_for_edit = max(
                    1.0, page_deadline - time.monotonic()
                )
                reference_files = []
                try:
                    reference_files = [open(path, "rb") for path in reference_paths]
                    # 参考图编辑同样是真实上游请求，必须占用网关额度。
                    response = _governed_reference_edit(
                        governor,
                        base_url,
                        client,
                        model=model,
                        reference_files=reference_files,
                        effective_prompt=effective_prompt,
                        image_size=image_size,
                        queue_wait_seconds=min(
                            remaining_for_edit, _IMAGE_QUEUE_WAIT_CAP_SEC
                        ),
                    )
                    used_reference_paths = list(reference_paths)
                    reference_status = "used"
                    logger.info(
                        "Image generation used %s style reference images.",
                        len(reference_files),
                    )
                except Exception as reference_error:
                    if reference_policy["policy"] == "required":
                        safe_reference_error = _redact_runtime_secrets(
                            reference_error, runtime_secrets
                        )
                        raise HTTPException(
                            status_code=502,
                            detail=f"参考图生成失败，已按创作配置停止：{safe_reference_error}",
                        ) from reference_error
                    reference_info = classify_image_error(
                        reference_error, phase=image_generation_errors.PHASE_SUBMIT
                    )
                    if reference_info.retryable:
                        # 参考图编辑的暂时性故障不切换到无参考重发（那会再次
                        # 付费提交）；交给本轮循环按结构化信息退避重试。
                        raise
                    reference_status = "fallback_text_only"
                    logger.warning(
                        "Reference image generation is unavailable, falling back to images.generate: %s",
                        reference_error,
                    )
                finally:
                    for reference_file in reference_files:
                        reference_file.close()

            if response is None:
                response = generate_image_response(
                    client=client,
                    model=model,
                    prompt=effective_prompt,
                    size=image_size,
                    base_url=base_url,
                    provider=image_provider,
                    api_key=api_key,
                    reference_paths=reference_paths if (use_reference_images and is_toapis) else None,
                    public_config=image_public_config,
                    queue_wait_seconds=min(
                        max(1.0, page_deadline - time.monotonic()),
                        _IMAGE_QUEUE_WAIT_CAP_SEC,
                    ),
                    resume_task_id=resume_task_id,
                )
                if is_toapis and reference_paths:
                    used_reference_paths = list(reference_paths)
                    reference_status = "used"

            img_bytes = _extract_image_bytes_with_bounded_retries(
                response,
                policy=retry_policy,
                deadline_monotonic=page_deadline,
                slide_id=slide_id,
            )

            canvas = get_project_canvas(project)
            process_and_save_image(
                img_bytes,
                save_path,
                target_width=canvas["width"],
                target_height=canvas["height"],
                raw_save_path=str(mask_source_raw_path(Path(save_path))),
            )
        except HTTPException:
            raise
        except ImageGenerationError as exc:
            info = exc.info
        except generation_governor.GovernorTimeout as exc:
            # 上游额度排队超时是"暂时忙"：记录为资源忙并在预算内停轮，
            # 绝不绕过额度强行发送。
            info = classify_image_error(exc)
        except Exception as exc:
            info = classify_image_error(exc)

        if info is None:
            # ── 图片已完整写盘：本地收尾失败不得再次调用生图接口 ──
            try:
                _enforce_project_subtitle_safe_zone(
                    project,
                    slide_id,
                    save_path,
                    source="generated",
                )
                seal_mask_source_pair(Path(save_path))
                with reveal_lock_for(project):
                    if current_input_version() != input_version:
                        raise HTTPException(
                            status_code=409,
                            detail="生图期间页面或模型输入已变化；旧任务结果未应用，请重新生成",
                        )
                    if not preview:
                        keep_derivatives = _check_image_change_choice(
                            project, slide_id, disposition, expected_version,
                        )
                    if not preview:
                        archive_current_slide_image(
                            project, slide_id, keep_derivatives=keep_derivatives,
                        )
                    os.replace(save_path, live_path)
                    rename_mask_source_pair(Path(save_path), live_path)
                    write_visual_provenance(
                        project.run_dir,
                        slide_id,
                        image_path=str(live_path),
                        provider=image_provider,
                        source_type="api_generation",
                        model=model,
                        prompt=effective_prompt,
                        reference_paths=used_reference_paths,
                        reference_policy=reference_policy["policy"],
                        reference_status=reference_status,
                        requested_reference_count=len(style_reference_paths),
                        submitted_reference_count=len(used_reference_paths),
                        source_bytes=img_bytes,
                        candidate=preview,
                    )
                    if not preview and not defer_invalidation:
                        mark_slide_image_changed(project, slide_id, db)
            except HTTPException:
                raise
            except Exception as finalize_error:
                failure = ImagePageFailure(
                    slide_id=str(slide_id),
                    attempts=attempts,
                    code=CODE_SAVE_FAILED,
                    phase=image_generation_errors.PHASE_SAVE,
                    message=_redact_runtime_secrets(
                        f"图片已保存但收尾失败（恢复时不会重新生图）: {finalize_error}",
                        runtime_secrets,
                    ),
                    retryable=False,
                    recoverable=True,
                    image_saved=True,
                    elapsed_sec=time.monotonic() - page_started_at,
                )
                break
            logger.info(
                f"Image saved for {slide_id}: {live_path} (attempts={attempts})"
            )
            if preview:
                return {
                    "success": True,
                    "reference_status": reference_status,
                    "reference_count": len(used_reference_paths),
                    "generation_attempts": attempts,
                    "candidate_url": f"/api/projects/{project_id}/slides/{slide_id}/candidate?t={uuid.uuid4().hex[:6]}",
                }
            return {
                "success": True,
                "reference_status": reference_status,
                "reference_count": len(used_reference_paths),
                "generation_attempts": attempts,
                "image_url": f"/api/projects/{project_id}/slides/{slide_id}/image?t={uuid.uuid4().hex[:6]}",
            }

        resume_task_id = info.upstream_task_id or resume_task_id
        safe_error = _redact_runtime_secrets(info.safe_message, runtime_secrets)
        try:
            write_project_log(
                project,
                "step3_image_attempt_failed",
                slide_id=str(slide_id),
                attempt=attempts,
                code=info.code,
                phase=info.phase,
                retryable=info.retryable,
                outcome_unknown=info.outcome_unknown,
                status_code=info.status_code,
                error=safe_error[:800],
            )
        except Exception:
            logger.debug("step3_image_attempt_failed log unavailable", exc_info=True)
        verdict = decide_retry(
            info,
            attempt=attempts,
            policy=retry_policy,
            remaining_sec=page_deadline - time.monotonic(),
        )
        if not verdict.retry:
            failure = ImagePageFailure(
                slide_id=str(slide_id),
                attempts=attempts,
                code=info.code,
                phase=info.phase,
                message=safe_error[:800],
                retryable=info.retryable,
                recoverable=verdict.recoverable,
                outcome_unknown=info.outcome_unknown,
                status_code=info.status_code,
                elapsed_sec=time.monotonic() - page_started_at,
                upstream_task_id=resume_task_id,
            )
            break
        logger.warning(
            "Image generation for %s failed (attempt %s/%s, code=%s); retrying in %.1fs",
            slide_id,
            attempts,
            retry_policy.max_generation_attempts,
            info.code,
            verdict.delay_sec,
        )
        if info.retry_scope == image_generation_errors.RETRY_SCOPE_REGENERATE:
            resume_task_id = ""
        time.sleep(verdict.delay_sec)

    assert failure is not None
    # 页级失败以结构化结果上抛：HTTP 边界映射为响应，一键编排层读取
    # image_generation_failure 汇总所有失败页，而不是只见首个异常。
    failure_exc = image_generation_errors.ImageGenerationFailure(failure)
    status_code = 503 if (failure.recoverable or failure.retryable) else 500
    if failure.code == CODE_GATEWAY_BUSY:
        detail = f"生图网关额度排队超时，请稍后继续：{failure.message}"
    elif failure.recoverable:
        detail = (
            f"图片生成暂时失败（已尝试 {failure.attempts} 次，code={failure.code}），"
            f"可稍后继续补齐：{failure.message}"
        )
    else:
        detail = f"生成图片失败: {failure.message}"
    http_error = HTTPException(status_code=status_code, detail=detail)
    http_error.image_generation_failure = failure  # type: ignore[attr-defined]
    raise http_error from failure_exc


def finalize_generated_images(
    project_id: str,
    slide_ids: List[str],
    db: Session,
) -> Dict[str, Any]:
    """Invalidate downstream artifacts once after a concurrent image batch.

    Individual image requests can safely write separate slide files in parallel.
    The project-level invalidation and database commit must stay singular so
    concurrent workers cannot overwrite each other's step-status updates.
    """
    project = project_or_404(db, project_id)
    normalized_ids = list(
        dict.fromkeys(
            str(slide_id).strip() for slide_id in slide_ids if str(slide_id).strip()
        )
    )
    if not normalized_ids:
        return {"success": True, "slide_ids": []}
    invalidation_service.slide_images_changed(
        project,
        normalized_ids,
        all_images_exist=all_current_slide_images_exist(project),
    )
    db.commit()
    return {"success": True, "slide_ids": normalized_ids}


def upload_slide_image(
    project_id: str,
    slide_id: str,
    file: UploadFile,
    db: Session,
    disposition: str = "keep",
    expected_version: str | None = None,
):
    project = project_or_404(db, project_id)
    content_type = str(getattr(file, "content_type", "") or "").lower()
    if (
        content_type
        and content_type != "application/octet-stream"
        and not content_type.startswith("image/")
    ):
        raise HTTPException(status_code=415, detail="仅支持图片文件（image/*）")
    save_path = current_slide_file_or_404(project, slide_id, "visual_draft.png")
    try:
        content = file.file.read(MAX_IMAGE_UPLOAD_BYTES + 1)
        if len(content) > MAX_IMAGE_UPLOAD_BYTES:
            raise ImagePayloadTooLarge(
                f"图片文件超过 {MAX_IMAGE_UPLOAD_BYTES // (1024 * 1024)} MB 限制"
            )
        canvas = get_project_canvas(project)
        target_save_path = save_path
        image_path = Path(target_save_path)
        image_path.parent.mkdir(parents=True, exist_ok=True)
        # Normalize into an isolated candidate first.  Upload bytes often vary
        # by PNG metadata or compression despite producing the same project
        # canvas, and replacing the live master before comparison used to
        # discard Mask work for those no-op saves.
        with tempfile.TemporaryDirectory(
            prefix="step3-upload-", dir=image_path.parent
        ) as temporary_value:
            candidate_path = Path(temporary_value) / image_path.name
            save_path = str(candidate_path)
            process_and_save_image(
                content,
                save_path,
                target_width=canvas["width"],
                target_height=canvas["height"],
                raw_save_path=str(mask_source_raw_path(Path(save_path))),
            )
            _enforce_project_subtitle_safe_zone(
                project,
                slide_id,
                save_path,
                source="uploaded",
            )
            seal_mask_source_pair(candidate_path)
            with reveal_lock_for(project):
                keep_derivatives = _check_image_change_choice(
                    project, slide_id, disposition, expected_version,
                )
                if _same_effective_slide_image(image_path, candidate_path):
                    return {
                        "success": True,
                        "unchanged": True,
                        "image_url": f"/api/projects/{project_id}/slides/{slide_id}/image",
                    }
                archive_current_slide_image(project, slide_id, keep_derivatives=keep_derivatives)
                os.replace(save_path, image_path)
                rename_mask_source_pair(Path(save_path), image_path)
                save_path = target_save_path
                # Re-seal after promotion so readers never observe an
                # unmatched raw pair.
                seal_mask_source_pair(Path(save_path))
                write_visual_provenance(
                    project.run_dir,
                    slide_id,
                    image_path=save_path,
                    provider="manual_upload",
                    source_type="local_upload",
                    source_bytes=content,
                    source_filename=str(file.filename or ""),
                )
                mark_slide_image_changed(project, slide_id, db)
        return {
            "success": True,
            "image_url": f"/api/projects/{project_id}/slides/{slide_id}/image?t={uuid.uuid4().hex[:6]}",
        }
    except ImagePayloadTooLarge as e:
        raise HTTPException(status_code=413, detail=str(e)) from e
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Upload image error for {slide_id}: {e}")
        raise HTTPException(status_code=500, detail=f"上传图片失败: {str(e)}")


# 获取指定页面的图片资源接口
def get_slide_image_file(project_id: str, slide_id: str, db: Session):
    project = project_or_404(db, project_id)

    img_path = current_slide_file_or_404(project, slide_id, "visual_draft.png")
    if not os.path.exists(img_path):
        raise HTTPException(status_code=404, detail="图片不存在")

    return FileResponse(img_path, media_type="image/png")


def _zip_entry_slide_id(slide_id: str) -> str:
    """Make a slide id safe for use as a flat ZIP entry filename."""
    forbidden = '\\/:*?"<>|'
    return "".join(
        "_" if character in forbidden or ord(character) < 32 else character
        for character in slide_id
    ).strip(". ") or "slide"


def download_all_slide_images(project_id: str, db: Session) -> Response:
    """Return the current Visual Contract's generated images as one ZIP file."""
    project = project_or_404(db, project_id)
    slide_ids = read_current_slide_ids_or_404(project)
    images: list[tuple[int, str, Path]] = []
    for page_number, slide_id in enumerate(slide_ids, start=1):
        image_path = Path(
            current_slide_file_or_404(project, slide_id, "visual_draft.png")
        )
        if image_path.is_file():
            images.append((page_number, slide_id, image_path))

    if not images:
        raise HTTPException(
            status_code=404,
            detail="当前项目没有已生成的图片，无法批量下载。",
        )

    archive = BytesIO()
    with ZipFile(archive, mode="w", compression=ZIP_DEFLATED) as zip_file:
        for page_number, slide_id, image_path in images:
            entry_name = f"{page_number:03d}_{_zip_entry_slide_id(slide_id)}.png"
            zip_file.write(image_path, arcname=entry_name)

    project_name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", str(project.name or "项目")).strip(" .")
    project_name = project_name[:120].strip(" .") or "项目"
    encoded_filename = quote(f"{project_name}.zip", safe="")
    return Response(
        content=archive.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                'attachment; filename="project-images.zip"; '
                f"filename*=UTF-8''{encoded_filename}"
            )
        },
    )


def get_slide_candidate_file(project_id: str, slide_id: str, db: Session):
    project = project_or_404(db, project_id)
    candidate_path = current_slide_file_or_404(
        project, slide_id, "visual_candidate.png"
    )
    if not os.path.exists(candidate_path):
        raise HTTPException(status_code=404, detail="候选图片不存在")
    return FileResponse(candidate_path, media_type="image/png")


def apply_slide_candidate(project_id: str, payload: Dict[str, Any], db: Session):
    project = project_or_404(db, project_id)

    slide_id = str(payload.get("slide_id") or "").strip()
    candidate_path = current_slide_file_or_404(
        project, slide_id, "visual_candidate.png"
    )
    image_path = current_slide_file_or_404(project, slide_id, "visual_draft.png")
    if not os.path.exists(candidate_path):
        raise HTTPException(status_code=404, detail="候选图片不存在，请先生成")

    same_visual = (
        os.path.exists(image_path)
        and sha256_file(candidate_path) == sha256_file(image_path)
        and sha256_file(mask_source_raw_path(Path(candidate_path)))
        == sha256_file(mask_source_raw_path(Path(image_path)))
    )
    with reveal_lock_for(project):
        keep_derivatives = _check_image_change_choice(
            project, slide_id,
            str(payload.get("disposition") or "keep"),
            str(payload.get("expected_version") or "") or None,
        )
        if not same_visual:
            archive_current_slide_image(project, slide_id, keep_derivatives=keep_derivatives)
        os.replace(candidate_path, image_path)
        # A candidate without a raw pair must clear the old draft pair.
        rename_mask_source_pair(Path(candidate_path), Path(image_path))
        promote_candidate_provenance(project.run_dir, slide_id)
        if not same_visual:
            mark_slide_image_changed(project, slide_id, db)
    return {
        "success": True,
        "image_url": f"/api/projects/{project_id}/slides/{slide_id}/image?t={uuid.uuid4().hex[:6]}",
    }


def delete_all_slide_images(project_id: str, db: Session, payload: Dict[str, Any] | None = None):
    project = project_or_404(db, project_id)
    slide_ids = read_current_slide_ids_or_404(project)
    deleted_count = 0
    with reveal_lock_for(project):
        choices = {
            str(item.get("slide_id") or ""): item
            for item in (payload or {}).get("changes", [])
            if isinstance(item, dict)
        } if isinstance((payload or {}).get("changes"), list) else {}
        for slide_id in slide_ids:
            item = choices.get(slide_id, {})
            _check_image_change_choice(
                project, slide_id,
                str(item.get("disposition") or "keep"),
                str(item.get("expected_version") or "") or None,
            )
        for slide_id in slide_ids:
            image_path = Path(
                storage_slide_file(project.run_dir, slide_id, "visual_draft.png")
            )
            candidate_path = Path(
                storage_slide_file(project.run_dir, slide_id, "visual_candidate.png")
            )
            if image_path.exists():
                item = choices.get(slide_id, {})
                archive_current_slide_image(
                    project, slide_id,
                    keep_derivatives=str(item.get("disposition") or "keep") == "keep",
                )
                image_path.unlink()
                deleted_count += 1
            for path in (
                candidate_path,
                visual_provenance_path(project.run_dir, slide_id),
                visual_provenance_path(project.run_dir, slide_id, candidate=True),
            ):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
            remove_mask_source_pair(image_path)
            remove_mask_source_pair(candidate_path)
        invalidation_service.slide_images_changed(
            project,
            slide_ids,
            all_images_exist=False,
        )
        try:
            db.query(ArtifactRecord).filter(
                ArtifactRecord.project_id == project.id,
                ArtifactRecord.artifact_type == "image",
            ).delete(synchronize_session=False)
        except Exception:
            logger.warning("Failed to remove image artifact records for project %s", project.id, exc_info=True)
        db.commit()
    return {"success": True, "deleted_count": deleted_count, "slide_ids": slide_ids}


def delete_slide_image(
    project_id: str, slide_id: str, db: Session,
    disposition: str = "keep", expected_version: str | None = None,
):
    project = project_or_404(db, project_id)
    image_path = current_slide_file_or_404(project, slide_id, "visual_draft.png")
    candidate_path = current_slide_file_or_404(
        project, slide_id, "visual_candidate.png"
    )
    if not os.path.exists(image_path):
        raise HTTPException(status_code=404, detail="图片不存在")
    with reveal_lock_for(project):
        keep_derivatives = _check_image_change_choice(
            project, slide_id, disposition, expected_version,
        )
        archive_current_slide_image(project, slide_id, keep_derivatives=keep_derivatives)
        os.remove(image_path)
        if os.path.exists(candidate_path):
            os.remove(candidate_path)
        remove_mask_source_pair(Path(image_path))
        remove_mask_source_pair(Path(candidate_path))
        for candidate in (
            visual_provenance_path(project.run_dir, slide_id),
            visual_provenance_path(project.run_dir, slide_id, candidate=True),
        ):
            try:
                candidate.unlink()
            except FileNotFoundError:
                pass
        mark_slide_image_changed(project, slide_id, db)
    try:
        remove_artifact_record(
            db,
            project_id=project.id,
            artifact_type="image",
            filename="visual_draft.png",
        )
    except Exception:
        logger.warning("Failed to remove image artifact record for slide %s", slide_id, exc_info=True)
    return {"success": True, "slide_id": slide_id}


def get_all_images(project_id: str, db: Session):
    project = project_or_404(db, project_id)

    slides_dir = os.path.join(project.run_dir, "slides")
    contract_path = os.path.join(project.run_dir, "planning", "visual_contract.json")
    contract_slide_ids: List[str] = []
    if os.path.exists(contract_path):
        try:
            with open(contract_path, "r", encoding="utf-8") as f:
                contract = json.load(f)
            contract_slide_ids = [
                str(slide.get("slide_id", "")).strip()
                for slide in contract.get("slides", [])
                if isinstance(slide, dict) and str(slide.get("slide_id", "")).strip()
            ]
        except Exception as exc:
            logger.warning(
                f"Failed to read visual contract for image list filtering: {exc}"
            )
    results = []

    if contract_slide_ids:
        for slide_id in contract_slide_ids:
            img_file = os.path.join(slides_dir, slide_id, "visual_draft.png")
            exists = os.path.exists(img_file)
            results.append(
                {
                    "slide_id": slide_id,
                    "exists": exists,
                    "url": f"/api/projects/{project_id}/slides/{slide_id}/image?t={os.stat(img_file).st_mtime_ns}-{os.stat(img_file).st_size}"
                    if exists
                    else None,
                    "provenance": visual_provenance_status(project.run_dir, slide_id)
                    if exists
                    else None,
                }
            )
    elif os.path.exists(slides_dir):
        # 扫描 slides 目录下的子目录，按名称字母排序
        for slide_dir_name in sorted(os.listdir(slides_dir)):
            slide_path = os.path.join(slides_dir, slide_dir_name)
            if os.path.isdir(slide_path):
                img_file = os.path.join(slide_path, "visual_draft.png")
                exists = os.path.exists(img_file)
                results.append(
                    {
                        "slide_id": slide_dir_name,
                        "exists": exists,
                        "url": f"/api/projects/{project_id}/slides/{slide_dir_name}/image?t={os.stat(img_file).st_mtime_ns}-{os.stat(img_file).st_size}"
                        if exists
                        else None,
                        "provenance": visual_provenance_status(
                            project.run_dir, slide_dir_name
                        )
                        if exists
                        else None,
                    }
                )
    return {
        "success": True,
        "images": results,
        "active_slide_ids": active_slide_image_generation(project_id),
        "order_version": step3_image_assignment_version(
            project.run_dir,
            [item["slide_id"] for item in results],
        ),
    }


def step3_image_assignment_version(run_dir: str, slide_ids: List[str]) -> str:
    """Fingerprint fixed storyboard slots and the image currently assigned to each slot."""
    root = Path(run_dir)
    return sha256_json(
        {
            "slots": [
                {
                    "slide_id": str(slide_id),
                    "image_sha256": sha256_file(
                        storage_slide_file(root, str(slide_id), "visual_draft.png")
                    ),
                    "provenance_sha256": sha256_file(
                        visual_provenance_path(root, str(slide_id))
                    ),
                }
                for slide_id in slide_ids
            ]
        }
    )


def _copy_file_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f"{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _restore_optional_file(snapshot: Optional[Path], destination: Path) -> None:
    if snapshot is not None and snapshot.exists():
        _copy_file_atomic(snapshot, destination)
        return
    try:
        destination.unlink()
    except FileNotFoundError:
        pass


def update_step3_image_order(project_id: str, payload: Dict[str, Any], db: Session):
    project = project_or_404(db, project_id)

    from_index = payload.get("from_index")
    to_index = payload.get("to_index")
    if (
        isinstance(from_index, bool)
        or isinstance(to_index, bool)
        or not isinstance(from_index, int)
        or not isinstance(to_index, int)
    ):
        raise HTTPException(status_code=400, detail="from_index 和 to_index 必须是整数")

    expected_version = str(payload.get("order_version") or "").strip()
    if not expected_version:
        raise HTTPException(status_code=428, detail="缺少排序版本，请刷新页面后重试")

    slide_ids = read_current_slide_ids_or_404(project)
    if not (0 <= from_index < len(slide_ids) and 0 <= to_index < len(slide_ids)):
        raise HTTPException(status_code=400, detail="图片移动位置超出当前分镜范围")
    if from_index == to_index:
        return {
            "success": True,
            "slide_ids": slide_ids,
            "order_version": step3_image_assignment_version(project.run_dir, slide_ids),
        }

    root = Path(project.run_dir)
    with reveal_lock_for(project):
        current_version = step3_image_assignment_version(project.run_dir, slide_ids)
        if expected_version != current_version:
            raise HTTPException(
                status_code=409, detail="图片对应关系已被其他操作更新，请刷新后重试"
            )

        source_slide_id = slide_ids[from_index]
        source_image = Path(
            storage_slide_file(root, source_slide_id, "visual_draft.png")
        )
        if not source_image.exists():
            raise HTTPException(status_code=400, detail="被移动的位置没有图片")

        source_ids = list(slide_ids)
        moved_source_id = source_ids.pop(from_index)
        source_ids.insert(to_index, moved_source_id)
        affected_indexes = range(
            min(from_index, to_index), max(from_index, to_index) + 1
        )
        affected_slide_ids = [slide_ids[index] for index in affected_indexes]
        choices = {
            str(item.get("slide_id") or ""): item
            for item in payload.get("changes", [])
            if isinstance(item, dict)
        } if isinstance(payload.get("changes"), list) else {}
        for affected_id in affected_slide_ids:
            item = choices.get(affected_id, {})
            _check_image_change_choice(
                project, affected_id,
                str(item.get("disposition") or "keep"),
                str(item.get("expected_version") or "") or None,
            )
        for affected_id in affected_slide_ids:
            item = choices.get(affected_id, {})
            archive_current_slide_image(
                project, affected_id,
                keep_derivatives=str(item.get("disposition") or "keep") == "keep",
            )

        with tempfile.TemporaryDirectory(
            prefix="step3-image-move-", dir=root
        ) as temporary_value:
            snapshot_root = Path(temporary_value)
            for slide_id in affected_slide_ids:
                slide_snapshot = snapshot_root / slide_id
                slide_snapshot.mkdir(parents=True, exist_ok=True)
                image_path = Path(
                    storage_slide_file(root, slide_id, "visual_draft.png")
                )
                provenance_path = visual_provenance_path(root, slide_id)
                if image_path.exists():
                    shutil.copy2(image_path, slide_snapshot / "visual_draft.png")
                if provenance_path.exists():
                    shutil.copy2(
                        provenance_path, slide_snapshot / "visual_provenance.json"
                    )
                # The raw pair travels with its master image; the marker binds
                # them by content hash so a stale or missing pair is ignored.
                for pair_path in (
                    mask_source_raw_path(image_path),
                    mask_source_marker_path(image_path),
                ):
                    if pair_path.exists():
                        shutil.copy2(pair_path, slide_snapshot / pair_path.name)

            try:
                reassigned_at = datetime.now().isoformat(timespec="seconds")
                for index in affected_indexes:
                    target_slide_id = slide_ids[index]
                    assigned_source_id = source_ids[index]
                    source_snapshot = snapshot_root / assigned_source_id
                    target_dir = Path(
                        storage_slide_file(root, target_slide_id, "visual_draft.png")
                    ).parent
                    target_dir.mkdir(parents=True, exist_ok=True)
                    target_image = target_dir / "visual_draft.png"
                    target_provenance = visual_provenance_path(root, target_slide_id)

                    _restore_optional_file(
                        source_snapshot / "visual_draft.png", target_image
                    )
                    _restore_optional_file(
                        source_snapshot / mask_source_raw_path(target_image).name,
                        mask_source_raw_path(target_image),
                    )
                    _restore_optional_file(
                        source_snapshot / mask_source_marker_path(target_image).name,
                        mask_source_marker_path(target_image),
                    )
                    source_provenance_path = source_snapshot / "visual_provenance.json"
                    if source_provenance_path.exists() and target_image.exists():
                        try:
                            provenance = json.loads(
                                source_provenance_path.read_text(encoding="utf-8-sig")
                            )
                        except (OSError, json.JSONDecodeError):
                            provenance = None
                        if isinstance(provenance, dict):
                            history = provenance.get("assignment_history")
                            if not isinstance(history, list):
                                history = []
                            history.append(
                                {
                                    "from_slide_id": assigned_source_id,
                                    "to_slide_id": target_slide_id,
                                    "reassigned_at": reassigned_at,
                                }
                            )
                            provenance["assignment_history"] = history[-20:]
                            provenance["slide_id"] = target_slide_id
                            provenance["copied_to"] = (
                                f"slides/{target_slide_id}/visual_draft.png"
                            )
                            provenance["output_sha256"] = sha256_file(target_image)
                            if provenance.get("schema_version") == "visual_provenance_v3":
                                provenance["contract_slide_sha256"] = slide_contract_hash(
                                    root, target_slide_id
                                )
                            write_json_atomic(target_provenance, provenance)
                        else:
                            _restore_optional_file(None, target_provenance)
                    else:
                        _restore_optional_file(None, target_provenance)
            except Exception:
                for slide_id in affected_slide_ids:
                    slide_snapshot = snapshot_root / slide_id
                    target_dir = Path(
                        storage_slide_file(root, slide_id, "visual_draft.png")
                    ).parent
                    _restore_optional_file(
                        slide_snapshot / "visual_draft.png",
                        target_dir / "visual_draft.png",
                    )
                    _restore_optional_file(
                        slide_snapshot / mask_source_raw_path(target_dir / "visual_draft.png").name,
                        mask_source_raw_path(target_dir / "visual_draft.png"),
                    )
                    _restore_optional_file(
                        slide_snapshot / mask_source_marker_path(target_dir / "visual_draft.png").name,
                        mask_source_marker_path(target_dir / "visual_draft.png"),
                    )
                    _restore_optional_file(
                        slide_snapshot / "visual_provenance.json",
                        visual_provenance_path(root, slide_id),
                    )
                raise

        for slide_id in affected_slide_ids:
            for candidate in (
                Path(storage_slide_file(root, slide_id, "visual_candidate.png")),
                visual_provenance_path(root, slide_id, candidate=True),
            ):
                try:
                    candidate.unlink()
                except FileNotFoundError:
                    pass
            remove_mask_source_pair(
                Path(storage_slide_file(root, slide_id, "visual_candidate.png"))
            )
        invalidation_service.slide_images_changed(
            project,
            affected_slide_ids,
            all_images_exist=all_current_slide_images_exist(project),
        )
        db.commit()

    return {
        "success": True,
        "slide_ids": slide_ids,
        "order_version": step3_image_assignment_version(project.run_dir, slide_ids),
    }


def confirm_images(project_id: str, db: Session):
    project = project_or_404(db, project_id)
    from project_impact_service import resolve_impacts, snapshot_impacts

    impact_snapshot = snapshot_impacts(project.run_dir, affected=("images",))
    slide_ids = read_current_slide_ids_or_404(project)
    missing_images = [
        slide_id
        for slide_id in slide_ids
        if not os.path.exists(
            os.path.join(project.run_dir, "slides", slide_id, "visual_draft.png")
        )
    ]
    if missing_images:
        raise HTTPException(
            status_code=400, detail=f"以下页面还没有图片: {', '.join(missing_images)}"
        )
    provenance_errors = validate_visual_provenance_set(project.run_dir, slide_ids)
    if provenance_errors:
        details = ", ".join(
            f"{item['slide_id']}({item['reason']})" for item in provenance_errors
        )
        raise HTTPException(
            status_code=409,
            detail=f"以下页面图片来源缺失或已过期，请重新生成或上传: {details}",
        )

    # 步骤4：确认图片。将步骤 3 与 4 状态标记为已完成
    # 自动调用 write_reveal_manifest_template.py 生成 manifest 模板
    manifest_path = os.path.join(project.run_dir, "reveal_manifest.json")
    if not os.path.exists(manifest_path):
        template_script = os.path.abspath(
            os.path.join(
                os.path.dirname(__file__),
                "scripts",
                "write_reveal_manifest_template.py",
            )
        )
        res = run_subprocess_killable(
            [sys.executable, template_script, "--run-dir", project.run_dir],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout_sec=90,
        )
        if res.returncode != 0:
            logger.error(f"Failed to write reveal manifest template: {res.stderr}")
            write_project_log(
                project,
                "step5_manifest_template_error",
                returncode=res.returncode,
                stdout=res.stdout.strip(),
                stderr=res.stderr.strip(),
            )
            raise HTTPException(
                status_code=500, detail="自动创建 Mask 标注文件失败，请确认分镜规划正常"
            )

        # Final rendering is manual-mask-only. Do not run historical box-fitting
        # algorithms during normal project initialization.
    sync_reveal_manifest_to_contract(project)
    refresh_reveal_semantic_blocks(project)

    # Register slide images as queryable artifacts for the Agent API.
    for slide_id in slide_ids:
        img_path = os.path.join(project.run_dir, "slides", slide_id, "visual_draft.png")
        if os.path.exists(img_path):
            try:
                record_artifact(
                    db,
                    project_id=project.id,
                    artifact_type="image",
                    path=img_path,
                    relative_path=f"slides/{slide_id}/visual_draft.png",
                    mime_type="image/png",
                    metadata={"slide_id": slide_id},
                )
            except Exception:
                logger.warning("Failed to register image artifact for slide %s", slide_id, exc_info=True)

    handle_step_navigation(project, 4, db)
    resolve_impacts(project.run_dir, affected=("images",), snapshot=impact_snapshot)
    return {"success": True}
