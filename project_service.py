"""Project creation, discovery, mode selection, and deletion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import shutil
from typing import Any, Callable, Optional
import uuid

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import ArtifactRecord, Chapter, Course, LocalJob, Project
from account_context import get_current_account_id
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
from visual_settings_service import (
    PROJECT_VISUAL_SETTINGS_FILE,
    normalize_subtitle_style,
)


logger = logging.getLogger("PPTStudio.Projects")


class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = ""
    ai_mode: Optional[str] = "auto"
    canvas_profile: Optional[str] = DEFAULT_CANVAS_PROFILE
    review_policy: Optional[str] = "none"
    manual_pause_steps: Optional[list[str]] = None
    image_style_template: Optional[str] = "default"
    # Kept for callers using the old API.  New projects start as full-frame.
    mask_enabled: Optional[bool] = False
    production_mode: Optional[str] = "guided"
    presentation_mode: Optional[str] = "full_frame"
    creation_config_package_id: Optional[str] = None
    creation_config_version: Optional[int] = None
    creation_config_overrides: Optional[dict[str, Any]] = None
    # Short aliases are accepted by automation clients; the response always
    # exposes the canonical ``creation_config`` summary.
    config_package_id: Optional[str] = None
    config_package_version: Optional[int] = None
    config_overrides: Optional[dict[str, Any]] = None
    # New projects are normally created from a chapter.  Both fields remain
    # optional for legacy standalone projects and Agent compatibility.
    course_id: Optional[str] = None
    chapter_id: Optional[str] = None


class AiModeUpdate(BaseModel):
    ai_mode: str


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    ai_mode: Optional[str] = None
    production_mode: Optional[str] = None
    presentation_mode: Optional[str] = None


@dataclass(frozen=True)
class ProjectDependencies:
    runs_root: Path
    project_audio_confirmed: Callable[[Project], bool]
    resolve_creation_config: Optional[
        Callable[[str, Optional[int], dict[str, Any]], dict[str, Any]]
    ] = None
    write_json_atomic: Optional[Callable[[str | Path, Any], None]] = None
    get_default_creation_config: Optional[Callable[[str, Session], dict[str, Any] | None]] = None
    materialize_image_style: Optional[
        Callable[[Project, dict[str, Any]], dict[str, Any] | None]
    ] = None


class ProjectService:
    def __init__(self, dependencies: ProjectDependencies) -> None:
        self.dependencies = dependencies

    def create(
        self,
        payload: ProjectCreate,
        db: Session,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        account_id = account_id or get_current_account_id()
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
        review_policy = (payload.review_policy or "none").strip().lower()
        if review_policy not in {"none", "images_and_video", "all_stages"}:
            review_policy = "none"
        # Normalize manual pause steps — only accept known module names.
        _valid_pause = {"digital_human", "mask", "narration", "tts"}
        raw_pause = payload.manual_pause_steps or []
        manual_pause = [s for s in raw_pause if s in _valid_pause]
        image_style_template = (payload.image_style_template or "default").strip()
        production_mode = (payload.production_mode or "guided").strip().lower()
        if production_mode not in {"one_click", "guided"}:
            production_mode = "guided"
        presentation_mode = (payload.presentation_mode or "full_frame").strip().lower()
        if presentation_mode not in {"full_frame", "reveal"}:
            presentation_mode = "full_frame"
        # One-click is always a complete-frame video.  ``mask_enabled`` stays
        # as a compatibility mirror for legacy render/timeline code.
        if production_mode == "one_click":
            presentation_mode = "full_frame"
        mask_enabled = 1 if presentation_mode == "reveal" else 0
        configured_subtitle_style: dict[str, Any] | None = None
        course_id = str(payload.course_id or "").strip() or None
        chapter_id = str(payload.chapter_id or "").strip() or None
        if chapter_id:
            chapter = (
                db.query(Chapter)
                .join(Course, Course.id == Chapter.course_id)
                .filter(
                    Chapter.id == chapter_id,
                    Course.account_id == account_id,
                )
                .first()
            )
            if chapter is None:
                raise HTTPException(status_code=404, detail="章节不存在或不属于当前创作账号")
            if course_id and course_id != chapter.course_id:
                raise HTTPException(status_code=400, detail="章节不属于指定课程")
            course_id = chapter.course_id
        elif course_id:
            course = (
                db.query(Course)
                .filter(Course.id == course_id, Course.account_id == account_id)
                .first()
            )
            if course is None:
                raise HTTPException(status_code=404, detail="课程不存在或不属于当前创作账号")
        creation_config: dict[str, Any] | None = None
        supplied_package_ids = [
            value.strip()
            for value in (
                payload.creation_config_package_id,
                payload.config_package_id,
            )
            if isinstance(value, str) and value.strip()
        ]
        if len(set(supplied_package_ids)) > 1:
            raise HTTPException(status_code=400, detail="创作配置包 ID 不能同时指定不同值")
        config_package_id = supplied_package_ids[0] if supplied_package_ids else None
        config_version = (
            payload.creation_config_version
            if payload.creation_config_version is not None
            else payload.config_package_version
        )
        if (
            payload.creation_config_version is not None
            and payload.config_package_version is not None
            and payload.creation_config_version != payload.config_package_version
        ):
            raise HTTPException(status_code=400, detail="创作配置版本不能同时指定不同值")
        config_overrides = (
            payload.creation_config_overrides
            if payload.creation_config_overrides is not None
            else payload.config_overrides
        )
        if (
            payload.creation_config_overrides is not None
            and payload.config_overrides is not None
            and payload.creation_config_overrides != payload.config_overrides
        ):
            raise HTTPException(status_code=400, detail="创作配置覆盖项不能同时指定不同值")
        if config_overrides is not None and not isinstance(config_overrides, dict):
            raise HTTPException(status_code=400, detail="creation_config_overrides 必须是对象")
        if config_package_id:
            if self.dependencies.resolve_creation_config is None:
                raise HTTPException(status_code=503, detail="创作配置服务尚未配置")
            overrides = config_overrides or {}
            try:
                creation_config = self.dependencies.resolve_creation_config(
                    config_package_id,
                    config_version,
                    overrides,
                )
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"创作配置不可用: {exc}") from exc
        elif self.dependencies.get_default_creation_config is not None:
            default_config = self.dependencies.get_default_creation_config(account_id, db)
            if default_config:
                config_package_id = str(default_config.get("package_id") or "").strip() or None
                # Explicit creation parameters must behave identically whether
                # the package was selected directly or supplied by the account
                # default.  In particular, callers may override a default
                # package's version and/or only selected fields.
                if config_version is None:
                    config_version = default_config.get("version")
                if config_package_id and self.dependencies.resolve_creation_config is not None:
                    try:
                        creation_config = self.dependencies.resolve_creation_config(
                            config_package_id, config_version, config_overrides or {}
                        )
                    except Exception as exc:
                        raise HTTPException(status_code=400, detail=f"账号默认创作配置不可用: {exc}") from exc
        elif config_version is not None or config_overrides:
            raise HTTPException(
                status_code=400,
                detail="指定创作配置版本或覆盖项时必须选择 creation_config_package_id",
            )
        # A creation package is the single owner of pipeline switches.  Once
        # resolved, its immutable snapshot decides Mask and automatic pause
        # behavior; project creation must not silently replace those choices.
        if creation_config is not None:
            config_payload = creation_config.get("payload")
            if isinstance(config_payload, dict):
                automation = config_payload.get("automation")
                configured_pause = (
                    automation.get("manual_pause_steps")
                    if isinstance(automation, dict)
                    else None
                )
                if isinstance(configured_pause, list):
                    if "manual_pause_steps" not in payload.model_fields_set:
                        manual_pause = [
                            step for step in configured_pause if step in _valid_pause
                        ]
                configured_mode = automation.get("mode") if isinstance(automation, dict) else None
                if (
                    "ai_mode" not in payload.model_fields_set
                    and configured_mode in {"auto", "manual"}
                ):
                    ai_mode = configured_mode
                # ``mask`` is intentionally preserved in the immutable
                # configuration snapshot for package import/export
                # compatibility.  It no longer chooses the presentation mode
                # of a new project: the user selects that in the workspace.
                subtitle = config_payload.get("subtitle")
                if (
                    isinstance(subtitle, dict)
                    and isinstance(subtitle.get("enabled"), bool)
                ):
                    configured_subtitle_style = normalize_subtitle_style(
                        subtitle
                    )
        project = Project(
            id=project_id,
            name=payload.name,
            description=payload.description,
            current_step=1,
            status="active",
            run_dir=str(run_dir),
            account_id=account_id,
            course_id=course_id,
            chapter_id=chapter_id,
            ai_mode=ai_mode,
            canvas_profile=canvas_profile,
            review_policy=review_policy,
            manual_pause_steps=json.dumps(manual_pause),
            image_style_template=image_style_template,
            mask_enabled=mask_enabled,
            production_mode=production_mode,
            presentation_mode=presentation_mode,
            creation_config_package_id=(
                creation_config.get("package_id") if creation_config else None
            ),
            creation_config_version=(
                creation_config.get("version") if creation_config else None
            ),
            creation_config_hash=(
                creation_config.get("content_hash") if creation_config else None
            ),
        )
        project.set_step_status(initial_step_status)
        db.add(project)
        try:
            write_project_canvas_snapshot(project)
            if configured_subtitle_style is not None:
                visual_settings_path = run_dir / PROJECT_VISUAL_SETTINGS_FILE
                visual_settings_payload = {
                    "subtitle_style": configured_subtitle_style,
                }
                if self.dependencies.write_json_atomic is None:
                    visual_settings_path.write_text(
                        json.dumps(
                            visual_settings_payload,
                            ensure_ascii=False,
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                else:
                    self.dependencies.write_json_atomic(
                        visual_settings_path,
                        visual_settings_payload,
                    )
            if creation_config is not None:
                snapshot_path = run_dir / "planning" / "project_config.json"
                if self.dependencies.write_json_atomic is None:
                    snapshot_path.write_text(
                        json.dumps(
                            creation_config,
                            ensure_ascii=False,
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                else:
                    self.dependencies.write_json_atomic(snapshot_path, creation_config)
                config_payload = creation_config.get("payload")
                image_style = (
                    config_payload.get("image_style")
                    if isinstance(config_payload, dict)
                    else None
                )
                if (
                    isinstance(image_style, dict)
                    and self.dependencies.materialize_image_style is not None
                ):
                    self.dependencies.materialize_image_style(project, image_style)
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
                "manual_pause_steps": json.loads(project.manual_pause_steps or "[]"),
                "image_style_template": project.image_style_template or "default",
                "mask_enabled": bool(project.mask_enabled if project.mask_enabled is not None else 1),
                "production_mode": project.production_mode or "guided",
                "presentation_mode": project.presentation_mode or "full_frame",
                "creation_config": self._creation_config_summary(project),
                "course_id": project.course_id,
                "chapter_id": project.chapter_id,
            },
        }

    def list(self, db: Session, account_id: str | None = None) -> list[dict[str, Any]]:
        account_id = account_id or get_current_account_id()
        projects = (
            db.query(Project)
            .filter(Project.account_id == account_id)
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
                "manual_pause_steps": json.loads(project.manual_pause_steps or "[]"),
                "image_style_template": project.image_style_template or "default",
                "mask_enabled": bool(project.mask_enabled if project.mask_enabled is not None else 1),
                "production_mode": project.production_mode or "guided",
                "presentation_mode": project.presentation_mode or "full_frame",
                "creation_config": self._creation_config_summary(project),
                "course_id": project.course_id,
                "chapter_id": project.chapter_id,
            }
            for project in projects
        ]

    def get(self, project_id: str, db: Session, account_id: str | None = None) -> dict[str, Any]:
        project = self._project(project_id, db, account_id or get_current_account_id())
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
            "manual_pause_steps": json.loads(project.manual_pause_steps or "[]"),
            "image_style_template": project.image_style_template or "default",
            "mask_enabled": bool(project.mask_enabled if project.mask_enabled is not None else 1),
            "production_mode": project.production_mode or "guided",
            "presentation_mode": project.presentation_mode or "full_frame",
            "creation_config": self._creation_config_summary(project),
            "course_id": project.course_id,
            "chapter_id": project.chapter_id,
        }

    @staticmethod
    def _creation_config_summary(project: Project) -> dict[str, Any] | None:
        package_id = getattr(project, "creation_config_package_id", None)
        if not package_id:
            return None
        return {
            "package_id": package_id,
            "version": getattr(project, "creation_config_version", None),
            "content_hash": getattr(project, "creation_config_hash", None),
        }

    def get_ai_mode(
        self,
        project_id: str,
        db: Session,
    ) -> dict[str, str]:
        project = self._project(project_id, db, get_current_account_id())
        return {"ai_mode": project.ai_mode or "auto"}

    def update_ai_mode(
        self,
        project_id: str,
        payload: AiModeUpdate,
        db: Session,
    ) -> dict[str, Any]:
        project = self._project(project_id, db, get_current_account_id())
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
        project = self._project(project_id, db, get_current_account_id())
        if payload.name is not None:
            project.name = payload.name.strip()
        if payload.description is not None:
            project.description = payload.description
        if payload.ai_mode is not None:
            ai_mode = (payload.ai_mode or "").strip().lower()
            if ai_mode not in {"auto", "manual"}:
                ai_mode = "auto"
            project.ai_mode = ai_mode
        if payload.production_mode is not None:
            production_mode = (payload.production_mode or "").strip().lower()
            if production_mode not in {"one_click", "guided"}:
                raise HTTPException(status_code=400, detail="production_mode 必须为 one_click 或 guided")
            project.production_mode = production_mode
            if production_mode == "one_click":
                project.presentation_mode = "full_frame"
                project.mask_enabled = 0
        if payload.presentation_mode is not None:
            presentation_mode = (payload.presentation_mode or "").strip().lower()
            if presentation_mode not in {"full_frame", "reveal"}:
                raise HTTPException(status_code=400, detail="presentation_mode 必须为 full_frame 或 reveal")
            if (project.production_mode or "guided") == "one_click" and presentation_mode == "reveal":
                raise HTTPException(status_code=400, detail="一键生成仅支持整页展示；请切换到分步制作后启用元素动画")
            project.presentation_mode = presentation_mode
            project.mask_enabled = 1 if presentation_mode == "reveal" else 0
        db.commit()
        db.refresh(project)
        return {
            "success": True,
            "project": {
                "id": project.id,
                "name": project.name,
                "description": project.description,
                "ai_mode": project.ai_mode or "auto",
                "production_mode": project.production_mode or "guided",
                "presentation_mode": project.presentation_mode or "full_frame",
            },
        }

    def delete(
        self,
        project_id: str,
        db: Session,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        project = self._project(project_id, db, account_id or get_current_account_id())
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
    def _project(project_id: str, db: Session, account_id: str = "default") -> Project:
        project = (
            db.query(Project)
            .filter(Project.id == project_id, Project.account_id == account_id)
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
