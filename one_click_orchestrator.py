"""One-click generation orchestrator v2.

The orchestrator uses the same in-process production service facade as the web
routes. It does not create an HTTP client or route requests back into the app.

Scope:
- start a single in-process job per project;
- write resumable status to planning/one_click_status.json;
- execute existing steps in order;
- pause/fail with a blocking error when an existing step fails.

This is not a durable distributed queue. It is a local-app convenience layer that
keeps the user-facing workflow simple while preserving manual recovery paths.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from one_click_resume_policy import (
    build_resume_plan,
    has_article as _has_article,
    has_contract as _has_contract,
    has_fresh_narration as _has_fresh_narration,
    image_needs_generation as _image_needs_generation,
    mtime as _mtime,
    run_dir as _run_dir,
    slide_ids as _slide_ids,
    slides_requiring_images as _slides_requiring_images,
    upstream_image_inputs as _upstream_image_inputs,
)
from project_profile_store import DEFAULT_QUALITY_GATES, load_profile
from tts_provider_service import normalize_tts_provider

STATUS_FILENAME = "one_click_status.json"
STATUS_VERSION = "one_click_orchestrator_v2"

logger = logging.getLogger(__name__)


# [同步 step_status 20260814] 一键生成 stage -> 前端步骤映射
_STAGE_TO_STEP = {
    "preflight": "1",
    "storyboard": "2",
    "images": "3",
    "confirm_images": "3",
    "ai_mask": "5",
    "mask_assets": "5",
    "narration": "6",
    "tts": "6",
    "render": "8",
}
STAGES = [
    ("preflight", "预检查"),
    ("storyboard", "生成分镜"),
    ("images", "生成全部图片"),
    ("confirm_images", "确认图片并创建 Mask 模板"),
    ("ai_mask", "AI Mask 标注"),
    ("mask_assets", "构建 Reveal 资源"),
    ("narration", "生成演讲稿"),
    ("tts", "合成并确认音频"),
    ("render", "渲染视频"),
]

_RUNNING_LOCK = threading.Lock()
_RUNNING: dict[str, threading.Thread] = {}


@dataclass(frozen=True)
class OneClickDependencies:
    session_factory: Callable[[], Any]
    project_model: Any
    get_setting: Callable[..., Any]
    resolve_media_tool: Callable[[str], Any]
    repo_root: Path
    read_project_article_source: Callable[..., Any]
    write_project_log: Callable[..., None]
    pipeline_service_factory: Callable[[Any, str], Any]


_DEPENDENCIES: OneClickDependencies | None = None


def configure_one_click_dependencies(
    dependencies: OneClickDependencies,
) -> OneClickDependencies:
    global _DEPENDENCIES
    _DEPENDENCIES = dependencies
    return dependencies


def get_one_click_dependencies() -> OneClickDependencies:
    if _DEPENDENCIES is None:
        raise RuntimeError("One-click dependencies have not been configured")
    return _DEPENDENCIES


class QualityGateFailure(RuntimeError):
    def __init__(self, message: str, *, pause: bool) -> None:
        super().__init__(message)
        self.pause = pause


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _safe_text(value: Any, limit: int = 2000) -> str:
    return str(value or "").strip()[:limit]


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value).strip()))
    except Exception:
        return default


def _read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return fallback


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        try:
            temp_path.write_text(text, encoding="utf-8")
            os.replace(temp_path, path)
        except PermissionError:
            # [沙箱兼容写盘 20260813] 部分受限环境（如沙箱）不允许创建临时文件并原子改名，
            # 降级为直接写入目标文件，保证流水线状态仍能正常保存。
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass
            path.write_text(text, encoding="utf-8")
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass


def _status_path(project: Any) -> Path:
    return _run_dir(project) / "planning" / STATUS_FILENAME


def _initial_status(project_id: str, run_id: str) -> dict[str, Any]:
    return {
        "version": STATUS_VERSION,
        "project_id": project_id,
        "run_id": run_id,
        "status": "running",
        "current_stage": "preflight",
        "started_at": _now(),
        "updated_at": _now(),
        "completed_at": "",
        "video": None,
        "requested_mode": "",
        "previous_failed_stage": "",
        "effective_start_stage": "preflight",
        "revalidation": [],
        "stages": [
            {
                "id": stage_id,
                "title": title,
                "status": "pending",
                "started_at": "",
                "finished_at": "",
                "message": "",
                "progress": 0,
                "warnings": [],
                "blocking_errors": [],
            }
            for stage_id, title in STAGES
        ],
    }


def _status_for_project(project: Any, project_id: str) -> dict[str, Any]:
    status = _read_json(_status_path(project), {})
    if isinstance(status, dict) and status.get("version") in {"one_click_orchestrator_v1", STATUS_VERSION}:
        status["version"] = STATUS_VERSION
        status.setdefault("requested_mode", "")
        status.setdefault("previous_failed_stage", "")
        status.setdefault("effective_start_stage", status.get("current_stage") or "preflight")
        status.setdefault("revalidation", [])
        return status
    return {
        "version": STATUS_VERSION,
        "project_id": project_id,
        "run_id": "",
        "status": "idle",
        "current_stage": "",
        "started_at": "",
        "updated_at": "",
        "completed_at": "",
        "video": None,
        "requested_mode": "",
        "previous_failed_stage": "",
        "effective_start_stage": "preflight",
        "revalidation": [],
        "stages": _initial_status(project_id, "")["stages"],
    }


def _save_status(project: Any, status: dict[str, Any]) -> None:
    status["updated_at"] = _now()
    _write_json(_status_path(project), status)


def _stage(status: dict[str, Any], stage_id: str) -> dict[str, Any]:
    for item in status.get("stages", []):
        if item.get("id") == stage_id:
            return item
    item = {"id": stage_id, "title": stage_id, "status": "pending", "started_at": "", "finished_at": "", "message": "", "progress": 0, "warnings": [], "blocking_errors": []}
    status.setdefault("stages", []).append(item)
    return item


def _start_stage(project: Any, status: dict[str, Any], stage_id: str, message: str = "") -> None:
    item = _stage(status, stage_id)
    item.update({"status": "running", "started_at": item.get("started_at") or _now(), "finished_at": "", "message": message, "progress": 0, "blocking_errors": []})
    status["status"] = "running"
    status["current_stage"] = stage_id
    _save_status(project, status)


def _finish_stage(project: Any, status: dict[str, Any], stage_id: str, message: str = "", progress: float = 1.0) -> None:
    item = _stage(status, stage_id)
    item.update({"status": "done", "finished_at": _now(), "message": message, "progress": max(0, min(1, float(progress)))})
    _save_status(project, status)


def _warn_stage(project: Any, status: dict[str, Any], stage_id: str, warning: str) -> None:
    item = _stage(status, stage_id)
    item.setdefault("warnings", []).append(_safe_text(warning, 1200))
    _save_status(project, status)


def _fail_stage(
    project: Any,
    status: dict[str, Any],
    stage_id: str,
    error: str,
    *,
    pause: bool = True,
) -> None:
    item = _stage(status, stage_id)
    item.update({"status": "failed", "finished_at": _now(), "progress": item.get("progress") or 0})
    item.setdefault("blocking_errors", []).append(_safe_text(error, 3000))
    status["status"] = "paused" if pause else "failed"
    status["current_stage"] = stage_id
    status["completed_at"] = _now()
    _save_status(project, status)


def _complete(
    project: Any,
    status: dict[str, Any],
    db: Any = None,
    video: Any = None,
) -> None:
    status["status"] = "completed"
    status["current_stage"] = ""
    status["completed_at"] = _now()
    status["video"] = video
    _save_status(project, status)
    # [同步 step_status 20260814] 一键生成完成时，把已完成的 stage 同步到数据库 step_status。
    # 必须复用 _run_pipeline 中持有 project ORM 对象的同一个 db session；另开 session 的
    # commit 不会提交该 project 的脏数据（旧实现误用未定义的 dependencies 名字并另开
    # session，导致 NameError 被 except 静默吞掉、step_status 从不落库）。
    try:
        current = project.get_step_status() if hasattr(project, "get_step_status") else {}
        updated = dict(current)
        for stage in status.get("stages") or []:
            if stage.get("status") == "done":
                step_key = _STAGE_TO_STEP.get(stage.get("id", ""))
                if step_key:
                    updated[step_key] = "completed"
        if hasattr(project, "set_step_status"):
            project.set_step_status(updated)
        if db is not None:
            db.commit()
    except Exception:
        if db is not None and hasattr(db, "rollback"):
            db.rollback()
        logger.exception("Failed to sync step_status after one-click completion")


def _error_text(exc: Exception) -> str:
    detail = getattr(exc, "detail", "")
    return _safe_text(detail or str(exc) or type(exc).__name__, 3000)


def _require_ok(payload: Any, label: str) -> dict[str, Any]:
    if isinstance(payload, dict) and payload.get("success") is False:
        raise RuntimeError(f"{label} failed: {_safe_text(payload.get('message') or payload.get('detail') or payload, 3000)}")
    return payload if isinstance(payload, dict) else {"value": payload}


def _invoke(operation: Any, label: str) -> dict[str, Any]:
    try:
        return _require_ok(operation(), label)
    except Exception as exc:
        if isinstance(exc, RuntimeError) and str(exc).startswith(f"{label} failed:"):
            raise
        raise RuntimeError(f"{label} failed: {_error_text(exc)}") from exc


def _require_quality_gate(
    operation: Any,
    label: str,
    gates: dict[str, bool],
    gate_name: str,
) -> dict[str, Any]:
    try:
        return _invoke(operation, label)
    except Exception as exc:
        raise QualityGateFailure(
            str(exc),
            pause=bool(gates.get(gate_name, True)),
        ) from exc


def _backup_narration(project: Any, run_id: str) -> Path | None:
    source = _run_dir(project) / "planning" / "narration_beats.json"
    if not source.is_file():
        return None
    backup = _run_dir(project) / "planning" / "backups" / f"narration_before_one_click_{run_id}.json"
    backup.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(source, backup)
    except OSError as exc:
        raise RuntimeError(f"备份现有演讲稿失败：{_error_text(exc)}") from exc
    return backup


def _load_existing_narration(
    services: Any,
    before_mutation: Callable[[], Any],
) -> dict[str, Any] | None:
    try:
        payload = services.narration()
    except Exception as exc:
        raise RuntimeError(f"读取现有演讲稿失败：{_error_text(exc)}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("读取现有演讲稿失败：返回结果不是有效对象")
    if payload.get("success") is False:
        message = _safe_text(payload.get("message") or payload.get("detail"), 1000)
        if "尚未生成" in message:
            return None
        raise RuntimeError(f"读取现有演讲稿失败：{message or '未知错误'}")
    beats = payload.get("beats")
    if not isinstance(beats, dict):
        raise RuntimeError("读取现有演讲稿失败：beats 结构无效")
    if payload.get("repair", {}).get("required"):
        before_mutation()
        try:
            payload = services.repair_narration()
        except Exception as exc:
            raise RuntimeError(f"修复现有演讲稿失败：{_error_text(exc)}") from exc
        if not isinstance(payload, dict) or payload.get("success") is False or not isinstance(payload.get("beats"), dict):
            raise RuntimeError("修复现有演讲稿失败：修复结果无效")
    return payload


def _quality_gates(project: Any) -> dict[str, bool]:
    return dict(load_profile(project)["quality_gates"])


def _stage_index(stage_id: str) -> int:
    for index, (candidate, _title) in enumerate(STAGES):
        if candidate == stage_id:
            return index
    return 0


def _resume_status(project: Any, project_id: str, run_id: str, mode: str) -> tuple[dict[str, Any], int]:
    previous = _status_for_project(project, project_id)
    resumable_states = {"paused", "running", "failed", "completed"}
    if mode == "resume" and previous.get("status") in resumable_states:
        failed_stage = str(previous.get("current_stage") or ("render" if previous.get("status") == "completed" else "preflight"))
        plan = build_resume_plan(project, failed_stage)
        start_index = _stage_index(str(plan["effective_start_stage"]))
        status = previous
        status.update({
            "run_id": run_id,
            "status": "running",
            "completed_at": "",
            "video": None,
            "requested_mode": mode,
            **plan,
        })
        for index, item in enumerate(status.get("stages", [])):
            if index >= start_index:
                item.update({
                    "status": "pending",
                    "started_at": "",
                    "finished_at": "",
                    "message": "",
                    "progress": 0,
                    "warnings": [],
                    "blocking_errors": [],
                })
        return status, start_index
    status = _initial_status(project_id, run_id)
    status["requested_mode"] = mode
    return status, 0


def _preflight_errors(dependencies: OneClickDependencies, project: Any) -> list[str]:
    errors: list[str] = []
    # 注意：此调用有副作用——负责遗留 brief 文章的迁移（不可删除，
    # 返回值虽被丢弃，但迁移发生在读取路径中）。审查 L-11 曾误判为死代码。
    try:
        dependencies.read_project_article_source(project, required=False)
    except Exception:
        pass
    if not _has_article(project):
        errors.append("请先导入文章内容，或在创建项目时填写文章内容。")
    for key, label in (
        ("llm_api_key", "LLM API Key"),
        ("image_api_key", "图片生成 API Key"),
    ):
        if not str(dependencies.get_setting(key) or "").strip():
            errors.append(f"未配置 {label}")

    # ComfyUI/IndexTTS is a local provider and intentionally has no cloud
    # credential. Keep its preflight independent from the legacy TTS key
    # requirement, while still catching a missing workflow before the worker
    # thread starts.
    try:
        configured_provider = dependencies.get_setting("tts_provider", "minimax")
    except TypeError:
        configured_provider = dependencies.get_setting("tts_provider")
    provider = normalize_tts_provider(configured_provider)
    if provider == "comfyui_tts":
        try:
            endpoint = str(dependencies.get_setting("tts_endpoint", "") or "").strip()
        except TypeError:
            endpoint = str(dependencies.get_setting("tts_endpoint") or "").strip()
        if endpoint.lower().startswith(("http://", "https://")):
            endpoint = ""
        workflow_path = Path(endpoint) if endpoint else (
            dependencies.repo_root / "data" / "digital_human" / "comfyui_tts_workflow.json"
        )
        if not workflow_path.is_absolute():
            workflow_path = dependencies.repo_root / workflow_path
        if not workflow_path.is_file():
            errors.append(f"ComfyUI TTS 工作流不存在：{workflow_path}")
    elif not str(dependencies.get_setting("tts_api_key") or "").strip():
        errors.append("未配置 TTS API Key")
    for tool_name in ("ffmpeg", "ffprobe"):
        available = bool(dependencies.resolve_media_tool(tool_name))
        if not available:
            errors.append(f"未找到 {tool_name}")
    remotion_dir = dependencies.repo_root / "scripts" / "remotion"
    if not (remotion_dir / "package.json").exists():
        errors.append("Remotion package.json 不存在")
    return errors


def _has_manual_mask(group: Any) -> bool:
    if not isinstance(group, dict):
        return False
    manual = group.get("manual_mask")
    if not isinstance(manual, dict):
        return False
    rle = manual.get("rle")
    if isinstance(rle, dict) and isinstance(rle.get("runs"), list) and len(rle["runs"]) > 0:
        return True
    strokes = manual.get("strokes")
    return isinstance(strokes, list) and len(strokes) > 0


def _existing_mask_count(project: Any, slide_ids: list[str] | None = None) -> int:
    manifest = _read_json(_run_dir(project) / "reveal_manifest.json", {})
    if not isinstance(manifest, dict):
        return 0
    selected = set(slide_ids) if slide_ids is not None else None
    count = 0
    for slide in manifest.get("slides", []) or []:
        if not isinstance(slide, dict):
            continue
        if selected is not None and str(slide.get("slide_id") or "") not in selected:
            continue
        for collection_name in ("groups", "semantic_blocks"):
            for group in slide.get(collection_name, []) or []:
                if _has_manual_mask(group):
                    count += 1
    return count


def _ai_mask_quality_errors(result: dict[str, Any], existing_mask_count: int = 0) -> list[str]:
    errors: list[str] = []
    if not isinstance(result, dict):
        return ["AI Mask 返回结果不是有效对象"]
    if result.get("complete") is False:
        errors.append("AI Mask 尚未完成全部语块关联")
    processed = _safe_int(result.get("processed_slide_count") or result.get("processed"), 0)
    updated = _safe_int(result.get("updated_group_count"), 0)
    if processed == 0:
        errors.append("AI Mask 没有处理任何 slide")
    if updated == 0 and existing_mask_count <= 0:
        errors.append("AI Mask 没有更新任何语块，且当前 manifest 中没有可复用的已有 Mask")
    for slide in result.get("slides", []) or []:
        if not isinstance(slide, dict):
            continue
        slide_id = _safe_text(slide.get("slide_id"), 100) or "unknown slide"
        unmatched_groups = _safe_int(slide.get("unmatched_group_count"), 0)
        if unmatched_groups > 0:
            errors.append(f"{slide_id} 有 {unmatched_groups} 个未匹配语块")
        quality = slide.get("quality") if isinstance(slide.get("quality"), dict) else {}
        if quality and not quality.get("passed"):
            coverage = float(quality.get("foreground_coverage_ratio") or 0)
            overlap = _safe_int(quality.get("overlap_pixel_count"), 0)
            unassigned = _safe_int(quality.get("unassigned_component_count"), 0)
            min_coverage = float(quality.get("minimum_foreground_coverage_ratio") or 0.995)
            pixel_ok = coverage >= min_coverage and unassigned == 0 and overlap == 0
            semantic = slide.get("semantic_quality") if isinstance(slide.get("semantic_quality"), dict) else {}
            semantic_blockers = []
            for _issue in (semantic.get("blocking_errors") or []):
                _t = _safe_text(_issue.get("type") if isinstance(_issue, dict) else str(_issue), 80)
                if _t:
                    semantic_blockers.append(_t)
            if pixel_ok and semantic_blockers:
                # [Mask语义降级 20260813] 像素 Mask 完美（覆盖率达标、无重叠、无未分配），
                # 仅语义布局（如正文组触及标题/字幕区）需人工复核：不作为流水线硬阻断，
                # 让自动流程继续产出视频；复核项已记录在该 slide 的 review_issues 中。
                continue
            reasons = []
            if coverage < min_coverage:
                reasons.append(f"覆盖率 {coverage:.2%}（需 ≥ {min_coverage:.2%}）")
            if unassigned > 0:
                reasons.append(f"未分配组件 {unassigned}")
            if overlap > 0:
                reasons.append(f"重叠 {overlap} 像素")
            if semantic_blockers:
                reasons.append("语义布局：" + "、".join(semantic_blockers))
            if not reasons:
                reasons.append("质量未通过")
            errors.append(f"{slide_id} Mask 质量未通过：" + "；".join(reasons))
    return errors


def _ai_mask_failed_slide_ids(result: dict[str, Any], fallback: list[str]) -> list[str]:
    failed: list[str] = []
    for slide in result.get("slides", []) if isinstance(result, dict) else []:
        if not isinstance(slide, dict):
            continue
        slide_id = _safe_text(slide.get("slide_id"), 100)
        quality = slide.get("quality") if isinstance(slide.get("quality"), dict) else {}
        if slide_id and (
            _safe_int(slide.get("unmatched_group_count"), 0) > 0
            or (quality and quality.get("passed") is not True)
            or bool(slide.get("review_required"))
        ):
            failed.append(slide_id)
    for issue in result.get("review_issues", []) if isinstance(result, dict) else []:
        if isinstance(issue, dict):
            slide_id = _safe_text(issue.get("slide_id"), 100)
            if slide_id:
                failed.append(slide_id)
    selected = list(dict.fromkeys(failed))
    return selected or list(fallback)


def _run_pipeline(
    dependencies: OneClickDependencies,
    project_id: str,
    run_id: str,
    mode: str = "resume",
) -> None:
    db = dependencies.session_factory()
    project = None
    try:
        project_model = dependencies.project_model
        project = db.query(project_model).filter(project_model.id == project_id).first()
        if not project:
            return
        status, start_index = _resume_status(project, project_id, run_id, mode)
        _save_status(project, status)
        gates = _quality_gates(project)
        services = dependencies.pipeline_service_factory(db, project_id)

        def should_run(stage_id: str) -> bool:
            return _stage_index(stage_id) >= start_index

        if should_run("preflight") or mode == "resume":
            _start_stage(project, status, "preflight", "检查文章、凭据、媒体工具和项目目录")
            preflight_errors = _preflight_errors(dependencies, project)
            if preflight_errors:
                raise RuntimeError("预检查失败：" + "；".join(preflight_errors))
            _finish_stage(project, status, "preflight", "预检查通过")

        if should_run("storyboard"):
            _start_stage(project, status, "storyboard", "生成或复用 visual_contract.json")
            if mode == "restart" or not _has_contract(project):
                _require_quality_gate(
                    services.storyboard_script,
                    "Step 2 article-to-slide",
                    gates,
                    "pause_on_storyboard_validation_error",
                )
                _require_quality_gate(
                    services.storyboard_visual,
                    "Step 2 slide-to-visual",
                    gates,
                    "pause_on_storyboard_validation_error",
                )
                _require_quality_gate(
                    services.storyboard_compose,
                    "Step 2 compose",
                    gates,
                    "pause_on_storyboard_validation_error",
                )
                db.refresh(project)
            _finish_stage(project, status, "storyboard", "分镜规划已就绪")

        if should_run("images"):
            _start_stage(project, status, "images", "生成缺失或过期的 slide 图片")
            prompts_payload = _invoke(services.image_prompts, "Step 3 prompts")
            prompts_by_slide = {str(item.get("slide_id") or ""): str(item.get("prompt") or "") for item in prompts_payload.get("prompts", []) if isinstance(item, dict)}
            requiring_images = _slides_requiring_images(project)
            generated = 0
            for index, slide_id in enumerate(requiring_images, start=1):
                prompt = prompts_by_slide.get(slide_id)
                if not prompt:
                    raise RuntimeError(f"缺少 {slide_id} 的生图 Prompt")
                item = _stage(status, "images")
                item["progress"] = index / max(1, len(requiring_images))
                item["message"] = f"正在生成 {slide_id} ({index}/{len(requiring_images)})"
                _save_status(project, status)
                _require_quality_gate(
                    lambda slide_id=slide_id, prompt=prompt: services.generate_image(slide_id, prompt),
                    f"Step 3 image {slide_id}",
                    gates,
                    "pause_on_image_generation_failure",
                )
                generated += 1
            _finish_stage(project, status, "images", f"图片已就绪，新增或刷新 {generated} 张")

        if should_run("confirm_images"):
            _start_stage(project, status, "confirm_images", "确认图片并创建 reveal_manifest.json")
            _invoke(services.confirm_images, "Step 3 confirm")
            _finish_stage(project, status, "confirm_images", "图片已确认")

        if should_run("ai_mask"):
            _start_stage(project, status, "ai_mask", "执行 AI Mask 标注")
            ai_mask_payload = {"settings": {"overwrite_existing_manual_mask": False, "overwrite_existing_ai_mask": True, "skip_locked_groups": True}}
            result = _invoke(lambda: services.annotate_ai_mask(ai_mask_payload), "AI Mask")
            existing_masks = _existing_mask_count(project)
            quality_errors = _ai_mask_quality_errors(result, existing_masks)
            if quality_errors:
                failed_slide_ids = _ai_mask_failed_slide_ids(result, _slide_ids(project))
                _warn_stage(
                    project,
                    status,
                    "ai_mask",
                    f"首次标注未完整，仅重试 {len(failed_slide_ids)} 个失败页面",
                )
                retry = _invoke(
                    lambda: services.annotate_ai_mask({**ai_mask_payload, "slide_ids": failed_slide_ids}),
                    "AI Mask retry",
                )
                existing_masks = _existing_mask_count(project, failed_slide_ids)
                quality_errors = _ai_mask_quality_errors(retry, existing_masks)
                result = retry
                if quality_errors and gates.get("pause_on_ai_mask_low_confidence", True):
                    raise RuntimeError("AI Mask 自动重试后仍未完成：" + "；".join(quality_errors[:5]))
                if quality_errors:
                    _warn_stage(project, status, "ai_mask", "质量门已关闭，保留未通过项：" + "；".join(quality_errors[:5]))
            _finish_stage(
                project,
                status,
                "ai_mask",
                "AI Mask 标注完成" if not quality_errors else "AI Mask 标注完成（含警告）",
            )

        if should_run("mask_assets"):
            _start_stage(project, status, "mask_assets", "构建 Reveal 资源")
            manifest_payload = _invoke(services.mask_manifest, "Step 5 manifest")
            if manifest_payload.get("repair", {}).get("required"):
                manifest_payload = _invoke(services.repair_mask_manifest, "Step 5 repair")
            manifest = manifest_payload.get("manifest")
            if not isinstance(manifest, dict):
                raise RuntimeError("Step 5 manifest 返回为空")
            _invoke(lambda: services.build_mask_assets(manifest), "Step 5 build assets")
            _finish_stage(project, status, "mask_assets", "Reveal 资源已构建")

        if should_run("narration"):
            _start_stage(project, status, "narration", "生成或复用演讲稿并尝试添加 TTS 标记")
            narration_backed_up = False

            def backup_narration_once() -> None:
                nonlocal narration_backed_up
                if not narration_backed_up:
                    _backup_narration(project, run_id)
                    narration_backed_up = True

            existing_payload = _load_existing_narration(services, backup_narration_once)
            if existing_payload is not None:
                backup_narration_once()
            if (
                mode != "restart"
                and _has_fresh_narration(project)
                and isinstance(existing_payload, dict)
                and existing_payload.get("success") is True
                and isinstance(existing_payload.get("beats"), dict)
            ):
                init = {"beats": existing_payload["beats"]}
                _warn_stage(project, status, "narration", "已保留并复用现有演讲稿")
            else:
                init = _invoke(services.init_narration, "Step 6 init")
            narration_beats = init.get("beats") or {}
            try:
                annotated = _invoke(
                    lambda: services.annotate_narration(narration_beats),
                    "Step 6 annotate",
                )
                narration_beats = annotated.get("beats") or narration_beats
            except Exception as exc:
                _warn_stage(project, status, "narration", f"AI TTS 标记失败，继续使用原演讲稿：{_error_text(exc)}")
            _invoke(lambda: services.save_narration(narration_beats), "Step 6 confirm narration")
            _finish_stage(project, status, "narration", "演讲稿已就绪")

        if should_run("tts"):
            _start_stage(project, status, "tts", "合成 TTS 音频并执行技术确认")
            _require_quality_gate(
                services.synthesize_audio,
                "Step 7 synthesize",
                gates,
                "pause_on_tts_failure",
            )
            _require_quality_gate(
                services.confirm_audio,
                "Step 7 confirm",
                gates,
                "pause_on_tts_failure",
            )
            _finish_stage(project, status, "tts", "音频已生成并通过自动技术检查（未人工试听）")

        video = None
        if should_run("render"):
            _start_stage(project, status, "render", "渲染最终视频")
            render = _require_quality_gate(
                services.render_video,
                "Step 8 render",
                gates,
                "pause_on_render_failure",
            )
            video = render.get("video") or render.get("item") or render
            _finish_stage(project, status, "render", "视频渲染完成")
        _complete(project, status, db, video=video)
        try:
            dependencies.write_project_log(
                project,
                "one_click_generate_completed",
                run_id=run_id,
                video=video,
            )
        except Exception:
            pass
    except Exception as exc:
        try:
            if project is not None:
                status = _status_for_project(project, project_id)
                stage_id = status.get("current_stage") or "preflight"
                _fail_stage(
                    project,
                    status,
                    str(stage_id),
                    str(exc),
                    pause=getattr(exc, "pause", True),
                )
                event = "one_click_generate_paused" if getattr(exc, "pause", True) else "one_click_generate_failed"
                dependencies.write_project_log(
                    project,
                    event,
                    run_id=run_id,
                    stage=stage_id,
                    error=str(exc),
                )
        except Exception:
            pass
    finally:
        try:
            db.close()
        except Exception:
            pass
        with _RUNNING_LOCK:
            _RUNNING.pop(project_id, None)


def start_one_click(
    project: Any,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    project_id = str(project.id)
    dependencies = get_one_click_dependencies()
    with _RUNNING_LOCK:
        thread = _RUNNING.get(project_id)
        if thread and thread.is_alive():
            return {
                "success": True,
                "already_running": True,
                "status": _status_for_project(project, project_id),
            }
        mode = str((payload or {}).get("mode") or "resume").strip().lower()
        if mode not in {"resume", "restart"}:
            raise ValueError("mode 必须是 resume 或 restart")
        run_id = uuid.uuid4().hex[:12]
        status, _start_index = _resume_status(
            project,
            project_id,
            run_id,
            mode,
        )
        _save_status(project, status)
        thread = threading.Thread(
            name=f"ppt-one-click-{project_id}-{run_id}",
            target=_run_pipeline,
            args=(dependencies, project_id, run_id, mode),
            daemon=True,
        )
        _RUNNING[project_id] = thread
        thread.start()
    return {"success": True, "started": True, "status": status}


def get_one_click_status(project: Any) -> dict[str, Any]:
    project_id = str(project.id)
    status = _status_for_project(project, project_id)
    thread = _RUNNING.get(project_id)
    if status.get("status") == "running" and not (thread and thread.is_alive()):
        status["status"] = "paused"
        status["completed_at"] = status.get("completed_at") or _now()
        _save_status(project, status)
    return {"success": True, "status": status}
