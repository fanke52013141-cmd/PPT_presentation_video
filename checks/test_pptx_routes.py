from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy import inspect
from sqlalchemy.orm import sessionmaker

import pptx_routes
from route_inventory import iter_effective_routes
import server
from database import ArtifactRecord, Base, LocalJob, Project, engine
from pptx_service import (
    PptxExportService,
    PptxServiceDependencies,
)
from visual_provenance import write_visual_provenance


def test_pptx_export_routes_are_registered() -> None:
    route_methods = {
        (getattr(route, "path", ""), method)
        for route in iter_effective_routes(server.app)
        for method in (getattr(route, "methods", set()) or set())
    }
    assert ("/api/projects/{project_id}/exports/pptx/readiness", "GET") in route_methods
    assert ("/api/projects/{project_id}/exports/pptx", "POST") in route_methods
    assert ("/api/projects/{project_id}/exports", "GET") in route_methods
    assert ("/api/projects/{project_id}/exports/{artifact_id}/download", "GET") in route_methods
    assert ("/api/projects/{project_id}/exports/{artifact_id}", "DELETE") in route_methods
    assert ("/api/projects/{project_id}/jobs/{job_id}", "GET") in route_methods
    assert ("/api/projects/{project_id}/jobs/{job_id}/retry", "POST") in route_methods
    assert hasattr(pptx_routes, "router")
    assert not hasattr(pptx_routes, "register_pptx_routes")
    assert not hasattr(pptx_routes, "_SERVER")


def test_artifact_and_job_tables_exist_after_startup_migration() -> None:
    tables = set(inspect(engine).get_table_names())
    assert {"schema_migrations", "artifact_records", "local_jobs"} <= tables


def test_persistent_pptx_job_completes_and_records_artifact(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "job-project"
    planning = run_dir / "planning"
    slide_dir = run_dir / "slides" / "slide_001"
    planning.mkdir(parents=True)
    slide_dir.mkdir(parents=True)
    (planning / "visual_contract.json").write_text(
        json.dumps({"slides": [{"slide_id": "slide_001"}]}),
        encoding="utf-8",
    )
    image_path = slide_dir / "visual_draft.png"
    Image.new("RGB", (640, 360), "#eef3ff").save(image_path)
    write_visual_provenance(
        run_dir,
        "slide_001",
        image_path=image_path,
        provider="manual_upload",
        source_type="test",
    )

    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'jobs.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(test_engine)
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = testing_session()
    try:
        db.add(Project(id="job-project", name="任务项目", run_dir=str(run_dir)))
        db.add(
            LocalJob(
                id="job-001",
                project_id="job-project",
                job_type="pptx_export",
                status="queued",
                progress=0,
                stage="queued",
                payload_json=json.dumps({"filename": "presentation_job_test.pptx"}),
            )
        )
        db.commit()
    finally:
        db.close()

    service = PptxExportService(
        PptxServiceDependencies(
            session_factory=testing_session,
            runs_root=tmp_path / "runs",
        )
    )

    service.run_job("job-001")

    db = testing_session()
    try:
        job = db.query(LocalJob).filter(LocalJob.id == "job-001").first()
        artifact = db.query(ArtifactRecord).filter(
            ArtifactRecord.project_id == "job-project"
        ).first()
        assert job.status == "succeeded"
        assert job.progress == 100
        project = db.query(Project).filter(
            Project.id == "job-project"
        ).first()
        assert project.get_step_status()["8"] == "completed"
        assert artifact is not None
        assert artifact.filename == "presentation_job_test.pptx"
        assert (run_dir / artifact.relative_path).is_file()
        assert Path(
            f"{run_dir / artifact.relative_path}.export.json"
        ).is_file()
    finally:
        db.close()


def test_pptx_job_recovery_interrupts_running_and_resubmits_queued(
    tmp_path: Path,
) -> None:
    class RecordingExecutor:
        def __init__(self) -> None:
            self.submissions: list[tuple[Any, tuple[Any, ...]]] = []

        def submit(self, operation, *args):
            self.submissions.append((operation, args))
            return None

    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'recovery.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(test_engine)
    testing_session = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=test_engine,
    )
    db = testing_session()
    try:
        db.add_all(
            [
                LocalJob(
                    id="job-running",
                    project_id="project-1",
                    job_type="pptx_export",
                    status="running",
                    progress=50,
                    stage="composing",
                ),
                LocalJob(
                    id="job-queued",
                    project_id="project-1",
                    job_type="pptx_export",
                    status="queued",
                    progress=0,
                    stage="queued",
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    executor = RecordingExecutor()
    service = PptxExportService(
        PptxServiceDependencies(
            session_factory=testing_session,
            runs_root=tmp_path / "runs",
            executor=executor,
        )
    )
    service.recover_jobs()

    db = testing_session()
    try:
        running = db.query(LocalJob).filter(
            LocalJob.id == "job-running"
        ).first()
        queued = db.query(LocalJob).filter(
            LocalJob.id == "job-queued"
        ).first()
        assert running.status == "interrupted"
        assert running.stage == "interrupted"
        assert running.finished_at is not None
        assert queued.status == "queued"
    finally:
        db.close()
    assert len(executor.submissions) == 1
    assert executor.submissions[0][1] == ("job-queued",)


def test_pptx_service_source_has_no_application_module_dependency() -> None:
    service_source = (
        Path(__file__).resolve().parents[1] / "pptx_service.py"
    ).read_text(encoding="utf-8")
    route_source = (
        Path(__file__).resolve().parents[1] / "pptx_routes.py"
    ).read_text(encoding="utf-8")
    for source in (service_source, route_source):
        assert "server_module" not in source
        assert "sys.modules" not in source
        assert "_SERVER" not in source
    assert "register_pptx_routes" not in route_source
