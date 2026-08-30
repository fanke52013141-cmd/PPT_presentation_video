from __future__ import annotations

from pathlib import Path

import pytest

from checks import e2e_one_click_run


def test_comfyui_provider_preflight_uses_local_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import comfyui_backend

    settings = {
        "tts_provider": "comfyui_tts",
        "tts_endpoint": "",
    }
    monkeypatch.setattr(
        e2e_one_click_run,
        "get_setting",
        lambda key, default=None: settings.get(key, default),
    )
    monkeypatch.setattr(
        comfyui_backend,
        "inspect_tts_preflight",
        lambda _workflow: {"success": True},
    )

    checks = e2e_one_click_run.provider_preflight_checks()

    assert checks["tts_credentials"] is True


def test_provider_preflight_reports_presence_without_returning_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = {
        "llm_api_key": "llm-secret",
        "image_api_key": "image-secret",
        "tts_provider": "minimax",
        "tts_api_key": "tts-secret",
    }
    monkeypatch.setattr(
        e2e_one_click_run,
        "get_setting",
        lambda key, default=None: settings.get(key, default),
    )
    assert e2e_one_click_run.provider_preflight_checks() == {
        "llm_credentials": True,
        "image_credentials": True,
        "tts_credentials": True,
    }


def test_provider_preflight_fails_before_external_work_when_credentials_are_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        e2e_one_click_run,
        "provider_preflight_checks",
        lambda: {
            "llm_credentials": False,
            "image_credentials": False,
            "tts_credentials": True,
        },
    )

    with pytest.raises(
        RuntimeError,
        match="llm_credentials, image_credentials",
    ):
        e2e_one_click_run.require_provider_preflight()


def test_preflight_report_uses_source_owned_media_resolver(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    article_path = run_dir / "inputs" / "article.md"
    article_path.parent.mkdir(parents=True)
    article_path.write_text("article", encoding="utf-8")
    monkeypatch.setattr(
        e2e_one_click_run,
        "provider_preflight_checks",
        lambda: {
            "llm_credentials": True,
            "image_credentials": True,
            "tts_credentials": True,
        },
    )
    monkeypatch.setattr(
        e2e_one_click_run,
        "resolve_media_tool",
        lambda name, repo_root: f"C:/tools/{name}",
    )

    e2e_one_click_run.write_preflight_report(run_dir, "project-1")

    report = (run_dir / "logs" / "preflight_report.md").read_text(
        encoding="utf-8"
    )
    assert "status: `passed`" in report
    assert "PASS: ffmpeg" in report
    assert "PASS: ffprobe" in report
    assert "secret" not in report
