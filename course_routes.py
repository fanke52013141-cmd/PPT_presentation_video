"""Course / Chapter / Project-move REST routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from course_service import (
    ChapterCreate,
    ChapterUpdate,
    CourseCreate,
    CourseUpdate,
    ProjectMove,
    ReorderRequest,
    get_course_service,
)
from database import get_db


router = APIRouter()


# ===== 重要：固定路径必须在参数路径之前声明 =====

@router.get("/api/courses/tree")
def get_tree(db: Session = Depends(get_db)) -> dict[str, Any]:
    """一次性返回整棵树：courses（含 chapters 和 projects）+ 独立项目。"""
    return get_course_service().get_tree(db)


@router.patch("/api/courses/reorder")
def reorder_courses(
    payload: ReorderRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return get_course_service().reorder_courses(payload, db)


@router.patch("/api/chapters/reorder")
def reorder_chapters(
    course_id: str,
    payload: ReorderRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return get_course_service().reorder_chapters(course_id, payload, db)


# ===== Course CRUD =====

@router.post("/api/courses")
def create_course(
    payload: CourseCreate,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """新建课程。name 为空时使用默认名，支持前端自动聚焦重命名。"""
    return get_course_service().create_course(payload, db)


@router.get("/api/courses")
def list_courses(
    include_children: bool = False,
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """列出所有课程。带 include_children=true 时包含章节和项目。"""
    return get_course_service().list_courses(db, include_children=include_children)


@router.get("/api/courses/{course_id}")
def get_course(
    course_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """获取课程详情（含所有章节和项目）。"""
    return get_course_service().get_course(course_id, db)


@router.patch("/api/courses/{course_id}")
def update_course(
    course_id: str,
    payload: CourseUpdate,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return get_course_service().update_course(course_id, payload, db)


@router.delete("/api/courses/{course_id}")
def delete_course(
    course_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """删除课程。课程下的项目会解绑为独立项目，章节会被删除。"""
    return get_course_service().delete_course(course_id, db)


# ===== Chapter CRUD =====

@router.post("/api/courses/{course_id}/chapters")
def create_chapter(
    course_id: str,
    payload: ChapterCreate,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """在指定课程下新建章节。name 为空时使用默认名。"""
    return get_course_service().create_chapter(course_id, payload, db)


@router.patch("/api/chapters/{chapter_id}")
def update_chapter(
    chapter_id: str,
    payload: ChapterUpdate,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return get_course_service().update_chapter(chapter_id, payload, db)


@router.delete("/api/chapters/{chapter_id}")
def delete_chapter(
    chapter_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """删除章节。章节下的项目会归到课程的"未归类"分组。"""
    return get_course_service().delete_chapter(chapter_id, db)


# ===== Project move =====

@router.post("/api/projects/{project_id}/move")
def move_project(
    project_id: str,
    payload: ProjectMove,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """移动项目到指定课程/章节。course_id 和 chapter_id 都为 null 时变成独立项目。"""
    return get_course_service().move_project(project_id, payload, db)
