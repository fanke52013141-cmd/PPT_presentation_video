"""Single-slide image generation bounded retry executor tests.

覆盖优化方案验证 §5.2：尝试次数、成功页保护、下载恢复、永久错误、
预算截止与"图片已保存仅收尾失败"不得重新生图。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import image_generation_errors as errors  # noqa: E402
import image_workflow_service as images  # noqa: E402


class StatusError(RuntimeError):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


def _project(tmp_path: Path) -> SimpleNamespace:
    run_dir = tmp_path / "runs" / "project-retry"
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
    return SimpleNamespace(id="project-retry", name="Test", run_dir=str(run_dir))


def _stub_workflow(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, project: SimpleNamespace) -> Path:
    out_path = tmp_path / "visual_draft.png"
    monkeypatch.setattr(images, "project_or_404", lambda _db, _id: project)
    monkeypatch.setattr(
        images,
        "resolve_model_connection",
        lambda *_args: {
            "kind": "image",
            "provider": "openai_compatible",
            "model": "retry-image-model",
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
    monkeypatch.setattr(
        images, "current_slide_file_or_404", lambda *_args: str(out_path)
    )
    monkeypatch.setattr(images, "get_openai_client", lambda **_kwargs: SimpleNamespace())
    monkeypatch.setattr(images, "get_project_canvas", lambda _p: {"width": 1920, "height": 1080})
    monkeypatch.setattr(images, "project_reference_paths", lambda _p: [])
    monkeypatch.setattr(images, "active_style_reference_paths", lambda: [])
    monkeypatch.setattr(images, "ip_character_reference_paths", lambda *_a: [])
    monkeypatch.setattr(images, "render_ip_character_prompt", lambda *_a: "")
    monkeypatch.setattr(
        images,
        "enforce_white_image_region",
        lambda *_a, **_kw: {"nonwhite_ratio": 0.0, "cleared": False},
    )
    monkeypatch.setattr(images, "write_visual_provenance", lambda *_a, **_kw: None)
    monkeypatch.setattr(images, "mark_slide_image_changed", lambda *_a, **_kw: None)
    monkeypatch.setenv("PPT_STUDIO_IMAGE_RETRY_INITIAL_BACKOFF_SEC", "0")
    monkeypatch.setenv("PPT_STUDIO_IMAGE_RETRY_JITTER_SEC", "0")
    monkeypatch.setenv("PPT_STUDIO_IMAGE_RETRY_DOWNLOAD_ATTEMPTS", "3")
    return out_path


def _stub_provider_sequence(monkeypatch: pytest.MonkeyPatch, outcomes: list) -> list[str]:
    """每次生图调用按 outcomes 依次消费一个结果（Exception 或 b"image"）。"""
    calls: list[str] = []
    queue = list(outcomes)

    def fake_generate(**_kwargs):
        calls.append("provider")
        outcome = queue.pop(0) if queue else b"image"
        if isinstance(outcome, Exception):
            raise outcome
        return {"data": [{"b64_json": None, "url": "https://cdn.invalid/img.png"}]}

    monkeypatch.setattr(images, "generate_image_response", fake_generate)
    return calls


def _invoke(project_id: str = "project-retry", slide_id: str = "slide_001"):
    try:
        return images.generate_slide_image(project_id, slide_id, "draw", False, object())
    except images.HTTPException as exc:
        return exc


def test_first_failure_then_success_calls_provider_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    out_path = _stub_workflow(monkeypatch, tmp_path, project)
    calls = _stub_provider_sequence(
        monkeypatch, [StatusError("503 overloaded", 503)]
    )
    monkeypatch.setattr(
        images, "extract_image_bytes_from_response", lambda _r: b"image"
    )
    monkeypatch.setattr(
        images, "process_and_save_image", lambda _d, p, **_kw: Path(p).write_bytes(b"image")
    )

    outcome = _invoke()

    assert outcome["success"] is True
    assert outcome["generation_attempts"] == 2
    assert calls == ["provider", "provider"]
    assert Path(out_path).read_bytes() == b"image"
    assert images.active_slide_image_generation("project-retry") == []


def test_transient_failure_recovers_on_third_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    _stub_workflow(monkeypatch, tmp_path, project)
    calls = _stub_provider_sequence(
        monkeypatch,
        [StatusError("overloaded", 503), StatusError("overloaded", 503)],
    )
    monkeypatch.setattr(
        images, "extract_image_bytes_from_response", lambda _r: b"image"
    )
    monkeypatch.setattr(
        images, "process_and_save_image", lambda _d, p, **_kw: Path(p).write_bytes(b"image")
    )

    outcome = _invoke()

    assert outcome["success"] is True
    assert outcome["generation_attempts"] == 3
    assert calls == ["provider"] * 3


def test_persistent_transient_failure_stops_at_cap_and_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    _stub_workflow(monkeypatch, tmp_path, project)
    calls = _stub_provider_sequence(
        monkeypatch, [StatusError("overloaded", 503) for _ in range(10)]
    )
    monkeypatch.setattr(
        images, "extract_image_bytes_from_response", lambda _r: b"image"
    )

    outcome = _invoke()

    assert isinstance(outcome, images.HTTPException)
    assert outcome.status_code == 503
    payload = getattr(outcome, "image_generation_failure")
    assert payload.attempts == 3
    assert payload.recoverable is True
    assert payload.image_saved is False
    assert calls == ["provider"] * 3


def test_permanent_error_fails_fast_with_single_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    _stub_workflow(monkeypatch, tmp_path, project)
    calls = _stub_provider_sequence(monkeypatch, [StatusError("invalid api key", 401)])
    monkeypatch.setattr(
        images, "extract_image_bytes_from_response", lambda _r: b"image"
    )

    outcome = _invoke()

    assert isinstance(outcome, images.HTTPException)
    payload = getattr(outcome, "image_generation_failure")
    assert payload.attempts == 1
    assert payload.code == errors.CODE_AUTH_FAILED
    assert payload.recoverable is False
    assert calls == ["provider"]


def test_image_saved_finalize_failure_never_regenerates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """图片已写盘但收尾失败：不得再次调用生图接口。"""
    project = _project(tmp_path)
    out_path = _stub_workflow(monkeypatch, tmp_path, project)
    calls = _stub_provider_sequence(monkeypatch, [])

    def fail_provenance(*_args, **_kwargs):
        raise OSError("disk full while writing provenance")

    monkeypatch.setattr(
        images, "extract_image_bytes_from_response", lambda _r: b"image"
    )
    monkeypatch.setattr(
        images, "process_and_save_image", lambda _d, p, **_kw: Path(p).write_bytes(b"image")
    )
    monkeypatch.setattr(images, "write_visual_provenance", fail_provenance)

    outcome = _invoke()

    assert isinstance(outcome, images.HTTPException)
    payload = getattr(outcome, "image_generation_failure")
    assert payload.image_saved is True
    assert payload.recoverable is True
    assert payload.attempts == 1
    assert calls == ["provider"]
    assert Path(out_path).read_bytes() == b"image"


def test_download_failure_retries_same_result_without_regenerating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    _stub_workflow(monkeypatch, tmp_path, project)
    calls = _stub_provider_sequence(monkeypatch, [])
    download_calls: list[int] = []

    def flaky_download(_response):
        download_calls.append(1)
        if len(download_calls) == 1:
            raise errors.ImageGenerationError(
                errors.ImageGenerationErrorInfo(
                    code=errors.CODE_DOWNLOAD_FAILED,
                    phase=errors.PHASE_DOWNLOAD,
                    retryable=True,
                    retry_scope=errors.RETRY_SCOPE_REDOWNLOAD,
                    safe_message="HTTP 503 while downloading",
                )
            )
        return b"image"

    monkeypatch.setattr(images, "extract_image_bytes_from_response", flaky_download)
    monkeypatch.setattr(
        images, "process_and_save_image", lambda _d, p, **_kw: Path(p).write_bytes(b"image")
    )

    outcome = _invoke()

    assert outcome["success"] is True
    assert calls == ["provider"]
    assert len(download_calls) == 2


def test_page_budget_exhaustion_stops_the_next_round(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    _stub_workflow(monkeypatch, tmp_path, project)

    class ZeroBudgetPolicy(images.ImageRetryPolicy):
        @classmethod
        def from_environment(cls, env=None):
            return cls(
                enabled=True,
                max_generation_attempts=3,
                initial_backoff_sec=0.0,
                jitter_sec=0.0,
                total_budget_sec=0.0,
            )

    monkeypatch.setattr(images, "ImageRetryPolicy", ZeroBudgetPolicy)
    calls = _stub_provider_sequence(
        monkeypatch, [StatusError("overloaded", 503) for _ in range(10)]
    )
    monkeypatch.setattr(
        images, "extract_image_bytes_from_response", lambda _r: b"image"
    )

    outcome = _invoke()

    assert isinstance(outcome, images.HTTPException)
    payload = getattr(outcome, "image_generation_failure")
    assert payload.attempts == 1
    assert payload.recoverable is True
    assert calls == ["provider"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
