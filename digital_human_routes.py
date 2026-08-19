# -*- coding: utf-8 -*-
"""主系统数字人对接路由：项目级配置 + 代理数字人服务。

项目配置存储于 <run_dir>/planning/digital_human.json；
每页数字人视频存储于 <run_dir>/planning/digital_human/digi_<slide_id>.mp4。
音频取自第 7 步产物 <run_dir>/slides/<slide_id>/voice.mp3。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from database import get_db, Project
from pipeline_lifecycle import read_json_file, write_json_atomic
from digital_human_client import (
    DigitalHumanUnavailable,
    get_digital_human_client,
)

logger = logging.getLogger("PPTStudio.DigitalHumanRoutes")

router = APIRouter()

DIGI_DIRNAME = "digital_human"
CONFIG_FILENAME = "digital_human.json"
DEFAULT_CIRCLE = {"cx": 0.8, "cy": 0.2, "r": 0.25}  # 默认右下角


def _project_or_404(db: Session, project_id: str) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


def _planning_dir(project: Project) -> Path:
    return Path(str(project.run_dir)).resolve() / "planning"


def _digi_dir(project: Project) -> Path:
    return _planning_dir(project) / DIGI_DIRNAME


def _config_path(project: Project) -> Path:
    return _planning_dir(project) / CONFIG_FILENAME


def _default_config() -> Dict[str, Any]:
    return {
        "enabled": False,
        "mode": "upload",  # 'upload' 上传已生成视频 | 'generate' LatentSync 生成
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
    return cfg


def _save_config(project: Project, cfg: Dict[str, Any]) -> None:
    write_json_atomic(_config_path(project), cfg)


def _slide_audio_path(project: Project, slide_id: str) -> Path:
    return Path(str(project.run_dir)).resolve() / "slides" / slide_id / "voice.mp3"


def _slide_digi_path(project: Project, slide_id: str) -> Path:
    return _digi_dir(project) / f"digi_{slide_id}.mp4"


# ---------------- 配置 ----------------


def _upload_digi_path(project: Project) -> Path:
    """上传模式：已生成数字人视频（整个讲解视频）。"""
    return _digi_dir(project) / "digi_upload.mp4"


@router.get("/api/projects/{project_id}/digital-human/config")
def get_dh_config(project_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    project = _project_or_404(db, project_id)
    cfg = _load_config(project)
    # 附带每页音频是否就绪，便于前端判断可生成
    slides_info = {}
    for slide_id in cfg.get("slides", {}):
        item = cfg["slides"][slide_id]
        slides_info[slide_id] = {
            "job_id": item.get("job_id"),
            "status": item.get("status"),
            "video_exists": _slide_digi_path(project, slide_id).exists(),
        }
    return {
        "success": True,
        "config": {
            "enabled": cfg.get("enabled"),
            "mode": cfg.get("mode"),
            "avatar_id": cfg.get("avatar_id"),
            "sync_mode": cfg.get("sync_mode"),
            "circle": cfg.get("circle"),
            "video": cfg.get("video"),
            "position": cfg.get("position"),
            "border": cfg.get("border"),
        },
        "slides": slides_info,
        "audio_ready": {
            slide_id: _slide_audio_path(project, slide_id).exists()
            for slide_id in slides_info
        },
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
    for key in ("enabled", "mode", "avatar_id", "sync_mode", "position", "border"):
        if key in payload:
            cfg[key] = payload[key]
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
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="上传文件为空")
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
    _project_or_404(db, project_id)
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
    content = await file.read()
    import tempfile

    with tempfile.NamedTemporaryFile(
        suffix=Path(file.filename or "avatar.mp4").suffix or ".mp4",
        delete=False,
    ) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        return client.upload_avatar(name, tmp_path)
    except (DigitalHumanUnavailable, Exception) as exc:
        raise HTTPException(status_code=503, detail=str(exc))
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
    try:
        result = client.create_job(
            avatar_id=avatar_id,
            audio_path=audio_path,
            slide_id=slide_id,
            sync_mode=sync_mode,
        )
    except DigitalHumanUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    job_id = result.get("job_id")
    if job_id:
        slides = cfg.setdefault("slides", {})
        slides.setdefault(slide_id, {})
        slides[slide_id]["job_id"] = job_id
        slides[slide_id]["status"] = result.get("status")
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

    # 任务完成时拉取数字人视频到项目目录
    if job.get("status") == "done":
        project = _project_or_404(db, project_id)
        slide_id = job.get("slide_id")
        if slide_id:
            dest = _slide_digi_path(project, slide_id)
            if not dest.exists():
                try:
                    client.download_result(job_id, dest)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("download digi failed: %s", exc)
            cfg = _load_config(project)
            cfg.setdefault("slides", {}).setdefault(slide_id, {})["status"] = "done"
            _save_config(project, cfg)
            job = {**job, "video_exists": dest.exists()}
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
