"""Persistent video render orchestration.

The coordinator owns task state and stage transitions. Remotion subprocesses,
MP4 filesystem operations, and SQLite job persistence live in dedicated
components.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import logging
from pathlib import Path
import threading
import time
import uuid
from typing import Any, Callable

from sqlalchemy.orm import Session

from database import LocalJob, Project
import invalidation_service
from remotion_runner import RemotionRunner
from tts_artifacts import confirmation_status as tts_confirmation_status
from video_artifact_service import VideoArtifactService
from video_contracts import VideoRenderConfig, VideoRenderError
from video_job_store import VideoJobStore
from visual_provenance import validate_visual_provenance_set


logger = logging.getLogger("PPTStudio.VideoRender")

RENDER_STAGE_LABELS = {
    "validating": "校验项目状态",
    "building_reveal": "构建 Reveal 资源",
    "binding_timeline": "绑定语音时间轴",
    "building_props": "构建 Remotion 配置",
    "rendering": "Remotion 渲染中",
    "validating_color": "校验视频颜色",
    "finalizing": "写入元数据",
    "interrupted": "任务已中断",
}

RENDER_STAGE_PROGRESS = {
    "validating": 5,
    "building_reveal": 15,
    "binding_timeline": 28,
    "building_props": 40,
    "rendering": 52,
    "validating_color": 88,
    "finalizing": 96,
}


@dataclass(frozen=True)
class VideoRenderDependencies:
    session_factory: Callable[[], Session]
    artifact_service: VideoArtifactService
    remotion_runner: RemotionRunner
    config: VideoRenderConfig


class VideoRenderService:
    """Coordinates validation, jobs, rendering, and artifact publication."""

    def __init__(self, dependencies: VideoRenderDependencies) -> None:
        self.dependencies = dependencies
        self.artifacts = dependencies.artifact_service
        self.runner = dependencies.remotion_runner
        self.job_store = VideoJobStore(dependencies.session_factory)
        self._tasks: dict[str, dict[str, Any]] = {}
        self._tasks_lock = threading.Lock()
        self._project_locks: dict[str, threading.Lock] = {}
        self._project_locks_guard = threading.Lock()

    @property
    def config(self) -> VideoRenderConfig:
        return self.dependencies.config

    def recover_jobs(self) -> int:
        return self.job_store.interrupt_orphaned(
            "应用上次运行时退出，视频渲染已中断；请重新生成。"
        )

    def get_project(self, db: Session, project_id: str) -> Project:
        return self.artifacts.get_project(db, project_id)

    # Compatibility facade: callers and routes keep one stable service surface.
    def validated_run_dir(self, project: Project) -> Path:
        return self.artifacts.validated_run_dir(project)

    def project_video_dir(self, project: Project) -> Path:
        return self.artifacts.project_video_dir(project)

    def project_video_file(
        self,
        project: Project,
        filename: str,
    ) -> Path:
        return self.artifacts.project_video_file(project, filename)

    def project_legacy_video_file(self, project: Project) -> Path:
        return self.artifacts.project_legacy_video_file(project)

    @staticmethod
    def video_metadata_path(path: str | Path) -> Path:
        return VideoArtifactService.video_metadata_path(path)

    def read_video_metadata(
        self,
        path: str | Path,
    ) -> dict[str, Any]:
        return self.artifacts.read_video_metadata(path)

    def current_render_input_fingerprint(
        self,
        project: Project,
    ) -> dict[str, Any]:
        return self.artifacts.current_render_input_fingerprint(project)

    def video_item(
        self,
        project: Project,
        path: str | Path,
        label: str | None = None,
        current_fingerprint: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.artifacts.video_item(
            project,
            path,
            label,
            current_fingerprint,
        )

    def list_video_items(
        self,
        project: Project,
    ) -> list[dict[str, Any]]:
        return self.artifacts.list_video_items(project)

    @staticmethod
    def validate_remotion_public_assets(
        props: dict[str, Any],
        public_dir: str | Path,
    ) -> list[str]:
        return RemotionRunner.validate_public_assets(
            props,
            public_dir,
        )

    def start_render(
        self,
        db: Session,
        project_id: str,
    ) -> dict[str, Any]:
        project = self.get_project(db, project_id)
        slide_ids = self._read_contract_slide_ids(project.run_dir)
        provenance_errors = validate_visual_provenance_set(
            project.run_dir,
            slide_ids,
        )
        if provenance_errors:
            details = ", ".join(
                f"{item['slide_id']}({item['reason']})"
                for item in provenance_errors
            )
            raise VideoRenderError(
                409,
                "图片来源校验未通过，请返回图片步骤处理：" + details,
            )
        audio_confirmation = tts_confirmation_status(
            project.run_dir,
            slide_ids,
        )
        if not audio_confirmation.get("confirmed"):
            raise VideoRenderError(
                400,
                "请先在“旁白与音频”步骤试听并确认音频，再开始视频渲染。",
            )

        project_lock = self._project_lock(project_id)
        if not project_lock.acquire(blocking=False):
            active = self._active_task(project_id)
            if active:
                return self._active_task_response(active)
            raise VideoRenderError(
                409,
                "该项目已有渲染任务进行中，请等待完成或刷新页面查看状态。",
            )

        active = self._active_task(project_id)
        if active:
            project_lock.release()
            return self._active_task_response(active)

        task_id = uuid.uuid4().hex
        try:
            self.job_store.create(
                project_id,
                job_id=task_id,
                stage="validating",
                payload={
                    "requested_at": datetime.now().isoformat(
                        timespec="seconds"
                    )
                },
            )
        except Exception as exc:
            project_lock.release()
            logger.exception(
                "Failed to persist video render job for %s",
                project_id,
            )
            raise VideoRenderError(
                500,
                "无法创建持久化视频任务，请重试。",
            ) from exc

        with self._tasks_lock:
            self._tasks[task_id] = {
                "task_id": task_id,
                "project_id": project_id,
                "status": "rendering",
                "stage": "validating",
                "stage_label": RENDER_STAGE_LABELS["validating"],
                "started_at": time.time(),
                "finished_at": None,
                "elapsed_sec": 0.0,
                "error": None,
                "video": None,
                "videos": None,
                "output_filename": None,
            }

        thread = threading.Thread(
            target=self.run_render_job,
            args=(project_id, task_id),
            name=f"render-{project_id}-{task_id[:8]}",
            daemon=True,
        )
        try:
            thread.start()
        except Exception as exc:
            self._set_task_status(
                task_id,
                "interrupted",
                error="视频任务启动失败，请重试",
            )
            project_lock.release()
            logger.exception(
                "Failed to start video render thread for %s",
                project_id,
            )
            raise VideoRenderError(
                500,
                "视频任务启动失败，请重试",
            ) from exc
        return {
            "success": True,
            "task_id": task_id,
            "status": "rendering",
            "stage": "validating",
            "stage_label": RENDER_STAGE_LABELS["validating"],
            "elapsed_sec": 0.0,
            "message": "渲染已启动，请轮询 render-status 接口",
        }

    def render_status(
        self,
        db: Session,
        project_id: str,
        *,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        project = self.get_project(db, project_id)
        task: dict[str, Any] | None = None
        with self._tasks_lock:
            if task_id:
                task = self._tasks.get(task_id)
                if (
                    task is not None
                    and task["project_id"] != project_id
                ):
                    task = None
            else:
                candidates = [
                    value
                    for value in self._tasks.values()
                    if value["project_id"] == project_id
                ]
                if candidates:
                    task = max(
                        candidates,
                        key=lambda value: value["started_at"],
                    )
        if task is None:
            persistent = (
                self.job_store.get(
                    task_id,
                    project_id=project_id,
                )
                if task_id
                else self.job_store.latest(project_id)
            )
            if persistent:
                task = self._persistent_job_to_task(persistent)
        if task is None:
            return {
                "success": True,
                "status": "idle",
                "task_id": None,
                "stage": None,
                "stage_label": "",
                "elapsed_sec": 0.0,
                "error": None,
                "video": None,
                "videos": self.list_video_items(project),
            }

        elapsed = (
            round(time.time() - task["started_at"], 1)
            if task["status"] == "rendering"
            else task.get("elapsed_sec", 0.0)
        )
        video = task.get("video")
        output_filename = str(
            task.get("output_filename") or ""
        )
        if not video and output_filename:
            try:
                output_path = self.project_video_file(
                    project,
                    output_filename,
                )
                if output_path.is_file():
                    video = self.video_item(project, output_path)
            except (VideoRenderError, OSError):
                video = None
        return {
            "success": True,
            "task_id": task["task_id"],
            "status": task["status"],
            "stage": task.get("stage"),
            "stage_label": RENDER_STAGE_LABELS.get(
                task.get("stage") or "",
                "",
            ),
            "started_at": task["started_at"],
            "finished_at": task.get("finished_at"),
            "elapsed_sec": elapsed,
            "error": task.get("error"),
            "video": video,
            "videos": (
                task.get("videos")
                or self.list_video_items(project)
            ),
        }

    def run_render_job(
        self,
        project_id: str,
        task_id: str,
    ) -> None:
        db = self.dependencies.session_factory()
        project_lock = self._project_lock(project_id)
        try:
            project = (
                db.query(Project)
                .filter(Project.id == project_id)
                .first()
            )
            if not project:
                self._set_task_status(
                    task_id,
                    "error",
                    error="项目不存在",
                )
                return
            try:
                result = self.runner.run(
                    project,
                    output_dir=self.project_video_dir(project),
                    set_stage=lambda stage: self._set_task_stage(
                        task_id,
                        stage,
                    ),
                )
                self._set_task_stage(task_id, "finalizing")
                render_fingerprint = (
                    self.current_render_input_fingerprint(project)
                )
                visual_settings = self.artifacts.visual_settings(project)
                render_metadata = {
                    "rendered_at": datetime.now().isoformat(
                        timespec="seconds"
                    ),
                    "reveal_pipeline_version": (
                        self.config.pipeline_version
                    ),
                    "video_background": visual_settings[
                        "video_background"
                    ],
                    "subtitle_style": visual_settings[
                        "subtitle_style"
                    ],
                    "manifest": "reveal_manifest.json",
                    "input_fingerprint": render_fingerprint,
                    "color_standard": "bt709_tv_yuv420p",
                    "color_validation": result.color_validation,
                }
                artifact = self.artifacts.record_rendered_video(
                    db,
                    project,
                    result.output_path,
                    result.output_filename,
                    render_metadata=render_metadata,
                    render_fingerprint=render_fingerprint,
                )
                invalidation_service.complete_stage(project, 8)
                db.commit()
                video = self.video_item(project, result.output_path)
                videos = self.list_video_items(project)
                self._set_task_status(
                    task_id,
                    "success",
                    video=video,
                    videos=videos,
                    output_filename=(
                        video.get("filename")
                        or result.output_filename
                    ),
                    result_artifact_id=artifact.id,
                )
            except Exception as exc:
                logger.exception(
                    "Async render failed for project %s",
                    project_id,
                )
                self._set_task_status(
                    task_id,
                    "error",
                    error=str(exc),
                )
        finally:
            db.close()
            if project_lock.locked():
                project_lock.release()

    def list_videos(
        self,
        db: Session,
        project_id: str,
    ) -> dict[str, Any]:
        return self.artifacts.list_videos(db, project_id)

    def video_download(
        self,
        db: Session,
        project_id: str,
        filename: str,
    ) -> Path:
        return self.artifacts.video_download(
            db,
            project_id,
            filename,
        )

    def create_speed_adjusted_video(
        self,
        db: Session,
        project_id: str,
        filename: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self.artifacts.create_speed_adjusted_video(
            db,
            project_id,
            filename,
            payload,
        )

    def delete_video(
        self,
        db: Session,
        project_id: str,
        filename: str,
    ) -> dict[str, Any]:
        return self.artifacts.delete_video(
            db,
            project_id,
            filename,
        )

    def final_video_status(
        self,
        db: Session,
        project_id: str,
    ) -> dict[str, Any]:
        return self.artifacts.final_video_status(db, project_id)

    def final_video_download(
        self,
        db: Session,
        project_id: str,
    ) -> Path:
        return self.artifacts.final_video_download(db, project_id)

    def _project_lock(self, project_id: str) -> threading.Lock:
        with self._project_locks_guard:
            lock = self._project_locks.get(project_id)
            if lock is None:
                lock = threading.Lock()
                self._project_locks[project_id] = lock
            return lock

    def _active_task(
        self,
        project_id: str,
    ) -> dict[str, Any] | None:
        with self._tasks_lock:
            for task in self._tasks.values():
                if (
                    task["project_id"] == project_id
                    and task["status"] == "rendering"
                ):
                    return task
        persistent = self.job_store.active(project_id)
        return (
            self._persistent_job_to_task(persistent)
            if persistent
            else None
        )

    @staticmethod
    def _active_task_response(
        active: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "success": True,
            "task_id": active["task_id"],
            "status": "rendering",
            "stage": active.get("stage", "rendering"),
            "stage_label": RENDER_STAGE_LABELS.get(
                active.get("stage", ""),
                "",
            ),
            "elapsed_sec": round(
                time.time() - active["started_at"],
                1,
            ),
            "message": "已有渲染任务进行中",
        }

    def _set_task_stage(
        self,
        task_id: str,
        stage: str,
    ) -> None:
        with self._tasks_lock:
            task = self._tasks.get(task_id)
            if task is not None:
                task["stage"] = stage
                task["elapsed_sec"] = round(
                    time.time() - task["started_at"],
                    1,
                )
        self.job_store.update(
            task_id,
            status="running",
            stage=stage,
            progress=RENDER_STAGE_PROGRESS.get(stage, 0),
        )

    def _set_task_status(
        self,
        task_id: str,
        status: str,
        **fields: Any,
    ) -> None:
        with self._tasks_lock:
            task = self._tasks.get(task_id)
            if task is not None:
                task["status"] = status
                task["elapsed_sec"] = round(
                    time.time() - task["started_at"],
                    1,
                )
                if status in {
                    "success",
                    "error",
                    "interrupted",
                }:
                    task["finished_at"] = time.time()
                task.update(fields)
        persistent_status = {
            "rendering": "running",
            "success": "succeeded",
            "error": "failed",
            "interrupted": "interrupted",
        }.get(status, status)
        self.job_store.update(
            task_id,
            status=persistent_status,
            stage=(
                "completed"
                if status == "success"
                else "failed"
                if status == "error"
                else None
            ),
            progress=100 if status == "success" else None,
            error=(
                fields.get("error")
                if status in {"error", "interrupted"}
                else None
            ),
            result_artifact_id=fields.get(
                "result_artifact_id"
            ),
            payload_updates=(
                {
                    "output_filename": fields[
                        "output_filename"
                    ]
                }
                if fields.get("output_filename")
                else None
            ),
        )

    @staticmethod
    def _persistent_job_to_task(
        job: LocalJob,
    ) -> dict[str, Any]:
        public_status = {
            "queued": "rendering",
            "running": "rendering",
            "succeeded": "success",
            "failed": "error",
            "interrupted": "interrupted",
            "cancelled": "interrupted",
        }.get(job.status, job.status)
        started_at = (
            job.started_at or job.created_at
        ).timestamp()
        finished_at = (
            job.finished_at.timestamp()
            if job.finished_at
            else None
        )
        payload = job.get_payload()
        elapsed = (
            max(
                0.0,
                (
                    job.finished_at
                    - (job.started_at or job.created_at)
                ).total_seconds(),
            )
            if job.finished_at
            else max(0.0, time.time() - started_at)
        )
        return {
            "task_id": job.id,
            "project_id": job.project_id,
            "status": public_status,
            "stage": job.stage,
            "started_at": started_at,
            "finished_at": finished_at,
            "elapsed_sec": round(elapsed, 1),
            "error": job.error,
            "video": None,
            "videos": None,
            "output_filename": (
                str(payload.get("output_filename") or "")
                or None
            ),
            "result_artifact_id": job.result_artifact_id,
            "progress": int(job.progress or 0),
        }

    @staticmethod
    def _read_contract_slide_ids(
        run_dir: str | Path,
    ) -> list[str]:
        path = Path(run_dir) / "planning" / "visual_contract.json"
        try:
            payload = json.loads(
                path.read_text(encoding="utf-8-sig")
            )
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(payload, dict):
            return []
        return [
            str(slide.get("slide_id") or "").strip()
            for slide in payload.get("slides", [])
            if (
                isinstance(slide, dict)
                and str(slide.get("slide_id") or "").strip()
            )
        ]


_SERVICE_LOCK = threading.Lock()
_SERVICE: VideoRenderService | None = None


def configure_video_render_service(
    dependencies: VideoRenderDependencies,
    *,
    recover_jobs: bool = True,
) -> VideoRenderService:
    global _SERVICE
    service = VideoRenderService(dependencies)
    with _SERVICE_LOCK:
        _SERVICE = service
    if recover_jobs:
        changed = service.recover_jobs()
        if changed:
            logger.info(
                "Marked %s orphaned video render job(s) as interrupted",
                changed,
            )
    return service


def get_video_render_service() -> VideoRenderService:
    if _SERVICE is None:
        raise RuntimeError(
            "Video render service has not been configured"
        )
    return _SERVICE
