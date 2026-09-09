from __future__ import annotations

from pathlib import Path
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from project_service import (
    ProjectCreate,
    ProjectDependencies,
    ProjectService,
)


def test_project_create_defaults_to_auto_mode() -> None:
    assert ProjectCreate(name="Automatic by default").ai_mode == "auto"


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


def test_project_creation_binds_and_snapshots_creation_config(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'config.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    materialized: list[tuple[str, dict]] = []
    effective = {
        "package_id": "science",
        "version": 3,
        "content_hash": "hash-v3",
        "payload": {
            "subtitle": {"enabled": False, "font_size": 52, "color": "#123456"},
            "mask": {"enabled": False},
            "automation": {"manual_pause_steps": ["mask", "tts"]},
            "image_style": {
                "template_id": "handdrawn",
                "version": 1,
                "reference_policy": "preferred",
                "minimum_reference_images": 1,
            },
            "model_bindings": {
                "article_generation": {
                    "connection_id": "text-a",
                    "revision": 2,
                }
            },
        },
    }
    service = ProjectService(
        ProjectDependencies(
            runs_root=tmp_path / "runs",
            project_audio_confirmed=lambda _project: False,
            resolve_creation_config=lambda package_id, version, overrides: (
                effective
                if package_id == "science" and version == 3 and overrides == {}
                else (_ for _ in ()).throw(ValueError("unexpected config"))
            ),
            write_json_atomic=lambda path, payload: Path(path).write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            ),
            materialize_image_style=lambda project, binding: materialized.append(
                (project.id, binding)
            ) or {"template_id": binding["template_id"]},
        )
    )
    db = session_factory()
    try:
        result = service.create(
            ProjectCreate(
                name="Configured project",
                creation_config_package_id="science",
                creation_config_version=3,
            ),
            db,
        )
        project_id = result["project"]["id"]
        project = service.get(project_id, db)
        assert project["creation_config"] == {
            "package_id": "science",
            "version": 3,
            "content_hash": "hash-v3",
        }
        snapshot = Path(project["run_dir"]) / "planning" / "project_config.json"
        assert json.loads(snapshot.read_text(encoding="utf-8")) == effective
        assert project["mask_enabled"] is False
        assert project["production_mode"] == "guided"
        assert project["presentation_mode"] == "full_frame"
        assert project["manual_pause_steps"] == ["mask", "tts"]
        visual_settings = Path(project["run_dir"]) / "visual_settings.json"
        saved_subtitle = json.loads(visual_settings.read_text(encoding="utf-8"))["subtitle_style"]
        assert saved_subtitle["enabled"] is False
        assert saved_subtitle["font_size"] == 52
        assert saved_subtitle["color"] == "#123456"
        assert materialized == [(project_id, effective["payload"]["image_style"])]
    finally:
        db.close()


def test_default_creation_config_honors_explicit_version_and_overrides(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'default-config.db'}")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    calls: list[tuple[str, int | None, dict]] = []

    def resolve(package_id: str, version: int | None, overrides: dict) -> dict:
        calls.append((package_id, version, overrides))
        return {
            "package_id": package_id,
            "version": version,
            "content_hash": "resolved",
            "payload": {"subtitle": {"enabled": overrides.get("enabled", True)}},
        }

    service = ProjectService(
        ProjectDependencies(
            runs_root=tmp_path / "runs",
            project_audio_confirmed=lambda _project: False,
            resolve_creation_config=resolve,
            get_default_creation_config=lambda _account_id, _db: {
                "package_id": "account-default", "version": 1
            },
        )
    )
    try:
        result = service.create(
            ProjectCreate(
                name="Default with overrides",
                config_package_version=2,
                config_overrides={"enabled": False},
            ),
            db,
        )
        assert calls == [("account-default", 2, {"enabled": False})]
        assert result["project"]["creation_config"]["version"] == 2
    finally:
        db.close()
        engine.dispose()
