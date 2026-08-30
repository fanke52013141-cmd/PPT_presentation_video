from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from project_service import (
    ProjectCreate,
    ProjectDependencies,
    ProjectService,
)


def test_project_can_be_created_without_article_content(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'projects.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    service = ProjectService(
        ProjectDependencies(
            runs_root=tmp_path / "runs",
            project_audio_confirmed=lambda _project: False,
        )
    )
    db = session_factory()
    try:
        result = service.create(
            ProjectCreate(
                name="Empty article project",
                description="",
                ai_mode="manual",
            ),
            db,
        )
        project_id = result["project"]["id"]
        project = service.get(project_id, db)
        assert project["current_step"] == 1
        assert project["ai_mode"] == "manual"
        assert project["canvas_profile"] == "landscape_16_9"
        assert project["canvas"]["width"] == 1920
        assert project["canvas"]["height"] == 1080
        run_dir = Path(project["run_dir"])
        assert (run_dir / "inputs").is_dir()
        assert not (run_dir / "inputs" / "article.md").exists()
        assert (run_dir / "planning" / "canvas_profile.json").is_file()

        deleted = service.delete(project_id, db)
        assert deleted["success"] is True
        assert not run_dir.exists()
    finally:
        db.close()


def test_project_can_be_created_with_portrait_canvas_profile(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'portrait.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    service = ProjectService(
        ProjectDependencies(
            runs_root=tmp_path / "runs",
            project_audio_confirmed=lambda _project: False,
        )
    )
    db = session_factory()
    try:
        result = service.create(
            ProjectCreate(name="Portrait project", canvas_profile="9:16"),
            db,
        )
        project = service.get(result["project"]["id"], db)
        assert project["canvas_profile"] == "portrait_9_16"
        assert project["canvas"] == {
            "id": "portrait_9_16",
            "orientation": "portrait",
            "aspect_ratio": "9:16",
            "width": 1080,
            "height": 1920,
            "subtitle_safe_zone": {"top": 1650, "bottom": 1920},
            "content_safe_area": {"left": 64, "top": 180, "right": 1016, "bottom": 1650},
        }
        snapshot = Path(project["run_dir"]) / "planning" / "canvas_profile.json"
        assert '"aspect_ratio": "9:16"' in snapshot.read_text(encoding="utf-8")
    finally:
        db.close()
