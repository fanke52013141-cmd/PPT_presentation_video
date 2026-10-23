"""Isolated persistent jobs, exact identity, restart and cooperative stop."""

from concurrent.futures import Future
from datetime import datetime, timedelta
from types import SimpleNamespace
from pathlib import Path
import uuid

import pytest
from fastapi.testclient import TestClient

from agent_contract.capabilities import get_capability
from agent_contract.discovery import describe_capability
from database import LocalJob, Project, SessionLocal


@pytest.fixture(scope="module")
def api():
    import server
    return TestClient(server.app, raise_server_exceptions=False, client=("agent-operations-" + uuid.uuid4().hex, 50000))


@pytest.fixture
def project(tmp_path):
    pid = uuid.uuid4().hex
    with SessionLocal() as db:
        db.add(Project(id=pid, name="Operation test", run_dir=str(tmp_path), account_id="default"))
        db.commit()
    return SimpleNamespace(id=pid, run_dir=str(tmp_path))


def call(api, capability_id, arguments):
    return api.post("/api/agent/v1/invoke", json={
        "capability_id": capability_id, "arguments": arguments,
        "expected_contract_revision": describe_capability(get_capability(capability_id))["contract_revision"],
    })


def add_job(project, *, status="running", job_type="video_render", **overrides):
    identity = uuid.uuid4().hex
    with SessionLocal() as db:
        db.add(LocalJob(id=identity, project_id=project.id, job_type=job_type, status=status,
                        stage="render", progress=35, **overrides))
        db.commit()
    return identity


def test_exact_query_never_uses_latest(api, project):
    older = add_job(project, status="interrupted", error="Server restarted", created_at=datetime.now() - timedelta(minutes=2))
    newer = add_job(project, status="succeeded")
    response = call(api, "operation.get", {"project_id": project.id, "operation_id": "job:" + older})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "interrupted"
    assert data["operation_id"] == "job:" + older
    assert "Server restarted" in data["blocking_errors"]
    result = call(api, "operation.list", {"project_id": project.id, "limit": 1}).json()
    assert result["total"] == 2 and result["next_offset"] == 1
    assert result["operations"][0]["operation_id"] == "job:" + newer


def test_unknown_job_state_is_explicit(api, project):
    identity = add_job(project, status="new_unrecognized_state")
    data = call(api, "operation.get", {"project_id": project.id, "operation_id": "job:" + identity}).json()
    assert data["status"] == "unknown"
    assert data["raw_status"] == "new_unrecognized_state"


def test_cancelling_old_job_cannot_stop_new_job(api, project):
    import generation_control
    older = add_job(project)
    newer = add_job(project)
    generation_control.reserve(project.id, "video", newer)
    result = call(api, "operation.cancel", {"project_id": project.id, "operation_id": "job:" + older})
    assert result.status_code == 200, result.text
    assert result.json()["accepted"] is False
    assert generation_control.status(project.id, "video")["stop_requested"] is False
    result = call(api, "operation.cancel", {"project_id": project.id, "operation_id": "job:" + newer})
    assert result.json()["accepted"] is True
    assert result.json()["status"] == "running"
    view = call(api, "operation.get", {"project_id": project.id, "operation_id": "job:" + newer}).json()
    assert view["cancellation_requested"] is True
    assert view["status"] == "running"  # Only the worker may set cancelled.


def test_terminal_cancellation_and_unsupported_producer(api, project):
    terminal = add_job(project, status="succeeded", error="old error")
    response = call(api, "operation.cancel", {"project_id": project.id, "operation_id": "job:" + terminal})
    assert response.json()["accepted"] is False
    assert response.json()["status"] == "succeeded"
    view = call(api, "operation.get", {"project_id": project.id, "operation_id": "job:" + terminal}).json()
    assert view["blocking_errors"] == [] and view["progress"] == 100
    other = add_job(project, job_type="annotation_detect")
    response = call(api, "operation.cancel", {"project_id": project.id, "operation_id": "job:" + other})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CANCELLATION_UNSUPPORTED"


def test_project_scoped_identity_and_invalid_id(api, project, tmp_path):
    foreign = SimpleNamespace(id=uuid.uuid4().hex)
    identity = add_job(foreign)
    response = call(api, "operation.get", {"project_id": project.id, "operation_id": "job:" + identity})
    assert response.status_code == 404
    assert call(api, "operation.get", {"project_id": project.id, "operation_id": "job:../secret"}).status_code == 422


