# -*- coding: utf-8 -*-
"""数字人推理服务（独立进程，默认端口 9001）。

职责：
1. 管理数字人形象素材（参考视频 avatar），提供上传/列表/预览。
2. 封装 LatentSync（音频驱动口型重同步）为异步任务：创建 → 轮询 → 下载。
3. 提供 ffmpeg 圆形窗口合成（圆形遮罩 + 叠加主画面）。
4. 模型未部署时可进入 MOCK 模式，便于先打通对接链路。

与主系统（PPT 演示视频系统 :8000）通过 HTTP 通信，音频/视频共享本地磁盘路径。

启动：python digital_human_service.py   （监听 127.0.0.1:9001）
环境变量：
  PPT_DIGITAL_HUMAN_PORT        监听端口（默认 9001）
  PPT_DIGITAL_HUMAN_DATA_DIR    数据目录（默认 <repo>/data/digital_human）
  PPT_DIGITAL_HUMAN_LATENTSYNC_REPO   LatentSync 仓库根目录（就绪检测用）
  PPT_DIGITAL_HUMAN_MOCK        =1 时启用 mock 推理（ffmpeg 生成测试视频）
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
import uvicorn

logger = logging.getLogger("PPTStudio.DigitalHuman")

REPO_ROOT = Path(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = Path(
    os.environ.get("PPT_DIGITAL_HUMAN_DATA_DIR")
    or (REPO_ROOT / "data" / "digital_human")
)
AVATAR_DIR = DATA_DIR / "avatars"
JOB_DIR = DATA_DIR / "jobs"
MAX_AVATAR_BYTES = int(
    os.environ.get("PPT_DIGITAL_HUMAN_MAX_AVATAR_BYTES", str(500 * 1024 * 1024))
)
MAX_JOBS = 32

MOCK_MODE = os.environ.get("PPT_DIGITAL_HUMAN_MOCK", "") == "1"
LATENTSYNC_REPO = Path(
    os.environ.get("PPT_DIGITAL_HUMAN_LATENTSYNC_REPO") or ""
)


def _log(*parts: Any) -> None:
    logger.info(" ".join(str(p) for p in parts))


def _ensure_ffmpeg_in_path() -> Optional[str]:
    """启动时探测 ffmpeg/ffprobe 并加入 PATH（mock 推理与圆形合成依赖）。"""
    candidates = [
        Path(os.environ.get("PPT_DIGITAL_HUMAN_FFMPEG_DIR") or ""),
        Path(os.environ.get("PPT_STUDIO_FFMPEG_DIR") or ""),
        Path(r"C:\Users\Administrator\AppData\Roaming\TRAE SOLO CN\ModularData\ai-agent\vm\tools\app\ffmpeg"),
        REPO_ROOT / "tools" / "ffmpeg" / "bin",
    ]
    for cand in candidates:
        if cand and (cand / "ffmpeg.exe").exists() and (cand / "ffprobe.exe").exists():
            os.environ["PATH"] = str(cand) + os.pathsep + os.environ.get("PATH", "")
            return str(cand)
    return None


# ============================================================
# 任务存储（进程内 + 简单 JSON 持久化）
# ============================================================

JOB_STATUS_QUEUED = "queued"
JOB_STATUS_PROCESSING = "processing"
JOB_STATUS_DONE = "done"
JOB_STATUS_FAILED = "failed"
JOB_STATUS_UNAVAILABLE = "unavailable"  # 模型未部署

_jobs_lock = threading.Lock()
_jobs: Dict[str, Dict[str, Any]] = {}


def _job_file(job_id: str) -> Path:
    return JOB_DIR / f"{job_id}.json"


def _persist_job(job: Dict[str, Any]) -> None:
    try:
        JOB_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _job_file(job["job_id"]).with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(_job_file(job["job_id"]))
    except OSError as exc:  # pragma: no cover
        logger.warning("persist job failed: %s", exc)


def _load_persisted_jobs() -> None:
    if not JOB_DIR.exists():
        return
    for path in sorted(JOB_DIR.glob("*.json")):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(job, dict) and job.get("job_id"):
                _jobs[job["job_id"]] = job
        except (OSError, json.JSONDecodeError):
            continue


# ============================================================
# LatentSync 就绪检测与推理执行（可插拔）
# ============================================================


def _latentsync_runner_script() -> Optional[Path]:
    if not LATENTSYNC_REPO or not LATENTSYNC_REPO.exists():
        return None
    for rel in ("scripts/inference.py", "scripts/run_inference.py"):
        candidate = LATENTSYNC_REPO / rel
        if candidate.exists():
            return candidate
    return None


def latentsync_ready() -> bool:
    """模型是否就绪：已配置 LatentSync 仓库且推理脚本存在。"""
    if MOCK_MODE:
        return True
    return _latentsync_runner_script() is not None


def _run_real_inference(
    job: Dict[str, Any],
    avatar_path: Path,
    audio_path: Path,
    output_path: Path,
) -> None:
    script = _latentsync_runner_script()
    if script is None:
        raise RuntimeError("LatentSync 推理脚本不存在（PPT_DIGITAL_HUMAN_LATENTSYNC_REPO）")
    # 推理命令必须在 LatentSync 仓库根目录运行（configs/checkpoints 均为相对路径）
    repo = str(LATENTSYNC_REPO)
    ckpt = os.environ.get(
        "PPT_DIGITAL_HUMAN_LATENTSYNC_CKPT", "checkpoints/latentsync_unet.pt"
    )
    unet_cfg = os.environ.get(
        "PPT_DIGITAL_HUMAN_LATENTSYNC_CONFIG",
        "configs/unet/stage2_efficient.yaml",
    )
    steps = int(job.get("inference_steps", 20))
    if job.get("sync_mode") == "fast":
        steps = min(steps, 12)
    cmd = [
        sys_executable(),
        *(["-m", "scripts.inference"] if script.name == "inference.py" else [str(script)]),
        "--unet_config_path", unet_cfg,
        "--inference_ckpt_path", ckpt,
        "--inference_steps", str(steps),
        "--guidance_scale", "1.5",
        "--enable_deepcache",
        "--video_path", str(avatar_path),
        "--audio_path", str(audio_path),
        "--video_out_path", str(output_path),
    ]
    _log("[latentsync] run (cwd=%s):", repo, " ".join(cmd))
    proc = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, timeout=3600)
    if proc.returncode != 0:
        raise RuntimeError(
            "LatentSync 推理失败:\n" + (proc.stderr or proc.stdout or "")[-2000:]
        )


def _run_mock_inference(
    job: Dict[str, Any],
    avatar_path: Path,
    audio_path: Path,
    output_path: Path,
) -> None:
    """Mock：用 ffmpeg 生成一段带音频的测试视频，验证对接链路。"""
    out_dir = output_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    # 用一张参考帧拼成测试视频（若 avatar 是视频则取首帧）
    frame_file = out_dir / "frame.jpg"
    probe = ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(avatar_path)]
    size = None
    try:
        size = subprocess.run(probe, capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception:
        size = None
    if not size:
        size = "512x512"
    cmd = [
        "ffmpeg", "-y", "-i", str(avatar_path), "-i", str(audio_path),
        "-filter_complex", (
            f"scale={size},setsar=1,fps=30,"
            "drawbox=x=8:y=8:w=iw-16:h=ih-16:color=0x5B7893@1:t=4,"
            f"drawtext=text='DIGI MOCK {job.get('slide_id','')}':fontfile='C\\:/Windows/Fonts/msyh.ttc':"
            "x=(w-text_w)/2:y=(h-text_h)/2:fontsize=48:fontcolor=white:"
            "shadowcolor=black@0.6:shadowx=2:shadowy=2"
        ),
        "-shortest", "-pix_fmt", "yuv420p", "-c:v", "libx264",
        "-c:a", "aac", "-movflags", "+faststart", str(output_path),
    ]
    _log("[mock] run:", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(
            "Mock 推理失败（需 ffmpeg）:\n" + (proc.stderr or "")[-2000:]
        )


def sys_executable() -> str:
    return os.environ.get("PPT_DIGITAL_HUMAN_PYTHON") or sys_executable_default()


def sys_executable_default() -> str:
    import sys

    return sys.executable


def _execute_job(job_id: str) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job["status"] = JOB_STATUS_PROCESSING
        job["started_at"] = _now()
        job["progress"] = 5
        avatar_path = Path(job["avatar_path"])
        audio_path = Path(job["audio_path"])
        output_path = Path(job["output_path"])
        _persist_job(job)

    try:
        if not latentsync_ready():
            raise RuntimeError("数字人模型未部署（LatentSync 未就绪，或未启用 MOCK）")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if MOCK_MODE:
            _run_mock_inference(job, avatar_path, audio_path, output_path)
        else:
            _run_real_inference(job, avatar_path, audio_path, output_path)
        with _jobs_lock:
            job = _jobs[job_id]
            job["status"] = JOB_STATUS_DONE
            job["progress"] = 100
            job["finished_at"] = _now()
            job["result_url"] = (
                f"/api/digital-human/jobs/{job_id}/result"
            )
            _persist_job(job)
        _log("[job] done:", job_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("job %s failed", job_id)
        with _jobs_lock:
            job = _jobs.get(job_id)
            if job:
                job["status"] = JOB_STATUS_FAILED
                job["error"] = str(exc)
                job["finished_at"] = _now()
                _persist_job(job)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


# ============================================================
# ffmpeg 圆形窗口合成
# ============================================================


def _probe_video_size(path: Path) -> tuple[int, int]:
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(path),
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout.strip()
    if "x" in out:
        w, h = out.split("x", 1)
        return int(w), int(h)
    return 512, 512


def _probe_duration_sec(path: Path) -> float:
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "csv=s=x:p=0", str(path),
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def composite_circle(
    *,
    digi_video: Path,
    base_video: Optional[Path],
    output: Path,
    circle: Dict[str, Any],
    position: Optional[Dict[str, Any]] = None,
    border: Optional[Dict[str, Any]] = None,
    video: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """把 digi_video 裁剪成圆形并叠加到 base_video 上。

    circle: {cx, cy, r}，归一化坐标（0~1，圆心相对页面宽/高，r 相对视频短边）。
    video: {ox, oy, zoom} 视频与框的相对位置：
        - ox/oy ∈ [0,1]：圆形窗口显示的是视频的哪个子区域（0=左/上边，0.5=居中，1=右/下边）
        - zoom：视频额外放大倍数（默认 1.0 = cover 填满圆形）
    position: {x, y} 叠加位置（像素）；省略时由 cx,cy 推导（圆心对齐）。
    """
    digi_size = _probe_video_size(digi_video)
    base_size = _probe_video_size(base_video) if base_video else None
    if base_size is None:
        base_size = digi_size
    # r 相对"页面短边"，保证预览与最终合成一致（r=0.25 → 直径=页面短边的一半）
    short_side = min(base_size)
    r = max(0.02, min(0.95, float(circle.get("r", 0.25))))
    diameter = int(round(r * 2 * short_side))
    cx_ratio = float(circle.get("cx", 0.8))
    cy_ratio = float(circle.get("cy", 0.2))
    cx_px = int(round(cx_ratio * base_size[0]))
    cy_px = int(round(cy_ratio * base_size[1]))
    if position:
        x = int(position.get("x", 0))
        y = int(position.get("y", 0))
    else:
        x = cx_px - diameter // 2
        y = cy_px - diameter // 2

    # 视频在框内相对位置：默认居中、cover、不额外缩放
    video = video if isinstance(video, dict) else {}
    ox = max(0.0, min(1.0, float(video.get("ox", 0.5))))
    oy = max(0.0, min(1.0, float(video.get("oy", 0.5))))
    zoom = max(0.5, min(4.0, float(video.get("zoom", 1.0))))
    target = int(round(diameter * zoom))
    # cover 缩放后实际尺寸（较小边 = target）
    w, h = digi_size
    if w > 0 and h > 0 and w >= h:
        scaled_w = int(round(target * w / h))
        scaled_h = target
    else:
        scaled_w = target
        scaled_h = int(round(target * h / w)) if w > 0 else target
    max_dx = max(0, scaled_w - diameter)
    max_dy = max(0, scaled_h - diameter)
    crop_x = int(round(max_dx * ox))
    crop_y = int(round(max_dy * oy))

    cx_local = diameter / 2
    cy_local = diameter / 2
    radius = diameter / 2

    output.parent.mkdir(parents=True, exist_ok=True)
    inputs = [str(digi_video)]
    if base_video is not None:
        inputs.append(str(base_video))

    # digi 缩放到 target（≥圆形直径），再按 ox/oy 裁出直径窗口，用 geq 生成圆形 alpha 遮罩
    alpha_expr = (
        f"if(lt((X-{cx_local:.2f})^2+(Y-{cy_local:.2f})^2,{radius:.2f}^2),255,0)"
    )
    digi_filter = (
        f"[0:v]scale={target}:{target}:force_original_aspect_ratio=increase,"
        f"crop={diameter}:{diameter}:{crop_x}:{crop_y},setsar=1,format=rgba,"
        f"geq=a='{alpha_expr}':r='r(X,Y)':g='g(X,Y)':b='b(X,Y)'[digi]"
    )

    if base_video is not None:
        fc = f"{digi_filter};[1:v][digi]overlay={x}:{y}:shortest=1[v]"
        cmd = ["ffmpeg", "-y", "-i", str(digi_video), "-i", str(base_video),
               "-filter_complex", fc, "-map", "[v]", "-map", "1:a?",
               "-c:v", "libx264", "-preset", "medium", "-crf", "20",
               "-c:a", "aac", "-shortest", "-movflags", "+faststart", str(output)]
    else:
        # 只输出圆形 digi 视频（透明背景会变黑，保持纯色底以便预览）
        fc = f"{digi_filter};[digi]format=yuv420p[v]"
        cmd = ["ffmpeg", "-y", "-i", str(digi_video),
               "-filter_complex", fc, "-map", "[v]", "-map", "0:a?",
               "-c:v", "libx264", "-preset", "medium", "-crf", "20",
               "-c:a", "aac", "-shortest", "-movflags", "+faststart", str(output)]

    _log("[composite] run:", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(
            "圆形合成失败（需 ffmpeg）:\n" + (proc.stderr or "")[-2000:]
        )
    return {
        "output": str(output),
        "diameter": diameter,
        "position": {"x": x, "y": y},
        "base_size": base_size,
        "video": {"ox": ox, "oy": oy, "zoom": zoom, "crop": [crop_x, crop_y]},
    }


# ============================================================
# FastAPI 应用
# ============================================================

app = FastAPI(title="Digital Human Service", description="LatentSync + 圆形讲解窗口")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/digital-human/health")
def health() -> Dict[str, Any]:
    return {
        "success": True,
        "service": "digital_human",
        "model_ready": latentsync_ready(),
        "mock_mode": MOCK_MODE,
        "latentsync_repo": str(LATENTSYNC_REPO) if LATENTSYNC_REPO else "",
        "data_dir": str(DATA_DIR),
        "active_jobs": len(_jobs),
    }


@app.get("/api/digital-human/status")
def status() -> Dict[str, Any]:
    with _jobs_lock:
        summary = [
            {
                "job_id": j["job_id"],
                "status": j.get("status"),
                "slide_id": j.get("slide_id"),
                "error": j.get("error"),
                "progress": j.get("progress"),
            }
            for j in _jobs.values()
        ]
    return {"success": True, "jobs": summary}


# ---------- 形象（参考视频） ----------


@app.post("/api/digital-human/avatars")
def upload_avatar(
    name: str = Form("数字人形象"),
    file: UploadFile = File(...),
) -> Dict[str, Any]:
    content = file.file.read(MAX_AVATAR_BYTES + 1)
    if len(content) > MAX_AVATAR_BYTES:
        raise HTTPException(status_code=400, detail="参考视频超过大小限制")
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    avatar_id = f"av_{uuid.uuid4().hex[:10]}"
    ext = Path(file.filename or "video.mp4").suffix.lower() or ".mp4"
    if ext not in (".mp4", ".mov", ".mkv", ".webm", ".avi"):
        ext = ".mp4"
    filename = f"{avatar_id}{ext}"
    target = AVATAR_DIR / filename
    target.write_bytes(content)
    duration = _probe_duration_sec(target)
    return {
        "success": True,
        "avatar_id": avatar_id,
        "name": name,
        "filename": filename,
        "url": f"/api/digital-human/avatars/{avatar_id}/video",
        "duration": duration,
    }


@app.get("/api/digital-human/avatars")
def list_avatars() -> Dict[str, Any]:
    avatars = []
    if AVATAR_DIR.exists():
        for path in sorted(AVATAR_DIR.glob("av_*")):
            if not path.is_file():
                continue
            avatar_id = path.stem
            avatars.append(
                {
                    "avatar_id": avatar_id,
                    "filename": path.name,
                    "url": f"/api/digital-human/avatars/{avatar_id}/video",
                }
            )
    return {"success": True, "avatars": avatars}


@app.get("/api/digital-human/avatars/{avatar_id}/video")
def avatar_video(avatar_id: str) -> FileResponse:
    for path in AVATAR_DIR.glob(f"{avatar_id}.*"):
        if path.is_file():
            return FileResponse(str(path), media_type="video/mp4")
    raise HTTPException(status_code=404, detail="形象不存在")


# ---------- 生成任务 ----------


@app.post("/api/digital-human/jobs", status_code=201)
def create_job(payload: Dict[str, Any]) -> Dict[str, Any]:
    avatar_id = str(payload.get("avatar_id") or "").strip()
    audio_path_raw = str(payload.get("audio_path") or "").strip()
    slide_id = str(payload.get("slide_id") or "slide_000").strip()
    sync_mode = str(payload.get("sync_mode") or "accurate").strip()
    if sync_mode not in ("accurate", "fast"):
        sync_mode = "accurate"

    if not avatar_id or not audio_path_raw:
        raise HTTPException(status_code=400, detail="avatar_id 与 audio_path 必填")

    avatar_path = next(
        (p for p in AVATAR_DIR.glob(f"{avatar_id}.*") if p.is_file()),
        None,
    )
    if avatar_path is None:
        raise HTTPException(status_code=404, detail="形象不存在")

    audio_path = Path(audio_path_raw)
    if not audio_path.exists():
        raise HTTPException(status_code=400, detail=f"音频不存在: {audio_path}")

    if not latentsync_ready():
        return JSONResponse(
            status_code=503,
            content={
                "success": False,
                "detail": "数字人模型未部署：请设置 PPT_DIGITAL_HUMAN_LATENTSYNC_REPO，或启用 PPT_DIGITAL_HUMAN_MOCK=1 以联调",
                "model_ready": False,
            },
        )

    if len(_jobs) >= MAX_JOBS:
        raise HTTPException(status_code=429, detail="任务队列已满，请稍后重试")

    job_id = f"job_{uuid.uuid4().hex[:10]}"
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    output_path = JOB_DIR / f"{job_id}.mp4"
    job: Dict[str, Any] = {
        "job_id": job_id,
        "avatar_id": avatar_id,
        "avatar_path": str(avatar_path),
        "audio_path": str(audio_path),
        "slide_id": slide_id,
        "sync_mode": sync_mode,
        "inference_steps": int(payload.get("inference_steps") or 20),
        "status": JOB_STATUS_QUEUED,
        "progress": 0,
        "output_path": str(output_path),
        "created_at": _now(),
    }
    with _jobs_lock:
        _jobs[job_id] = job
        _persist_job(job)

    thread = threading.Thread(target=_execute_job, args=(job_id,), daemon=True)
    thread.start()
    _log("[job] created:", job_id, "slide:", slide_id)
    return {
        "success": True,
        "job_id": job_id,
        "status": JOB_STATUS_QUEUED,
    }


@app.get("/api/digital-human/jobs/{job_id}")
def get_job(job_id: str) -> Dict[str, Any]:
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {
        "job_id": job_id,
        "status": job.get("status"),
        "progress": job.get("progress"),
        "slide_id": job.get("slide_id"),
        "error": job.get("error"),
        "result_url": job.get("result_url"),
        "created_at": job.get("created_at"),
        "finished_at": job.get("finished_at"),
    }


@app.get("/api/digital-human/jobs/{job_id}/result")
def job_result(job_id: str) -> FileResponse:
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.get("status") != JOB_STATUS_DONE:
        raise HTTPException(status_code=409, detail="任务尚未完成")
    path = Path(job.get("output_path") or "")
    if not path.exists():
        raise HTTPException(status_code=404, detail="结果文件不存在")
    return FileResponse(str(path), media_type="video/mp4")


# ---------- 圆形窗口合成 ----------


@app.post("/api/digital-human/composite")
def composite(payload: Dict[str, Any]) -> Dict[str, Any]:
    digi_video = str(payload.get("digi_video") or "").strip()
    base_video = str(payload.get("base_video") or "").strip() or None
    circle = payload.get("circle") if isinstance(payload.get("circle"), dict) else {}
    position = payload.get("position") if isinstance(payload.get("position"), dict) else None
    border = payload.get("border") if isinstance(payload.get("border"), dict) else None
    video = payload.get("video") if isinstance(payload.get("video"), dict) else None
    output = str(payload.get("output") or "").strip()

    if not digi_video or not Path(digi_video).exists():
        raise HTTPException(status_code=400, detail="digi_video 必填且必须存在")
    if base_video and not Path(base_video).exists():
        raise HTTPException(status_code=400, detail=f"base_video 不存在: {base_video}")
    if not output:
        output = str(JOB_DIR / f"composite_{uuid.uuid4().hex[:8]}.mp4")

    try:
        result = composite_circle(
            digi_video=Path(digi_video),
            base_video=Path(base_video) if base_video else None,
            output=Path(output),
            circle=circle,
            position=position,
            border=border,
            video=video,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    result["success"] = True
    return result


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    )
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _load_persisted_jobs()
    ffmpeg_dir = _ensure_ffmpeg_in_path()
    if ffmpeg_dir:
        logger.info("Using ffmpeg tools: %s", ffmpeg_dir)
    port = int(os.environ.get("PPT_DIGITAL_HUMAN_PORT", "9001"))
    _log("Digital Human service starting on 127.0.0.1:", port)
    _log("  mock_mode:", MOCK_MODE, "| latentsync_ready:", latentsync_ready())
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
