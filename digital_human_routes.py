# -*- coding: utf-8 -*-
"""主系统数字人对接路由：项目级配置 + 代理数字人服务。

项目配置存储于 <run_dir>/planning/digital_human.json；
每页数字人视频存储于 <run_dir>/planning/digital_human/digi_<slide_id>.mp4。
音频取自第 7 步产物 <run_dir>/slides/<slide_id>/voice.mp3。
"""

from __future__ import annotations

import logging
import os
import subprocess
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
from visual_contract_service import read_contract_slide_ids

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
    """定位 ffmpeg/ffprobe（主服务进程可能不在带 ffmpeg 的 PATH 中启动）。"""
    import shutil

    found = shutil.which("ffmpeg")
    if found:
        return found
    candidates = [
        os.environ.get("PPT_STUDIO_FFMPEG_DIR", ""),
        os.environ.get("PPT_DIGITAL_HUMAN_FFMPEG_DIR", ""),
        str(Path(os.environ.get("APPDATA", ""))
            / "TRAE SOLO CN" / "ModularData" / "ai-agent" / "vm" / "tools" / "app" / "ffmpeg"),
    ]
    for cand in candidates:
        if cand and (Path(cand) / "ffmpeg.exe").exists():
            return str(Path(cand) / "ffmpeg.exe")
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

    # 输入：每页音频 + 1 个静音源（anullsrc）
    cmd = [ffmpeg, "-y"]
    for af in audio_files:
        cmd += ["-i", str(af)]
    cmd += ["-f", "lavfi", "-t", f"{gap}", "-i", "anullsrc=r=44100:cl=stereo"]

    # 各页音频规整采样率；静音裁剪为 gap 秒
    n = len(audio_files)
    fc_parts = []
    for i in range(n):
        fc_parts.append(f"[{i}:a]aresample=async=1:first_pts=0,asetpts=PTS-STARTPTS[a{i}]")
    fc_parts.append(f"[{n}:a]atrim=0:{gap},asetpts=PTS-STARTPTS[g]")
    concat_inputs = []
    for i in range(n):
        concat_inputs.append(f"[a{i}]")
        if i < n - 1:
            concat_inputs.append("[g]")
    fc_parts.append("".join(concat_inputs) + f"concat=n={2 * n - 1}:v=0:a=1[out]")
    fc = ";".join(fc_parts)

    cmd += ["-filter_complex", fc, "-map", "[out]",
            "-c:a", "libmp3lame", "-b:a", "192k", str(out)]
    _log_cmd = " ".join(cmd)
    logger.info("[audio-export] %s", _log_cmd)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if proc.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail="整段语音导出失败（需 ffmpeg）: " + (proc.stderr or "")[-800:],
        )

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
