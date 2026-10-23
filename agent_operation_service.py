"""Exact operation views over source-owned durable jobs and pipeline run files.

This service does not persist a competing terminal status or recover workers.
Each producer retains ownership of recovery and cancellation semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from database import LocalJob
from agent_contract.operations import (
    OperationResult, OperationStatus, OperationListResult, OperationCancelResult,
    normalize_status, operation_from_one_click,
)


@dataclass(frozen=True)
class AgentOperationDependencies:
    pipeline_get: Callable
    pipeline_list: Callable
    control_status: Callable
    control_stop: Callable


class AgentOperationError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 404):
        self.code, self.message, self.status_code = code, message, status_code
        super().__init__(message)


class AgentOperationService:
    def __init__(self, deps: AgentOperationDependencies):
        self.deps = deps

    @staticmethod
    def _parts(operation_id: str) -> tuple[str, str]:
        kind, separator, source_id = operation_id.partition(":")
        if not separator or kind not in {"job", "pipeline"} or not source_id or any(
            ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for ch in source_id
        ) or len(source_id) > 128:
            raise AgentOperationError("VALIDATION_ERROR", "Invalid operation ID", 422)
        return kind, source_id

    def _job_view(self, job) -> OperationResult:
        status = normalize_status(str(job.status))
        if job.status == "paused":
            status = OperationStatus.waiting_for_user
        kind = {"tts_synthesis": "tts", "video_render": "video"}.get(job.job_type)
        control = self.deps.control_status(job.project_id, kind) if kind else {}
        supported = bool(kind and control.get("operation_id") == job.id and control.get("active"))
        errors = [str(job.error)] if job.error and status != OperationStatus.succeeded else []
        return OperationResult(
            operation_id=f"job:{job.id}", project_id=job.project_id,
            operation_type=job.job_type, status=status, raw_status=str(job.status),
            progress=100 if status == OperationStatus.succeeded else max(0, min(100, int(job.progress or 0))),
            stage=job.stage or "", blocking_errors=errors,
            message=errors[0] if errors else "",
            artifacts=[{"artifact_id": job.result_artifact_id}] if job.result_artifact_id else [],
            started_at=job.started_at.isoformat() if job.started_at else None,
            finished_at=job.finished_at.isoformat() if job.finished_at else None,
            cancellation_supported=supported and status in {OperationStatus.queued, OperationStatus.running},
            cancellation_requested=bool(supported and control.get("stop_requested")),
        )

    @staticmethod
    def _pipeline_view(data: dict, project_id: str) -> OperationResult:
        return operation_from_one_click(data, project_id)

    def get(self, db, project, operation_id: str) -> OperationResult:
        kind, source_id = self._parts(operation_id)
        if kind == "job":
            job = db.query(LocalJob).filter(LocalJob.id == source_id, LocalJob.project_id == project.id).first()
            if job:
                return self._job_view(job)
        else:
            try:
                data = self.deps.pipeline_get(project, source_id)
            except (ValueError, OSError) as exc:
                raise AgentOperationError("OPERATION_UNAVAILABLE", "Pipeline run record is unavailable", 503) from exc
            if data:
                return self._pipeline_view(data, str(project.id))
        raise AgentOperationError("OPERATION_NOT_FOUND", "Operation not found in this project")

    def list(self, db, project, *, offset: int = 0, limit: int = 50) -> OperationListResult:
        query = db.query(LocalJob).filter(LocalJob.project_id == project.id)
        job_total = query.count()
        # Only the first offset+limit jobs can contribute to this page after
        # merging pipeline runs; do not load every job payload into memory.
        jobs = query.order_by(LocalJob.created_at.desc(), LocalJob.id.desc()).limit(offset + limit).all()
        records = [(job.created_at.isoformat(), "job:" + job.id, self._job_view(job)) for job in jobs]
        try:
            runs = self.deps.pipeline_list(project)
        except (ValueError, OSError) as exc:
            raise AgentOperationError("OPERATION_UNAVAILABLE", "Pipeline run records are unavailable", 503) from exc
        for data in runs:
            if data:
                view = self._pipeline_view(data, str(project.id))
                records.append((str(data.get("run_started_at") or data.get("started_at") or ""), view.operation_id, view))
        records.sort(key=lambda row: (row[0], row[1]), reverse=True)
        total = job_total + sum(1 for data in runs if data)
        return OperationListResult(project_id=str(project.id), operations=[row[2] for row in records[offset:offset + limit]],
                                   total=total, next_offset=offset + limit if offset + limit < total else None)

    def cancel(self, db, project, operation_id: str) -> OperationCancelResult:
        operation = self.get(db, project, operation_id)
        if operation.status in {OperationStatus.succeeded, OperationStatus.failed, OperationStatus.cancelled, OperationStatus.interrupted}:
            return OperationCancelResult(operation_id=operation_id, accepted=False, status=operation.status,
                                         message="Operation is already terminal")
        kind, source_id = self._parts(operation_id)
        if kind == "pipeline" or operation.operation_type not in {"tts_synthesis", "video_render"}:
            raise AgentOperationError("CANCELLATION_UNSUPPORTED", "This operation does not support exact cancellation", 422)
        control_kind = "tts" if operation.operation_type == "tts_synthesis" else "video"
        response = self.deps.control_stop(str(project.id), control_kind, source_id)
        # Cancellation may finish synchronously for a queued task; read source
        # state again instead of claiming the stop request itself is terminal.
        db.expire_all()
        after = self.get(db, project, operation_id)
        return OperationCancelResult(operation_id=operation_id, accepted=bool(response["accepted"]),
                                     status=after.status, message=response["message"])
