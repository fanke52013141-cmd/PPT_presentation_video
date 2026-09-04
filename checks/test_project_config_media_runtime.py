"""Project creation-config runtime coverage for image and TTS providers."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import image_workflow_service as images  # noqa: E402
import tts_service as tts  # noqa: E402


def _project(tmp_path: Path, payload: dict) -> SimpleNamespace:
    run_dir = tmp_path / "runs" / "project-media"
    planning = run_dir / "planning"
    planning.mkdir(parents=True)
    (planning / "project_config.json").write_text(
        json.dumps(
            {
                "package_id": "account-a",
                "version": 1,
                "content_hash": "test-hash",
                "payload": {"schema_version": "creation_config_v1", **payload},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return SimpleNamespace(id="project-media", name="Test", run_dir=str(run_dir))


def _image_connection(_connection_id: str, _revision: int) -> dict:
    return {
        "kind": "image",
        "provider": "openai_compatible",
        "model": "snapshot-image-model",
        "endpoint": "https://image.snapshot.test/v1",
        "credential_ref": "credential://image",
        "public_config": {"image_size": "1536x1024"},
    }


def _tts_connection(_connection_id: str, _revision: int) -> dict:
    return {
        "kind": "tts",
        "provider": "minimax",
        "model": "snapshot-voice-model",
        "endpoint": "https://tts.snapshot.test/v1",
        "credential_ref": "credential://tts",
        "public_config": {"region": "cn"},
    }


def test_image_generation_uses_project_connection_and_redacts_credential_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    project = _project(
        tmp_path,
        {"model_bindings": {"image_generation": {"connection_id": "image-a", "revision": 2}}},
    )
    captured: dict[str, object] = {}
    output_path = tmp_path / "visual_draft.png"

    monkeypatch.setattr(images, "project_or_404", lambda _db, _id: project)
    monkeypatch.setattr(images, "resolve_model_connection", _image_connection)
    monkeypatch.setattr(images, "get_credential", lambda _ref: {"api_key": "image-secret"})
    monkeypatch.setattr(images, "get_setting", lambda key, default=None: {
        "image_api_key": "global-secret",
        "image_base_url": "https://global.invalid/v1",
        "image_model": "global-image-model",
        "image_size": "1024x1024",
    }.get(key, default))
    monkeypatch.setattr(images, "current_slide_file_or_404", lambda *_args: str(output_path))
    monkeypatch.setattr(
        images,
        "get_openai_client",
        lambda **kwargs: captured.setdefault("client", kwargs) or SimpleNamespace(),
    )
    monkeypatch.setattr(images, "generate_image_response", lambda **_kwargs: object())
    monkeypatch.setattr(images, "extract_image_bytes_from_response", lambda _response: b"image")
    monkeypatch.setattr(images, "process_and_save_image", lambda _data, path, **_kwargs: Path(path).write_bytes(b"image"))
    monkeypatch.setattr(images, "get_project_canvas", lambda _project: {"width": 1920, "height": 1080})
    monkeypatch.setattr(images, "project_reference_paths", lambda _project: [])
    monkeypatch.setattr(images, "active_style_reference_paths", lambda: [])
    monkeypatch.setattr(images, "ip_character_reference_paths", lambda *_args: [])
    monkeypatch.setattr(images, "render_ip_character_prompt", lambda *_args: "")
    monkeypatch.setattr(images, "write_visual_provenance", lambda *_args, **kwargs: captured.setdefault("provenance", kwargs))
    monkeypatch.setattr(images, "mark_slide_image_changed", lambda *_args: None)

    result = images.generate_slide_image("project-media", "slide_001", "draw", False, object())

    assert result["success"] is True
    assert captured["client"] == {
        "api_key": "image-secret",
        "base_url": "https://image.snapshot.test/v1",
    }
    assert captured["provenance"]["model"] == "snapshot-image-model"

    monkeypatch.setattr(
        images,
        "generate_image_response",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("provider exposed image-secret")),
    )
    with caplog.at_level(logging.ERROR), pytest.raises(images.HTTPException) as exc_info:
        images.generate_slide_image("project-media", "slide_001", "draw", False, object())
    assert "image-secret" not in exc_info.value.detail
    assert "image-secret" not in caplog.text


def test_image_runtime_without_snapshot_binding_keeps_global_fallback(tmp_path: Path) -> None:
    project = SimpleNamespace(run_dir=str(tmp_path / "legacy"))
    assert images._project_image_runtime(project) is None


def test_tts_generation_uses_project_voice_settings_and_redacts_failed_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(
        tmp_path,
        {
            "model_bindings": {"tts": {"connection_id": "voice-a", "revision": 3}},
            "tts": {
                "voice_id": "snapshot-voice-id",
                "speed": 1.15,
                "volume": 0.9,
                "pitch": 2,
                "region": "shanghai",
                "provider_extra": "snapshot-extra",
            },
        },
    )
    contract_path = Path(project.run_dir) / "planning" / "visual_contract.json"
    contract_path.write_text(json.dumps({"slides": [{"slide_id": "slide_001"}]}), encoding="utf-8")
    captured: dict[str, object] = {}
    logs: list[dict] = []
    status_calls = 0

    monkeypatch.setattr(tts, "project_or_404", lambda _db, _id: project)
    monkeypatch.setattr(tts, "resolve_model_connection", _tts_connection)
    monkeypatch.setattr(tts, "get_credential", lambda _ref: {"api_key": "tts-secret"})
    monkeypatch.setattr(tts, "normalize_tts_provider", lambda value: value)
    monkeypatch.setattr(tts, "tts_provider_defaults", lambda _provider: {"endpoint": "default", "model": "default", "voice_id": "default"})
    monkeypatch.setattr(tts, "TTS_PROVIDER_DEFAULTS", {"minimax": {}})
    monkeypatch.setattr(
        tts,
        "first_non_empty",
        lambda *values: next((str(value).strip() for value in values if str(value or "").strip()), ""),
    )
    monkeypatch.setattr(tts, "get_setting", lambda _key, default=None: "global-value" if default is None else default)
    monkeypatch.setattr(tts, "sync_narration_beats_to_contract", lambda *_args: None)
    monkeypatch.setattr(tts.invalidation_service, "narration_synthesis_started", lambda _project: None)
    monkeypatch.setattr(tts, "slide_tts_artifact_paths", lambda *_args: {"audio": "a", "metadata": "m", "srt": "s", "timeline": "t"})
    monkeypatch.setattr(tts, "ensure_slide_tts_text_file", lambda *_args: "input.txt")

    def artifact_status(*_args):
        nonlocal status_calls
        status_calls += 1
        return {"complete": status_calls > 1, "audio_exists": False, "missing_artifacts": [], "stale": False, "slide_id": "slide_001"}

    monkeypatch.setattr(tts, "slide_tts_artifact_status", artifact_status)
    monkeypatch.setattr(tts, "remove_tts_artifacts", lambda _paths: None)
    monkeypatch.setattr(tts, "rewrite_audio_timeline_by_beats", lambda *_args: None)
    monkeypatch.setattr(tts, "provider_tts_command", lambda **kwargs: captured.setdefault("command", kwargs) or [])
    monkeypatch.setattr(tts, "provider_tts_environment", lambda api, secret: captured.setdefault("environment", {"api": api, "secret": secret}))
    monkeypatch.setattr(tts, "run_tts_command_with_retries", lambda *_args: {"ok": False, "stderr": "provider tts-secret failed", "stdout": "", "attempts": 1, "returncode": 1})
    monkeypatch.setattr(tts, "write_project_log", lambda *_args, **kwargs: logs.append(kwargs))
    monkeypatch.setattr(tts, "mark_step_retry_needed", lambda *_args: None)

    result = tts.synthesize_tts_resumable("project-media", SimpleNamespace(commit=lambda: None))

    command = captured["command"]
    assert command["endpoint"] == "https://tts.snapshot.test/v1"
    assert command["model"] == "snapshot-voice-model"
    assert command["voice_id"] == "snapshot-voice-id"
    assert command["speed"] == "1.15"
    assert command["volume"] == "0.9"
    assert command["pitch"] == "2"
    assert command["region"] == "shanghai"
    assert command["provider_extra"] == "snapshot-extra"
    assert captured["environment"] == {"api": "tts-secret", "secret": ""}
    assert "tts-secret" not in result["failed"][0]["error"]
    assert all("tts-secret" not in repr(item) for item in logs)


def test_tts_runtime_without_snapshot_binding_keeps_global_fallback(tmp_path: Path) -> None:
    project = SimpleNamespace(run_dir=str(tmp_path / "legacy"))
    assert tts._project_tts_runtime(project) is None
