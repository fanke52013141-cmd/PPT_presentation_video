"""Agent HTTP acceptance for the portrait presenter sources and config patch.

Covers the real multipart motion upload, the declared non-invocable transport,
the typed configuration schema/discovery, source precondition errors and the
readiness checks surfaced through project.state.  Uses the same real business
storage as the Web UI; no model runtime is contacted.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from checks.agent.test_full_workflow_mocked import api, invoke  # noqa: F401


def _project(api, name: str) -> str:
    created = invoke(api, "project.create", {"name": name})
    assert created.status_code == 200, created.text
    return created.json()["project"]["project_id"]


def _run_dir(project_id: str) -> Path:
    from database import Project, SessionLocal

    with SessionLocal() as db:
        return Path(db.get(Project, project_id).run_dir)


def _motion_template() -> tuple[Path, bytes]:
    from repository_paths import DEFAULT_PORTRAIT_MOTION_VIDEO

    path = Path(DEFAULT_PORTRAIT_MOTION_VIDEO)
    if not path.is_file():
        pytest.skip("bundled portrait motion template is unavailable")
    return path, path.read_bytes()


def _write_config(project_id: str, **overrides) -> dict:
    from digital_human_contracts import config_path, default_config
    from pipeline_lifecycle import write_json_atomic

    run_dir = _run_dir(project_id)
    (run_dir / "planning").mkdir(parents=True, exist_ok=True)
    config = default_config()
    config.update(overrides)
    write_json_atomic(config_path(run_dir), config)
    return config


def test_motion_upload_roundtrip_is_real_and_noop(api):
    project_id = _project(api, "Agent motion upload")
    _, content = _motion_template()
    base = f"/api/agent/v1/projects/{project_id}/digital-human/motion"

    first = api.post(base, files={"file": ("driving.mp4", content, "video/mp4")})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["success"] is True and body["changed"] is True
    motion = body["motion"]
    assert motion["source"] == "custom" and motion["exists"] is True
    assert motion["metadata"]["width"] > 0 and motion["metadata"]["duration_sec"] > 0

    repeated = api.post(base, files={"file": ("driving.mp4", content, "video/mp4")})
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["changed"] is False

    config = invoke(api, "digital_human.config.get", {"project_id": project_id})
    assert config.status_code == 200, config.text
    payload = config.json()
    assert payload["config"]["motion_source"] == "custom"
    assert payload["motion"]["exists"] is True
    assert payload["motion"]["metadata"]["duration_sec"] == motion["metadata"]["duration_sec"]


def test_motion_upload_transport_is_declared_non_invocable(api):
    project_id = _project(api, "Agent motion transport")
    detail = api.get("/api/agent/v1/capabilities/digital_human.motion.upload")
    assert detail.status_code == 200, detail.text
    described = detail.json()
    assert described["response_kind"] == "file_upload"
    assert described["invocable"] is False
    assert described["mcp_enabled"] is False
    assert described["required_scopes"] == ["project:write"]

    invoked = invoke(api, "digital_human.motion.upload", {"project_id": project_id})
    assert invoked.status_code == 422, invoked.text
    assert invoked.json()["error"]["code"] == "UNSUPPORTED_TRANSPORT"


def _def_name(property_schema: dict) -> str:
    """Return the referenced definition name from an anyOf/$ref property."""
    for option in property_schema.get("anyOf") or [property_schema]:
        if "$ref" in option:
            return option["$ref"].rsplit("/", 1)[-1]
    raise AssertionError(f"no $ref in {property_schema!r}")


def test_config_patch_schema_is_discoverable(api):
    detail = api.get("/api/agent/v1/capabilities/digital_human.config.update")
    assert detail.status_code == 200, detail.text
    schema = detail.json()["input_schema"]
    patch = schema["$defs"]["DigitalHumanConfigPatch"]
    properties = patch["properties"]
    expected = {
        "enabled", "mode", "motion_source", "upload_start_sec",
        "upload_short_video_policy", "shape", "avatar_id", "sync_mode",
        "position", "border", "circle", "video",
    }
    assert expected <= set(properties)
    assert schema["$defs"][_def_name(properties["mode"])]["enum"] == [
        "portrait", "comfyui", "upload", "generate",
    ]
    assert schema["$defs"][_def_name(properties["motion_source"])]["enum"] == ["default", "custom"]
    assert schema["$defs"][_def_name(properties["upload_short_video_policy"])]["enum"] == ["reject", "loop"]
    assert properties["enabled"]["description"]
    assert properties["upload_start_sec"]["anyOf"][0]["minimum"] == 0

    config_get = api.get("/api/agent/v1/capabilities/digital_human.config.get").json()
    view = config_get["output_schema"]["$defs"]["DigitalHumanConfigView"]
    assert "motion_source" in view["properties"]
    assert "upload_short_video_policy" in view["properties"]


def test_config_patch_roundtrip_and_typed_validation(api):
    project_id = _project(api, "Agent config patch")
    updated = invoke(api, "digital_human.config.update", {
        "project_id": project_id,
        "config": {
            "enabled": True,
            "mode": "portrait",
            "motion_source": "custom",
            "upload_start_sec": 1.5,
            "upload_short_video_policy": "loop",
        },
    })
    assert updated.status_code == 200, updated.text
    assert updated.json()["config"]["mode"] == "portrait"

    fetched = invoke(api, "digital_human.config.get", {"project_id": project_id}).json()["config"]
    assert fetched["enabled"] is True
    assert fetched["mode"] == "portrait"
    assert fetched["motion_source"] == "custom"
    assert fetched["upload_start_sec"] == 1.5
    assert fetched["upload_short_video_policy"] == "loop"

    for invalid in ({"mode": "nope"}, {"motion_source": "nope"},
                    {"upload_short_video_policy": "stretch"}, {"upload_start_sec": -1},
                    {"unexpected_field": True}):
        response = invoke(api, "digital_human.config.update",
                          {"project_id": project_id, "config": invalid})
        assert response.status_code == 422, (invalid, response.text)
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_presenter_source_preconditions_use_typed_errors(api):
    project_id = _project(api, "Agent presenter preconditions")
    assert invoke(api, "digital_human.config.update", {
        "project_id": project_id,
        "config": {"enabled": True, "mode": "portrait"},
    }).status_code == 200

    missing_avatar = invoke(api, "digital_human.slide.generate", {
        "project_id": project_id, "slide_id": "slide_001", "payload": {},
    })
    assert missing_avatar.status_code == 400, missing_avatar.text
    assert missing_avatar.json()["error"]["code"] == "VALIDATION_ERROR"

    assert invoke(api, "digital_human.config.update", {
        "project_id": project_id, "config": {"mode": "upload"},
    }).status_code == 200
    upload_mode = invoke(api, "digital_human.slide.generate", {
        "project_id": project_id, "slide_id": "slide_001", "payload": {},
    })
    assert upload_mode.status_code == 409, upload_mode.text
    assert upload_mode.json()["error"]["code"] == "CONFLICT"


def test_project_state_exposes_presenter_readiness(api):
    project_id = _project(api, "Agent presenter readiness")
    run_dir = _run_dir(project_id)
    _write_config(
        project_id,
        enabled=True,
        mode="portrait",
        slides={"full": {
            "job_id": "old-job",
            "status": "done",
            "published": {"source_sha256": "stale-source", "audio_sha256": ""},
        }},
    )
    digi = run_dir / "planning" / "digital_human"
    digi.mkdir(parents=True, exist_ok=True)
    (digi / "digi_full.mp4").write_bytes(b"previous-presenter-video")

    state = invoke(api, "project.state", {"project_id": project_id})
    assert state.status_code == 200, state.text
    payload = state.json()
    stage = next(item for item in payload["stages"] if item["id"] == "digital_human")
    assert stage["skipped"] is False
    assert stage["module_state"] == "blocked"
    assert "presenter_source_stale" in stage["checks"]["presenter"]
    assert "presenter_audio_stale" in stage["checks"]["audio"]

    readiness = payload["render_submission"]["presenter_readiness"]
    assert readiness["enabled"] is True and readiness["ready"] is False
    assert "presenter_source_stale" in readiness["issues"]


def test_project_state_marks_disabled_presenter_skipped(api):
    project_id = _project(api, "Agent presenter disabled")
    state = invoke(api, "project.state", {"project_id": project_id}).json()
    stage = next(item for item in state["stages"] if item["id"] == "digital_human")
    assert stage["skipped"] is True
    assert stage["module_state"] == "disabled"
    assert stage["checks"] == {}
    assert state["render_submission"]["presenter_readiness"]["ready"] is True
