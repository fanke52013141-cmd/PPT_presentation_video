"""Step 7 TTS generation, audio status, download, and confirmation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
import json
import logging
import os
import sys
import threading
import uuid
from typing import Any, Callable, Dict, List, Optional

from fastapi import HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from database import LocalJob, Project
from project_path_service import project_or_404
import invalidation_service
from pipeline_lifecycle import write_json_atomic
from tts_artifacts import (
    build_confirmation_payload as build_audio_confirmation_payload,
)


logger = logging.getLogger("PPTStudio.TTS")


def _not_configured(*_args: Any, **_kwargs: Any) -> Any:
    raise RuntimeError("TTS dependencies have not been configured")


audio_confirmation_path: Callable[..., Any] = _not_configured
configured_tts_api_key: Callable[..., Any] = _not_configured
configured_tts_secret_key: Callable[..., Any] = _not_configured
current_slide_file_or_404: Callable[..., Any] = _not_configured
ensure_slide_tts_text_file: Callable[..., Any] = _not_configured
first_non_empty: Callable[..., Any] = _not_configured
get_setting: Callable[..., Any] = _not_configured
handle_step_navigation: Callable[..., Any] = _not_configured
mark_step_retry_needed: Callable[..., Any] = _not_configured
normalize_tts_provider: Callable[..., Any] = _not_configured
project_audio_confirmed: Callable[..., Any] = _not_configured
provider_tts_command: Callable[..., Any] = _not_configured
provider_tts_environment: Callable[..., Any] = _not_configured
read_current_slide_ids_or_404: Callable[..., Any] = _not_configured
remove_tts_artifacts: Callable[..., Any] = _not_configured
rewrite_audio_timeline_by_beats: Callable[..., Any] = _not_configured
run_subprocess_bounded: Callable[..., Any] = _not_configured
run_tts_command_with_retries: Callable[..., Any] = _not_configured
slide_tts_artifact_paths: Callable[..., Any] = _not_configured
slide_tts_artifact_status: Callable[..., Any] = _not_configured
sync_narration_beats_to_contract: Callable[..., Any] = _not_configured
tts_provider_defaults: Callable[..., Any] = _not_configured
write_project_log: Callable[..., Any] = _not_configured
# 注意：运行时会由 server.py 的 configure_tts_dependencies 注入权威值（0.45 / 90）。
# 此处默认值必须与 server.py 保持一致，避免未注入时静默使用过时值。
REVEAL_VISUAL_LEAD_SEC = 0.45
STEP7_BIND_TIMEOUT_SEC = 90
TTS_PROVIDER_DEFAULTS: dict[str, Any] = {}


@dataclass(frozen=True)
class TtsDependencies:
    audio_confirmation_path: Callable[..., Any]
    configured_tts_api_key: Callable[..., Any]
    configured_tts_secret_key: Callable[..., Any]
    current_slide_file_or_404: Callable[..., Any]
    ensure_slide_tts_text_file: Callable[..., Any]
    first_non_empty: Callable[..., Any]
    get_setting: Callable[..., Any]
    handle_step_navigation: Callable[..., Any]
    mark_step_retry_needed: Callable[..., Any]
    normalize_tts_provider: Callable[..., Any]
    project_audio_confirmed: Callable[..., Any]
    provider_tts_command: Callable[..., Any]
    provider_tts_environment: Callable[..., Any]
    read_current_slide_ids_or_404: Callable[..., Any]
    remove_tts_artifacts: Callable[..., Any]
    rewrite_audio_timeline_by_beats: Callable[..., Any]
    run_subprocess_bounded: Callable[..., Any]
    run_tts_command_with_retries: Callable[..., Any]
    slide_tts_artifact_paths: Callable[..., Any]
    slide_tts_artifact_status: Callable[..., Any]
    sync_narration_beats_to_contract: Callable[..., Any]
    tts_provider_defaults: Callable[..., Any]
    write_project_log: Callable[..., Any]
    provider_defaults: dict[str, Any]
    reveal_visual_lead_sec: float
    bind_timeout_sec: float


def configure_tts_dependencies(
    dependencies: TtsDependencies,
) -> None:
    global REVEAL_VISUAL_LEAD_SEC
    global STEP7_BIND_TIMEOUT_SEC
    global TTS_PROVIDER_DEFAULTS
    global audio_confirmation_path
    global configured_tts_api_key
    global configured_tts_secret_key
    global current_slide_file_or_404
    global ensure_slide_tts_text_file
    global first_non_empty
    global get_setting
    global handle_step_navigation
    global mark_step_retry_needed
    global normalize_tts_provider
    global project_audio_confirmed
    global provider_tts_command
    global provider_tts_environment
    global read_current_slide_ids_or_404
    global remove_tts_artifacts
    global rewrite_audio_timeline_by_beats
    global run_subprocess_bounded
    global run_tts_command_with_retries
    global slide_tts_artifact_paths
    global slide_tts_artifact_status
    global sync_narration_beats_to_contract
    global tts_provider_defaults
    global write_project_log

    audio_confirmation_path = dependencies.audio_confirmation_path
    configured_tts_api_key = dependencies.configured_tts_api_key
    configured_tts_secret_key = dependencies.configured_tts_secret_key
    current_slide_file_or_404 = dependencies.current_slide_file_or_404
    ensure_slide_tts_text_file = dependencies.ensure_slide_tts_text_file
    first_non_empty = dependencies.first_non_empty
    get_setting = dependencies.get_setting
    handle_step_navigation = dependencies.handle_step_navigation
    mark_step_retry_needed = dependencies.mark_step_retry_needed
    normalize_tts_provider = dependencies.normalize_tts_provider
    project_audio_confirmed = dependencies.project_audio_confirmed
    provider_tts_command = dependencies.provider_tts_command
    provider_tts_environment = dependencies.provider_tts_environment
    read_current_slide_ids_or_404 = (
        dependencies.read_current_slide_ids_or_404
    )
    remove_tts_artifacts = dependencies.remove_tts_artifacts
    rewrite_audio_timeline_by_beats = (
        dependencies.rewrite_audio_timeline_by_beats
    )
    run_subprocess_bounded = dependencies.run_subprocess_bounded
    run_tts_command_with_retries = (
        dependencies.run_tts_command_with_retries
    )
    slide_tts_artifact_paths = dependencies.slide_tts_artifact_paths
    slide_tts_artifact_status = dependencies.slide_tts_artifact_status
    sync_narration_beats_to_contract = (
        dependencies.sync_narration_beats_to_contract
    )
    tts_provider_defaults = dependencies.tts_provider_defaults
    write_project_log = dependencies.write_project_log
    TTS_PROVIDER_DEFAULTS = dependencies.provider_defaults
    REVEAL_VISUAL_LEAD_SEC = dependencies.reveal_visual_lead_sec
    STEP7_BIND_TIMEOUT_SEC = dependencies.bind_timeout_sec

def _load_beats_by_slide(
    project: Any,
    slide_ids: List[str],
    context: str,
) -> Dict[str, List[Dict[str, Any]]]:
    """读取旁白 beats 并按 slide 分组（审查 M-09 去重）。

    TTS 合成与音频确认两条路径共用；读取失败仅降级为空映射并记录警告。
    """
    beats_by_slide: Dict[str, List[Dict[str, Any]]] = {}
    beats_path = os.path.join(project.run_dir, "planning", "narration_beats.json")
    if not os.path.exists(beats_path):
        return beats_by_slide
    try:
        sync_narration_beats_to_contract(project, slide_ids)
        with open(beats_path, "r", encoding="utf-8") as f:
            beats_payload = json.load(f)
        for slide_data in beats_payload.get("slides", []) or []:
            if isinstance(slide_data, dict):
                beats_by_slide[str(slide_data.get("slide_id", ""))] = slide_data.get("beats", []) or []
    except Exception as exc:
        logger.warning("Failed to load edited narration beats (%s): %s", context, exc)
    return beats_by_slide


def _run_bind_reveal_timeline(project: Any) -> Any:
    """有界运行 bind_reveal_timeline 子进程（审查 M-09 去重）。"""
    bind_script = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "scripts", "bind_reveal_timeline.py")
    )
    return run_subprocess_bounded(
        [sys.executable, bind_script, "--run-dir", project.run_dir, "--lead-sec", str(REVEAL_VISUAL_LEAD_SEC)],
        timeout_sec=STEP7_BIND_TIMEOUT_SEC,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def synthesize_tts_resumable(project_id: str, db: Session):
    project = project_or_404(db, project_id)

    provider = normalize_tts_provider(get_setting("tts_provider", "minimax"))
    defaults = tts_provider_defaults(provider)
    if provider not in TTS_PROVIDER_DEFAULTS:
        raise HTTPException(status_code=400, detail=f"不支持的 TTS Provider: {provider}")
    tts_api_key = configured_tts_api_key(provider)
    tts_secret_key = configured_tts_secret_key(provider)
    if not tts_api_key:
        env_name = defaults.get("api_key_env") or "TTS_API_KEY"
        raise HTTPException(status_code=400, detail=f"未配置 {provider} 语音合成密钥，也没有读取到环境变量 {env_name}。")
    if provider == "tencent_tts" and not tts_secret_key:
        raise HTTPException(status_code=400, detail="腾讯云 TTS 需要同时配置 SecretId 和 SecretKey。")

    contract_path = os.path.join(project.run_dir, "planning", "visual_contract.json")
    if not os.path.exists(contract_path):
        raise HTTPException(status_code=400, detail="分镜规划尚未生成，请返回确认第二步状态。")

    with open(contract_path, "r", encoding="utf-8") as f:
        contract = json.load(f)

    slide_ids = [
        str(slide["slide_id"])
        for slide in contract.get("slides", [])
        if isinstance(slide, dict) and slide.get("slide_id")
    ]
    if not slide_ids:
        raise HTTPException(status_code=400, detail="分镜规划中没有可生成音频的页面。")

    beats_by_slide = _load_beats_by_slide(project, slide_ids, "TTS synthesis")

    tts_endpoint = first_non_empty(get_setting("tts_endpoint"), defaults.get("endpoint"))
    tts_model = first_non_empty(get_setting("tts_model"), defaults.get("model"))
    tts_voice_id = first_non_empty(get_setting("tts_voice_id"), defaults.get("voice_id"))
    tts_clone_voice_id = get_setting("tts_clone_voice_id", "")
    tts_region = first_non_empty(get_setting("tts_region"), defaults.get("region"))
    tts_provider_extra = get_setting("tts_provider_extra", "")
    tts_speed = get_setting("tts_speed", "1.2")
    tts_volume = get_setting("tts_volume", "1.0")
    tts_pitch = get_setting("tts_pitch", "0" if provider == "minimax" else "1.0")

    invalidation_service.narration_synthesis_started(project)
    db.commit()

    generated_slides: List[str] = []
    skipped_slides: List[str] = []
    failed_slides: List[Dict[str, Any]] = []

    for slide_id in slide_ids:
        paths = slide_tts_artifact_paths(project, slide_id)
        text_file = ensure_slide_tts_text_file(project, slide_id, contract)
        artifact_status = slide_tts_artifact_status(project, slide_id)

        if artifact_status["complete"]:
            logger.info("Skipping TTS for %s because audio artifacts are already complete and fresh", slide_id)
            rewrite_audio_timeline_by_beats(paths["timeline"], slide_id, beats_by_slide.get(slide_id, []))
            skipped_slides.append(slide_id)
            continue

        if artifact_status["audio_exists"] or artifact_status["missing_artifacts"] or artifact_status["stale"]:
            remove_tts_artifacts(paths)

        logger.info("Synthesizing TTS audio for slide %s via %s", slide_id, provider)
        tts_args = provider_tts_command(
            provider=provider,
            text_file=text_file,
            out_audio=paths["audio"],
            out_meta=paths["metadata"],
            out_srt=paths["srt"],
            out_timeline=paths["timeline"],
            slide_id=slide_id,
            endpoint=tts_endpoint,
            region=tts_region,
            model=tts_model,
            voice_id=tts_voice_id,
            clone_voice_id=tts_clone_voice_id,
            provider_extra=tts_provider_extra,
            speed=tts_speed,
            volume=tts_volume,
            pitch=tts_pitch,
        )

        tts_result = run_tts_command_with_retries(
            project,
            slide_id,
            tts_args,
            provider_tts_environment(tts_api_key, tts_secret_key),
        )
        if not tts_result["ok"]:
            error_text = (tts_result["stderr"] or tts_result["stdout"] or "TTS synthesis failed").strip()
            error_text = error_text[-1200:]
            logger.error("TTS synthesis failed for %s after %s attempts: %s", slide_id, tts_result["attempts"], error_text)
            write_project_log(
                project,
                "step7_slide_tts_error",
                slide_id=slide_id,
                attempts=tts_result["attempts"],
                returncode=tts_result["returncode"],
                stdout=tts_result["stdout"],
                stderr=tts_result["stderr"],
            )
            failed_slides.append({
                "slide_id": slide_id,
                "attempts": tts_result["attempts"],
                "returncode": tts_result["returncode"],
                "error": error_text,
            })
            continue

        post_status = slide_tts_artifact_status(project, slide_id)
        if not post_status["complete"]:
            error_text = "TTS command returned success but required audio artifacts are incomplete: " + ", ".join(post_status["missing_artifacts"])
            logger.error("%s for %s", error_text, slide_id)
            write_project_log(
                project,
                "step7_slide_tts_incomplete_artifacts",
                slide_id=slide_id,
                status=post_status,
            )
            failed_slides.append({
                "slide_id": slide_id,
                "attempts": tts_result["attempts"],
                "returncode": tts_result["returncode"],
                "error": error_text,
            })
            continue

        rewrite_audio_timeline_by_beats(paths["timeline"], slide_id, beats_by_slide.get(slide_id, []))
        generated_slides.append(slide_id)

    if failed_slides:
        mark_step_retry_needed(project, 7, db)
        write_project_log(
            project,
            "step7_tts_partial_failed",
            generated=generated_slides,
            skipped=skipped_slides,
            failed=failed_slides,
        )
        failed_ids = [item["slide_id"] for item in failed_slides]
        return {
            "success": False,
            "message": f"音频部分生成失败，请重试缺失页面：{', '.join(failed_ids)}",
            "generated": generated_slides,
            "skipped": skipped_slides,
            "failed": failed_slides,
            "audio_status": [slide_tts_artifact_status(project, sid) for sid in slide_ids],
            "audio_confirmed": False,
        }

    bind_res = _run_bind_reveal_timeline(project)

    if bind_res.returncode != 0:
        logger.error("Timeline binding failed: %s", bind_res.stderr)
        write_project_log(
            project,
            "step7_timeline_bind_error",
            returncode=bind_res.returncode,
            stdout=bind_res.stdout.strip(),
            stderr=bind_res.stderr.strip(),
        )
        mark_step_retry_needed(project, 7, db)
        return {
            "success": False,
            "message": f"音频已生成，但时间轴绑定失败：{bind_res.stderr[-1200:]}",
            "generated": generated_slides,
            "skipped": skipped_slides,
            "failed": [{"slide_id": "timeline_binding", "error": bind_res.stderr[-1200:]}],
            "audio_status": [slide_tts_artifact_status(project, sid) for sid in slide_ids],
            "audio_confirmed": False,
        }

    return {
        "success": True,
        "message": "音频生成完成",
        "generated": generated_slides,
        "skipped": skipped_slides,
        "failed": [],
        "audio_status": [slide_tts_artifact_status(project, sid) for sid in slide_ids],
        "audio_confirmed": False,
    }

def get_tts_audio_status(project_id: str, db: Session):
    project = project_or_404(db, project_id)
    slide_ids = read_current_slide_ids_or_404(project)
    slides = [slide_tts_artifact_status(project, slide_id) for slide_id in slide_ids]
    missing = [item["slide_id"] for item in slides if not item["complete"]]
    return {
        "success": True,
        "slides": slides,
        "complete": not missing,
        "missing": missing,
        "audio_confirmed": project_audio_confirmed(project),
    }

def get_slide_audio_file(project_id: str, slide_id: str, db: Session):
    project = project_or_404(db, project_id)
        
    audio_path = current_slide_file_or_404(project, slide_id, "voice.mp3")
    status = slide_tts_artifact_status(project, slide_id)
    if not status["audio_exists"]:
        raise HTTPException(status_code=404, detail="该页面音频尚未生成")
        
    if status["stale"]:
        raise HTTPException(status_code=409, detail="该页面音频已过期，请重新生成。")

    return FileResponse(audio_path, media_type="audio/mp3")

def confirm_tts_audio(project_id: str, db: Session, payload: Optional[Dict[str, Any]] = None):
    project = project_or_404(db, project_id)
    slide_ids = read_current_slide_ids_or_404(project)
    missing = [
        slide_id for slide_id in slide_ids
        if not slide_tts_artifact_status(project, slide_id)["complete"]
    ]
    if missing:
        raise HTTPException(status_code=400, detail=f"以下页面尚未生成音频: {', '.join(missing)}")
    beats_by_slide = _load_beats_by_slide(project, slide_ids, "audio confirm")
    for slide_id in slide_ids:
        rewrite_audio_timeline_by_beats(
            os.path.join(project.run_dir, "slides", slide_id, "audio_timeline.json"),
            slide_id,
            beats_by_slide.get(slide_id, []),
        )
    bind_res = _run_bind_reveal_timeline(project)
    if bind_res.returncode != 0:
        logger.error(f"Timeline binding failed during audio confirm: {bind_res.stderr}")
        raise HTTPException(status_code=500, detail=f"时间轴绑定失败: {bind_res.stderr}")
    confirmation_path = audio_confirmation_path(project)
    os.makedirs(os.path.dirname(confirmation_path), exist_ok=True)
    write_json_atomic(
        confirmation_path,
        build_audio_confirmation_payload(
            project.run_dir,
            slide_ids,
            confirmation_mode=str((payload or {}).get("confirmation_mode") or "user_reviewed"),
        ),
    )
    handle_step_navigation(project, 7, db)
    return {"success": True, "audio_confirmed": True}


# ==================== 持久化 TTS 合成任务（审查 M-09 第二步） ====================

TTS_JOB_TYPE = "tts_synthesis"


@dataclass(frozen=True)
class TtsAsyncDependencies:
    """后台合成任务的最小依赖：会话工厂 + 同步合成入口。"""

    session_factory: Callable[[], Session]
    synthesize: Callable[[str, Session], dict[str, Any]]


class TtsAsyncService:
    """SQLite 持久化的 TTS 合成后台任务（结构与 pptx_export 一致）。

    合成在独立线程执行，客户端断连/代理超时不再影响生成；状态经
    local_jobs 表持久化，进程重启时 running→interrupted、queued→重新排队。
    """

    def __init__(self, dependencies: TtsAsyncDependencies) -> None:
        self.dependencies = dependencies
        self.executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="tts-synthesis",
        )
        self._create_lock = threading.Lock()

    @staticmethod
    def _iso(value: datetime | None) -> str | None:
        return value.isoformat(timespec="seconds") if value else None

    def job_item(self, job: LocalJob) -> dict[str, Any]:
        payload = job.get_payload() or {}
        return {
            "id": job.id,
            "project_id": job.project_id,
            "job_type": job.job_type,
            "status": job.status,
            "progress": int(job.progress or 0),
            "stage": job.stage,
            "error": job.error,
            "result": payload.get("result") or {},
            "created_at": self._iso(job.created_at),
            "started_at": self._iso(job.started_at),
            "finished_at": self._iso(job.finished_at),
            "updated_at": self._iso(job.updated_at),
        }

    def _active_job(self, db: Session, project_id: str) -> LocalJob | None:
        return (
            db.query(LocalJob)
            .filter(
                LocalJob.project_id == project_id,
                LocalJob.job_type == TTS_JOB_TYPE,
                LocalJob.status.in_(("queued", "running")),
            )
            .first()
        )

    def create_job(self, db: Session, project_id: str) -> dict[str, Any]:
        project = project_or_404(db, project_id)
        with self._create_lock:
            active = self._active_job(db, project.id)
            if active:
                return {
                    "success": True,
                    "reused": True,
                    "job": self.job_item(active),
                }
            job = LocalJob(
                id=uuid.uuid4().hex,
                project_id=project.id,
                job_type=TTS_JOB_TYPE,
                status="queued",
                progress=0,
                stage="queued",
            )
            db.add(job)
            db.commit()
            db.refresh(job)
        self.submit(job.id)
        return {"success": True, "reused": False, "job": self.job_item(job)}

    def list_jobs(self, db: Session, project_id: str) -> dict[str, Any]:
        project_or_404(db, project_id)
        jobs = (
            db.query(LocalJob)
            .filter(
                LocalJob.project_id == project_id,
                LocalJob.job_type == TTS_JOB_TYPE,
            )
            .order_by(LocalJob.created_at.desc())
            .limit(20)
            .all()
        )
        return {"success": True, "jobs": [self.job_item(job) for job in jobs]}

    def get_job(
        self,
        db: Session,
        project_id: str,
        job_id: str,
    ) -> dict[str, Any]:
        project_or_404(db, project_id)
        job = (
            db.query(LocalJob)
            .filter(
                LocalJob.id == job_id,
                LocalJob.project_id == project_id,
                LocalJob.job_type == TTS_JOB_TYPE,
            )
            .first()
        )
        if not job:
            raise HTTPException(status_code=404, detail="任务不存在")
        return {"success": True, "job": self.job_item(job)}

    def submit(self, job_id: str) -> None:
        self.executor.submit(self.run_job, job_id)

    def recover_jobs(self) -> int:
        """进程重启恢复：running→interrupted，queued→重新排队。"""
        db = self.dependencies.session_factory()
        queued_ids: list[str] = []
        try:
            now = datetime.now()
            running = (
                db.query(LocalJob)
                .filter(
                    LocalJob.job_type == TTS_JOB_TYPE,
                    LocalJob.status == "running",
                )
                .all()
            )
            for job in running:
                job.status = "interrupted"
                job.stage = "interrupted"
                job.error = "服务重启导致合成中断，请重新生成音频。"
                job.finished_at = now
            queued_ids = [
                job.id
                for job in db.query(LocalJob)
                .filter(
                    LocalJob.job_type == TTS_JOB_TYPE,
                    LocalJob.status == "queued",
                )
                .all()
            ]
            db.commit()
        finally:
            db.close()
        for job_id in queued_ids:
            self.submit(job_id)
        return len(running)

    def run_job(self, job_id: str) -> None:
        db = self.dependencies.session_factory()
        try:
            job = (
                db.query(LocalJob)
                .filter(
                    LocalJob.id == job_id,
                    LocalJob.job_type == TTS_JOB_TYPE,
                )
                .first()
            )
            if not job:
                return
            project = (
                db.query(Project).filter(Project.id == job.project_id).first()
            )
            if not project:
                job.status = "failed"
                job.stage = "failed"
                job.error = "项目不存在，无法继续合成"
                job.finished_at = datetime.now()
                db.commit()
                return
            job.status = "running"
            job.stage = "synthesizing"
            job.progress = 10
            job.started_at = datetime.now()
            db.commit()

            result = self.dependencies.synthesize(job.project_id, db)
            summary = {
                "generated": len(result.get("generated") or []),
                "skipped": len(result.get("skipped") or []),
                "failed_ids": [
                    item.get("slide_id")
                    for item in (result.get("failed") or [])
                    if isinstance(item, dict) and item.get("slide_id")
                ],
                "message": result.get("message") or "",
            }
            job.payload_json = json.dumps(
                {"result": summary}, ensure_ascii=False
            )
            if result.get("success"):
                job.status = "completed"
                job.stage = "completed"
                job.progress = 100
            else:
                job.status = "failed"
                job.stage = "failed"
                job.error = summary["message"] or "音频生成未完成，请重试。"
            job.finished_at = datetime.now()
            db.commit()
        except Exception as exc:
            logger.exception("Async TTS synthesis failed for job %s", job_id)
            try:
                db.rollback()
                stale = (
                    db.query(LocalJob)
                    .filter(
                        LocalJob.id == job_id,
                        LocalJob.job_type == TTS_JOB_TYPE,
                    )
                    .first()
                )
                if stale:
                    stale.status = "failed"
                    stale.stage = "failed"
                    stale.error = str(exc)[:2000] or "合成过程发生异常"
                    stale.finished_at = datetime.now()
                    db.commit()
            except Exception:
                logger.exception("Failed to persist TTS job failure state")
        finally:
            db.close()


_SERVICE: TtsAsyncService | None = None
_SERVICE_LOCK = threading.Lock()


def configure_tts_async_service(
    dependencies: TtsAsyncDependencies,
    *,
    recover_jobs: bool = True,
) -> TtsAsyncService:
    global _SERVICE
    service = TtsAsyncService(dependencies)
    with _SERVICE_LOCK:
        _SERVICE = service
    if recover_jobs:
        service.recover_jobs()
    return service


def get_tts_async_service() -> TtsAsyncService:
    if _SERVICE is None:
        raise RuntimeError("TTS async service has not been configured")
    return _SERVICE

