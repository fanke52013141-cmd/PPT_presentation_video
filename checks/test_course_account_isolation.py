from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from account_context import account_scope
from course_service import ChapterCreate, CourseCreate, CourseDependencies, ProjectMove, get_course_service, configure_course_service
from database import Account, Base, Project
from project_service import ProjectCreate, ProjectDependencies, ProjectService


def test_course_tree_and_project_moves_are_scoped_to_current_account(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'courses.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    db = session_factory()
    try:
        db.add_all([
            Account(id="default", name="默认", status="active"),
            Account(id="account_b", name="B", status="active"),
        ])
        db.commit()
        configure_course_service(CourseDependencies())
        service = get_course_service()

        with account_scope("default"):
            course_a = service.create_course(CourseCreate(name="A 课程"), db)
            chapter_a = service.create_chapter(course_a["id"], ChapterCreate(name="A 章节"), db)
            project_a = Project(
                id="project_a", name="A 项目", run_dir=str(tmp_path / "a"), account_id="default"
            )
            db.add(project_a)
            db.commit()
            service.move_project(project_a.id, ProjectMove(chapter_id=chapter_a["id"]), db)
            assert service.get_tree(db)["courses"][0]["chapters"][0]["projects"][0]["id"] == project_a.id
            project_service = ProjectService(
                ProjectDependencies(
                    runs_root=tmp_path / "runs",
                    project_audio_confirmed=lambda _project: False,
                )
            )
            created = project_service.create(
                ProjectCreate(
                    name="章节内创建",
                    course_id=course_a["id"],
                    chapter_id=chapter_a["id"],
                ),
                db,
            )
            assert created["project"]["course_id"] == course_a["id"]
            assert created["project"]["chapter_id"] == chapter_a["id"]

        with account_scope("account_b"):
            assert service.list_courses(db) == []
            with pytest.raises(Exception) as course_error:
                service.get_course(course_a["id"], db)
            assert getattr(course_error.value, "status_code", None) == 404
            project_b = Project(
                id="project_b", name="B 项目", run_dir=str(tmp_path / "b"), account_id="account_b"
            )
            db.add(project_b)
            db.commit()
            with pytest.raises(Exception) as move_error:
                service.move_project(project_b.id, ProjectMove(chapter_id=chapter_a["id"]), db)
            assert getattr(move_error.value, "status_code", None) == 404
            project_service = ProjectService(
                ProjectDependencies(
                    runs_root=tmp_path / "runs-b",
                    project_audio_confirmed=lambda _project: False,
                )
            )
            with pytest.raises(Exception) as create_error:
                project_service.create(
                    ProjectCreate(name="越权章节", chapter_id=chapter_a["id"]),
                    db,
                )
            assert getattr(create_error.value, "status_code", None) == 404
    finally:
        db.close()
        engine.dispose()
