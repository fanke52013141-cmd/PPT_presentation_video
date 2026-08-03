from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import artifact_registry
from database import ArtifactRecord, Base, LocalJob, Project
import server
from video_job_store import (
    VIDEO_RENDER_JOB_TYPE,
    VideoJobStore,
)


def _session_factory(tmp_path: Path):
    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'persistent-jobs.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(test_engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def test_video_job_state_survives_outside_memory_cache(
    tmp_path: Path,
) -> None:
    testing_session = _session_factory(tmp_path)
    store = VideoJobStore(testing_session)

    created = store.create(
        "project-001",
        job_id="video-job-001",
        stage="validating",
        payload={},
    )
    assert created.status == "queued"
    assert store.active("project-001").id == created.id

    store.update(
        created.id,
        status="running",
        stage="rendering",
        progress=52,
    )
    running = store.get(
        created.id,
        project_id="project-001",
    )
    assert running.status == "running"
    assert running.stage == "rendering"
    assert running.progress == 52
    assert running.started_at is not None

    store.update(
        created.id,
        status="succeeded",
        stage="completed",
        progress=100,
        result_artifact_id="artifact-001",
        payload_updates={"output_filename": "render_test.mp4"},
    )
    completed = store.latest("project-001")
    assert completed.status == "succeeded"
    assert completed.result_artifact_id == "artifact-001"
    assert completed.get_payload()["output_filename"] == "render_test.mp4"
    assert completed.finished_at is not None


def test_successful_video_job_clears_an_earlier_error(
    tmp_path: Path,
) -> None:
    testing_session = _session_factory(tmp_path)
    store = VideoJobStore(testing_session)
    created = store.create(
        "project-clear-error",
        job_id="video-job-clear-error",
        stage="rendering",
        payload={},
    )
    store.update(
        created.id,
        status="interrupted",
        stage="interrupted",
        error="应用退出，任务中断",
    )

    store.update(
        created.id,
        status="succeeded",
        stage="completed",
        progress=100,
        error=None,
    )

    completed = store.get(created.id)
    assert completed.status == "succeeded"
    assert completed.error is None


def test_startup_recovery_marks_active_video_jobs_interrupted(
    tmp_path: Path,
) -> None:
    testing_session = _session_factory(tmp_path)
    store = VideoJobStore(testing_session)
    store.create(
        "project-002",
        job_id="video-job-orphaned",
        stage="validating",
        payload={},
    )

    changed = store.interrupt_orphaned(
        "应用退出，任务中断",
    )

    recovered = store.get("video-job-orphaned")
    assert changed == 1
    assert recovered.status == "interrupted"
    assert recovered.stage == "interrupted"
    assert recovered.error == "应用退出，任务中断"


def test_render_status_reads_interrupted_job_from_sqlite_fallback(tmp_path: Path, monkeypatch) -> None:
    project_run_dir = tmp_path / "project-status"
    project_run_dir.mkdir()
    project = SimpleNamespace(
        id="project-status",
        run_dir=str(project_run_dir),
    )
    job = LocalJob(
        id="video-job-status",
        project_id=project.id,
        job_type=VIDEO_RENDER_JOB_TYPE,
        status="interrupted",
        progress=52,
        stage="interrupted",
        error="应用退出，任务中断",
        payload_json="{}",
        created_at=datetime.now() - timedelta(minutes=2),
        started_at=datetime.now() - timedelta(minutes=1),
        finished_at=datetime.now(),
        updated_at=datetime.now(),
    )

    class Query:
        def filter(self, *_args):
            return self

        def first(self):
            return project

    class Db:
        def query(self, *_args):
            return Query()

    from dataclasses import replace
    from video_artifact_service import VideoArtifactService
    from video_render_service import VideoRenderService

    artifacts = VideoArtifactService(
        replace(
            server.video_render_service.artifacts.dependencies,
            runs_root=tmp_path,
        )
    )
    service = VideoRenderService(
        replace(
            server.video_render_service.dependencies,
            artifact_service=artifacts,
            config=replace(
                server.video_render_service.config,
                runs_root=tmp_path,
            ),
        )
    )
    monkeypatch.setattr(
        service.job_store,
        "get",
        lambda *_args, **_kwargs: job,
    )
    with service._tasks_lock:
        service._tasks.pop(job.id, None)

    result = service.render_status(
        Db(),
        project.id,
        task_id=job.id,
    )

    assert result["status"] == "interrupted"
    assert result["task_id"] == job.id
    assert result["error"] == "应用退出，任务中断"


def test_video_artifact_registry_records_and_removes_file_metadata(tmp_path: Path) -> None:
    testing_session = _session_factory(tmp_path)
    video = tmp_path / "render_test.mp4"
    video.write_bytes(b"video-bytes")
    db = testing_session()
    try:
        db.add(Project(id="artifact-project", name="产物项目", run_dir=str(tmp_path)))
        db.commit()
        artifact = artifact_registry.record_artifact(
            db,
            project_id="artifact-project",
            artifact_type="video",
            path=video,
            relative_path="videos/render_test.mp4",
            mime_type="video/mp4",
            source_fingerprint={"digest": "input-digest"},
            metadata={"playback_rate": 1.0},
        )
        db.commit()
        assert artifact.size_bytes == len(b"video-bytes")
        assert artifact.get_source_fingerprint()["digest"] == "input-digest"
        assert artifact.get_metadata()["playback_rate"] == 1.0

        removed = artifact_registry.remove_artifact_record(
            db,
            project_id="artifact-project",
            artifact_type="video",
            filename="render_test.mp4",
        )
        db.commit()
        assert removed == 1
        assert db.query(ArtifactRecord).filter(
            ArtifactRecord.project_id == "artifact-project"
        ).count() == 0
    finally:
        db.close()