def test_tts_submit_replay_cancel_and_restart(api, project, monkeypatch):
    import tts_service
    from generation_control import status
    submitted = []
    class HoldingExecutor:
        def submit(self, func, job_id):
            submitted.append(job_id)
            return Future()
    service = tts_service.get_tts_async_service()
    monkeypatch.setattr(service, "executor", HoldingExecutor())
    arguments = {"project_id": project.id, "idempotency_key": uuid.uuid4().hex}
    response = call(api, "tts.synthesize", arguments)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["operation_id"] == "job:" + result["job_id"]
    replay = call(api, "tts.synthesize", arguments)
    assert replay.json() == result
    assert submitted == [result["job_id"]]
    cancelled = call(api, "operation.cancel", {"project_id": project.id, "operation_id": result["operation_id"]})
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    assert not status(project.id, "tts")["active"]
    # The existing producer's startup recovery owns running -> interrupted.
    running = add_job(project, job_type="tts_synthesis")
    service.recover_jobs()
    restored = call(api, "operation.get", {"project_id": project.id, "operation_id": "job:" + running})
    assert restored.json()["status"] == "interrupted"


def test_pipeline_history_preserves_old_run_after_restart(api, project):
    import one_click_orchestrator as one_click
    old = one_click._initial_status(project.id, "old_run")
    old["status"] = "completed"
    old["video"] = {"url": "/a-video.mp4"}
    one_click._save_status(project, old)
    current = one_click._initial_status(project.id, "new_run")
    one_click._save_status(project, current)
    exact = call(api, "operation.get", {"project_id": project.id, "operation_id": "pipeline:old_run"})
    assert exact.status_code == 200, exact.text
    assert exact.json()["status"] == "succeeded"
    assert exact.json()["progress"] == 100
    assert exact.json()["artifacts"][0]["url"] == "/a-video.mp4"
    restart = call(api, "operation.get", {"project_id": project.id, "operation_id": "pipeline:new_run"})
    assert restart.json()["status"] == "interrupted"
    assert call(api, "operation.get", {"project_id": project.id, "operation_id": "pipeline:missing"}).status_code == 404
    assert call(api, "operation.list", {"project_id": project.id}).json()["total"] == 2


def test_pipeline_record_identity_mismatch_is_not_read(api, project):
    import json
    from one_click_run_store import run_path
    path = run_path(project, "wrong")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"run_id": "wrong", "project_id": "other", "status": "succeeded"}), encoding="utf-8")
    response = call(api, "operation.get", {"project_id": project.id, "operation_id": "pipeline:wrong"})
    assert response.status_code == 503


def test_polling_checks_exact_identity_and_unknown_status():
    from agent_client.client import AgentClientError
    from agent_client.polling import wait_operation
    from unittest.mock import MagicMock
    client = MagicMock()
    client.get_operation.return_value = {"operation_id": "job:new", "status": "succeeded"}
    with pytest.raises(AgentClientError, match="identity mismatch"):
        wait_operation(client, "p1", "job:old")
    client.get_operation.return_value = {"operation_id": "job:old", "status": "unknown"}
    with pytest.raises(AgentClientError, match="Unknown operation status"):
        wait_operation(client, "p1", "job:old")


def test_video_submission_returns_the_durable_job_identity(api, project, monkeypatch):
    from unittest.mock import MagicMock
    identity = add_job(project, status="queued")
    services = MagicMock()
    services.render_video.return_value = {"success": True, "task_id": identity, "status": "rendering"}
    monkeypatch.setattr("pipeline_services.get_project_pipeline_services", lambda db, pid: services)
    result = call(api, "video.render", {"project_id": project.id, "idempotency_key": uuid.uuid4().hex})
    assert result.status_code == 200, result.text
    assert result.json()["operation_id"] == "job:" + identity
    assert call(api, "operation.get", {"project_id": project.id, "operation_id": result.json()["operation_id"]}).json()["status"] == "queued"


