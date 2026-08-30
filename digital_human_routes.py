# -*- coding: utf-8 -*-
"""主系统数字人对接路由：项目级配置 + 代理数字人服务。

项目配置存储于 <run_dir>/planning/digital_human.json；
每页数字人视频存储于 <run_dir>/planning/digital_human/digi_<slide_id>.mp4。
音频取自第 7 步产物 <run_dir>/slides/<slide_id>/voice.mp3。
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from database import get_db, Project
from pipeline_lifecycle import read_json_file, write_json_atomic

REPO_ROOT = Path(__file__).resolve().parent
from digital_human_client import (
    DigitalHumanUnavailable,
    get_digital_human_client,
)
from visual_contract_service import read_contract_slide_ids

logger = logging.getLogger("PPTStudio.DigitalHumanRoutes")

router = APIRouter()

DIGI_DIRNAME = "digital_human"
CONFIG_FILENAME = "digital_human.json"
DEFAULT_CIRCLE = {"cx": 0.8, "cy": 0.2, "r": 0.25}  # 默认右下角

# ---- 上传安全限制 ----
MAX_UPLOAD_VIDEO_BYTES = int(
    os.environ.get("PPT_MAX_UPLOAD_VIDEO_BYTES", str(2 * 1024 * 1024 * 1024))  # 2GB
)
MAX_AVATAR_UPLOAD_BYTES = int(
    os.environ.get("PPT_MAX_AVATAR_UPLOAD_BYTES", str(200 * 1024 * 1024))  # 200MB，与 digital_human_service.MAX_AVATAR_BYTES 保持一致
)
MAX_WORKFLOW_BYTES = int(
    os.environ.get("PPT_MAX_WORKFLOW_BYTES", str(1024 * 1024))  # 1MB
)
MAX_WORKFLOW_NODES = int(
    os.environ.get("PPT_MAX_WORKFLOW_NODES", "500")
)
ALLOWED_VIDEO_MIMES = {
    "video/mp4", "video/quicktime", "video/x-msvideo",
    "video/x-matroska", "application/octet-stream",  # 部分浏览器不发送正确 MIME
}
ALLOWED_WORKFLOW_MIMES = {
    "application/json", "text/plain", "application/octet-stream",
}


def _validate_upload(
    content: bytes,
    file: UploadFile,
    max_bytes: int,
    allowed_mimes: set[str],
) -> None:
    """统一的文件上传校验：大小 + MIME 类型。"""
    if not content:
        raise HTTPException(status_code=400, detail="上传文件为空")
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=(
                f"文件过大：{len(content) // 1048576}MB，"
                f"上限 {max_bytes // 1048576}MB"
            ),
        )
    mime = (file.content_type or "").lower()
    if mime and mime not in allowed_mimes:
        raise HTTPException(
            status_code=415,
            detail=f"不支持的文件类型：{mime}，允许：{', '.join(sorted(allowed_mimes))}",
        )


# 视频/头像上传的扩展名白名单（octet-stream 通融时的第二道校验，审查 L-03）
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm"}


def _validate_video_extension(filename: str | None) -> None:
    ext = Path(str(filename or "")).suffix.lower()
    if ext and ext not in VIDEO_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=(
                f"不支持的文件扩展名：{ext}，"
                f"允许：{', '.join(sorted(VIDEO_EXTENSIONS))}"
            ),
        )


from project_path_service import project_or_404 as _project_or_404


def _planning_dir(project: Project) -> Path:
    return Path(str(project.run_dir)).resolve() / "planning"


def _digi_dir(project: Project) -> Path:
    return _planning_dir(project) / DIGI_DIRNAME


def _config_path(project: Project) -> Path:
    return _planning_dir(project) / CONFIG_FILENAME


def _default_config() -> Dict[str, Any]:
    return {
        "enabled": False,
        "mode": "comfyui",  # 'comfyui' ComfyUI 生成 | 'upload' 导入已生成视频
        "shape": "circle",  # 窗口形状 'circle' | 'rect'
        "avatar_id": "",
        "sync_mode": "accurate",
        "circle": dict(DEFAULT_CIRCLE),  # 框在页面位置(cx,cy) + 大小(r)
        "video": {"ox": 0.5, "oy": 0.5, "zoom": 1.0},  # 视频与框相对位置
        "position": None,
        "border": {"width": 2, "color": "#FFFFFF"},
        "slides": {},
    }


def _load_config(project: Project) -> Dict[str, Any]:
    raw = read_json_file(_config_path(project))
    if not isinstance(raw, dict):
        raw = {}
    cfg = _default_config()
    cfg.update({k: v for k, v in raw.items() if k in cfg})
    if not isinstance(cfg["circle"], dict):
        cfg["circle"] = dict(DEFAULT_CIRCLE)
    if not isinstance(cfg.get("video"), dict):
        cfg["video"] = {"ox": 0.5, "oy": 0.5, "zoom": 1.0}
    if cfg.get("shape") not in ("circle", "rect"):
        cfg["shape"] = "circle"
    if cfg.get("mode") not in ("comfyui", "upload", "generate"):
        cfg["mode"] = "comfyui"
    return cfg


def _save_config(project: Project, cfg: Dict[str, Any]) -> None:
    write_json_atomic(_config_path(project), cfg)


_SLIDE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _assert_safe_slide_id(slide_id: str) -> None:
    if not _SLIDE_ID_RE.match(slide_id or ""):
        raise HTTPException(status_code=400, detail="slide_id 无效")


def _slide_audio_path(project: Project, slide_id: str) -> Path:
    _assert_safe_slide_id(slide_id)
    return Path(str(project.run_dir)).resolve() / "slides" / slide_id / "voice.mp3"


def _slide_digi_path(project: Project, slide_id: str) -> Path:
    _assert_safe_slide_id(slide_id)
    return _digi_dir(project) / f"digi_{slide_id}.mp4"


# ---------------- 配置 ----------------


def _upload_digi_path(project: Project) -> Path:
    """上传模式：已生成数字人视频（整个讲解视频）。"""
    return _digi_dir(project) / "digi_upload.mp4"


@router.get("/api/projects/{project_id}/digital-human/config")
def get_dh_config(project_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    project = _project_or_404(db, project_id)
    cfg = _load_config(project)
    # 从 Visual Contract 获取全部 slide ID（不局限于已生成过的）
    contract_ids = read_contract_slide_ids(project.run_dir)
    # 附带每页音频是否就绪、生成状态
    slides_info = {}
    for slide_id in contract_ids:
        item = cfg.get("slides", {}).get(slide_id, {})
        audio_ok = _slide_audio_path(project, slide_id).exists()
        slides_info[slide_id] = {
            "job_id": item.get("job_id"),
            "status": item.get("status"),
            "video_exists": _slide_digi_path(project, slide_id).exists(),
            "audio_ready": audio_ok,
        }
    audio_ready_count = sum(1 for s in slides_info.values() if s["audio_ready"])
    # 附带整段数字人生成状态（如有）
    full_item = cfg.get("slides", {}).get("full", {})
    if full_item:
        slides_info["full"] = {
            "job_id": full_item.get("job_id"),
            "status": full_item.get("status"),
            "video_exists": _slide_digi_path(project, "full").exists(),
            "audio_ready": _full_audio_path(project).exists(),
        }
    return {
        "success": True,
        "config": {
            "enabled": cfg.get("enabled"),
            "mode": cfg.get("mode"),
            "shape": cfg.get("shape"),
            "avatar_id": cfg.get("avatar_id"),
            "sync_mode": cfg.get("sync_mode"),
            "circle": cfg.get("circle"),
            "video": cfg.get("video"),
            "position": cfg.get("position"),
            "border": cfg.get("border"),
        },
        "slides": slides_info,
        "audio_ready": {
            slide_id: info["audio_ready"]
            for slide_id, info in slides_info.items()
        },
        "audio_ready_count": audio_ready_count,
        "total_slides": len(contract_ids),
        "upload_video_exists": _upload_digi_path(project).exists(),
    }


@router.put("/api/projects/{project_id}/digital-human/config")
def put_dh_config(
    project_id: str,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    project = _project_or_404(db, project_id)
    cfg = _load_config(project)
    for key in ("enabled", "mode", "shape", "avatar_id", "sync_mode", "position", "border"):
        if key in payload:
            cfg[key] = payload[key]
    if cfg.get("shape") not in ("circle", "rect"):
        cfg["shape"] = "circle"
    if isinstance(payload.get("circle"), dict):
        circle = dict(cfg.get("circle") or DEFAULT_CIRCLE)
        circle.update(
            {k: v for k, v in payload["circle"].items() if k in ("cx", "cy", "r")}
        )
        cfg["circle"] = circle
    if isinstance(payload.get("video"), dict):
        video = dict(cfg.get("video") or {"ox": 0.5, "oy": 0.5, "zoom": 1.0})
        video.update(
            {k: v for k, v in payload["video"].items() if k in ("ox", "oy", "zoom")}
        )
        cfg["video"] = video
    _save_config(project, cfg)
    return {"success": True, "config": cfg}


# ---------------- 上传已生成数字人视频（upload 模式） ----------------


@router.post("/api/projects/{project_id}/digital-human/upload")
async def upload_dh_video(
    project_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    project = _project_or_404(db, project_id)
    # 有界读取：最多多读 1 字节用于超限判定，避免超大文件全量进内存
    content = await file.read(MAX_UPLOAD_VIDEO_BYTES + 1)
    _validate_upload(content, file, MAX_UPLOAD_VIDEO_BYTES, ALLOWED_VIDEO_MIMES)
    _validate_video_extension(file.filename)
    _digi_dir(project).mkdir(parents=True, exist_ok=True)
    dest = _upload_digi_path(project)
    tmp = dest.with_suffix(".mp4.tmp")
    tmp.write_bytes(content)
    tmp.replace(dest)
    cfg = _load_config(project)
    cfg["mode"] = "upload"
    cfg["enabled"] = True
    _save_config(project, cfg)
    return {
        "success": True,
        "mode": "upload",
        "filename": file.filename or dest.name,
        "bytes": len(content),
        "url": f"/api/projects/{project_id}/digital-human/upload/video",
    }


@router.get("/api/projects/{project_id}/digital-human/upload/video")
def get_dh_upload_video(
    project_id: str,
    db: Session = Depends(get_db),
) -> FileResponse:
    project = _project_or_404(db, project_id)
    path = _upload_digi_path(project)
    if not path.exists():
        raise HTTPException(status_code=404, detail="尚未上传数字人视频")
    return FileResponse(str(path), media_type="video/mp4")


# ---------------- 数字人服务状态 ----------------


@router.get("/api/projects/{project_id}/digital-human/health")
def dh_health(project_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    _project_or_404(db, project_id)
    client = get_digital_human_client()
    try:
        return client.health()
    except DigitalHumanUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))


# ---------------- 形象（参考视频） ----------------


@router.post("/api/projects/{project_id}/digital-human/avatars")
async def upload_dh_avatar(
    project_id: str,
    name: str = "数字人形象",
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _project_or_404(db, project_id)
    client = get_digital_human_client()
    content = await file.read(MAX_AVATAR_UPLOAD_BYTES + 1)
    _validate_upload(content, file, MAX_AVATAR_UPLOAD_BYTES, ALLOWED_VIDEO_MIMES)
    _validate_video_extension(file.filename)
    import tempfile

    with tempfile.NamedTemporaryFile(
        suffix=Path(file.filename or "avatar.mp4").suffix or ".mp4",
        delete=False,
    ) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        return client.upload_avatar(name, tmp_path)
    except DigitalHumanUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.exception("upload_avatar 内部错误")
        raise HTTPException(status_code=500, detail=f"内部错误: {exc}")
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


@router.get("/api/projects/{project_id}/digital-human/avatars")
def list_dh_avatars(project_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    _project_or_404(db, project_id)
    client = get_digital_human_client()
    try:
        return {"success": True, "avatars": client.list_avatars()}
    except DigitalHumanUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))


# ---------------- ComfyUI 工作流模板上传 ----------------


@router.post("/api/projects/{project_id}/digital-human/comfyui/workflow")
async def upload_comfyui_workflow(
    project_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """上传 ComfyUI API 格式工作流 JSON 模板。"""
    project = _project_or_404(db, project_id)
    content = await file.read(MAX_WORKFLOW_BYTES + 1)
    _validate_upload(content, file, MAX_WORKFLOW_BYTES, ALLOWED_WORKFLOW_MIMES)
    try:
        import json as _json
        wf = _json.loads(content)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"JSON 解析失败: {exc}")
    if not isinstance(wf, dict):
        raise HTTPException(status_code=400, detail="工作流 JSON 格式不正确")
    if len(wf) > MAX_WORKFLOW_NODES:
        raise HTTPException(
            status_code=400,
            detail=f"工作流节点数过多：{len(wf)}（上限 {MAX_WORKFLOW_NODES}）",
        )
    _digi_dir(project).mkdir(parents=True, exist_ok=True)
    wf_path = _digi_dir(project) / "comfyui_workflow.json"
    wf_path.write_bytes(content)
    cfg = _load_config(project)
    cfg["mode"] = "comfyui"
    _save_config(project, cfg)
    node_count = len(wf)
    return {"success": True, "nodes": node_count, "saved": str(wf_path)}


@router.get("/api/projects/{project_id}/digital-human/comfyui/workflow")
def get_comfyui_workflow(
    project_id: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """返回已保存的工作流模板是否存在及节点数。"""
    project = _project_or_404(db, project_id)
    wf_path = _digi_dir(project) / "comfyui_workflow.json"
    if not wf_path.exists():
        return {"success": True, "exists": False}
    try:
        import json as _json
        wf = _json.loads(wf_path.read_text(encoding="utf-8"))
        return {"success": True, "exists": True, "nodes": len(wf)}
    except Exception:
        return {"success": True, "exists": True, "nodes": 0}


# ---------------- 生成任务（手动触发） ----------------


@router.post("/api/projects/{project_id}/digital-human/generate/{slide_id}")
def generate_dh(
    project_id: str,
    slide_id: str,
    payload: Optional[Dict[str, Any]] = None,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    project = _project_or_404(db, project_id)
    cfg = _load_config(project)
    avatar_id = str(
        (payload or {}).get("avatar_id") or cfg.get("avatar_id") or ""
    ).strip()
    if not avatar_id:
        raise HTTPException(status_code=400, detail="请先上传并选择数字人形象")
    sync_mode = str((payload or {}).get("sync_mode") or cfg.get("sync_mode") or "accurate")

    audio_path = _slide_audio_path(project, slide_id)
    if not audio_path.exists():
        raise HTTPException(status_code=400, detail="当前页面音频未生成，请先完成旁白合成")

    client = get_digital_human_client()
    # 构建 create_job payload，附加 ComfyUI 专用字段
    job_payload: Dict[str, Any] = {
        "avatar_id": avatar_id,
        "audio_path": str(audio_path),
        "slide_id": slide_id,
        "sync_mode": sync_mode,
    }
    if cfg.get("mode") == "comfyui":
        job_payload["backend"] = "comfyui"
        # 附带工作流模板（如有）；画质参数由工作流 JSON 自身决定
        wf_path = _digi_dir(project) / "comfyui_workflow.json"
        if wf_path.exists():
            try:
                import json as _json
                job_payload["workflow_template"] = _json.loads(wf_path.read_text(encoding="utf-8"))
            except Exception:
                pass

    try:
        result = client.create_job(payload=job_payload)
    except DigitalHumanUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.exception("[dh-generate] create_job failed")
        raise HTTPException(status_code=500, detail=f"提交数字人生成任务失败: {exc}")

    job_id = result.get("job_id")
    if job_id:
        slides = cfg.setdefault("slides", {})
        slides.setdefault(slide_id, {})
        slides[slide_id]["job_id"] = job_id
        slides[slide_id]["status"] = result.get("status")
        _save_config(project, cfg)
    return {"success": True, "job_id": job_id, "status": result.get("status")}


# ---------------- 生成整段数字人视频（单任务） ----------------


@router.post("/api/projects/{project_id}/digital-human/generate-full")
def generate_dh_full(
    project_id: str,
    payload: Optional[Dict[str, Any]] = None,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """使用整段导出音频创建一个数字人生成任务（合并所有页面音频为一段）。"""
    project = _project_or_404(db, project_id)
    cfg = _load_config(project)
    avatar_id = str(
        (payload or {}).get("avatar_id") or cfg.get("avatar_id") or ""
    ).strip()
    if not avatar_id:
        raise HTTPException(status_code=400, detail="请先上传并选择数字人形象")

    audio_path = _full_audio_path(project)
    if not audio_path.exists():
        raise HTTPException(status_code=400, detail="请先导出整段语音")

    sync_mode = str((payload or {}).get("sync_mode") or cfg.get("sync_mode") or "accurate")
    client = get_digital_human_client()
    job_payload: Dict[str, Any] = {
        "avatar_id": avatar_id,
        "audio_path": str(audio_path),
        "slide_id": "full",
        "sync_mode": sync_mode,
    }
    if cfg.get("mode") == "comfyui":
        job_payload["backend"] = "comfyui"
        wf_path = _digi_dir(project) / "comfyui_workflow.json"
        if wf_path.exists():
            try:
                import json as _json
                job_payload["workflow_template"] = _json.loads(wf_path.read_text(encoding="utf-8"))
            except Exception:
                pass

    try:
        result = client.create_job(payload=job_payload)
    except DigitalHumanUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.exception("[dh-generate-full] create_job failed")
        raise HTTPException(status_code=500, detail=f"提交数字人生成任务失败: {exc}")

    job_id = result.get("job_id")
    if job_id:
        slides = cfg.setdefault("slides", {})
        slides["full"] = {"job_id": job_id, "status": result.get("status")}
        _save_config(project, cfg)
    return {"success": True, "job_id": job_id, "status": result.get("status")}


@router.get("/api/projects/{project_id}/digital-human/jobs/{job_id}")
def get_dh_job(
    project_id: str,
    job_id: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _project_or_404(db, project_id)
    client = get_digital_human_client()
    try:
        job = client.get_job(job_id)
    except DigitalHumanUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"任务不存在: {exc}")

    # 任务完成时拉取数字人视频到项目目录（始终覆盖旧文件）
    job_status = job.get("status")
    if job_status in ("done", "failed"):
        project = _project_or_404(db, project_id)
        slide_id = job.get("slide_id")
        if slide_id:
            cfg = _load_config(project)
            cfg.setdefault("slides", {}).setdefault(slide_id, {})["status"] = job_status
            if job_status == "done":
                dest = _slide_digi_path(project, slide_id)
                try:
                    client.download_result(job_id, dest)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("download digi failed: %s", exc)
                job = {**job, "video_exists": dest.exists()}
            _save_config(project, cfg)
    return {"success": True, "job": job}


@router.get("/api/projects/{project_id}/digital-human/slides/{slide_id}/video")
def get_dh_slide_video(
    project_id: str,
    slide_id: str,
    db: Session = Depends(get_db),
) -> FileResponse:
    project = _project_or_404(db, project_id)
    path = _slide_digi_path(project, slide_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="数字人视频尚未生成")
    return FileResponse(str(path), media_type="video/mp4")


# ---------------- 圆形窗口合成（导出） ----------------


@router.post("/api/projects/{project_id}/digital-human/composite/{slide_id}")
def compose_dh_slide(
    project_id: str,
    slide_id: str,
    payload: Optional[Dict[str, Any]] = None,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    project = _project_or_404(db, project_id)
    cfg = _load_config(project)
    # 上传模式优先用已上传的讲解视频；否则用按页生成的数字人视频
    upload_video = _upload_digi_path(project)
    digi = upload_video if (cfg.get("mode") == "upload" and upload_video.exists()) else _slide_digi_path(project, slide_id)
    if not digi.exists():
        raise HTTPException(status_code=400, detail="数字人视频未就绪：请先上传已生成的讲解视频")

    body = payload or {}
    circle = body.get("circle") if isinstance(body.get("circle"), dict) else cfg.get("circle")
    video = body.get("video") if isinstance(body.get("video"), dict) else cfg.get("video")
    shape = str(body.get("shape") or cfg.get("shape") or "circle")
    position = body.get("position") if isinstance(body.get("position"), dict) else cfg.get("position")
    border = body.get("border") if isinstance(body.get("border"), dict) else cfg.get("border")
    base_video = str(body.get("base_video") or "").strip() or None
    output = str(body.get("output") or "").strip()
    if not output:
        output = str(_digi_dir(project) / f"composite_{slide_id}.mp4")

    client = get_digital_human_client()
    try:
        result = client.composite(
            digi_video=digi,
            base_video=base_video,
            output=output,
            circle=circle or DEFAULT_CIRCLE,
            video=video,
            position=position,
            border=border,
            shape=shape,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    result["output_url"] = (
        f"/api/projects/{project_id}/digital-human/composite/{slide_id}/video"
    )
    return result


@router.get(
    "/api/projects/{project_id}/digital-human/composite/{slide_id}/video"
)
def get_dh_composite_video(
    project_id: str,
    slide_id: str,
    db: Session = Depends(get_db),
) -> FileResponse:
    project = _project_or_404(db, project_id)
    path = _digi_dir(project) / f"composite_{slide_id}.mp4"
    if not path.exists():
        raise HTTPException(status_code=404, detail="合成视频不存在")
    return FileResponse(str(path), media_type="video/mp4")


# ---------------- 整段语音导出（供离线生成数字人视频） ----------------


def _full_audio_path(project: Project) -> Path:
    return _digi_dir(project) / "audio_full.mp3"


def _find_ffmpeg() -> str:
    """定位 ffmpeg/ffprobe（优先使用项目内 Remotion 自带版本，避免外部精简版不兼容）。"""
    import shutil

    # 优先：项目内 Remotion 自带的 ffmpeg（完整版，兼容性最好）
    remotion_ff = REPO_ROOT / "scripts" / "remotion" / "node_modules" / \
        "@remotion" / "compositor-win32-x64-msvc" / "ffmpeg.exe"
    if remotion_ff.exists():
        return str(remotion_ff)

    # 次选：环境变量指定的目录
    candidates = [
        os.environ.get("PPT_STUDIO_FFMPEG_DIR", ""),
        os.environ.get("PPT_DIGITAL_HUMAN_FFMPEG_DIR", ""),
    ]
    for cand in candidates:
        if cand and (Path(cand) / "ffmpeg.exe").exists():
            return str(Path(cand) / "ffmpeg.exe")

    # 最后回退到 PATH 上的 ffmpeg
    found = shutil.which("ffmpeg")
    if found:
        return found
    raise HTTPException(status_code=503, detail="未找到 ffmpeg，无法导出整段语音")


def _find_ffprobe() -> str:
    ffmpeg = _find_ffmpeg()
    if ffmpeg.lower().endswith("ffmpeg.exe"):
        probe = Path(ffmpeg).with_name("ffprobe.exe")
        if probe.exists():
            return str(probe)
    found = shutil.which("ffprobe")
    return found or ffmpeg


def _full_audio_ready(project: Project) -> bool:
    return _full_audio_path(project).exists()


@router.post("/api/projects/{project_id}/digital-human/export-audio")
def export_full_audio(
    project_id: str,
    payload: Optional[Dict[str, Any]] = None,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """按页面顺序拼接全部 voice.mp3（页间加 0.6s 静音）为一段完整课程语音。"""
    project = _project_or_404(db, project_id)
    slide_ids = read_contract_slide_ids(project.run_dir)
    audio_files = [_slide_audio_path(project, sid) for sid in slide_ids]
    audio_files = [p for p in audio_files if p.exists() and p.stat().st_size > 0]
    if not audio_files:
        raise HTTPException(status_code=400, detail="未找到任何已生成的旁白音频，请先完成音频合成")

    ffmpeg = _find_ffmpeg()
    gap = max(0.0, min(3.0, float((payload or {}).get("gap_sec") or 0.6)))
    out = _full_audio_path(project)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = out.parent / ".tmp_audio_export"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    n = len(audio_files)
    logger.info("[audio-export] 开始拼接 %d 页音频，间隔 %.1fs", n, gap)

    try:
        # 方案：逐页转码为统一格式 wav，生成静音片段，再用 concat demuxer 拼接
        normalized_files: list[Path] = []
        for i, af in enumerate(audio_files):
            norm_path = tmp_dir / f"norm_{i:04d}.wav"
            cmd_norm = [ffmpeg, "-y", "-i", str(af),
                        "-ar", "44100", "-ac", "2", "-sample_fmt", "s16",
                        str(norm_path)]
            proc_n = subprocess.run(cmd_norm, capture_output=True, text=True, timeout=120)
            if proc_n.returncode != 0:
                raise RuntimeError(f"转码第 {i+1} 页音频失败: {(proc_n.stderr or '')[-400:]}")
            normalized_files.append(norm_path)

        # 生成静音片段
        silence_path = tmp_dir / "silence.wav"
        if gap > 0:
            cmd_sil = [ffmpeg, "-y", "-f", "lavfi", "-i",
                       f"anullsrc=r=44100:cl=stereo", "-t", str(gap),
                       "-sample_fmt", "s16", str(silence_path)]
            proc_s = subprocess.run(cmd_sil, capture_output=True, text=True, timeout=30)
            if proc_s.returncode != 0:
                raise RuntimeError(f"生成静音片段失败: {(proc_s.stderr or '')[-400:]}")

        # 写 concat 列表文件
        concat_list = tmp_dir / "concat_list.txt"
        lines = []
        for i, nf in enumerate(normalized_files):
            # Windows 路径需要转义反斜杠和单引号
            safe = str(nf).replace("\\", "/").replace("'", "\\'")
            lines.append(f"file '{safe}'")
            if i < n - 1 and gap > 0:
                safe_sil = str(silence_path).replace("\\", "/").replace("'", "\\'")
                lines.append(f"file '{safe_sil}'")
        concat_list.write_text("\n".join(lines), encoding="utf-8")

        # 用 concat demuxer 拼接，输出 mp3
        cmd_concat = [ffmpeg, "-y", "-f", "concat", "-safe", "0",
                      "-i", str(concat_list),
                      "-c:a", "libmp3lame", "-b:a", "192k", str(out)]
        logger.info("[audio-export] concat demuxer: %s", " ".join(cmd_concat))
        proc_c = subprocess.run(cmd_concat, capture_output=True, text=True, timeout=900)
        if proc_c.returncode != 0:
            raise RuntimeError((proc_c.stderr or "")[-800:])

    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=f"整段语音导出失败: {exc}")
    finally:
        # 清理临时文件
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)

    duration = None
    try:
        probe = subprocess.run(
            [_find_ffprobe(), "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=s=x:p=0", str(out)],
            capture_output=True, text=True, timeout=30,
        )
        duration = float(probe.stdout.strip()) if probe.returncode == 0 else None
    except Exception:  # noqa: BLE001
        duration = None

    return {
        "success": True,
        "slides": len(audio_files),
        "gap_sec": gap,
        "duration_sec": duration,
        "bytes": out.stat().st_size,
        "url": f"/api/projects/{project_id}/digital-human/export-audio/file",
    }


@router.get("/api/projects/{project_id}/digital-human/export-audio/file")
def get_full_audio(
    project_id: str,
    db: Session = Depends(get_db),
) -> FileResponse:
    project = _project_or_404(db, project_id)
    path = _full_audio_path(project)
    if not path.exists():
        raise HTTPException(status_code=404, detail="整段语音尚未导出")
    return FileResponse(str(path), media_type="audio/mpeg", filename="course_audio_full.mp3")
