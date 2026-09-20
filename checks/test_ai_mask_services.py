from contextlib import nullcontext
import logging
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

import ai_mask_config
import ai_mask_doclayout
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
    assert "ai_mask_semantic_mapping_v4" in methodology
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
        slide_ids,
    ):
        captured.update(
            capabilities=capabilities,
            project=project,
            settings=settings,
            methodology=methodology,
            output_structure=output_structure,
            vision_matcher=vision_matcher,
            slide_ids=slide_ids,
        )
        return {"success": True, "processed_slide_count": 1}

    monkeypatch.setattr(ai_mask_engine, "_annotate_project", annotate)
    project = SimpleNamespace(id="project-1", run_dir="unused")

    result = ai_mask_service.AiMaskTaskService(dependencies).annotate_project(
        project,
        {"white_threshold": 230},
        ["slide_002"],
    )

    assert result["success"] is True
    assert captured["project"] is project
    assert captured["settings"]["white_threshold"] == 230
    assert captured["methodology"] == "methodology"
    assert captured["output_structure"] == "output"
    assert captured["vision_matcher"] is dependencies.vision_matcher
    assert captured["slide_ids"] == ["slide_002"]
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
        "ai_mask_assignment.py",
        "ai_mask_component_detection.py",
        "ai_mask_contracts.py",
        "ai_mask_engine.py",
        "ai_mask_manifest_apply.py",
        "ai_mask_semantic_matcher.py",
        "ai_mask_service.py",
    ):
        source = (root / filename).read_text(encoding="utf-8")
        assert "server_module" not in source
        assert "import server" not in source

    component_source = (root / "ai_mask_component_detection.py").read_text(
        encoding="utf-8"
    )
    engine_source = (root / "ai_mask_engine.py").read_text(encoding="utf-8")
    for owner in (
        "detect_elements",
        "_projection_split",
        "_morph_dilate",
        "_merge_row_runs",
    ):
        assert f"def {owner}(" in component_source
        assert f"def {owner}(" not in engine_source
    assert "from ai_mask_component_detection import (" in engine_source

    manifest_source = (root / "ai_mask_manifest_apply.py").read_text(
        encoding="utf-8"
    )
    for owner in (
        "_exact_manual_mask",
        "_replaceable_ai_mask",
        "_review_issues",
        "_apply",
    ):
        assert f"def {owner}(" in manifest_source
        assert f"def {owner}(" not in engine_source
    assert "from ai_mask_manifest_apply import (" in engine_source

    assignment_source = (root / "ai_mask_assignment.py").read_text(
        encoding="utf-8"
    )
    for owner in (
        "_fallback_match",
        "_clean_match",
        "_rebind_shared_containers",
        "_consolidate_title_regions",
        "_ensure_narrated_group_anchors",
        "_complete_component_coverage",
    ):
        assert f"def {owner}(" in assignment_source
        assert f"def {owner}(" not in engine_source
    assert "from ai_mask_assignment import (" in engine_source


