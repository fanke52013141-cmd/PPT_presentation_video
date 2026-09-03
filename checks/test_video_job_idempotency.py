from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base, LocalJob
from video_contracts import VideoRenderConfig
from video_job_store import VideoJobStore
from video_render_service import VideoRenderDependencies, VideoRenderService


def _config(tmp_path: Path) -> VideoRenderConfig:
    return VideoRenderConfig(
        repo_root=tmp_path,
        runs_root=tmp_path,
        pipeline_version="test-pipeline",
        reveal_visual_lead_sec=0.2,
        bind_timeout_sec=1,
        build_props_timeout_sec=1,
        npm_install_timeout_sec=1,
        render_timeout_sec=1,
        color_process_timeout_sec=1,
    )


def _job(
    job_id: str,
    status: str,
    payload: dict[str, object],
) -> LocalJob:
    now = datetime.now()
    return LocalJob(
        id=job_id,
        project_id="project-001",
        job_type="video_render",
        status=status,
        progress=100 if status == "succeeded" else 0,
        stage="completed" if status == "succeeded" else "validating",
        payload_json=json.dumps(payload),
        created_at=now,
        updated_at=now,
        started_at=now,
        finished_at=now if status == "succeeded" else None,
    )


class _SubmissionStore:
    def __init__(self, latest: LocalJob | None = None) -> None:
        self.latest = latest
        self.created: list[dict[str, object]] = []

    def latest_for_submission(
        self,
        _project_id: str,
        _submission_key: str,
    ) -> LocalJob | None:
        return self.latest

    def active(self, _project_id: str) -> None:
        return None

    def create(self, _project_id: str, **kwargs: object) -> None:
        self.created.append(kwargs)


def _service(
    tmp_path: Path,
    store: _SubmissionStore,
    *,
    input_digest: str = "input-a",
) -> tuple[VideoRenderService, SimpleNamespace]:
    project = SimpleNamespace(id="project-001", run_dir=str(tmp_path))
    artifacts = SimpleNamespace(
        current_render_input_fingerprint=lambda _project: {
            "digest": input_digest,
        },
    )
    service = VideoRenderService(
        VideoRenderDependencies(
            session_factory=lambda: None,
            artifact_service=artifacts,
            remotion_runner=SimpleNamespace(),
            config=_config(tmp_path),
        )
    )
    service.job_store = store
    service.get_project = lambda _db, _project_id: project
    service._read_contract_slide_ids = lambda _run_dir: ["slide_001"]
    return service, project


def _prepare_start(monkeypatch) -> None:
    monkeypatch.setattr(
        "video_render_service.validate_visual_provenance_set",
        lambda *_args: [],
    )
    monkeypatch.setattr(
        "video_render_service.tts_confirmation_status",
        lambda *_args: {"confirmed": True},
    )

    class NoopThread:
        def __init__(self, **_kwargs) -> None:
            pass

        def start(self) -> None:
            return None

    monkeypatch.setattr("video_render_service.threading.Thread", NoopThread)


class _CallerDb:
    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


