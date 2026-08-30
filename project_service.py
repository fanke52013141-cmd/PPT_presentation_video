"""Project creation, discovery, mode selection, and deletion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
import os
from pathlib import Path
import shutil
from typing import Any, Callable, Optional
import uuid

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import ArtifactRecord, LocalJob, Project
from project_storage import (
    UnsafeProjectPath,
    project_run_dir,
)
from canvas_profile_service import (
    DEFAULT_CANVAS_PROFILE,
    get_canvas_profile,
    normalize_canvas_profile,
    write_project_canvas_snapshot,
)


logger = logging.getLogger("PPTStudio.Projects")


class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = ""
    ai_mode: Optional[str] = "auto"
    canvas_profile: Optional[str] = DEFAULT_CANVAS_PROFILE


class AiModeUpdate(BaseModel):
    ai_mode: str


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    ai_mode: Optional[str] = None


@dataclass(frozen=True)
class ProjectDependencies:
    runs_root: Path
    project_audio_confirmed: Callable[[Project], bool]


class ProjectService:
    def __init__(self, dependencies: ProjectDependencies) -> None:
        self.dependencies = dependencies

    def create(
        self,
        payload: ProjectCreate,
        db: Session,
    ) -> dict[str, Any]:
        project_id = (
            str(uuid.uuid4())[:8]
            + "_"
            + datetime.now().strftime("%H%M%S")
        )
        run_dir = project_run_dir(
            self.dependencies.runs_root,
            self.dependencies.runs_root / project_id,
            project_id,
        )
        for child in ("inputs", "planning", "slides", "review"):
            (run_dir / child).mkdir(parents=True, exist_ok=True)
        initial_step_status = {
            str(index): "pending"
            for index in range(1, 9)
        }
        ai_mode = (payload.ai_mode or "auto").strip().lower()
        if ai_mode not in {"auto", "manual"}:
            ai_mode = "auto"
        canvas_profile = normalize_canvas_profile(payload.canvas_profile)
        project = Project(
            id=project_id,
            name=payload.name,
            description=payload.description,
            current_step=1,
            status="active",
            run_dir=str(run_dir),
            ai_mode=ai_mode,
            canvas_profile=canvas_profile,
        )
        project.set_step_status(initial_step_status)
        db.add(project)
        try:
            write_project_canvas_snapshot(project)
            db.commit()
        except Exception:
            db.rollback()
            raise
        db.refresh(project)
        canvas = get_canvas_profile(project.canvas_profile)
        return {
            "success": True,
            "project": {
                "id": project.id,
                "name": project.name,
                "description": project.description,
                "current_step": project.current_step,
                "step_status": project.get_step_status(),
                "audio_confirmed": False,
                "ai_mode": project.ai_mode or "auto",
                "canvas_profile": project.canvas_profile or DEFAULT_CANVAS_PROFILE,
                "canvas": canvas,
            },
        }

    def list(self, db: Session) -> list[dict[str, Any]]:
        projects = (
            db.query(Project)
            .order_by(Project.created_at.desc())
            .all()
        )
        return [
            {
                "id": project.id,
                "name": project.name,
                "description": project.description,
                "current_step": project.current_step,
                "status": project.status,
                "step_status": project.get_step_status(),
                "audio_confirmed": (
                    self.dependencies.project_audio_confirmed(project)
                ),
                "ai_mode": project.ai_mode or "auto",
                "canvas_profile": project.canvas_profile or DEFAULT_CANVAS_PROFILE,
                "canvas": get_canvas_profile(project.canvas_profile),
                "created_at": project.created_at.isoformat(),
            }
            for project in projects
        ]

    def get(self, project_id: str, db: Session) -> dict[str, Any]:
        project = self._project(project_id, db)
        return {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "current_step": project.current_step,
            "status": project.status,
            "step_status": project.get_step_status(),
            "audio_confirmed": (
                self.dependencies.project_audio_confirmed(project)
            ),
            "run_dir": project.run_dir,
            "ai_mode": project.ai_mode or "auto",
            "canvas_profile": project.canvas_profile or DEFAULT_CANVAS_PROFILE,
            "canvas": get_canvas_profile(project.canvas_profile),
        }

    def get_ai_mode(
        self,
        project_id: str,
        db: Session,
    ) -> dict[str, str]:
        project = self._project(project_id, db)
        return {"ai_mode": project.ai_mode or "auto"}

    def update_ai_mode(
        self,
        project_id: str,
        payload: AiModeUpdate,
        db: Session,
    ) -> dict[str, Any]:
        project = self._project(project_id, db)
        ai_mode = (payload.ai_mode or "").strip().lower()
        if ai_mode not in {"auto", "manual"}:
            raise HTTPException(
                status_code=400,
                detail="ai_mode 必须为 auto 或 manual",
            )
        project.ai_mode = ai_mode
        db.commit()
        db.refresh(project)
        return {"success": True, "ai_mode": project.ai_mode}

    def update(
        self,
        project_id: str,
        payload: "ProjectUpdate",
        db: Session,
    ) -> dict[str, Any]:
        project = self._project(project_id, db)
        if payload.name is not None:
            project.name = payload.name.strip()
        if payload.description is not None:
            project.description = payload.description
        if payload.ai_mode is not None:
            ai_mode = (payload.ai_mode or "").strip().lower()
            if ai_mode not in {"auto", "manual"}:
                ai_mode = "auto"
            project.ai_mode = ai_mode
        db.commit()
        db.refresh(project)
        return {
            "success": True,
            "project": {
                "id": project.id,
                "name": project.name,
                "description": project.description,
                "ai_mode": project.ai_mode or "auto",
            },
        }

    def delete(
        self,
        project_id: str,
        db: Session,
    ) -> dict[str, Any]:
        project = self._project(project_id, db)
        # 拒绝在活跃渲染/一键生成任务期间删除，避免渲染线程重建
        # 已删除目录（幽灵目录）或对已删除记录继续写库。
        active_job = (
            db.query(LocalJob)
            .filter(
                LocalJob.project_id == project_id,
                LocalJob.status.in_(("queued", "running")),
            )
            .first()
        )
        if active_job is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "项目仍有正在进行的渲染任务，请先等待完成或取消后再删除。"
                ),
            )
        try:
            run_dir = project_run_dir(
                self.dependencies.runs_root,
                project.run_dir,
                project.id,
            )
        except UnsafeProjectPath as exc:
            raise HTTPException(
                status_code=500,
                detail="项目运行目录安全校验失败",
            ) from exc
        if run_dir.exists():
            try:
                shutil.rmtree(run_dir)
            except Exception as exc:
                logger.error(
                    "Failed to delete directory %s: %s",
                    run_dir,
                    exc,
                )
                raise HTTPException(
                    status_code=500,
                    detail="项目文件删除失败",
                ) from exc
        # 清理 Remotion 运行时缓存目录（scripts/remotion/public/runtime/<id>），
        # 避免删除项目后缓存永久残留、占用磁盘。
        runtime_cache = (
            Path(__file__).resolve().parent
            / "scripts"
            / "remotion"
            / "public"
            / "runtime"
            / project_id
        )
        if runtime_cache.exists():
            shutil.rmtree(runtime_cache, ignore_errors=True)
        (
            db.query(ArtifactRecord)
            .filter(ArtifactRecord.project_id == project_id)
            .delete(synchronize_session=False)
        )
        (
            db.query(LocalJob)
            .filter(LocalJob.project_id == project_id)
            .delete(synchronize_session=False)
        )
        db.delete(project)
        db.commit()
        return {"success": True, "message": "项目删除成功"}

    @staticmethod
    def _project(project_id: str, db: Session) -> Project:
        project = (
            db.query(Project)
            .filter(Project.id == project_id)
            .first()
        )
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
        return project


_SERVICE: ProjectService | None = None


def configure_project_service(
    dependencies: ProjectDependencies,
) -> ProjectService:
    global _SERVICE
    _SERVICE = ProjectService(dependencies)
    return _SERVICE


def get_project_service() -> ProjectService:
    if _SERVICE is None:
        raise RuntimeError("Project service has not been configured")
    return _SERVICE
