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
import sys
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
from urllib.parse import urlsplit

# 复用项目已有的 killable 子进程执行器（超时后终止整个进程树，含孙进程）
sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime_support import run_subprocess_killable

logger = logging.getLogger("PPTStudio.DigitalHuman")

REPO_ROOT = Path(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = Path(
    os.environ.get("PPT_DIGITAL_HUMAN_DATA_DIR")
    or (REPO_ROOT / "data" / "digital_human")
)
AVATAR_DIR = DATA_DIR / "avatars"
JOB_DIR = DATA_DIR / "jobs"
MAX_AVATAR_BYTES = int(
    os.environ.get("PPT_DIGITAL_HUMAN_MAX_AVATAR_BYTES", str(200 * 1024 * 1024))  # 200MB
)
MAX_JOBS = 32

MOCK_MODE = os.environ.get("PPT_DIGITAL_HUMAN_MOCK", "") == "1"
LATENTSYNC_REPO = Path(
    os.environ.get("PPT_DIGITAL_HUMAN_LATENTSYNC_REPO") or ""
)
# 推理后端：latentsync（默认）| comfyui（Wan2.2 S2V）| mock
INFERENCE_BACKEND = os.environ.get("PPT_DIGITAL_HUMAN_BACKEND", "").strip().lower()
_wf_env = os.environ.get("PPT_DIGITAL_HUMAN_COMFYUI_WORKFLOW", "").strip()
COMFYUI_WORKFLOW_PATH = Path(_wf_env) if _wf_env else None


def _log(*parts: Any, level: str = "info") -> None:
    """统一的日志输出，支持 info/debug/warning/error 级别。

    默认 info 级别输出到控制台。verbose 操作日志可通过 level="debug" 降级，
    在需要排查问题时设置 logging.DEBUG 即可查看。
    """
    msg = " ".join(str(p) for p in parts)
    getattr(logger, level, logger.info)(msg)


def _run_subprocess_safe(
    cmd: list[str],
    *,
    cwd: Optional[str] = None,
    timeout: int = 3600,
) -> subprocess.CompletedProcess:
    """安全的 subprocess 执行：超时后终止整个进程树（含孙进程）。

    替代直接 subprocess.run，确保 GPU 推理进程在超时后不会残留，
    避免 Windows 上 subprocess.run 只 kill 直接子进程的问题。
    """
    result = run_subprocess_killable(
        cmd,
        timeout_sec=float(timeout),
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    if result.returncode == 124:
        raise RuntimeError(f"子进程超时（{timeout}s），已终止进程树: {' '.join(cmd[:3])}...")
    return result


def _is_relative(child: Path, parent: Path) -> bool:
    """判断 child 是否在 parent 目录下（含自身）。"""
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _assert_path_safe(path_str: str, label: str = "file") -> Path:
    """验证路径在允许范围内，防止路径遍历攻击。

    允许的根目录：DATA_DIR、REPO_ROOT、系统临时目录。
    """
    if not path_str:
        raise HTTPException(status_code=400, detail=f"{label} 路径为空")
    p = Path(path_str).resolve()
    allowed_roots = [DATA_DIR, REPO_ROOT]
    # 加入系统临时目录（mock 生成的临时视频可能在这里）
    import tempfile
    allowed_roots.append(Path(tempfile.gettempdir()))
    if not any(_is_relative(p, root) for root in allowed_roots):
        raise HTTPException(
            status_code=403,
            detail=f"{label} 路径超出允许范围: {p}",
        )
    return p


def _ensure_ffmpeg_in_path() -> Optional[str]:
    """启动时探测 ffmpeg/ffprobe 并加入 PATH（mock 推理与圆形合成依赖）。"""
    candidates = [
        Path(os.environ.get("PPT_DIGITAL_HUMAN_FFMPEG_DIR") or ""),
        Path(os.environ.get("PPT_STUDIO_FFMPEG_DIR") or ""),
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

# 全局取消令牌：服务关闭时通知所有活跃任务停止轮询和推理
_cancel_event = threading.Event()


def _shutdown_gracefully(*_args: Any) -> None:
    """服务关闭时通知所有活跃任务取消（atexit / signal handler）。"""
    _log("[shutdown] 通知活跃任务取消...")
    _cancel_event.set()
    # 等待活跃任务退出（最多 10s）
    for _ in range(100):
        with _jobs_lock:
            active = sum(
                1 for j in _jobs.values()
                if j.get("status") == JOB_STATUS_PROCESSING
            )
        if active == 0:
            break
        time.sleep(0.1)
    _log("[shutdown] 所有任务已停止")


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
                # 服务重启后修复中断的 job：
                # 后台线程在执行中被杀死，磁盘上的 job 可能停留在
                # queued/processing 状态，但已无线程继续执行。
                status = job.get("status")
                if status in (JOB_STATUS_QUEUED, JOB_STATUS_PROCESSING):
                    out = Path(job.get("output_path") or "")
                    if out.exists() and out.stat().st_size > 0:
                        # 输出文件已生成（ComfyUI 完成了但标记前被中断）
                        job["status"] = JOB_STATUS_DONE
                        job["progress"] = 100
                        job["finished_at"] = _now()
                        job["result_url"] = f"/api/digital-human/jobs/{job['job_id']}/result"
                        _log("[restore] job %s output exists → done", job["job_id"], level="debug")
                    else:
                        # 输出文件不存在 → 任务中断
                        job["status"] = JOB_STATUS_FAILED
                        job["error"] = "服务重启导致任务中断，请重新生成"
                        job["finished_at"] = _now()
                        _log("[restore] job %s was interrupted → failed", job["job_id"], level="debug")
                    _persist_job(job)
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
    _log("[latentsync] run (cwd=%s):", repo, " ".join(cmd), level="debug")
    proc = _run_subprocess_safe(cmd, cwd=repo, timeout=3600)
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
        size = _run_subprocess_safe(probe, timeout=20).stdout.strip()
    except Exception:
        size = None
    if not size:
        size = "512x512"
    # 动态获取系统字体路径（兼容不同 Windows 版本和 SystemRoot 配置）
    _font_path = os.path.join(
        os.environ.get("SystemRoot", r"C:\Windows"), "Fonts", "msyh.ttc"
    )
    _font_arg = _font_path.replace("\\", "/").replace(":", "\\:")
    cmd = [
        "ffmpeg", "-y", "-i", str(avatar_path), "-i", str(audio_path),
        "-filter_complex", (
            f"scale={size},setsar=1,fps=30,"
            "drawbox=x=8:y=8:w=iw-16:h=ih-16:color=0x5B7893@1:t=4,"
            f"drawtext=text='DIGI MOCK {job.get('slide_id','')}':fontfile='{_font_arg}':"
            "x=(w-text_w)/2:y=(h-text_h)/2:fontsize=48:fontcolor=white:"
            "shadowcolor=black@0.6:shadowx=2:shadowy=2"
        ),
        "-shortest", "-pix_fmt", "yuv420p", "-c:v", "libx264",
        "-c:a", "aac", "-movflags", "+faststart", str(output_path),
    ]
    _log("[mock] run:", " ".join(cmd), level="debug")
    proc = _run_subprocess_safe(cmd, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(
            "Mock 推理失败（需 ffmpeg）:\n" + (proc.stderr or "")[-2000:]
        )


def _run_comfyui_inference(
    job: Dict[str, Any],
    avatar_path: Path,
    audio_path: Path,
    output_path: Path,
) -> None:
    """通过 ComfyUI HTTP API 驱动 Wan2.2 S2V 工作流生成数字人视频。"""
    from comfyui_backend import run_comfyui_inference, ComfyUIError, check_health

    if not check_health():
        raise ComfyUIError("ComfyUI 服务不可达，请确认已启动且监听 http://127.0.0.1:8188")

    # 工作流模板优先取 job 内嵌，其次取环境变量路径，最后尝试默认文件
    workflow_template = job.get("workflow_template")
    # 检测是否为 API 格式（每个 value 都是 dict 且含 class_type）
    def _is_api_format(wf):
        if not isinstance(wf, dict) or not wf:
            return False
        return all(isinstance(v, dict) and "class_type" in v for v in wf.values())

    if not _is_api_format(workflow_template):
        if workflow_template is not None:
            _log("[comfyui] 工作流不是 API 格式（可能是 UI 编辑器格式），回退到默认模板", level="debug")
        workflow_template = None

    if not workflow_template:
        wf_path = COMFYUI_WORKFLOW_PATH or (DATA_DIR / "comfyui_workflow.json")
        if not wf_path.exists():
            raise ComfyUIError(f"ComfyUI 工作流模板不存在: {wf_path}")
        with open(wf_path, "r", encoding="utf-8") as f:
            workflow_template = json.load(f)
        if not _is_api_format(workflow_template):
            raise ComfyUIError(
                "ComfyUI 工作流模板格式错误：需要 API 格式（在 ComfyUI 中使用 'Save (API Format)' 导出）"
            )

    result = run_comfyui_inference(
        image_path=avatar_path,
        audio_path=audio_path,
        output_path=output_path,
        workflow_template=workflow_template,
        timeout=float(job.get("timeout", 7200)),
        cancel_event=_cancel_event,
    )
    _log("[comfyui] done: prompt_id=%s output=%s", result.get("prompt_id"), result.get("output"), level="debug")


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
        # 优先使用任务自带的 backend（允许前端逐任务指定），其次全局环境变量
        job_backend = (job.get("backend") or "").strip().lower()
        backend = job_backend or INFERENCE_BACKEND or ("mock" if MOCK_MODE else "latentsync")
        if not latentsync_ready() and backend not in ("comfyui",):
            raise RuntimeError("数字人模型未部署（LatentSync 未就绪，或未启用 MOCK）")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if backend == "comfyui":
            _run_comfyui_inference(job, avatar_path, audio_path, output_path)
        elif MOCK_MODE or backend == "mock":
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
    out = _run_subprocess_safe(cmd, timeout=30).stdout.strip()
    if "x" in out:
        w, h = out.split("x", 1)
        return int(w), int(h)
    return 512, 512


def _probe_duration_sec(path: Path) -> float:
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "csv=s=x:p=0", str(path),
    ]
    out = _run_subprocess_safe(cmd, timeout=30).stdout.strip()
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
    shape: str = "circle",
) -> Dict[str, Any]:
    """把 digi_video 裁剪成圆形/矩形窗口并叠加到 base_video 上。

    circle: {cx, cy, r}，归一化坐标（0~1，圆心相对页面宽/高，r 相对页面短边）。
    video: {ox, oy, zoom} 视频与框的相对位置：
        - ox/oy ∈ [0,1]：窗口显示的是视频的哪个子区域（0=左/上边，0.5=居中，1=右/下边）
        - zoom：视频额外放大倍数（默认 1.0 = cover 填满窗口）
    shape: "circle" | "rect" 窗口形状。
    position: {x, y} 叠加位置（像素）；省略时由 cx,cy 推导（窗口中心对齐）。
    """
    shape = "rect" if str(shape).lower() in ("rect", "rectangle", "square") else "circle"
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
    # zoom<1 时 target<diameter，crop 会超界导致 ffmpeg 失败；
    # zoom 语义是"cover 填满后的额外放大"，强制至少 1.0（cover 填满窗口）。
    if target < diameter:
        target = diameter
        zoom = max(1.0, zoom)
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

    # digi 缩放到 target（≥窗口直径），再按 ox/oy 裁出窗口；圆形额外加 alpha 遮罩
    base_digi = (
        f"[0:v]scale={target}:{target}:force_original_aspect_ratio=increase,"
        f"crop={diameter}:{diameter}:{crop_x}:{crop_y},setsar=1"
    )
    if shape == "rect":
        digi_filter = f"{base_digi},format=yuv420p[digi]"
    else:
        alpha_expr = (
            f"if(lt((X-{cx_local:.2f})^2+(Y-{cy_local:.2f})^2,{radius:.2f}^2),255,0)"
        )
        digi_filter = (
            f"{base_digi},format=rgba,"
            f"geq=a='{alpha_expr}':r='r(X,Y)':g='g(X,Y)':b='b(X,Y)'[digi]"
        )

    if base_video is not None:
        # 以主视频时长为基准：去掉 overlay 的 shortest 与输出级 -shortest，
        # 避免上传的数字人视频比整课短时把整段课程截断
        fc = f"{digi_filter};[1:v][digi]overlay={x}:{y}[v]"
        cmd = ["ffmpeg", "-y", "-i", str(digi_video), "-i", str(base_video),
               "-filter_complex", fc, "-map", "[v]", "-map", "1:a?",
               "-c:v", "libx264", "-preset", "medium", "-crf", "20",
               "-c:a", "aac", "-movflags", "+faststart", str(output)]
    else:
        # 只输出圆形 digi 视频（透明背景会变黑，保持纯色底以便预览）
        fc = f"{digi_filter};[digi]format=yuv420p[v]"
        cmd = ["ffmpeg", "-y", "-i", str(digi_video),
               "-filter_complex", fc, "-map", "[v]", "-map", "0:a?",
               "-c:v", "libx264", "-preset", "medium", "-crf", "20",
               "-c:a", "aac", "-shortest", "-movflags", "+faststart", str(output)]

    _log("[composite] run:", " ".join(cmd), level="debug")
    proc = _run_subprocess_safe(cmd, timeout=600)
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

# CORS 来源可通过环境变量配置，默认仅允许本机
_cors_env = os.environ.get("PPT_DIGITAL_HUMAN_CORS_ORIGINS", "").strip()
_default_cors = [
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://127.0.0.1:9001",
    "http://localhost:9001",
]
_cors_origins = [o.strip() for o in _cors_env.split(",") if o.strip()] or _default_cors

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def localhost_origin_guard(request, call_next):
    """仅允许本机来源的浏览器请求，阻止恶意网页借浏览器调用本服务。"""
    origin = request.headers.get("origin")
    if origin:
        host = (urlsplit(origin).hostname or "").lower()
        if host not in ("127.0.0.1", "localhost", "::1"):
            return JSONResponse({"detail": "Origin not allowed."}, status_code=403)
    return await call_next(request)


@app.get("/api/digital-human/health")
def health() -> Dict[str, Any]:
    import importlib
    # ComfyUI 在线检测（无论当前后端名为何，供 UI 显示与判断）
    comfyui_online = False
    try:
        comfyui_mod = importlib.import_module("comfyui_backend")
        comfyui_online = bool(comfyui_mod.check_health())
    except Exception:
        comfyui_online = False
    # 后端类型：ComfyUI 在线时优先显示 comfyui，其次 mock / 显式配置 / latentsync
    if comfyui_online:
        backend_used = "comfyui"
    else:
        backend_used = INFERENCE_BACKEND or ("mock" if MOCK_MODE else "latentsync")
    # model_ready：优先认 ComfyUI（用户当前主走 ComfyUI），其次 LatentSync
    model_ready = MOCK_MODE or comfyui_online or latentsync_ready()
    return {
        "success": True,
        "service": "digital_human",
        "model_ready": model_ready,
        "mock_mode": MOCK_MODE,
        "comfyui_online": comfyui_online,
        "inference_backend": backend_used,
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
        raise HTTPException(status_code=400, detail="文件超过大小限制")
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    avatar_id = f"av_{uuid.uuid4().hex[:10]}"
    raw_ext = Path(file.filename or "file").suffix.lower()
    video_exts = (".mp4", ".mov", ".mkv", ".webm", ".avi")
    image_exts = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
    if raw_ext in video_exts:
        ext = raw_ext
    elif raw_ext in image_exts:
        ext = raw_ext
    elif file.content_type and "image" in file.content_type:
        ext = ".png"
    else:
        ext = ".mp4"
    filename = f"{avatar_id}{ext}"
    target = AVATAR_DIR / filename
    target.write_bytes(content)
    result = {
        "success": True,
        "avatar_id": avatar_id,
        "name": name,
        "filename": filename,
    }
    if ext in video_exts:
        result["url"] = f"/api/digital-human/avatars/{avatar_id}/video"
        result["duration"] = _probe_duration_sec(target)
    else:
        result["url"] = f"/api/digital-human/avatars/{avatar_id}/image"
        result["duration"] = 0
    return result


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

    # ComfyUI 后端不需要 LatentSync 就绪
    is_comfyui = INFERENCE_BACKEND == "comfyui" or str(payload.get("backend") or "").lower() == "comfyui"
    if not is_comfyui and not latentsync_ready():
        return JSONResponse(
            status_code=503,
            content={
                "success": False,
                "detail": "数字人模型未部署：请设置 PPT_DIGITAL_HUMAN_LATENTSYNC_REPO，或启用 PPT_DIGITAL_HUMAN_MOCK=1 以联调",
                "model_ready": False,
            },
        )

    with _jobs_lock:
        # 计数、上限判断与任务注册必须在同一临界区内，避免无锁遍历 _jobs
        # 时被 _execute_job 线程修改字典（RuntimeError: dict changed size）
        # 以及并发 create_job 双双读到 < MAX_JOBS 的 TOCTOU 竞态。
        active_count = sum(
            1
            for j in _jobs.values()
            if j.get("status") in (JOB_STATUS_QUEUED, JOB_STATUS_PROCESSING)
        )
        if active_count >= MAX_JOBS:
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
        # ComfyUI 专用字段
        if is_comfyui:
            job["backend"] = "comfyui"
            wf_template = payload.get("workflow_template")
            if isinstance(wf_template, dict):
                job["workflow_template"] = wf_template
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
    shape = str(payload.get("shape") or "circle").strip() or "circle"
    output = str(payload.get("output") or "").strip()

    if not digi_video:
        raise HTTPException(status_code=400, detail="digi_video 必填且必须存在")
    digi_path = _assert_path_safe(digi_video, "digi_video")
    if not digi_path.exists():
        raise HTTPException(status_code=400, detail="digi_video 必填且必须存在")
    base_path = None
    if base_video:
        base_path = _assert_path_safe(base_video, "base_video")
        if not base_path.exists():
            raise HTTPException(status_code=400, detail=f"base_video 不存在: {base_video}")
    out_path = None
    if output:
        out_path = _assert_path_safe(output, "output")
    else:
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
            shape=shape,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    result["success"] = True
    return result


def main() -> None:
    import atexit
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    )
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _load_persisted_jobs()
    # 注册优雅关闭：服务退出时通知活跃任务停止
    atexit.register(_shutdown_gracefully)
    ffmpeg_dir = _ensure_ffmpeg_in_path()
    if ffmpeg_dir:
        logger.info("Using ffmpeg tools: %s", ffmpeg_dir)
    port = int(os.environ.get("PPT_DIGITAL_HUMAN_PORT", "9001"))
    _log("Digital Human service starting on 127.0.0.1:", port)
    _log("  mock_mode:", MOCK_MODE, "| latentsync_ready:", latentsync_ready())
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
