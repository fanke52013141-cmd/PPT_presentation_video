"""Per-project video background and subtitle style settings."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable

from fastapi import HTTPException
from sqlalchemy.orm import Session

from database import Project


@dataclass(frozen=True)
class VisualSettingsDependencies:
    read_settings: Callable[[Project], dict[str, Any]]
    write_settings: Callable[..., dict[str, Any]]
    sync_background: Callable[[Project], Any]
    invalidate_background: Callable[[Project, Session], None]
    invalidate_subtitles: Callable[[Project, Session], None]
    preview_background_url: Callable[[Project], str]
    fonts: list[dict[str, Any]]


class VisualSettingsService:
    def __init__(self, dependencies: VisualSettingsDependencies) -> None:
        self.dependencies = dependencies

    def get(
        self,
        project_id: str,
        db: Session,
    ) -> dict[str, Any]:
        project = self._project(project_id, db)
        return {
            "success": True,
            **self.dependencies.read_settings(project),
        }

    def update_background(
        self,
        project_id: str,
        payload: dict[str, Any],
        db: Session,
    ) -> dict[str, Any]:
        project = self._project(project_id, db)
        raw_color = str(
            payload.get("video_background") or ""
        ).strip().upper()
        if not re.fullmatch(r"#[0-9A-F]{6}", raw_color):
            raise HTTPException(
                status_code=400,
                detail="视频背景色必须是 #RRGGBB 格式",
            )
        previous = self.dependencies.read_settings(project)
        settings = self.dependencies.write_settings(
            project,
            raw_color,
        )
        self.dependencies.sync_background(project)
        if (
            previous["video_background"]
            != settings["video_background"]
        ):
            self.dependencies.invalidate_background(project, db)
        return {"success": True, **settings}

    def get_subtitles(
        self,
        project_id: str,
        db: Session,
    ) -> dict[str, Any]:
        project = self._project(project_id, db)
        settings = self.dependencies.read_settings(project)
        return {
            "success": True,
            "subtitle_style": settings["subtitle_style"],
            "fonts": self.dependencies.fonts,
            "preview_url": (
                self.dependencies.preview_background_url(project)
            ),
        }

    def update_subtitles(
        self,
        project_id: str,
        payload: dict[str, Any],
        db: Session,
    ) -> dict[str, Any]:
        project = self._project(project_id, db)
        previous = self.dependencies.read_settings(project)
        subtitle_style = (
            payload.get("subtitle_style")
            if isinstance(payload, dict)
            else None
        )
        settings = self.dependencies.write_settings(
            project,
            subtitle_style=subtitle_style,
        )
        if previous["subtitle_style"] != settings["subtitle_style"]:
            self.dependencies.invalidate_subtitles(project, db)
        return {
            "success": True,
            "subtitle_style": settings["subtitle_style"],
            "fonts": self.dependencies.fonts,
            "preview_url": (
                self.dependencies.preview_background_url(project)
            ),
        }

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


_SERVICE: VisualSettingsService | None = None


def configure_visual_settings_service(
    dependencies: VisualSettingsDependencies,
) -> VisualSettingsService:
    global _SERVICE
    _SERVICE = VisualSettingsService(dependencies)
    return _SERVICE


def get_visual_settings_service() -> VisualSettingsService:
    if _SERVICE is None:
        raise RuntimeError(
            "Visual settings service has not been configured"
        )
    return _SERVICE
