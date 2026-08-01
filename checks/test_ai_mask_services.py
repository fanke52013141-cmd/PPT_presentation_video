from contextlib import nullcontext
import logging
from pathlib import Path
from types import SimpleNamespace

import ai_mask_config
import ai_mask_engine
import ai_mask_service


def test_config_service_reads_migrates_and_saves(monkeypatch) -> None:
    stored = {
        ai_mask_engine.PROMPT_METHOD_KEY: ai_mask_engine.LEGACY_STORED_METHODOLOGY_V2,
        ai_mask_engine.PROMPT_OUTPUT_KEY: ai_mask_engine.LEGACY_DEFAULT_OUTPUT_STRUCTURE_V2,
        "ai_mask_white_threshold": "241",
    }
    updates = {}
    monkeypatch.setattr(
        ai_mask_config,
        "get_setting",
        lambda key, default="": stored.get(key, default),
    )
    monkeypatch.setattr(
        ai_mask_config,
        "update_settings",
        lambda values: updates.update(values),
    )

    methodology, output_structure = ai_mask_config.read_ai_mask_prompts()
    assert "ai_mask_semantic_mapping_v3" in methodology
    assert "系统会按 object 自动展开" in output_structure
    assert ai_mask_config.get_ai_mask_settings()["white_threshold"] == 241

    saved = ai_mask_config.save_ai_mask_settings(
        {
            "settings": {"white_threshold": 233},
            "prompts": {
                "methodology": "custom methodology",
                "output_structure": "custom output",
            },
        }
    )
    assert saved["white_threshold"] == 233
    assert updates["ai_mask_white_threshold"] == 233
    assert updates[ai_mask_engine.PROMPT_METHOD_KEY] == "custom methodology"
    assert updates[ai_mask_engine.PROMPT_OUTPUT_KEY] == "custom output"


def test_task_service_uses_narrow_dependencies(monkeypatch) -> None:
    captured = {}
    logs = []
    dependencies = ai_mask_service.AiMaskDependencies(
        get_setting=lambda *_args, **_kwargs: "",
        get_openai_client=lambda **_kwargs: None,
        reveal_lock_for=lambda _project: nullcontext(),
        write_project_log=lambda project, event, **fields: logs.append(
            (project.id, event, fields)
        ),
        read_style_tokens_data=lambda: {},
        step2_llm_vendor_options=lambda *_args: {},
        clean_json_markdown=lambda value: value,
        is_timeout_exception=lambda _exc: False,
        vision_matcher=lambda *_args, **_kwargs: None,
        logger=logging.getLogger("ai-mask-service-test"),
    )
    monkeypatch.setattr(
        ai_mask_service,
        "get_ai_mask_settings",
        lambda: ai_mask_engine.normalize_settings({}),
    )
    monkeypatch.setattr(
        ai_mask_service,
        "read_ai_mask_prompts",
        lambda: ("methodology", "output"),
    )

    def annotate(
        capabilities,
        project,
        settings,
        methodology,
        output_structure,
        vision_matcher,
    ):
        captured.update(
            capabilities=capabilities,
            project=project,
            settings=settings,
            methodology=methodology,
            output_structure=output_structure,
            vision_matcher=vision_matcher,
        )
        return {"success": True, "processed_slide_count": 1}

    monkeypatch.setattr(ai_mask_engine, "_annotate_project", annotate)
    project = SimpleNamespace(id="project-1", run_dir="unused")

    result = ai_mask_service.AiMaskTaskService(dependencies).annotate_project(
        project,
        {"white_threshold": 230},
    )

    assert result["success"] is True
    assert captured["project"] is project
    assert captured["settings"]["white_threshold"] == 230
    assert captured["methodology"] == "methodology"
    assert captured["output_structure"] == "output"
    assert captured["vision_matcher"] is dependencies.vision_matcher
    assert isinstance(
        captured["capabilities"],
        ai_mask_engine.AiMaskEngineDependencies,
    )
    assert not hasattr(captured["capabilities"], "app")
    assert not hasattr(captured["capabilities"], "Project")
    assert logs[0][1] == "ai_mask_annotation"


def test_runtime_registration_module_is_gone() -> None:
    root = Path(__file__).resolve().parents[1]
    assert not (root / "runtime_ai_mask.py").exists()
    assert not (root / "runtime_ai_mask_semantic_patch.py").exists()
    assert not hasattr(ai_mask_engine, "_register")
    assert not hasattr(ai_mask_engine, "_vision_match")
    assert not hasattr(ai_mask_engine, "annotate_project")
    assert not hasattr(ai_mask_engine, "_get_store_settings")
    server_source = (root / "server.py").read_text(encoding="utf-8")
    pipeline_source = (root / "pipeline_services.py").read_text(encoding="utf-8")
    profile_source = (root / "project_profile_store.py").read_text(
        encoding="utf-8"
    )
    assert "app.include_router(ai_mask_router)" in server_source
    assert "runtime_ai_mask" not in server_source
    assert "semantic_vision_matcher" in server_source
    assert "get_ai_mask_task_service" in pipeline_source
    assert "runtime_ai_mask" not in pipeline_source
    assert "import ai_mask_semantic_matcher" not in profile_source
    assert "ai_mask_semantic_matcher" not in profile_source
    for filename in (
        "ai_mask_engine.py",
        "ai_mask_semantic_matcher.py",
        "ai_mask_service.py",
    ):
        source = (root / filename).read_text(encoding="utf-8")
        assert "server_module" not in source
        assert "import server" not in source
