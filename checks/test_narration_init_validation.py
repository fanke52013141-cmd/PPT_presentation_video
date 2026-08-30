from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import narration_service


def test_init_narration_reports_invalid_contract_as_recoverable_error(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planning = tmp_path / "planning"
    planning.mkdir()
    (planning / "visual_contract.json").write_text("{broken", encoding="utf-8")
    project = SimpleNamespace(id="narration-test", run_dir=str(tmp_path))

    monkeypatch.setattr(narration_service, "project_or_404", lambda *_args: project)
    monkeypatch.setattr(narration_service, "read_json_file", lambda *_args: {})
    monkeypatch.setattr(
        narration_service.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stderr=""),
    )

    with pytest.raises(HTTPException) as invalid:
        narration_service.init_step6_narration(project.id, object())

    assert invalid.value.status_code == 500
    assert "分镜规划数据无效" in str(invalid.value.detail)


def test_init_narration_keeps_stdout_diagnostics_when_writer_fails(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    planning = tmp_path / "planning"
    planning.mkdir()
    (planning / "visual_contract.json").write_text("{}", encoding="utf-8")
    project = SimpleNamespace(id="narration-test", run_dir=str(tmp_path))

    monkeypatch.setattr(narration_service, "project_or_404", lambda *_args: project)
    monkeypatch.setattr(narration_service, "read_json_file", lambda *_args: {})
    monkeypatch.setattr(
        narration_service.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=17,
            stdout="writer failed with useful context",
            stderr="",
        ),
    )

    with pytest.raises(HTTPException):
        narration_service.init_step6_narration(project.id, object())

    assert "writer failed with useful context" in caplog.text


def test_init_narration_reports_invalid_slide_beats_as_recoverable_error(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planning = tmp_path / "planning"
    planning.mkdir()
    (planning / "visual_contract.json").write_text(
        json.dumps({"slides": [{"slide_id": "slide_001"}]}),
        encoding="utf-8",
    )
    beats = tmp_path / "slides" / "slide_001" / "narration_beats.json"
    beats.parent.mkdir(parents=True)
    beats.write_text('{"beats": "not-a-list"}', encoding="utf-8")
    project = SimpleNamespace(id="narration-test", run_dir=str(tmp_path))

    monkeypatch.setattr(narration_service, "project_or_404", lambda *_args: project)
    monkeypatch.setattr(narration_service, "read_json_file", lambda *_args: {})
    monkeypatch.setattr(
        narration_service.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stderr=""),
    )

    with pytest.raises(HTTPException) as invalid:
        narration_service.init_step6_narration(project.id, object())

    assert invalid.value.status_code == 500
    assert "slide_001" in str(invalid.value.detail)