def test_reuses_active_submission_without_creating_or_starting_worker(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _prepare_start(monkeypatch)
    store = _SubmissionStore(_job("active-001", "queued", {}))
    service, project = _service(tmp_path, store)

    response = service.start_render(_CallerDb(), project.id)

    assert response["task_id"] == "active-001"
    assert response["status"] == "rendering"
    assert store.created == []


def test_reuses_succeeded_submission_only_when_output_still_exists(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _prepare_start(monkeypatch)
    output = tmp_path / "render.mp4"
    output.write_bytes(b"video")
    store = _SubmissionStore(
        _job(
            "success-001",
            "succeeded",
            {"output_filename": output.name},
        )
    )
    service, project = _service(tmp_path, store)
    service.project_video_file = lambda _project, _filename: output

    response = service.start_render(_CallerDb(), project.id)

    assert response["task_id"] == "success-001"
    assert response["status"] == "success"
    assert store.created == []


def test_failed_submission_creates_linked_new_attempt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _prepare_start(monkeypatch)
    store = _SubmissionStore(
        _job(
            "failed-001",
            "failed",
            {"submission_attempt": 2},
        )
    )
    service, project = _service(tmp_path, store)

    response = service.start_render(_CallerDb(), project.id)

    assert response["success"] is True
    assert len(store.created) == 1
    payload = store.created[0]["payload"]
    assert payload["prior_job_id"] == "failed-001"
    assert payload["submission_attempt"] == 3
    assert store.created[0]["submission_attempt"] == 3


def test_changed_input_generates_new_submission_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _prepare_start(monkeypatch)
    store = _SubmissionStore()
    service, project = _service(tmp_path, store, input_digest="input-a")

    service.start_render(_CallerDb(), project.id)
    service._project_lock(project.id).release()
    service._tasks.clear()
    service.artifacts.current_render_input_fingerprint = lambda _project: {
        "digest": "input-b",
    }
    service.start_render(_CallerDb(), project.id)

    assert len(store.created) == 2
    assert store.created[0]["submission_key"] != store.created[1]["submission_key"]


def test_submission_key_is_stable_and_does_not_embed_sensitive_input(
    tmp_path: Path,
) -> None:
    store = _SubmissionStore()
    service, project = _service(tmp_path, store, input_digest="same-input")
    service.artifacts.current_render_input_fingerprint = lambda _project: {
        "digest": "same-input",
        "provider_token": "secret-value-must-not-appear",
        "absolute_path": "C:/private/location",
    }

    first = service._submission_key(project)
    second = service._submission_key(project)

    assert first == second
    assert first != "secret-value-must-not-appear"
    assert "secret-value-must-not-appear" not in first
    assert "C:/private/location" not in first


def test_submission_key_ignores_artifacts_created_during_render(
    tmp_path: Path,
) -> None:
    store = _SubmissionStore()
    service, project = _service(tmp_path, store)
    source_components = {
        "planning/visual_contract.json": "contract-hash",
        "slides/slide_001/visual_draft.png": "image-hash",
        "slides/slide_001/voice.mp3": "audio-hash",
        "remotion_props.json": None,
        "slides/slide_001/scene.json": None,
        "slides/slide_001/animation_timeline.json": None,
    }
    service.artifacts.current_render_input_fingerprint = lambda _project: {
        "schema_version": 1,
        "pipeline_version": "test-pipeline",
        "slide_ids": ["slide_001"],
        "visual_settings": {"video_background": "#FEFDF9"},
        "components": source_components,
    }
    first = service._submission_key(project)
    service.artifacts.current_render_input_fingerprint = lambda _project: {
        "schema_version": 1,
        "pipeline_version": "test-pipeline",
        "slide_ids": ["slide_001"],
        "visual_settings": {"video_background": "#FEFDF9"},
        "components": {
            **source_components,
            "remotion_props.json": "new-props-hash",
            "slides/slide_001/scene.json": "new-scene-hash",
            "slides/slide_001/animation_timeline.json": "new-timeline-hash",
        },
    }

    assert service._submission_key(project) == first


def test_store_reads_submission_key_and_preserves_retry_attempts(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "jobs.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "ALTER TABLE local_jobs ADD COLUMN submission_key VARCHAR"
        )
        connection.exec_driver_sql(
            "ALTER TABLE local_jobs ADD COLUMN submission_attempt INTEGER NOT NULL DEFAULT 0"
        )
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX ux_test_submission_attempt "
            "ON local_jobs (project_id, job_type, submission_key, submission_attempt) "
            "WHERE submission_key IS NOT NULL"
        )
    store = VideoJobStore(sessionmaker(bind=engine))

    store.create(
        "project-001",
        job_id="first",
        stage="validating",
        payload={"submission_attempt": 0},
        submission_key="a" * 64,
        submission_attempt=0,
    )
    store.create(
        "project-001",
        job_id="retry",
        stage="validating",
        payload={"submission_attempt": 1, "prior_job_id": "first"},
        submission_key="a" * 64,
        submission_attempt=1,
    )

    latest = store.latest_for_submission("project-001", "a" * 64)

    assert latest is not None
    assert latest.id == "retry"
    assert latest.get_payload()["prior_job_id"] == "first"
