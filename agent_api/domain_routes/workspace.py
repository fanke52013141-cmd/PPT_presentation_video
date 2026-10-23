"""Agent workspace adapters: courses, creation configs, one-click controls and
storyboard background settings."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from agent_contract.domains.freeform import FreeFormRequest
from agent_contract.domains.project import StoryboardChangePreviewRequest
from database import Project, SessionLocal, get_db
from account_context import get_current_account_id
from course_service import (
    get_course_service,
)
from creation_config_models import (
    CreationConfigArchive,
    CreationConfigCopy,
    CreationConfigCreate,
    CreationConfigImport,
    CreationConfigResolve,
    CreationConfigUpdate,
    CreationConfigVersionCreate,
)

import creation_config_routes
import storyboard_background

router = APIRouter()


def _course_models():
    from course_service import (
        ChapterCreate,
        ChapterMove,
        ChapterUpdate,
        CourseCreate,
        CourseUpdate,
        ProjectMove,
        ProjectReorder,
        ReorderRequest,
    )
    return {
        "ChapterCreate": ChapterCreate,
        "ChapterMove": ChapterMove,
        "ChapterUpdate": ChapterUpdate,
        "CourseCreate": CourseCreate,
        "CourseUpdate": CourseUpdate,
        "ProjectMove": ProjectMove,
        "ProjectReorder": ProjectReorder,
        "ReorderRequest": ReorderRequest,
    }


# ---- 课程库 ----

@router.get("/courses/tree")
def agent_get_course_tree(db: Session = Depends(get_db)) -> dict[str, Any]:
    return get_course_service().get_tree(db)


@router.patch("/courses/reorder")
def agent_reorder_courses(payload: FreeFormRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    body = _course_models()["ReorderRequest"].model_validate(payload.payload)
    return get_course_service().reorder_courses(body, db)


@router.patch("/chapters/reorder")
def agent_reorder_chapters(payload: FreeFormRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    data = dict(payload.payload)
    course_id = str(data.pop("course_id", "") or "")
    body = _course_models()["ReorderRequest"].model_validate(data)
    return get_course_service().reorder_chapters(course_id, body, db)


@router.post("/courses")
def agent_create_course(payload: FreeFormRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    body = _course_models()["CourseCreate"].model_validate(payload.payload)
    return get_course_service().create_course(body, db)


@router.get("/courses")
def agent_list_courses(db: Session = Depends(get_db)) -> dict[str, Any]:
    return get_course_service().list_courses(db)


@router.get("/courses/{course_id}")
def agent_get_course(course_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return get_course_service().get_course(course_id, db)


@router.patch("/courses/{course_id}")
def agent_update_course(
    course_id: str,
    payload: FreeFormRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    body = _course_models()["CourseUpdate"].model_validate(payload.payload)
    return get_course_service().update_course(course_id, body, db)


@router.delete("/courses/{course_id}")
def agent_delete_course(course_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return get_course_service().delete_course(course_id, db)


@router.post("/courses/{course_id}/chapters")
def agent_create_chapter(
    course_id: str,
    payload: FreeFormRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    body = _course_models()["ChapterCreate"].model_validate(payload.payload)
    return get_course_service().create_chapter(course_id, body, db)


@router.patch("/chapters/{chapter_id}")
def agent_update_chapter(
    chapter_id: str,
    payload: FreeFormRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    body = _course_models()["ChapterUpdate"].model_validate(payload.payload)
    return get_course_service().update_chapter(chapter_id, body, db)


@router.delete("/chapters/{chapter_id}")
def agent_delete_chapter(chapter_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return get_course_service().delete_chapter(chapter_id, db)


@router.post("/chapters/{chapter_id}/move")
def agent_move_chapter(
    chapter_id: str,
    payload: FreeFormRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    body = _course_models()["ChapterMove"].model_validate(payload.payload)
    return get_course_service().move_chapter(chapter_id, body, db)


@router.post("/projects/{project_id}/move")
def agent_move_project(
    project_id: str,
    payload: FreeFormRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    body = _course_models()["ProjectMove"].model_validate(payload.payload)
    return get_course_service().move_project(project_id, body, db)


@router.patch("/projects/reorder")
def agent_reorder_projects(payload: FreeFormRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    body = _course_models()["ProjectReorder"].model_validate(payload.payload)
    return get_course_service().reorder_projects(body, db)


# ---- 创作配置包 ----

@router.get("/creation-configs")
def agent_list_configs(include_archived: bool = False) -> dict[str, Any]:
    import creation_config_service

    return {
        "success": True,
        "packages": creation_config_service.list_creation_configs(
            include_archived=include_archived
        ),
    }


@router.get("/creation-configs/default-payload")
def agent_default_config_payload() -> dict[str, Any]:
    return creation_config_routes.get_default_creation_config_payload()


@router.post("/creation-configs")
def agent_create_config(payload: FreeFormRequest) -> dict[str, Any]:
    return creation_config_routes.create_creation_config(
        CreationConfigCreate.model_validate(payload.payload)
    )


@router.post("/creation-configs/import")
def agent_import_config(payload: FreeFormRequest) -> dict[str, Any]:
    return creation_config_routes.import_creation_config(
        CreationConfigImport.model_validate(payload.payload)
    )


@router.get("/creation-configs/{package_id}")
def agent_get_config(package_id: str) -> dict[str, Any]:
    return creation_config_routes.get_creation_config(package_id)


@router.put("/creation-configs/{package_id}")
def agent_update_config(package_id: str, payload: FreeFormRequest) -> dict[str, Any]:
    return creation_config_routes.update_creation_config(
        package_id, CreationConfigUpdate.model_validate(payload.payload)
    )


@router.get("/creation-configs/{package_id}/versions/{version}")
def agent_get_config_version(package_id: str, version: str) -> dict[str, Any]:
    return creation_config_routes.get_creation_config_version(package_id, version)


@router.post("/creation-configs/{package_id}/copy")
def agent_copy_config(package_id: str, payload: FreeFormRequest) -> dict[str, Any]:
    return creation_config_routes.copy_creation_config(
        package_id, CreationConfigCopy.model_validate(payload.payload)
    )


@router.post("/creation-configs/{package_id}/versions")
def agent_create_config_version(package_id: str, payload: FreeFormRequest) -> dict[str, Any]:
    return creation_config_routes.create_creation_config_version(
        package_id, CreationConfigVersionCreate.model_validate(payload.payload)
    )


@router.put("/creation-configs/{package_id}/archive")
def agent_archive_config(package_id: str, payload: FreeFormRequest) -> dict[str, Any]:
    return creation_config_routes.archive_creation_config(
        package_id, CreationConfigArchive.model_validate(payload.payload)
    )


@router.delete("/creation-configs/{package_id}")
def agent_delete_config(package_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return creation_config_routes.delete_creation_config(package_id, db=db)


@router.post("/creation-configs/{package_id}/resolve")
def agent_resolve_config(package_id: str, payload: FreeFormRequest) -> dict[str, Any]:
    return creation_config_routes.resolve_creation_config(
        package_id, CreationConfigResolve.model_validate(payload.payload)
    )


# ---- 一键控制 ----

@router.post("/projects/{project_id}/runs/latest/pause")
def agent_pause_pipeline(project_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    from one_click_routes import _project_or_404, pause_one_click

    return pause_one_click(_project_or_404(db, project_id))


@router.get("/one-click-statuses")
def agent_pipeline_statuses() -> dict[str, Any]:
    from one_click_routes import batch_one_click_status

    return batch_one_click_status(Project, SessionLocal, get_current_account_id())


# ---- 分镜背景 ----

@router.get("/projects/{project_id}/storyboard-background")
def agent_get_background(project_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return storyboard_background.get_background(project_id, db)


@router.put("/projects/{project_id}/storyboard-background")
def agent_update_background(
    project_id: str,
    payload: FreeFormRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return storyboard_background.put_background(project_id, payload.payload, db)


@router.post("/projects/{project_id}/storyboard-background/image")
async def agent_upload_background_image(
    project_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return await storyboard_background.upload_background(project_id, file=file, db=db)


@router.get("/projects/{project_id}/storyboard-background/image")
def agent_get_background_image(
    project_id: str, db: Session = Depends(get_db)
) -> FileResponse:
    return storyboard_background.get_background_image(project_id, db)


# ---- P4 变更预检 ----

@router.post("/projects/{project_id}/change-preview")
def agent_change_preview(
    project_id: str,
    payload: StoryboardChangePreviewRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from agent_api.domain_routes.common import _resolve_project
    from agent_workflow_service import preview_storyboard_change

    project = _resolve_project(db, project_id)
    return preview_storyboard_change(project, proposed_contract=payload.contract)
