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
        run_dir = Path(project["run_dir"])
        assert (run_dir / "inputs").is_dir()
        assert not (run_dir / "inputs" / "article.md").exists()

        deleted = service.delete(project_id, db)
        assert deleted["success"] is True
        assert not run_dir.exists()
    finally:
        db.close()