def test_degraded_stages_become_their_own_log_events(monkeypatch) -> None:
    logs = []
    dependencies = ai_mask_service.AiMaskDependencies(
        get_setting=lambda *_args, **_kwargs: "",
        get_openai_client=lambda **_kwargs: None,
        reveal_lock_for=lambda _project: nullcontext(),
        write_project_log=lambda project, event, **fields: logs.append((event, fields)),
        read_style_tokens_data=lambda: {},
        step2_llm_vendor_options=lambda *_args: {},
        clean_json_markdown=lambda value: value,
        is_timeout_exception=lambda _exc: False,
        vision_matcher=lambda *_args, **_kwargs: None,
        logger=logging.getLogger("ai-mask-degradation-test"),
    )
    monkeypatch.setattr(
        ai_mask_service, "get_ai_mask_settings",
        lambda: ai_mask_engine.normalize_settings({}),
    )
    monkeypatch.setattr(
        ai_mask_service, "read_ai_mask_prompts", lambda: ("m", "o")
    )
    slides = [
        {
            "slide_id": "slide_001",
            "layout_detection": {
                "status": "missing_model", "enabled": True, "box_count": 0,
                "fallback_reason": "模型文件不存在: tools/doclayout/x.onnx",
                "device_mode": "auto",
                "actual_providers": ["CPUExecutionProvider"],
                "device_reason": "cuda_provider_not_installed",
            },
            "vision_status": "deterministic_fallback",
            "vision_error_type": "APITimeoutError",
        },
        {
            "slide_id": "slide_002",
            "layout_detection": {"status": "disabled", "enabled": False, "box_count": 0},
            "vision_status": "ok",
        },
    ]
    monkeypatch.setattr(
        ai_mask_engine, "_annotate_project",
        lambda *_args, **_kwargs: {"success": True, "slides": slides},
    )
    result = ai_mask_service.AiMaskTaskService(dependencies).annotate_project(
        SimpleNamespace(id="p1", run_dir="unused")
    )
    assert result["success"] is True
    events = [entry for entry in logs if entry[0] != "ai_mask_annotation"]
    # Disabling the optional stage on purpose is not a degradation, so only the
    # first slide reports; every cause stays a separate, readable event.
    assert [(name, fields["slide_id"]) for name, fields in events] == [
        ("ai_mask_layout_degraded", "slide_001"),
        ("ai_mask_vision_degraded", "slide_001"),
    ]
    assert events[0][1]["status"] == "missing_model"
    assert "模型文件不存在" in events[0][1]["reason"]
    # The log has to say which device really ran, never just what was requested.
    assert events[0][1]["actual_providers"] == ["CPUExecutionProvider"]
    assert events[0][1]["device_reason"] == "cuda_provider_not_installed"
    assert events[1][1]["reason"] == "APITimeoutError"


def test_detect_layout_states_are_distinguishable(tmp_path) -> None:
    image_path = tmp_path / "visual_draft.png"
    Image.new("RGB", (40, 30), "white").save(image_path)
    capabilities = SimpleNamespace(logger=logging.getLogger("ai-mask-detect-layout-test"))

    disabled = ai_mask_engine.normalize_settings({"doclayout_enabled": False})
    boxes, record = ai_mask_engine._detect_layout(capabilities, disabled, image_path)
    assert boxes is None
    assert record["status"] == "disabled"
    assert record["available"] is False
    assert record["elapsed_ms"] == {"layout_load": 0.0, "layout_infer": 0.0}

    missing_model = ai_mask_engine.normalize_settings(
        {"doclayout_enabled": True, "doclayout_model_path": "Z:/definitely/missing.onnx"}
    )
    boxes, record = ai_mask_engine._detect_layout(capabilities, missing_model, image_path)
    assert boxes is None
    # Which of the two prerequisite states applies depends on this environment;
    # the point is that they are reported as distinct states, never as "no boxes".
    assert record["status"] in {"missing_model", "missing_dependency"}
    assert record["fallback_reason"]

    # A detector that cannot even be imported must degrade, not abort the slide.
    def explode(*_args, **_kwargs):
        raise RuntimeError("onnx build crashed")

    original = ai_mask_doclayout.DocLayoutDetector
    try:
        ai_mask_doclayout.DocLayoutDetector = explode  # type: ignore[assignment,misc]
        boxes, record = ai_mask_engine._detect_layout(capabilities, missing_model, image_path)
    finally:
        ai_mask_doclayout.DocLayoutDetector = original  # type: ignore[misc]
    assert boxes is None
    assert record["status"] == "session_init_failed"
    assert record["error_type"] == "RuntimeError"


def test_engine_selects_requested_contract_slides_in_contract_order() -> None:
    contract = {
        "slides": [
            {"slide_id": "slide_001"},
            {"slide_id": "slide_002"},
            {"slide_id": "slide_003"},
        ]
    }

    selected = ai_mask_engine._select_contract_slides(
        contract,
        ["slide_003", "slide_001", "slide_003"],
    )

    assert [slide["slide_id"] for slide in selected] == ["slide_001", "slide_003"]


def test_engine_rejects_unknown_or_empty_slide_scope() -> None:
    contract = {"slides": [{"slide_id": "slide_001"}]}
    for invalid in (["slide_999"], []):
        try:
            ai_mask_engine._select_contract_slides(contract, invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid AI Mask scope was accepted: {invalid!r}")
