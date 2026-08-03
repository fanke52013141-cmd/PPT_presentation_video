"""Persistent SQLite storage for video render jobs."""

from __future__ import annotations

from datetime import datetime
import json
from typing import Any, Callable

from sqlalchemy.orm import Session

from database import LocalJob


VIDEO_RENDER_JOB_TYPE = "video_render"
ACTIVE_JOB_STATUSES = ("queued", "running")
_UNSET = object()
TERMINAL_JOB_STATUSES = (
    "succeeded",
    "failed",
    "interrupted",
    "cancelled",
)


class VideoJobStore:
    """SQLite job operations bound to the rendering session factory."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory

    def create(
        self,
        project_id: str,
        *,
        job_id: str,
        stage: str,
        payload: dict[str, Any],
    ) -> LocalJob:
        db = self.session_factory()
        try:
            job = LocalJob(
                id=job_id,
                project_id=project_id,
                job_type=VIDEO_RENDER_JOB_TYPE,
                status="queued",
                progress=0,
                stage=stage,
                payload_json=json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            )
            db.add(job)
            db.commit()
            db.refresh(job)
            db.expunge(job)
            return job
        finally:
            db.close()

    def get(
        self,
        job_id: str,
        *,
        project_id: str | None = None,
    ) -> LocalJob | None:
        db = self.session_factory()
        try:
            query = db.query(LocalJob).filter(LocalJob.id == job_id)
            if project_id:
                query = query.filter(LocalJob.project_id == project_id)
            job = query.first()
            if job:
                db.expunge(job)
            return job
        finally:
            db.close()

    def latest(self, project_id: str) -> LocalJob | None:
        db = self.session_factory()
        try:
            job = (
                db.query(LocalJob)
                .filter(
                    LocalJob.project_id == project_id,
                    LocalJob.job_type == VIDEO_RENDER_JOB_TYPE,
                )
                .order_by(LocalJob.created_at.desc())
                .first()
            )
            if job:
                db.expunge(job)
            return job
        finally:
            db.close()

    def active(self, project_id: str) -> LocalJob | None:
        db = self.session_factory()
        try:
            job = (
                db.query(LocalJob)
                .filter(
                    LocalJob.project_id == project_id,
                    LocalJob.job_type == VIDEO_RENDER_JOB_TYPE,
                    LocalJob.status.in_(ACTIVE_JOB_STATUSES),
                )
                .order_by(LocalJob.created_at.desc())
                .first()
            )
            if job:
                db.expunge(job)
            return job
        finally:
            db.close()

    def update(
        self,
        job_id: str,
        *,
        status: str | None = None,
        stage: str | None = None,
        progress: int | None = None,
        error: str | None | object = _UNSET,
        result_artifact_id: str | None = None,
        payload_updates: dict[str, Any] | None = None,
    ) -> LocalJob | None:
        db = self.session_factory()
        try:
            job = db.query(LocalJob).filter(LocalJob.id == job_id).first()
            if not job:
                return None
            now = datetime.now()
            if status:
                job.status = status
                if status == "running" and not job.started_at:
                    job.started_at = now
                if status in TERMINAL_JOB_STATUSES:
                    job.finished_at = now
            if stage is not None:
                job.stage = stage
            if progress is not None:
                job.progress = max(0, min(100, int(progress)))
            if error is not _UNSET:
                job.error = str(error)[:4000] if error else None
            if result_artifact_id is not None:
                job.result_artifact_id = result_artifact_id
            if payload_updates:
                payload = job.get_payload()
                payload.update(payload_updates)
                job.payload_json = json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                )
            job.updated_at = now
            db.commit()
            db.refresh(job)
            db.expunge(job)
            return job
        finally:
            db.close()

    def interrupt_orphaned(self, message: str) -> int:
        db = self.session_factory()
        try:
            jobs = (
                db.query(LocalJob)
                .filter(
                    LocalJob.job_type == VIDEO_RENDER_JOB_TYPE,
                    LocalJob.status.in_(ACTIVE_JOB_STATUSES),
                )
                .all()
            )
            now = datetime.now()
            for job in jobs:
                job.status = "interrupted"
                job.stage = "interrupted"
                job.error = str(message)[:4000]
                job.finished_at = now
                job.updated_at = now
            db.commit()
            return len(jobs)
        finally:
            db.close()
