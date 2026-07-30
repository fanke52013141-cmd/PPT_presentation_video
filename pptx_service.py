"""Persistent image-only PPTX export jobs and artifact lifecycle."""

from __future__ import annotations

from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
import json
import logging
from pathlib import Path
import threading
import uuid
from typing import Any, Callable

from sqlalchemy.orm import Session

from artifact_fingerprint import presentation_input_fingerprint
from database import ArtifactRecord, LocalJob, Project
import invalidation_service
from pptx_export import (
    PPTX_MIME_TYPE,
    PptxReadinessError,
    build_image_only_pptx,
    inspect_pptx_readiness,
)
from project_storage import (
    UnsafeProjectPath,
    presentation_file,
    presentation_sidecar,
    project_run_dir,
)


logger = logging.getLogger("PPTStudio.PPTX")


class PptxServiceError(RuntimeError):
    def __init__(self, status_code: int, detail: Any) -> None:
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class PptxServiceDependencies:
    session_factory: Callable[[], Session]
    runs_root: Path
    executor: Executor | None = None


class PptxExportService:
    def __init__(self, dependencies: PptxServiceDependencies) -> None:
        self.dependencies = dependencies
        self.executor = dependencies.executor or ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="pptx-export",
        )
        self._create_lock = threading.Lock()

    @staticmethod
    def _iso(value: datetime | None) -> str | None:
        return value.isoformat(timespec="seconds") if value else None

    def project_run_dir(self, project: Project) -> str:
        try:
            return str(
                project_run_dir(
                    self.dependencies.runs_root,
                    project.run_dir,
                    project.id,
                )
            )
        except UnsafeProjectPath as exc:
            logger.error(
                "Unsafe project run directory for %s: %s",
                project.id,
                exc,
            )
            raise PptxServiceError(
                500,
                "项目运行目录安全校验失败",
            ) from exc

    def get_project(self, db: Session, project_id: str) -> Project:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise PptxServiceError(404, "项目不存在")
        return project

    def job_item(self, job: LocalJob) -> dict[str, Any]:
        return {
            "id": job.id,
            "project_id": job.project_id,
            "job_type": job.job_type,
            "status": job.status,
            "progress": int(job.progress or 0),
            "stage": job.stage,
            "error": job.error,
            "result_artifact_id": job.result_artifact_id,
            "created_at": self._iso(job.created_at),
            "started_at": self._iso(job.started_at),
            "finished_at": self._iso(job.finished_at),
            "updated_at": self._iso(job.updated_at),
        }

    def artifact_item(
        self,
        project: Project,
        artifact: ArtifactRecord,
        *,
        current_fingerprint: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        run_dir = self.project_run_dir(project)
        metadata = artifact.get_metadata()
        stored_fingerprint = artifact.get_source_fingerprint()
        try:
            path = presentation_file(run_dir, artifact.filename)
        except UnsafeProjectPath:
            path = Path(run_dir) / "__invalid__"
        exists = path.is_file()
        current_fingerprint = (
            current_fingerprint
            or presentation_input_fingerprint(run_dir)
        )
        state = "missing"
        if exists:
            state = (
                "current"
                if stored_fingerprint.get("digest")
                == current_fingerprint.get("digest")
                else "stale"
            )
        return {
            "id": artifact.id,
            "artifact_type": artifact.artifact_type,
            "filename": artifact.filename,
            "size_bytes": (
                path.stat().st_size
                if exists
                else int(artifact.size_bytes or 0)
            ),
            "mime_type": artifact.mime_type,
            "created_at": self._iso(artifact.created_at),
            "slide_count": int(metadata.get("slide_count") or 0),
            "content_mode": (
                metadata.get("content_mode")
                or "full_slide_bitmap"
            ),
            "artifact_state": state,
            "is_current": state == "current",
            "is_stale": state == "stale",
            "exists": exists,
            "download_url": (
                f"/api/projects/{project.id}/exports/"
                f"{artifact.id}/download"
            ),
        }

    def readiness(
        self,
        db: Session,
        project_id: str,
    ) -> dict[str, Any]:
        project = self.get_project(db, project_id)
        return {
            "success": True,
            **inspect_pptx_readiness(self.project_run_dir(project)),
        }

    def create_export(
        self,
        db: Session,
        project_id: str,
    ) -> dict[str, Any]:
        project = self.get_project(db, project_id)
        readiness = inspect_pptx_readiness(self.project_run_dir(project))
        if not readiness["ready"]:
            raise PptxServiceError(
                409,
                {
                    "message": "当前项目还不能生成 PPTX。",
                    "issues": readiness["issues"],
                },
            )
        with self._create_lock:
            active = self._active_job(db, project.id)
            if active:
                return {
                    "success": True,
                    "reused": True,
                    "job": self.job_item(active),
                }
            job = self._new_job(project.id)
            db.add(job)
            db.commit()
            db.refresh(job)
        self.submit(job.id)
        return {
            "success": True,
            "reused": False,
            "job": self.job_item(job),
        }

    def list_jobs(
        self,
        db: Session,
        project_id: str,
        *,
        job_type: str | None = None,
    ) -> dict[str, Any]:
        self.get_project(db, project_id)
        query = db.query(LocalJob).filter(
            LocalJob.project_id == project_id
        )
        if job_type:
            query = query.filter(LocalJob.job_type == job_type)
        jobs = (
            query.order_by(LocalJob.created_at.desc())
            .limit(50)
            .all()
        )
        return {
            "success": True,
            "jobs": [self.job_item(job) for job in jobs],
        }

    def get_job(
        self,
        db: Session,
        project_id: str,
        job_id: str,
    ) -> dict[str, Any]:
        self.get_project(db, project_id)
        job = (
            db.query(LocalJob)
            .filter(
                LocalJob.id == job_id,
                LocalJob.project_id == project_id,
            )
            .first()
        )
        if not job:
            raise PptxServiceError(404, "任务不存在")
        return {"success": True, "job": self.job_item(job)}

    def retry_job(
        self,
        db: Session,
        project_id: str,
        job_id: str,
    ) -> dict[str, Any]:
        project = self.get_project(db, project_id)
        previous = (
            db.query(LocalJob)
            .filter(
                LocalJob.id == job_id,
                LocalJob.project_id == project_id,
                LocalJob.job_type == "pptx_export",
            )
            .first()
        )
        if not previous:
            raise PptxServiceError(404, "任务不存在")
        if previous.status not in {"failed", "interrupted"}:
            raise PptxServiceError(
                409,
                "只有失败或中断的任务可以重试",
            )
        readiness = inspect_pptx_readiness(
            self.project_run_dir(project)
        )
        if not readiness["ready"]:
            raise PptxServiceError(
                409,
                {
                    "message": "当前项目还不能重新导出。",
                    "issues": readiness["issues"],
                },
            )
        with self._create_lock:
            active = self._active_job(db, project_id)
            if active:
                return {
                    "success": True,
                    "reused": True,
                    "job": self.job_item(active),
                }
            job = self._new_job(project_id)
            db.add(job)
            db.commit()
            db.refresh(job)
        self.submit(job.id)
        return {
            "success": True,
            "reused": False,
            "job": self.job_item(job),
        }

    def list_exports(
        self,
        db: Session,
        project_id: str,
    ) -> dict[str, Any]:
        project = self.get_project(db, project_id)
        artifacts = self._artifacts(db, project_id)
        fingerprint = presentation_input_fingerprint(
            self.project_run_dir(project)
        )
        return {
            "success": True,
            "artifacts": [
                self.artifact_item(
                    project,
                    artifact,
                    current_fingerprint=fingerprint,
                )
                for artifact in artifacts
            ],
        }

    def download_export(
        self,
        db: Session,
        project_id: str,
        artifact_id: str,
    ) -> tuple[Path, ArtifactRecord]:
        project = self.get_project(db, project_id)
        artifact = self._artifact_or_404(
            db,
            project_id,
            artifact_id,
        )
        try:
            path = presentation_file(
                self.project_run_dir(project),
                artifact.filename,
            )
        except UnsafeProjectPath as exc:
            raise PptxServiceError(
                400,
                "PPTX 文件名无效",
            ) from exc
        if not path.is_file():
            raise PptxServiceError(404, "PPTX 文件已不存在")
        return path, artifact

    def delete_export(
        self,
        db: Session,
        project_id: str,
        artifact_id: str,
    ) -> dict[str, Any]:
        project = self.get_project(db, project_id)
        artifact = self._artifact_or_404(
            db,
            project_id,
            artifact_id,
        )
        try:
            path = presentation_file(
                self.project_run_dir(project),
                artifact.filename,
            )
        except UnsafeProjectPath as exc:
            raise PptxServiceError(
                400,
                "PPTX 文件名无效",
            ) from exc
        sidecar = presentation_sidecar(path)
        for target in (path, sidecar):
            if target.exists():
                target.unlink()
        db.delete(artifact)
        db.commit()
        remaining = self._artifacts(db, project_id)
        fingerprint = presentation_input_fingerprint(
            self.project_run_dir(project)
        )
        return {
            "success": True,
            "artifacts": [
                self.artifact_item(
                    project,
                    item,
                    current_fingerprint=fingerprint,
                )
                for item in remaining
            ],
        }

    def submit(self, job_id: str) -> None:
        self.executor.submit(self.run_job, job_id)

    def recover_jobs(self) -> None:
        db = self.dependencies.session_factory()
        queued_ids: list[str] = []
        try:
            running = (
                db.query(LocalJob)
                .filter(
                    LocalJob.job_type == "pptx_export",
                    LocalJob.status == "running",
                )
                .all()
            )
            now = datetime.now()
            for job in running:
                job.status = "interrupted"
                job.stage = "interrupted"
                job.error = (
                    "应用上次运行时退出，任务已中断；可以重新导出。"
                )
                job.finished_at = now
                job.updated_at = now
            queued_ids = [
                job.id
                for job in (
                    db.query(LocalJob)
                    .filter(
                        LocalJob.job_type == "pptx_export",
                        LocalJob.status == "queued",
                    )
                    .all()
                )
            ]
            db.commit()
        finally:
            db.close()
        for job_id in queued_ids:
            self.submit(job_id)

    def run_job(self, job_id: str) -> None:
        db = self.dependencies.session_factory()
        output_path: Path | None = None
        try:
            job = (
                db.query(LocalJob)
                .filter(LocalJob.id == job_id)
                .first()
            )
            if not job:
                return
            project = (
                db.query(Project)
                .filter(Project.id == job.project_id)
                .first()
            )
            if not project:
                raise RuntimeError(
                    "项目不存在，无法继续导出"
                )
            job.status = "running"
            job.stage = "validating"
            job.progress = 5
            job.started_at = datetime.now()
            job.updated_at = datetime.now()
            db.commit()

            filename = str(
                job.get_payload().get("filename") or ""
            )
            result = build_image_only_pptx(
                self.project_run_dir(project),
                filename,
                title=project.name,
                progress=lambda value, stage: self.set_job_progress(
                    job_id,
                    value,
                    stage,
                ),
            )
            output_path = Path(result["path"])
            artifact = ArtifactRecord(
                id=uuid.uuid4().hex,
                project_id=project.id,
                artifact_type="pptx",
                filename=result["filename"],
                relative_path=(
                    f"presentations/{result['filename']}"
                ),
                mime_type=PPTX_MIME_TYPE,
                size_bytes=result["size_bytes"],
                source_fingerprint=json.dumps(
                    result["fingerprint"],
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                metadata_json=json.dumps(
                    result["metadata"],
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            )
            db.add(artifact)
            invalidation_service.complete_stage(project, 8)
            job = (
                db.query(LocalJob)
                .filter(LocalJob.id == job_id)
                .first()
            )
            if not job:
                raise RuntimeError("PPTX 导出任务记录不存在")
            job.status = "succeeded"
            job.stage = "completed"
            job.progress = 100
            job.error = None
            job.result_artifact_id = artifact.id
            job.finished_at = datetime.now()
            job.updated_at = datetime.now()
            db.commit()
        except PptxReadinessError as exc:
            self.fail_job(
                db,
                job_id,
                "导出条件已变化，请刷新页面后重新检查。",
            )
            logger.info(
                "PPTX readiness changed for job %s: %s",
                job_id,
                exc.readiness,
            )
        except Exception as exc:
            self._remove_partial_output(output_path)
            logger.exception("PPTX export failed for job %s", job_id)
            self.fail_job(db, job_id, str(exc))
        finally:
            db.close()

    def set_job_progress(
        self,
        job_id: str,
        progress: int,
        stage: str,
    ) -> None:
        db = self.dependencies.session_factory()
        try:
            job = (
                db.query(LocalJob)
                .filter(LocalJob.id == job_id)
                .first()
            )
            if not job or job.status not in {"queued", "running"}:
                return
            job.status = "running"
            job.progress = max(0, min(100, int(progress)))
            job.stage = str(stage or "running")
            job.updated_at = datetime.now()
            db.commit()
        finally:
            db.close()

    @staticmethod
    def fail_job(
        db: Session,
        job_id: str,
        message: str,
    ) -> None:
        job = (
            db.query(LocalJob)
            .filter(LocalJob.id == job_id)
            .first()
        )
        if not job:
            return
        job.status = "failed"
        job.stage = "failed"
        job.error = str(message or "PPTX 导出失败")[:4000]
        job.finished_at = datetime.now()
        job.updated_at = datetime.now()
        db.commit()

    @staticmethod
    def _remove_partial_output(output_path: Path | None) -> None:
        if not output_path or not output_path.exists():
            return
        try:
            output_path.unlink()
        except OSError:
            pass
        sidecar = presentation_sidecar(output_path)
        if sidecar.exists():
            try:
                sidecar.unlink()
            except OSError:
                pass

    @staticmethod
    def _new_job(project_id: str) -> LocalJob:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = (
            f"presentation_{timestamp}_{uuid.uuid4().hex[:6]}.pptx"
        )
        return LocalJob(
            id=uuid.uuid4().hex,
            project_id=project_id,
            job_type="pptx_export",
            status="queued",
            progress=0,
            stage="queued",
            payload_json=json.dumps(
                {"filename": filename},
                ensure_ascii=False,
            ),
        )

    @staticmethod
    def _active_job(
        db: Session,
        project_id: str,
    ) -> LocalJob | None:
        return (
            db.query(LocalJob)
            .filter(
                LocalJob.project_id == project_id,
                LocalJob.job_type == "pptx_export",
                LocalJob.status.in_(("queued", "running")),
            )
            .order_by(LocalJob.created_at.desc())
            .first()
        )

    @staticmethod
    def _artifacts(
        db: Session,
        project_id: str,
    ) -> list[ArtifactRecord]:
        return (
            db.query(ArtifactRecord)
            .filter(
                ArtifactRecord.project_id == project_id,
                ArtifactRecord.artifact_type == "pptx",
            )
            .order_by(ArtifactRecord.created_at.desc())
            .all()
        )

    @staticmethod
    def _artifact_or_404(
        db: Session,
        project_id: str,
        artifact_id: str,
    ) -> ArtifactRecord:
        artifact = (
            db.query(ArtifactRecord)
            .filter(
                ArtifactRecord.id == artifact_id,
                ArtifactRecord.project_id == project_id,
                ArtifactRecord.artifact_type == "pptx",
            )
            .first()
        )
        if not artifact:
            raise PptxServiceError(404, "PPTX 产物不存在")
        return artifact


_SERVICE_LOCK = threading.Lock()
_SERVICE: PptxExportService | None = None


def configure_pptx_export_service(
    dependencies: PptxServiceDependencies,
    *,
    recover_jobs: bool = True,
) -> PptxExportService:
    global _SERVICE
    service = PptxExportService(dependencies)
    with _SERVICE_LOCK:
        _SERVICE = service
    if recover_jobs:
        service.recover_jobs()
    return service


def get_pptx_export_service() -> PptxExportService:
    if _SERVICE is None:
        raise RuntimeError("PPTX export service has not been configured")
    return _SERVICE
