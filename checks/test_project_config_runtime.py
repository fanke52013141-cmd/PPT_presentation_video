"""Regression coverage for immutable project config reads in text stages."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import narration_service
import project_config_runtime as runtime
import storyboard_service


def _snapshot(tmp_path: Path, payload: dict) -> SimpleNamespace:
    planning = tmp_path / "planning"
    planning.mkdir()
    (planning / "project_config.json").write_text(
        json.dumps({"payload": {"schema_version": "creation_config_v1", **payload}}),
        encoding="utf-8",
    )
    return SimpleNamespace(id="project-config-test", run_dir=str(tmp_path))


def _text_connection(connection_id: str, revision: int) -> SimpleNamespace:
    return SimpleNamespace(
        connection_id=connection_id,
        revision=revision,
        kind="text",
        provider="openai_compatible",
        model="project-text-model",
        endpoint="https://project.example.test/v1",
        credential_ref="credential://project/text",
        public_config={"temperature": 0.1, "max_tokens": 4096},
    )


def test_safe_snapshot_read_and_legacy_fallback(tmp_path: Path) -> None:
    legacy = SimpleNamespace(run_dir=str(tmp_path))
    assert runtime.load_project_config(legacy) is None
    assert runtime.get_config_value(legacy, "prompts.article_generation") is None

    project = _snapshot(
        tmp_path,
        {"prompts": {"article_generation": {"system_content": "项目 Prompt"}}},
    )
    assert runtime.get_config_value(
        project, "prompts.article_generation.system_content"
    ) == "项目 Prompt"
    value = runtime.get_config_value(project, "prompts.article_generation")
    value["system_content"] = "不应改变文件"
    assert runtime.get_config_value(
        project, "prompts.article_generation.system_content"
    ) == "项目 Prompt"


def test_storyboard_snapshot_prompt_and_model_override(tmp_path: Path, monkeypatch) -> None:
    project = _snapshot(
        tmp_path,
        {
            "prompts": {
                "storyboard": {
                    "system_content": "PROJECT STORYBOARD PROMPT",
                    "output_example": "{\"slides\": []}",
                },
                "visualization": {"system_content": "PROJECT VISUAL PROMPT"},
            },
            "model_bindings": {
                "storyboard": {"connection_id": "story-model", "revision": 2}
            },
        },
    )
    monkeypatch.setattr(
        storyboard_service,
        "read_step2_prompts",
        lambda _project: {
            "script_system": "legacy script",
            "script_output_example": "legacy example",
            "visual_system": "legacy visual",
            "visual_output_example": "legacy visual example",
        },
    )
    monkeypatch.setattr(
        storyboard_service,
        "_DEPENDENCIES",
        SimpleNamespace(
            resolve_model_connection=_text_connection,
            get_credential=lambda _reference: {"api_key": "story-secret"},
        ),
    )
    monkeypatch.setattr(
        storyboard_service,
        "parse_int_setting",
        lambda value, *_args: int(value),
    )

    prompts = storyboard_service.read_project_step2_prompts(project)
    llm = storyboard_service.configured_project_step2_llm(project, "visualization")

    assert prompts["script_system"] == "PROJECT STORYBOARD PROMPT"
    assert prompts["script_output_example"] == '{"slides": []}'
    assert prompts["visual_system"] == "PROJECT VISUAL PROMPT"
    assert llm == (
        "story-secret",
        "https://project.example.test/v1",
        "project-text-model",
        0.1,
        4096,
    )
    assert "story-secret" not in repr(
        runtime.resolve_project_model_binding(
            project,
            "storyboard",
            expected_kind="text",
            resolve_model_connection=_text_connection,
            get_credential=lambda _reference: {"api_key": "story-secret"},
        )
    )


def test_narration_snapshot_prompt_and_model_override(tmp_path: Path, monkeypatch) -> None:
    project = _snapshot(
        tmp_path,
        {
            "prompts": {
                "narration_annotation": {
                    "system_content": "PROJECT NARRATION PROMPT",
                    "output_example": "{\"slides\": []}",
                }
            },
            "model_bindings": {
                "narration_annotation": {
                    "connection_id": "narration-model",
                    "revision": 1,
                }
            },
        },
    )
    monkeypatch.setattr(narration_service, "resolve_model_connection", _text_connection)
    monkeypatch.setattr(
        narration_service,
        "get_credential",
        lambda _reference: {"api_key": "narration-secret"},
    )
    monkeypatch.setattr(
        narration_service,
        "parse_int_setting",
        lambda value, *_args: int(value),
    )
    monkeypatch.setattr(
        narration_service,
        "get_setting",
        lambda key, default=None: {"llm_model": "legacy"}.get(key, default),
    )

    prompts = narration_service.read_narration_annotation_prompts(project)
    llm = narration_service.configured_narration_annotation_llm(project)

    assert prompts == ("PROJECT NARRATION PROMPT", '{"slides": []}')
    assert llm == (
        "narration-secret",
        "https://project.example.test/v1",
        "project-text-model",
        4096,
    )
