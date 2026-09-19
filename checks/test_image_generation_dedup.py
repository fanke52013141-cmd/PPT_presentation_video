"""Per-(project, slide) image generation in-flight guard tests."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import image_workflow_service as images  # noqa: E402


def _project(tmp_path: Path) -> SimpleNamespace:
    run_dir = tmp_path / "runs" / "project-dedup"
    planning = run_dir / "planning"
    planning.mkdir(parents=True)
    (planning / "project_config.json").write_text(
        json.dumps(
            {
                "package_id": "account-a",
                "version": 1,
                "content_hash": "test-hash",
                "payload": {
                    "schema_version": "creation_config_v1",
                    "model_bindings": {
                        "image_generation": {"connection_id": "image-a", "revision": 1}
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return SimpleNamespace(id="project-dedup", name="Test", run_dir=str(run_dir))


def _stub_provider(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, project: SimpleNamespace, gate: threading.Event):
    calls: list[str] = []
    entered = threading.Event()

    def fake_generate_image_response(**_kwargs):
        calls.append("provider")
        entered.set()
        assert gate.wait(timeout=5), "provider never released"
        return object()

    monkeypatch.setattr(images, "project_or_404", lambda _db, _id: project)
    monkeypatch.setattr(
        images,
        "resolve_model_connection",
        lambda *_args: {
            "kind": "image",
            "provider": "openai_compatible",
            "model": "dedup-image-model",
            "endpoint": "https://image.snapshot.test/v1",
            "credential_ref": "credential://image",
            "public_config": {"image_size": "1024x1024"},
        },
    )
    monkeypatch.setattr(images, "get_credential", lambda _ref: {"api_key": "secret"})
    monkeypatch.setattr(images, "get_setting", lambda key, default=None: {
        "image_api_key": "global-secret",
        "image_base_url": "https://global.invalid/v1",
        "image_model": "global-image-model",
        "image_size": "1024x1024",
    }.get(key, default))
    monkeypatch.setattr(images, "current_slide_file_or_404", lambda *_args: str(tmp_path / "out.png"))
    monkeypatch.setattr(images, "get_openai_client", lambda **_kwargs: SimpleNamespace())
    monkeypatch.setattr(images, "generate_image_response", fake_generate_image_response)
    monkeypatch.setattr(images, "extract_image_bytes_from_response", lambda _response: b"image")
    monkeypatch.setattr(images, "process_and_save_image", lambda _data, path, **_kwargs: Path(path).write_bytes(b"image"))
    monkeypatch.setattr(
        images, "enforce_white_image_region", lambda *_args, **_kwargs: {"nonwhite_ratio": 0.0, "cleared": False}
    )
    monkeypatch.setattr(images, "get_project_canvas", lambda _project: {"width": 1920, "height": 1080})
    monkeypatch.setattr(images, "project_reference_paths", lambda _project: [])
    monkeypatch.setattr(images, "active_style_reference_paths", lambda: [])
    monkeypatch.setattr(images, "ip_character_reference_paths", lambda *_args: [])
    monkeypatch.setattr(images, "render_ip_character_prompt", lambda *_args: "")
    monkeypatch.setattr(images, "write_visual_provenance", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(images, "mark_slide_image_changed", lambda *_args: None)
    return calls, entered


def test_second_request_for_same_slide_is_rejected_while_generating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    gate = threading.Event()
    calls, entered = _stub_provider(monkeypatch, tmp_path, project, gate)

    def invoke():
        try:
            return images.generate_slide_image("project-dedup", "slide_001", "draw", False, object())
        except images.HTTPException as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(invoke)
        assert entered.wait(timeout=5)
        second = pool.submit(invoke)
        # Give the second thread a moment to hit the guard while the first is blocked.
        for _ in range(50):
            if images.active_slide_image_generation("project-dedup") == ["slide_001"]:
                break
            threading.Event().wait(0.02)
        assert images.active_slide_image_generation("project-dedup") == ["slide_001"]
        rejection = second.result(timeout=5)
        gate.set()
        outcome = first.result(timeout=5)

    assert isinstance(rejection, images.HTTPException)
    assert rejection.status_code == 409
    assert "正在生成图片" in rejection.detail
    assert isinstance(outcome, dict) and outcome["success"] is True
    assert calls == ["provider"]
    assert images.active_slide_image_generation("project-dedup") == []

    # The guard releases cleanly: a follow-up request for the same slide runs again.
    gate.set()
    retry = invoke()
    assert isinstance(retry, dict) and retry["success"] is True
    assert calls == ["provider", "provider"]


def test_different_slides_generate_concurrently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    gate = threading.Event()
    _calls, entered = _stub_provider(monkeypatch, tmp_path, project, gate)

    def invoke(slide_id: str):
        try:
            return images.generate_slide_image("project-dedup", slide_id, "draw", False, object())
        except images.HTTPException as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(invoke, "slide_001")
        assert entered.wait(timeout=5)
        second = pool.submit(invoke, "slide_002")
        # Both slides must reach the provider without a 409.
        for _ in range(50):
            if len(_calls) >= 2:
                break
            threading.Event().wait(0.02)
        gate.set()
        outcome_a = first.result(timeout=5)
        outcome_b = second.result(timeout=5)

    assert isinstance(outcome_a, dict) and outcome_a["success"] is True
    assert isinstance(outcome_b, dict) and outcome_b["success"] is True
    assert len(_calls) == 2


def test_guard_released_even_when_provider_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    gate = threading.Event()
    gate.set()
    _calls, _entered = _stub_provider(monkeypatch, tmp_path, project, gate)

    def failing_response(**_kwargs):
        _calls.append("provider")
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(images, "generate_image_response", failing_response)

    with pytest.raises(images.HTTPException):
        images.generate_slide_image("project-dedup", "slide_001", "draw", False, object())
    assert images.active_slide_image_generation("project-dedup") == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