def test_response_lost_after_commit_never_reexecutes(api, project, monkeypatch):
    import article_service
    original = article_service.import_article
    attempts = []
    def import_then_lose_response(*args, **kwargs):
        attempts.append(1)
        original(*args, **kwargs)
        raise RuntimeError("Simulated response loss after commit")
    monkeypatch.setattr(article_service, "import_article", import_then_lose_response)
    arguments = {"project_id": project.id, "content": "# Already saved", "idempotency_key": uuid.uuid4().hex}
    assert call(api, "source.set", arguments).status_code == 500
    response = call(api, "source.set", arguments)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "OPERATION_OUTCOME_UNKNOWN"
    assert attempts == [1]
    assert (Path(project.run_dir) / "inputs" / "article.md").read_text(encoding="utf-8").strip() == "# Already saved"


def test_replay_fingerprint_binds_resource_and_behavior():
    from agent_api.fingerprints import request_fingerprint
    data = {"narration_text": "same", "idempotency_key": "k1"}
    left = request_fingerprint("narration.update", data, project_id="p1", slide_id="slide_001")
    right = request_fingerprint("narration.update", data, project_id="p1", slide_id="slide_002")
    assert left != right
    assert left == request_fingerprint("narration.update", {**data, "idempotency_key": "k2"}, project_id="p1", slide_id="slide_001")


def test_noop_project_edit_preserves_revision(api, project):
    before = call(api, "project.get", {"project_id": project.id}).json()["project"]
    result = call(api, "project.update", {"project_id": project.id, "name": before["name"],
                                          "expected_revision": before["revision"]})
    assert result.status_code == 200, result.text
    assert result.json()["updated"] is False
    assert result.json()["project"]["revision"] == before["revision"]


def test_noop_narration_edit_preserves_version_and_artifact(api, project, monkeypatch):
    from unittest.mock import MagicMock
    services = MagicMock()
    services.narration.return_value = {"beats": {"slides": [{"slide_id": "slide_001", "tts_text": "Existing speech"}]}}
    monkeypatch.setattr("pipeline_services.get_project_pipeline_services", lambda db, pid: services)
    result = call(api, "narration.update", {"project_id": project.id, "slide_id": "slide_001",
                                           "narration_text": "Existing speech", "expected_revision": 0})
    assert result.status_code == 200, result.text
    assert result.json()["updated"] is False
    assert result.json()["revision"] == 0
    services.save_narration.assert_not_called()
    with SessionLocal() as db:
        assert db.get(Project, project.id).revision == 0


def test_exact_wait_stops_at_completion_without_cancelling(monkeypatch):
    from agent_client.polling import wait_operation, PollConfig
    from unittest.mock import MagicMock
    client = MagicMock()
    client.get_operation.side_effect = [
        {"operation_id": "job:one", "status": status} for status in ("queued", "running", "succeeded")
    ]
    monkeypatch.setattr("agent_client.polling.time.sleep", lambda seconds: None)
    result = wait_operation(client, "p1", "job:one", PollConfig(timeout=10, interval=1))
    assert result["status"] == "succeeded"
    assert all(item.args == ("p1", "job:one") for item in client.get_operation.call_args_list)
    client.cancel_operation.assert_not_called()


def test_wait_timeout_only_ends_local_wait(monkeypatch):
    from agent_client.polling import wait_operation, PollConfig
    from unittest.mock import MagicMock
    client = MagicMock()
    client.get_operation.return_value = {"operation_id": "job:one", "status": "running"}
    moments = iter([0, 2])
    monkeypatch.setattr("agent_client.polling.time.monotonic", lambda: next(moments))
    with pytest.raises(TimeoutError):
        wait_operation(client, "p1", "job:one", PollConfig(timeout=1, interval=1))
    client.cancel_operation.assert_not_called()


def test_tts_control_conflict_does_not_leave_a_queued_orphan(api, project, monkeypatch):
    import generation_control
    from tts_service import get_tts_async_service
    from unittest.mock import MagicMock
    executor = MagicMock()
    monkeypatch.setattr(get_tts_async_service(), "executor", executor)
    generation_control.reserve(project.id, "tts", "existing_synchronous_operation")
    response = call(api, "tts.synthesize", {"project_id": project.id, "idempotency_key": uuid.uuid4().hex})
    assert response.status_code == 409, response.text
    executor.submit.assert_not_called()
    with SessionLocal() as db:
        job = db.query(LocalJob).filter(LocalJob.project_id == project.id, LocalJob.job_type == "tts_synthesis").one()
        assert job.status == "interrupted" and job.finished_at is not None
    assert generation_control.status(project.id, "tts")["operation_id"] == "existing_synchronous_operation"
