"""Course & Chapter CRUD service for the tree-style course → chapter → project hierarchy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import uuid
from typing import Any, Optional

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import Chapter, Course, Project


logger = logging.getLogger("PPTStudio.Courses")

# 主题色池：快速新建时随机分配，视觉上区分不同课程
DEFAULT_COVER_COLORS = [
    "#5B7893", "#3D5A80", "#1B998B", "#4C956C",
    "#F6AE2D", "#E84A5F", "#7B2CBF", "#2F80ED",
]

DEFAULT_COURSE_NAME = "新建课程"
DEFAULT_CHAPTER_NAME = "新建章节"


class CourseCreate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = ""
    cover_color: Optional[str] = None
    cover_image_path: Optional[str] = None


class CourseUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    cover_color: Optional[str] = None
    cover_image_path: Optional[str] = None


class ChapterCreate(BaseModel):
    name: Optional[str] = None


class ChapterUpdate(BaseModel):
    name: Optional[str] = None


class ProjectMove(BaseModel):
    course_id: Optional[str] = None
    chapter_id: Optional[str] = None


class ReorderRequest(BaseModel):
    ordered_ids: list[str]


class ProjectReorder(BaseModel):
    """拖拽排序 + 跨层级移动视频的统一请求体。

    ordered_ids 里所有视频会被按顺序写入 sort_order，并同时归属到：
    - chapter_id 有值：该章节（course_id 自动同步为章节所属课程）
    - chapter_id 为 None、course_id 有值：该课程的"未归类"区
    - 两者都为 None：变成独立项目
    """
    ordered_ids: list[str]
    course_id: Optional[str] = None
    chapter_id: Optional[str] = None


class ChapterMove(BaseModel):
    """把章节移动到目标课程的请求体。目标课程下若已有同名章节会自动改名。"""
    course_id: str


@dataclass(frozen=True)
class CourseDependencies:
    pass


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _gen_id(prefix: str) -> str:
    """生成形如 course_a1b2c3d4 的 ID（与项目 ID 风格一致）。"""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _course_to_dict(course: Course, db: Session, include_children: bool = False) -> dict[str, Any]:
    result = {
        "id": course.id,
        "name": course.name,
        "description": course.description or "",
        "cover_color": course.cover_color,
        "cover_image_path": course.cover_image_path,
        "sort_order": course.sort_order,
        "created_at": course.created_at.isoformat() if course.created_at else None,
        "updated_at": course.updated_at.isoformat() if course.updated_at else None,
    }
    if include_children:
        chapters = (
            db.query(Chapter)
            .filter(Chapter.course_id == course.id)
            .order_by(Chapter.sort_order, Chapter.created_at)
            .all()
        )
        chapter_list = []
        for ch in chapters:
            chapter_list.append(_chapter_to_dict(ch, db, include_projects=True))
        # 课程下未归入章节的项目
        unchaptered_projects = (
            db.query(Project)
            .filter(Project.course_id == course.id, Project.chapter_id.is_(None))
            .order_by(Project.sort_order, Project.created_at.desc())
            .all()
        )
        result["chapters"] = chapter_list
        result["unchaptered_projects"] = [_project_brief(p) for p in unchaptered_projects]
        result["chapter_count"] = len(chapter_list)
        result["project_count"] = (
            sum(len(ch_dict.get("projects", [])) for ch_dict in chapter_list)
            + len(unchaptered_projects)
        )
    return result


def _chapter_to_dict(chapter: Chapter, db: Session, include_projects: bool = False) -> dict[str, Any]:
    result = {
        "id": chapter.id,
        "course_id": chapter.course_id,
        "name": chapter.name,
        "sort_order": chapter.sort_order,
        "created_at": chapter.created_at.isoformat() if chapter.created_at else None,
        "updated_at": chapter.updated_at.isoformat() if chapter.updated_at else None,
    }
    if include_projects:
        projects = (
            db.query(Project)
            .filter(Project.chapter_id == chapter.id)
            .order_by(Project.sort_order, Project.created_at.desc())
            .all()
        )
        result["projects"] = [_project_brief(p) for p in projects]
    return result


def _project_brief(project: Project) -> dict[str, Any]:
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description or "",
        "current_step": project.current_step,
        "status": project.status,
        "ai_mode": project.ai_mode,
        "sort_order": project.sort_order,
        "course_id": project.course_id,
        "chapter_id": project.chapter_id,
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None,
    }


class CourseService:
    def __init__(self, dependencies: CourseDependencies) -> None:
        self.dependencies = dependencies

    # ===== Course CRUD =====

    def create_course(self, payload: CourseCreate, db: Session) -> dict[str, Any]:
        import random
        course_id = _gen_id("course")
        course = Course(
            id=course_id,
            name=(payload.name or "").strip() or DEFAULT_COURSE_NAME,
            description=(payload.description or "").strip() or None,
            cover_color=payload.cover_color or random.choice(DEFAULT_COVER_COLORS),
            cover_image_path=payload.cover_image_path,
            sort_order=self._next_course_sort_order(db),
            created_at=_utc_now_naive(),
            updated_at=_utc_now_naive(),
        )
        db.add(course)
        db.commit()
        db.refresh(course)
        return _course_to_dict(course, db)

    def list_courses(self, db: Session, include_children: bool = False) -> list[dict[str, Any]]:
        courses = (
            db.query(Course)
            .order_by(Course.sort_order, Course.created_at.desc())
            .all()
        )
        return [_course_to_dict(c, db, include_children=include_children) for c in courses]

    def get_course(self, course_id: str, db: Session) -> dict[str, Any]:
        course = self._require_course(course_id, db)
        return _course_to_dict(course, db, include_children=True)

    def update_course(self, course_id: str, payload: CourseUpdate, db: Session) -> dict[str, Any]:
        course = self._require_course(course_id, db)
        if payload.name is not None:
            course.name = payload.name.strip() or course.name
        if payload.description is not None:
            course.description = payload.description.strip() or None
        if payload.cover_color is not None:
            course.cover_color = payload.cover_color
        if payload.cover_image_path is not None:
            course.cover_image_path = payload.cover_image_path
        course.updated_at = _utc_now_naive()
        db.commit()
        db.refresh(course)
        return _course_to_dict(course, db)

    def delete_course(self, course_id: str, db: Session) -> dict[str, Any]:
        course = self._require_course(course_id, db)
        # 删除课程下所有章节
        chapters = db.query(Chapter).filter(Chapter.course_id == course_id).all()
        chapter_ids = [ch.id for ch in chapters]
        # 把课程下所有项目解绑（变成独立项目）
        projects = db.query(Project).filter(Project.course_id == course_id).all()
        for p in projects:
            p.course_id = None
            p.chapter_id = None
        # 删除章节
        for ch in chapters:
            db.delete(ch)
        db.delete(course)
        db.commit()
        return {
            "success": True,
            "deleted_chapter_ids": chapter_ids,
            "unbound_project_ids": [p.id for p in projects],
        }

    def reorder_courses(self, payload: ReorderRequest, db: Session) -> dict[str, Any]:
        for index, cid in enumerate(payload.ordered_ids):
            course = db.query(Course).filter(Course.id == cid).first()
            if course:
                course.sort_order = index
        db.commit()
        return {"success": True, "ordered_ids": payload.ordered_ids}

    # ===== Chapter CRUD =====

    def create_chapter(self, course_id: str, payload: ChapterCreate, db: Session) -> dict[str, Any]:
        self._require_course(course_id, db)
        chapter = Chapter(
            id=_gen_id("chapter"),
            course_id=course_id,
            name=(payload.name or "").strip() or DEFAULT_CHAPTER_NAME,
            sort_order=self._next_chapter_sort_order(course_id, db),
            created_at=_utc_now_naive(),
            updated_at=_utc_now_naive(),
        )
        db.add(chapter)
        db.commit()
        db.refresh(chapter)
        return _chapter_to_dict(chapter, db)

    def update_chapter(self, chapter_id: str, payload: ChapterUpdate, db: Session) -> dict[str, Any]:
        chapter = self._require_chapter(chapter_id, db)
        if payload.name is not None:
            chapter.name = payload.name.strip() or chapter.name
        chapter.updated_at = _utc_now_naive()
        db.commit()
        db.refresh(chapter)
        return _chapter_to_dict(chapter, db)

    def delete_chapter(self, chapter_id: str, db: Session) -> dict[str, Any]:
        chapter = self._require_chapter(chapter_id, db)
        # 把章节下所有项目解绑（保留 course_id 归到课程的"未归类"分组）
        projects = db.query(Project).filter(Project.chapter_id == chapter_id).all()
        for p in projects:
            p.chapter_id = None
        db.delete(chapter)
        db.commit()
        return {"success": True, "unbound_project_ids": [p.id for p in projects]}

    def reorder_chapters(self, course_id: str, payload: ReorderRequest, db: Session) -> dict[str, Any]:
        for index, cid in enumerate(payload.ordered_ids):
            chapter = db.query(Chapter).filter(Chapter.id == cid, Chapter.course_id == course_id).first()
            if chapter:
                chapter.sort_order = index
        db.commit()
        return {"success": True, "ordered_ids": payload.ordered_ids}

    def move_chapter(self, chapter_id: str, payload: ChapterMove, db: Session) -> dict[str, Any]:
        """把章节移动到目标课程下，章节下的所有项目随之迁移。

        若目标课程下已存在同名章节，自动给被移动的章节追加序号后缀（如「(1)」「(2)」）。
        同课程内移动视为无操作（直接返回）。
        """
        chapter = self._require_chapter(chapter_id, db)
        target_course_id = (payload.course_id or "").strip()
        if not target_course_id:
            raise HTTPException(status_code=400, detail="目标课程 ID 不能为空")
        original_name = chapter.name
        if target_course_id == chapter.course_id:
            result = _chapter_to_dict(chapter, db, include_projects=True)
            result["moved_project_ids"] = []
            result["renamed"] = False
            result["original_name"] = original_name
            return result
        self._require_course(target_course_id, db)
        # 同名检测 + 自动改名（追加 (1)/(2) 后缀直到不重名）
        renamed = False
        clash = (
            db.query(Chapter)
            .filter(Chapter.course_id == target_course_id, Chapter.name == chapter.name)
            .first()
        )
        if clash is not None:
            base_name = chapter.name
            suffix = 1
            while True:
                candidate = f"{base_name}({suffix})"
                exists = (
                    db.query(Chapter)
                    .filter(Chapter.course_id == target_course_id, Chapter.name == candidate)
                    .first()
                )
                if exists is None:
                    break
                suffix += 1
            chapter.name = candidate
            renamed = True
        chapter.course_id = target_course_id
        chapter.sort_order = self._next_chapter_sort_order(target_course_id, db)
        chapter.updated_at = _utc_now_naive()
        # 章节下所有项目的 course_id 同步为新课程（chapter_id 保持不变）
        moved_projects = db.query(Project).filter(Project.chapter_id == chapter_id).all()
        moved_project_ids = []
        for p in moved_projects:
            p.course_id = target_course_id
            p.updated_at = _utc_now_naive()
            moved_project_ids.append(p.id)
        db.commit()
        db.refresh(chapter)
        result = _chapter_to_dict(chapter, db, include_projects=True)
        result["moved_project_ids"] = moved_project_ids
        result["renamed"] = renamed
        result["original_name"] = original_name
        return result

    # ===== Project move =====

    def move_project(self, project_id: str, payload: ProjectMove, db: Session) -> dict[str, Any]:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail=f"项目不存在: {project_id}")
        # 校验 course_id 有效
        if payload.course_id is not None:
            self._require_course(payload.course_id, db)
        # 校验 chapter_id 有效且属于该 course
        if payload.chapter_id is not None:
            chapter = self._require_chapter(payload.chapter_id, db)
            if payload.course_id is not None and chapter.course_id != payload.course_id:
                raise HTTPException(status_code=400, detail="章节不属于指定的课程")
            project.course_id = chapter.course_id
        else:
            project.course_id = payload.course_id
        project.chapter_id = payload.chapter_id
        project.updated_at = _utc_now_naive()
        db.commit()
        db.refresh(project)
        return _project_brief(project)

    def reorder_projects(self, payload: ProjectReorder, db: Session) -> dict[str, Any]:
        """按顺序设置项目的 sort_order，并可同时把它们重新归属到指定课程/章节。

        这是拖拽排序 + 跨层级移动视频的统一入口：
        - chapter_id 有值：所有项目挂到该章节，course_id 自动同步为章节所属课程
        - chapter_id 为 None、course_id 有值：所有项目挂到该课程的"未归类"区
        - 两者都为 None：所有项目变成独立项目
        """
        if not payload.ordered_ids:
            return {"success": True, "ordered_ids": [], "course_id": None, "chapter_id": None, "projects": []}
        # 若指定了 chapter_id，以章节所属课程为准（并校验章节存在）
        target_chapter_id = payload.chapter_id
        target_course_id = payload.course_id
        if target_chapter_id is not None:
            chapter = self._require_chapter(target_chapter_id, db)
            target_course_id = chapter.course_id
        elif target_course_id is not None:
            self._require_course(target_course_id, db)
        # 逐个更新归属 + 排序
        updated = []
        for index, pid in enumerate(payload.ordered_ids):
            project = db.query(Project).filter(Project.id == pid).first()
            if not project:
                raise HTTPException(status_code=404, detail=f"项目不存在: {pid}")
            project.course_id = target_course_id
            project.chapter_id = target_chapter_id
            project.sort_order = index
            project.updated_at = _utc_now_naive()
            updated.append(project)
        db.commit()
        for p in updated:
            db.refresh(p)
        return {
            "success": True,
            "ordered_ids": payload.ordered_ids,
            "course_id": target_course_id,
            "chapter_id": target_chapter_id,
            "projects": [_project_brief(p) for p in updated],
        }

    # ===== Tree =====

    def get_tree(self, db: Session) -> dict[str, Any]:
        """一次性返回整棵树：courses（含 chapters 和 projects）+ 独立项目。"""
        courses = self.list_courses(db, include_children=True)
        # 独立项目（未归入任何课程）
        standalone_projects = (
            db.query(Project)
            .filter(Project.course_id.is_(None))
            .order_by(Project.sort_order, Project.created_at.desc())
            .all()
        )
        return {
            "courses": courses,
            "standalone_projects": [_project_brief(p) for p in standalone_projects],
        }

    # ===== Helpers =====

    def _require_course(self, course_id: str, db: Session) -> Course:
        course = db.query(Course).filter(Course.id == course_id).first()
        if not course:
            raise HTTPException(status_code=404, detail=f"课程不存在: {course_id}")
        return course

    def _require_chapter(self, chapter_id: str, db: Session) -> Chapter:
        chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
        if not chapter:
            raise HTTPException(status_code=404, detail=f"章节不存在: {chapter_id}")
        return chapter

    def _next_course_sort_order(self, db: Session) -> int:
        max_order = db.query(Course).count()
        return max_order

    def _next_chapter_sort_order(self, course_id: str, db: Session) -> int:
        count = db.query(Chapter).filter(Chapter.course_id == course_id).count()
        return count


# ===== 单例装配 =====

_SERVICE: CourseService | None = None


def configure_course_service(
    dependencies: CourseDependencies | None = None,
) -> CourseService:
    global _SERVICE
    _SERVICE = CourseService(dependencies or CourseDependencies())
    return _SERVICE


def get_course_service() -> CourseService:
    if _SERVICE is None:
        configure_course_service()
    return _SERVICE
