"""Persistent SQLite storage for video render jobs."""

from __future__ import annotations

from datetime import datetime
import json
import time
from typing import Any, Callable

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from database import LocalJob


VIDEO_RENDER_JOB_TYPE = "video_render"
ACTIVE_JOB_STATUSES = ("queued", "running")
_UNSET = object()
_CREATE_RETRY_DELAYS_SEC = (0.15, 0.5)
TERMINAL_JOB_STATUSES = (
    "succeeded",
    "failed",
    "interrupted",
    "cancelled",
)


class VideoJobPersistenceError(RuntimeError):
    """A safe, structured failure while creating a persistent render job.

    The underlying driver exception can include SQL statements, bound values, or
    database locations.  Keep it chained for local debugging, but expose only
    this small diagnostic contract to the render service and user-facing logs.
    """

    def __init__(
        self,
        *,
        category: str,
        exception_type: str,
        attempt_count: int,
        retryable: bool,
    ) -> None:
        super().__init__(category)
        self.category = category
        self.exception_type = exception_type
        self.attempt_count = attempt_count
        self.retryable = retryable

    @property
    def public_message(self) -> str:
        if self.category == "sqlite_write_locked":
            return "本地任务数据库正忙，请稍后重试。"
        return "无法创建持久化视频任务，请重试。"


def _is_sqlite_busy_or_locked(exc: OperationalError) -> bool:
    """Return true only for SQLite's explicit transient writer contention."""

    message = str(getattr(exc, "orig", exc)).lower()
    return "database is locked" in message or "database is busy" in message


class VideoJobStore:
    """SQLite job operations bound to the rendering session factory."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.session_factory = session_factory
        self._sleep = sleep

    def create(
        self,
        project_id: str,
        *,
        job_id: str,
        stage: str,
        payload: dict[str, Any],
        submission_key: str | None = None,
        submission_attempt: int = 0,
    ) -> LocalJob:
        """Insert one queued job in a short transaction.

        Each attempt receives a fresh session.  SQLite writer contention is the
        only retryable database condition; all other failures are surfaced with
        a sanitized diagnostic instead of retrying a potentially invalid write.
        """
        max_attempts = len(_CREATE_RETRY_DELAYS_SEC) + 1
        for attempt in range(1, max_attempts + 1):
            try:
                db = self.session_factory()
            except Exception as exc:
                raise VideoJobPersistenceError(
                    category="database_session_open_failed",
                    exception_type=type(exc).__name__,
                    attempt_count=attempt,
                    retryable=False,
                ) from exc
            committed = False
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
                if submission_key is not None:
                    # LocalJob intentionally remains backward-compatible with
                    # older database.py mappings.  The migration-owned fields
                    # are read and written through parameterized SQL until the
                    # shared model can be updated in its own change set.
                    db.flush()
                    db.execute(
                        text(
                            "UPDATE local_jobs "
                            "SET submission_key = :submission_key, "
                            "submission_attempt = :submission_attempt "
                            "WHERE id = :job_id"
                        ),
                        {
                            "submission_key": submission_key,
                            "submission_attempt": max(
                                0,
                                int(submission_attempt),
                            ),
                            "job_id": job_id,
                        },
                    )
                db.commit()
                committed = True
                db.refresh(job)
                db.expunge(job)
                return job
            except OperationalError as exc:
                locked = not committed and _is_sqlite_busy_or_locked(exc)
                retryable = locked
                if locked and attempt < max_attempts:
                    delay = _CREATE_RETRY_DELAYS_SEC[attempt - 1]
                else:
                    category = (
                        "sqlite_write_locked"
                        if locked
                        else "database_operational_error"
                    )
                    raise VideoJobPersistenceError(
                        category=category,
                        exception_type=type(exc).__name__,
                        attempt_count=attempt,
                        retryable=retryable,
                    ) from exc
            except Exception as exc:
                raise VideoJobPersistenceError(
                    category="database_write_failed",
                    exception_type=type(exc).__name__,
                    attempt_count=attempt,
                    retryable=False,
                ) from exc
            finally:
                # Rollback is harmless after a successful commit and ensures
                # failures never leave a pending write transaction behind.
                try:
                    db.rollback()
                except Exception:
                    # The original persistence error remains the actionable
                    # one.  Do not replace its sanitized diagnostic with a
                    # cleanup implementation detail.
                    pass
                finally:
                    try:
                        db.close()
                    except Exception:
                        # A close failure must not replace the sanitized write
                        # failure above or expose driver details to callers.
                        pass
            self._sleep(delay)

        raise AssertionError("video job retry loop exited unexpectedly")

    def latest_for_submission(
        self,
        project_id: str,
        submission_key: str,
    ) -> LocalJob | None:
        """Return the latest render job for one stable input submission.

        ``submission_key`` and ``submission_attempt`` were added by migration
        0010.  They intentionally stay outside the legacy ``LocalJob`` ORM
        mapping so a concurrent, unrelated model change cannot alter this
        persistence path.
        """
        db = self.session_factory()
        try:
            job = (
                db.query(LocalJob)
                .from_statement(
                    text(
                        "SELECT id, project_id, job_type, status, progress, "
                        "stage, error, result_artifact_id, payload_json, "
                        "created_at, started_at, finished_at, updated_at "
                        "FROM local_jobs "
                        "WHERE project_id = :project_id "
                        "AND job_type = :job_type "
                        "AND submission_key = :submission_key "
                        "ORDER BY submission_attempt DESC, created_at DESC "
                        "LIMIT 1"
                    )
                )
                .params(
                    project_id=project_id,
                    job_type=VIDEO_RENDER_JOB_TYPE,
                    submission_key=submission_key,
                )
                .first()
            )
            if job:
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
