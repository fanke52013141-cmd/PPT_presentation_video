"""Observe actual isolated artifacts without transitions, repair or generation."""

import hashlib
from dataclasses import replace
import json
from pathlib import Path
import uuid

import pytest
from fastapi.testclient import TestClient

from agent_contract.capabilities import get_capability
from agent_contract.discovery import describe_capability


@pytest.fixture(scope="module")
def api():
    import server
    return TestClient(server.app, client=("workflow-state-" + uuid.uuid4().hex, 50000))


def invoke(api, capability, arguments, **kwargs):
    return api.post("/api/agent/v1/invoke", json={"capability_id": capability, "arguments": arguments,
        "expected_contract_revision": describe_capability(get_capability(capability))["contract_revision"]}, **kwargs)


@pytest.fixture
def project(api):
    from database import Project, SessionLocal
    created = api.post("/api/agent/v1/projects", json={"name": "Workflow state observation"})
    assert created.status_code == 200, created.text
    pid = created.json()["project"]["project_id"]
    with SessionLocal() as db:
        return pid, Path(db.get(Project, pid).run_dir)


def snapshot(root):
    return {str(path.relative_to(root)): (path.stat().st_mtime_ns, path.read_bytes())
            for path in root.rglob("*") if path.is_file()}


def state(api, pid, **kwargs):
    result = invoke(api, "project.state", {"project_id": pid}, **kwargs)
    assert result.status_code == 200, result.text
    return result.json()


def test_empty_project_state_is_read_only_and_keeps_eight_positions(api, project):
    pid, root = project
    before = snapshot(root)
    observed = state(api, pid)
    assert [stage["visible_step"] for stage in observed["stages"]] == list(range(1, 9))
    assert [stage["internal_steps"] for stage in observed["stages"]] == [[1], [2], [3, 4], [5], [6, 7], [10], [9], [8]]
    assert observed["stages"][6]["required"] is False
    assert observed["stages"][6]["skipped"] is True
    assert observed["stages"][3]["skipped"] is True
    assert observed["render_submission"]["can_submit"] is False
    assert "video.render" not in {action["capability_id"] for action in observed["allowed_actions"]}
    assert state(api, pid) == observed
    direct = api.get(f"/api/agent/v1/projects/{pid}/state")
    assert direct.status_code == 200
    assert direct.json() == observed
    assert snapshot(root) == before


@pytest.fixture
def ready_artifacts(project):
    from annotation_contracts import default_annotation_settings
    from database import Project, SessionLocal
    from tts_artifacts import artifact_paths, build_confirmation_payload, confirmation_path
    from visual_provenance import write_visual_provenance
    pid, root = project
    planning = root / "planning"
    planning.mkdir(exist_ok=True)
    contract = planning / "visual_contract.json"
    contract.write_text(json.dumps({"slides": [{"slide_id": "slide_1", "title": "Slide"}]}), encoding="utf-8")
    (planning / "visual_contract.validation.json").write_text(json.dumps({"valid": True, "contract_sha256": hashlib.sha256(contract.read_bytes()).hexdigest()}), encoding="utf-8")
    paths = artifact_paths(root, "slide_1")
    paths["slide_dir"].mkdir(parents=True, exist_ok=True)
    for key, path in paths.items():
        if key != "slide_dir":
            path.write_bytes(("synthetic-" + key).encode())
    image = paths["slide_dir"] / "visual_draft.png"
    image.write_bytes(b"synthetic-image")
    write_visual_provenance(root, "slide_1", image_path=image, provider="manual_upload", source_type="local_upload", source_bytes=image.read_bytes())
    confirmation_path(root).write_text(json.dumps(build_confirmation_payload(root, ["slide_1"], confirmation_mode="test_hash_fixture")), encoding="utf-8")
    settings = replace(default_annotation_settings(), decision="no_annotations")
    (planning / "annotation_settings.json").write_text(json.dumps(settings.to_dict()), encoding="utf-8")
    with SessionLocal() as db:
        db.get(Project, pid).set_step_status({str(step): "completed" for step in range(1, 11)})
        db.commit()
    return project


def test_state_uses_current_audio_hashes_and_the_same_submission_guard(api, ready_artifacts):
    from database import Project, SessionLocal
    from video_render_service import get_video_render_service
    from video_contracts import VideoRenderError
    pid, root = ready_artifacts
    before = snapshot(root)
    observed = state(api, pid)
    assert observed["stages"][5]["module_state"] == "no_annotations"
    assert observed["stages"][5]["skipped"] is True
    assert observed["render_submission"]["can_submit"] is True
    assert "video.render" in {action["capability_id"] for action in observed["allowed_actions"]}
    assert snapshot(root) == before
    (root / "slides/slide_1/voice.mp3").write_bytes(b"changed-audio")
    changed = state(api, pid)
    assert changed["observation_revision"] != observed["observation_revision"]
    assert changed["revision"] == observed["revision"]
    assert changed["render_submission"]["can_submit"] is False
    assert changed["stages"][4]["checks"]["tts"] == ["audio_not_confirmed:artifacts_changed"]
    assert "video.render" not in {action["capability_id"] for action in changed["allowed_actions"]}
    with SessionLocal() as db:
        with pytest.raises(VideoRenderError) as caught:
            get_video_render_service().validate_submission(db.get(Project, pid))
    assert str(caught.value.detail) == changed["render_submission"]["blocking"][0]["message"]


def test_optional_presenter_and_invalid_annotation_decision(api, ready_artifacts):
    pid, root = ready_artifacts
    (root / "planning/digital_human.json").write_text('{"enabled": true}', encoding="utf-8")
    observed = state(api, pid)
    assert observed["stages"][6]["required"] is False
    assert observed["stages"][6]["skipped"] is False
    (root / "planning/annotation_settings.json").write_text("{broken", encoding="utf-8")
    observed = state(api, pid)
    assert observed["stages"][5]["module_state"] == "unavailable"
    assert observed["render_submission"]["annotation_readiness"]["can_render"] is False
    assert "video.render" not in {action["capability_id"] for action in observed["allowed_actions"]}


def test_state_filters_actions_and_isolates_accounts(api, project):
    from account_service import create_account, create_agent_token
    from database import SessionLocal
    pid, root = project
    with SessionLocal() as db:
        reader = create_agent_token(db, "default", scopes=["project:read"])["token"]
        account = create_account(db, name="State isolation " + uuid.uuid4().hex[:6])
        outsider = create_agent_token(db, account["id"], scopes=["project:read"])["token"]
    observed = state(api, pid, headers={"Authorization": "Bearer " + reader})
    assert {action["capability_id"] for action in observed["allowed_actions"]} == {"project.get", "operation.list"}
    assert invoke(api, "project.state", {"project_id": pid}, headers={"Authorization": "Bearer " + outsider}).status_code == 404


def test_active_jobs_remove_delete_advice_without_changing_job_state(api, project):
    from database import LocalJob, SessionLocal
    pid, root = project
    identity = uuid.uuid4().hex
    with SessionLocal() as db:
        db.add(LocalJob(id=identity, project_id=pid, job_type="video_render", status="running"))
        db.commit()
    observed = state(api, pid)
    assert observed["render_submission"]["active_jobs"] == ["job:" + identity]
    assert "project.delete" not in {action["capability_id"] for action in observed["allowed_actions"]}
    with SessionLocal() as db:
        assert db.get(LocalJob, identity).status == "running"
