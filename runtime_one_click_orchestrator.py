"""One-click generation orchestrator v1.

This runtime bridge adds a small in-process automation layer without rewriting the
large server.py module. V1 intentionally reuses existing FastAPI routes instead of
maintaining a second implementation of Step 2/3/5/6/7/8.

Scope:
- start a single in-process job per project;
- write resumable status to planning/one_click_status.json;
- execute existing steps in order;
- pause/fail with a blocking error when an existing step fails.

This is not a durable distributed queue. It is a local-app convenience layer that
keeps the user-facing workflow simple while preserving manual recovery paths.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any

PATCH_MARKER = "__ppt_one_click_orchestrator_patch__"
STATUS_FILENAME = "one_click_status.json"
INSTALL_TIMEOUT_SEC = 120.0

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

DEFAULT_QUALITY_GATES = {
    "pause_on_storyboard_validation_error": True,
    "pause_on_image_generation_failure": True,
    "pause_on_ai_mask_low_confidence": True,
    "pause_on_tts_failure": True,
    "pause_on_render_failure": True,
}

_RUNNING_LOCK = threading.Lock()
_RUNNING: dict[str, threading.Thread] = {}


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
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _run_dir(project: Any) -> Path:
    return Path(str(project.run_dir)).resolve()


def _status_path(project: Any) -> Path:
    return _run_dir(project) / "planning" / STATUS_FILENAME


def _profile_path(project: Any) -> Path:
    return _run_dir(project) / "planning" / "project_profile.json"


def _initial_status(project_id: str, run_id: str) -> dict[str, Any]:
    return {
        "version": "one_click_orchestrator_v1",
        "project_id": project_id,
        "run_id": run_id,
        "status": "running",
        "current_stage": "preflight",
        "started_at": _now(),
        "updated_at": _now(),
        "completed_at": "",
        "video": None,
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
    if isinstance(status, dict) and status.get("version") == "one_click_orchestrator_v1":
        return status
    return {
        "version": "one_click_orchestrator_v1",
        "project_id": project_id,
        "run_id": "",
        "status": "idle",
        "current_stage": "",
        "started_at": "",
        "updated_at": "",
        "completed_at": "",
        "video": None,
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


def _fail_stage(project: Any, status: dict[str, Any], stage_id: str, error: str) -> None:
    item = _stage(status, stage_id)
    item.update({"status": "failed", "finished_at": _now(), "progress": item.get("progress") or 0})
    item.setdefault("blocking_errors", []).append(_safe_text(error, 3000))
    status["status"] = "paused"
    status["current_stage"] = stage_id
    status["completed_at"] = _now()
    _save_status(project, status)


def _complete(project: Any, status: dict[str, Any], video: Any = None) -> None:
    status["status"] = "completed"
    status["current_stage"] = ""
    status["completed_at"] = _now()
    status["video"] = video
    _save_status(project, status)


def _http_error(response: Any) -> str:
    try:
        payload = response.json()
    except Exception:
        payload = {}
    detail = ""
    if isinstance(payload, dict):
        detail = payload.get("detail") or payload.get("message") or payload.get("error") or ""
    return _safe_text(detail or getattr(response, "text", "") or f"HTTP {response.status_code}", 3000)


def _require_ok(response: Any, label: str) -> dict[str, Any]:
    if response.status_code >= 400:
        raise RuntimeError(f"{label} failed: {_http_error(response)}")
    try:
        payload = response.json()
    except Exception as exc:
        raise RuntimeError(f"{label} returned non-JSON response: {exc}") from exc
    if isinstance(payload, dict) and payload.get("success") is False:
        raise RuntimeError(f"{label} failed: {_safe_text(payload.get('message') or payload.get('detail') or payload, 3000)}")
    return payload if isinstance(payload, dict) else {"value": payload}


def _has_contract(project: Any) -> bool:
    return (_run_dir(project) / "planning" / "visual_contract.json").exists()


def _has_article(project: Any) -> bool:
    return (_run_dir(project) / "planning" / "article_brief.json").exists()


def _slide_ids(project: Any) -> list[str]:
    contract = _read_json(_run_dir(project) / "planning" / "visual_contract.json", {})
    slides = contract.get("slides") if isinstance(contract, dict) else []
    return [str(slide.get("slide_id") or "").strip() for slide in slides if isinstance(slide, dict) and str(slide.get("slide_id") or "").strip()]


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _upstream_image_inputs(project: Any, slide_id: str) -> list[Path]:
    run_dir = _run_dir(project)
    paths = [
        run_dir / "planning" / "visual_contract.json",
        run_dir / "planning" / "step3_image_style.json",
        run_dir / "planning" / "project_style_references.json",
        run_dir / "slides" / slide_id / "visual_prompt.md",
    ]
    references_dir = run_dir / "planning" / "style_references"
    if references_dir.exists():
        paths.extend(sorted(references_dir.glob("style_reference_*.png"))[:3])
    return paths


def _image_needs_generation(project: Any, slide_id: str) -> bool:
    image_path = _run_dir(project) / "slides" / slide_id / "visual_draft.png"
    if not image_path.exists():
        return True
    image_mtime = _mtime(image_path)
    return any(_mtime(path) > image_mtime for path in _upstream_image_inputs(project, slide_id))


def _slides_requiring_images(project: Any) -> list[str]:
    return [slide_id for slide_id in _slide_ids(project) if _image_needs_generation(project, slide_id)]


def _profile(project: Any) -> dict[str, Any]:
    value = _read_json(_profile_path(project), {})
    return value if isinstance(value, dict) else {}


def _quality_gates(project: Any) -> dict[str, bool]:
    gates = (_profile(project).get("quality_gates") or {})
    if not isinstance(gates, dict):
        gates = {}
    return {key: bool(gates.get(key, default)) for key, default in DEFAULT_QUALITY_GATES.items()}


def _has_manual_mask(group: Any) -> bool:
    if not isinstance(group, dict):
        return False
    manual = group.get("manual_mask")
    if not isinstance(manual, dict):
        return False
    strokes = manual.get("strokes")
    return isinstance(strokes, list) and len(strokes) > 0


def _existing_mask_count(project: Any) -> int:
    manifest = _read_json(_run_dir(project) / "reveal_manifest.json", {})
    if not isinstance(manifest, dict):
        return 0
    count = 0
    for slide in manifest.get("slides", []) or []:
        if not isinstance(slide, dict):
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
    return errors


def _client(server_module: ModuleType) -> Any:
    from fastapi.testclient import TestClient
    return TestClient(server_module.app)


def _session_factory(server_module: ModuleType) -> Any:
    factory = getattr(server_module, "SessionLocal", None)
    if factory is not None:
        return factory
    from database import SessionLocal
    return SessionLocal


def _run_pipeline(server_module: ModuleType, project_id: str, run_id: str) -> None:
    db = _session_factory(server_module)()
    project = None
    try:
        project = db.query(server_module.Project).filter(server_module.Project.id == project_id).first()
        if not project:
            return
        status = _initial_status(project_id, run_id)
        _save_status(project, status)
        gates = _quality_gates(project)
        client = _client(server_module)

        _start_stage(project, status, "preflight", "检查文章、配置和项目目录")
        if not _has_article(project):
            raise RuntimeError("请先导入文章内容，或在创建项目时填写文章内容。")
        _finish_stage(project, status, "preflight", "预检查通过")

        _start_stage(project, status, "storyboard", "生成或复用 visual_contract.json")
        if not _has_contract(project):
            _require_ok(client.post(f"/api/projects/{project_id}/steps/2/script/execute", json={}), "Step 2 article-to-slide")
            _require_ok(client.post(f"/api/projects/{project_id}/steps/2/visual/execute", json={}), "Step 2 slide-to-visual")
            _require_ok(client.post(f"/api/projects/{project_id}/steps/2/compose", json={}), "Step 2 compose")
            db.refresh(project)
        _finish_stage(project, status, "storyboard", "分镜规划已就绪")

        _start_stage(project, status, "images", "生成缺失或过期的 slide 图片")
        prompts_payload = _require_ok(client.get(f"/api/projects/{project_id}/steps/3/prompts"), "Step 3 prompts")
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
            _require_ok(client.post(f"/api/projects/{project_id}/steps/3/generate", data={"slide_id": slide_id, "prompt": prompt, "preview": "false"}), f"Step 3 image {slide_id}")
            generated += 1
        _finish_stage(project, status, "images", f"图片已就绪，新增或刷新 {generated} 张")

        _start_stage(project, status, "confirm_images", "确认图片并创建 reveal_manifest.json")
        _require_ok(client.post(f"/api/projects/{project_id}/steps/3/confirm"), "Step 3 confirm")
        _finish_stage(project, status, "confirm_images", "图片已确认")

        _start_stage(project, status, "ai_mask", "执行 AI Mask 标注")
        ai_mask_payload = {"settings": {"overwrite_existing_manual_mask": True, "skip_locked_groups": False}}
        ai_mask = client.post(f"/api/projects/{project_id}/steps/5/ai-mask/annotate", json=ai_mask_payload)
        if ai_mask.status_code == 404:
            ai_mask = client.post(f"/api/projects/{project_id}/steps/5/semantic-blocks", json={})
        result = _require_ok(ai_mask, "AI Mask")
        existing_masks = _existing_mask_count(project)
        quality_errors = _ai_mask_quality_errors(result, existing_masks)
        if quality_errors:
            _warn_stage(project, status, "ai_mask", "首次标注未完整，正在自动重试")
            retry = _require_ok(
                client.post(f"/api/projects/{project_id}/steps/5/ai-mask/annotate", json=ai_mask_payload),
                "AI Mask retry",
            )
            existing_masks = _existing_mask_count(project)
            quality_errors = _ai_mask_quality_errors(retry, existing_masks)
            result = retry
            if quality_errors and gates.get("pause_on_ai_mask_low_confidence", True):
                raise RuntimeError("AI Mask 自动重试后仍未完成：" + "；".join(quality_errors[:5]))
        _finish_stage(project, status, "ai_mask", "AI Mask 标注完成")

        _start_stage(project, status, "mask_assets", "构建 Reveal 资源")
        manifest_payload = _require_ok(client.get(f"/api/projects/{project_id}/steps/5/result"), "Step 5 manifest")
        manifest = manifest_payload.get("manifest")
        if not isinstance(manifest, dict):
            raise RuntimeError("Step 5 manifest 返回为空")
        _require_ok(client.put(f"/api/projects/{project_id}/steps/5/result", json=manifest), "Step 5 build assets")
        _finish_stage(project, status, "mask_assets", "Reveal 资源已构建")

        _start_stage(project, status, "narration", "生成演讲稿并尝试添加 TTS 标记")
        init = _require_ok(client.post(f"/api/projects/{project_id}/steps/6/init"), "Step 6 init")
        annotate = client.post(f"/api/projects/{project_id}/steps/6/annotate", json=init.get("beats") or {})
        if annotate.status_code >= 400:
            _warn_stage(project, status, "narration", f"AI TTS 标记失败，继续使用原演讲稿：{_http_error(annotate)}")
        _finish_stage(project, status, "narration", "演讲稿已就绪")

        _start_stage(project, status, "tts", "合成 TTS 音频并确认")
        _require_ok(client.post(f"/api/projects/{project_id}/steps/7/synthesize"), "Step 7 synthesize")
        _require_ok(client.post(f"/api/projects/{project_id}/steps/7/confirm"), "Step 7 confirm")
        _finish_stage(project, status, "tts", "音频已生成并确认")

        _start_stage(project, status, "render", "渲染最终视频")
        render = _require_ok(client.post(f"/api/projects/{project_id}/steps/8/render"), "Step 8 render")
        video = render.get("video") or render.get("item") or render
        _finish_stage(project, status, "render", "视频渲染完成")
        _complete(project, status, video=video)
        try:
            server_module.write_project_log(project, "one_click_generate_completed", run_id=run_id, video=video)
        except Exception:
            pass
    except Exception as exc:
        try:
            if project is not None:
                status = _status_for_project(project, project_id)
                stage_id = status.get("current_stage") or "preflight"
                _fail_stage(project, status, str(stage_id), str(exc))
                server_module.write_project_log(project, "one_click_generate_paused", run_id=run_id, stage=stage_id, error=str(exc))
        except Exception:
            pass
    finally:
        try:
            db.close()
        except Exception:
            pass
        with _RUNNING_LOCK:
            _RUNNING.pop(project_id, None)


def _register(server_module: ModuleType) -> bool:
    if getattr(server_module, PATCH_MARKER, False):
        return True
    required = ("app", "Project", "HTTPException", "Depends", "get_db")
    if not all(hasattr(server_module, item) for item in required):
        return False
    app = server_module.app

    def start_one_click(project_id: str, payload: dict[str, Any] | None = None, db: Any = server_module.Depends(server_module.get_db)) -> dict[str, Any]:
        project = db.query(server_module.Project).filter(server_module.Project.id == project_id).first()
        if not project:
            raise server_module.HTTPException(status_code=404, detail="项目不存在")
        with _RUNNING_LOCK:
            thread = _RUNNING.get(project_id)
            if thread and thread.is_alive():
                return {"success": True, "already_running": True, "status": _status_for_project(project, project_id)}
            run_id = uuid.uuid4().hex[:12]
            status = _initial_status(project_id, run_id)
            _save_status(project, status)
            thread = threading.Thread(name=f"ppt-one-click-{project_id}-{run_id}", target=_run_pipeline, args=(server_module, project_id, run_id), daemon=True)
            _RUNNING[project_id] = thread
            thread.start()
        return {"success": True, "started": True, "status": status}

    def get_one_click_status(project_id: str, db: Any = server_module.Depends(server_module.get_db)) -> dict[str, Any]:
        project = db.query(server_module.Project).filter(server_module.Project.id == project_id).first()
        if not project:
            raise server_module.HTTPException(status_code=404, detail="项目不存在")
        status = _status_for_project(project, project_id)
        thread = _RUNNING.get(project_id)
        if status.get("status") == "running" and not (thread and thread.is_alive()):
            status["status"] = "paused"
            status["completed_at"] = status.get("completed_at") or _now()
            _save_status(project, status)
        return {"success": True, "status": status}

    app.add_api_route("/api/projects/{project_id}/one-click-generate", start_one_click, methods=["POST"])
    app.add_api_route("/api/projects/{project_id}/one-click-generate/status", get_one_click_status, methods=["GET"])
    setattr(server_module, PATCH_MARKER, True)
    return True


def _candidate_modules() -> list[ModuleType]:
    return [module for module in list(sys.modules.values()) if isinstance(module, ModuleType) and hasattr(module, "app") and hasattr(module, "Project")]


def _log_timeout() -> None:
    for module in _candidate_modules():
        logger = getattr(module, "logger", None)
        if logger:
            logger.warning("One-click orchestrator bridge was not installed within %.0f seconds; server app or database helpers may be missing.", INSTALL_TIMEOUT_SEC)
            return


def _install_when_ready() -> None:
    def worker() -> None:
        started_at = time.monotonic()
        while not os.environ.get("PPT_STUDIO_DISABLE_ONE_CLICK_ORCHESTRATOR"):
            for module in _candidate_modules():
                try:
                    if _register(module):
                        return
                except Exception:
                    return
            if time.monotonic() - started_at > INSTALL_TIMEOUT_SEC:
                _log_timeout()
                return
            time.sleep(0.1)
    threading.Thread(name="ppt-one-click-orchestrator-runtime", target=worker, daemon=True).start()


_install_when_ready()
