from __future__ import annotations

from pathlib import Path
import sys
import json
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from storyboard_planning import (
    build_step2_visual_repair_user_prompt,
    compose_visual_contract_from_plans,
    normalize_slide_visual_plan,
)
from visual_contract_service import normalize_visual_contract


SCRIPT_PLAN = {
    "title": "测试主题",
    "slides": [{
        "slide_id": "slide_001",
        "slide_title": "三个阶段",
        "narration": "先看三个阶段。它们在这一段说明中同时展示。",
    }],
}


def test_old_visual_plan_defaults_to_sequential_reveal() -> None:
    plan = normalize_slide_visual_plan({
        "slides": [{
            "slide_id": "slide_001",
            "visual_elements": [
                {"element_id": "el_001", "role": "title", "visual_type": "text", "visual_description": "三个阶段", "narration": "先看三个阶段。"},
                {"element_id": "el_002", "role": "body", "visual_type": "picture", "visual_description": "三个独立卡片横向排列", "narration": "它们在这一段说明中同时展示。"},
            ],
        }],
    }, SCRIPT_PLAN)
    assert plan["slides"][0]["visual_elements"][1]["reveal_mode"] == "sequential"


def test_together_intent_is_preserved_in_the_contract_and_manual_normalization() -> None:
    visual_plan = normalize_slide_visual_plan({
        "slides": [{
            "slide_id": "slide_001",
            "visual_elements": [
                {"element_id": "el_001", "role": "title", "visual_type": "text", "visual_description": "三个阶段", "narration": "先看三个阶段。", "reveal_mode": "sequential"},
                {"element_id": "el_002", "role": "body", "visual_type": "picture", "visual_description": "三个独立卡片横向排列", "narration": "它们在这一段说明中同时展示。", "reveal_mode": "together"},
            ],
        }],
    }, SCRIPT_PLAN)
    contract = compose_visual_contract_from_plans(SCRIPT_PLAN, visual_plan, "test", "测试主题")
    assert contract["slides"][0]["visual_groups"][1]["reveal_mode"] == "together"
    old_contract = {"slides": [{"visual_groups": [{"id": "old", "role": "content_body"}]}]}
    assert normalize_visual_contract(old_contract)["slides"][0]["visual_groups"][0]["reveal_mode"] == "sequential"


def test_atomicity_repair_prompt_requires_a_full_plan_and_explicit_intent() -> None:
    prompt = build_step2_visual_repair_user_prompt(
        SCRIPT_PLAN,
        {"slides": []},
        "Visual group slide_001_el_002 in slide_001 describes multiple independent visual islands",
    )
    assert "重新输出全部 slides" in prompt
    assert "reveal_mode 为 together" in prompt


def test_compose_retries_atomicity_failure_once_with_the_repaired_plan(monkeypatch, tmp_path: Path) -> None:
    """The quality gate gets one specific repair attempt before pausing Step 2."""
    import server  # Configure storyboard dependencies as the app does.
    import storyboard_service as service

    del server
    planning = tmp_path / "planning"
    planning.mkdir()
    initial_plan = normalize_slide_visual_plan({
        "slides": [{
            "slide_id": "slide_001",
            "visual_elements": [
                {"element_id": "el_001", "role": "title", "visual_type": "text", "visual_description": "三个阶段", "narration": "先看三个阶段。"},
                {"element_id": "el_002", "role": "body", "visual_type": "picture", "visual_description": "三个独立卡片横向排列", "narration": "它们在这一段说明中同时展示。"},
            ],
        }],
    }, SCRIPT_PLAN)
    repaired_plan = json.loads(json.dumps(initial_plan, ensure_ascii=False))
    repaired_plan["slides"][0]["visual_elements"][1]["reveal_mode"] = "together"
    (planning / "slide_script_plan.json").write_text(json.dumps(SCRIPT_PLAN, ensure_ascii=False), encoding="utf-8")
    (planning / "slide_visual_plan.json").write_text(json.dumps(initial_plan, ensure_ascii=False), encoding="utf-8")

    project = SimpleNamespace(id="project-reveal", run_dir=str(tmp_path), mask_enabled=1)
    validation_results = iter([
        {"valid": False, "stderr": "Visual group slide_001_el_002 in slide_001 describes multiple independent visual islands", "stdout": "", "returncode": 1},
        {"valid": True, "stderr": "", "stdout": "ok", "returncode": 0},
    ])
    repair_calls: list[dict] = []
    monkeypatch.setattr(service, "project_or_404", lambda _db, _id: project)
    monkeypatch.setattr(service, "read_project_article_source", lambda _project: {"title": "测试主题", "summary": ""})
    monkeypatch.setattr(service, "read_project_pipeline_profile", lambda _project: {})
    monkeypatch.setattr(service, "write_project_log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(service, "handle_step_navigation", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(service, "validate_visual_contract_file", lambda *_args, **_kwargs: next(validation_results))

    def fake_repair(_project, _script_plan, **kwargs):
        repair_calls.append(kwargs)
        return {"success": True, "visual_plan": repaired_plan}

    monkeypatch.setattr(service, "_execute_step2_visual_plan", fake_repair)
    result = service.compose_step2_visual_contract("project-reveal", object())

    assert result["success"] is True
    assert len(repair_calls) == 1
    assert "multiple independent visual islands" in repair_calls[0]["repair_validation_error"]
    assert result["contract"]["slides"][0]["visual_groups"][1]["reveal_mode"] == "together"
