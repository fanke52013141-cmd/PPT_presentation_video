"""Visible Step 1-2 domain scenarios through the current-contract bootstrap.

Every case drives the real isolated services (no LLM provider calls);
deterministic planning paths only. Template storage is redirected to a
temporary directory because repository_paths keeps it in the shared data dir.
"""

import uuid

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def api():
    # conftest has selected an isolated database/runs directory before this import.
    import server
    return TestClient(server.app, client=("agent-step12-" + uuid.uuid4().hex, 50000))


@pytest.fixture()
def isolated_template_paths(monkeypatch, tmp_path):
    import storyboard_prompt_templates as prompt_templates
    import storyboard_service as storyboard

    monkeypatch.setattr(
        storyboard, "STORYBOARD_TEMPLATES_PATH", str(tmp_path / "storyboard_templates.json")
    )
    monkeypatch.setattr(
        prompt_templates, "STEP2_PROMPT_TEMPLATES_PATH", str(tmp_path / "step2_prompt_templates.json")
    )
    return tmp_path


def invoke(api, capability_id, arguments, revision=None):
    if revision is None:
        detail = api.get(f"/api/agent/v1/capabilities/{capability_id}")
        assert detail.status_code == 200, detail.text
        revision = detail.json()["contract_revision"]
    return api.post("/api/agent/v1/invoke", json={
        "capability_id": capability_id, "expected_contract_revision": revision,
        "arguments": arguments,
    })


def make_project(api, name):
    project = invoke(api, "project.create", {"name": name}).json()["project"]
    return project["project_id"]


ARTICLE = "# 测试主题\n\n这是第一段正文内容，用于驱动 Step 2 规划场景。\n\n这是第二段正文内容。\n"


SCRIPT_SLIDES = [
    {"slide_id": "slide_001", "slide_title": "开篇", "narration": "大家好，这一页介绍测试主题的背景。"},
    {"slide_id": "slide_002", "slide_title": "结论", "narration": "最后总结测试主题的关键结论。"},
]


def visual_slides_payload():
    return {"slides": [
        {
            "slide_id": "slide_001",
            "visual_elements": [
                {"role": "title", "visual_type": "text", "visual_description": "开篇"},
                {"role": "body", "visual_type": "text", "visual_description": "背景要点"},
            ],
        },
        {
            "slide_id": "slide_002",
            "visual_elements": [
                {"role": "title", "visual_type": "text", "visual_description": "结论"},
                {"role": "body", "visual_type": "text", "visual_description": "结论要点"},
            ],
        },
    ]}


def seed_planned_project(api, name):
    project_id = make_project(api, name)
    assert invoke(api, "source.set", {"project_id": project_id, "content": ARTICLE}).status_code == 200
    assert invoke(api, "storyboard.script.update", {
        "project_id": project_id, "slides": SCRIPT_SLIDES,
    }).status_code == 200
    return project_id


# ---- Step 1 article ----

def test_article_settings_roundtrip(api):
    original = invoke(api, "article.settings.get", {}).json()
    assert original["success"] is True and original["system_content"].strip()

    updated = invoke(api, "article.settings.update", {"system_content": "自定义文章生成 System Content"})
    assert updated.status_code == 200 and updated.json()["system_content"] == "自定义文章生成 System Content"
    # Direct HTTP reads the same stored setting.
    assert api.get("/api/agent/v1/article/settings").json()["system_content"] == "自定义文章生成 System Content"
    assert invoke(api, "article.settings.update", {"system_content": original["system_content"]}).status_code == 200


def test_article_source_update_and_read(api):
    project_id = make_project(api, "文章结果场景")

    before = invoke(api, "article.result.get", {"project_id": project_id}).json()
    assert before["success"] is False and before["message"]

    assert invoke(api, "source.set", {"project_id": project_id, "content": ARTICLE}).status_code == 200
    stored = invoke(api, "article.result.get", {"project_id": project_id}).json()
    assert stored["success"] is True and "第一段正文" in stored["brief"]["content"]

    changed = invoke(api, "article.result.update", {
        "project_id": project_id, "content": ARTICLE + "\n追加的一段。",
    })
    assert changed.status_code == 200 and "追加的一段" in changed.json()["brief"]["content"]
    # Identical save is accepted and does not fail.
    noop = invoke(api, "article.result.update", {
        "project_id": project_id, "content": ARTICLE + "\n追加的一段。",
    })
    assert noop.status_code == 200


# ---- Step 2 configuration ----

def test_storyboard_rules_and_prompts_roundtrip(api):
    project_id = make_project(api, "规则提示词场景")

    rules = invoke(api, "storyboard.rules.get", {"project_id": project_id}).json()
    assert rules["success"] is True and rules["rules"].strip() and rules["profile_yaml"].strip()

    updated = invoke(api, "storyboard.rules.update", {
        "project_id": project_id, "rules": "场景自定义规则：保持页面简洁。",
    })
    assert updated.status_code == 200 and "场景自定义规则" in updated.json()["rules"]
    assert "场景自定义规则" in invoke(api, "storyboard.rules.get", {"project_id": project_id}).json()["rules"]

    prompts = invoke(api, "storyboard.prompts.get", {"project_id": project_id}).json()
    assert prompts["success"] is True and "script_system" in prompts["prompts"]
    set_prompts = invoke(api, "storyboard.prompts.update", {
        "project_id": project_id, "script_system": "自定义脚本系统提示词",
    })
    assert set_prompts.status_code == 200
    assert set_prompts.json()["prompts"]["script_system"] == "自定义脚本系统提示词"
    assert set_prompts.json()["prompts"]["visual_system"] == prompts["defaults"]["visual_system"]


def test_preview_composes_article_request(api):
    project_id = make_project(api, "预览合成场景")
    assert invoke(api, "storyboard.preview", {"project_id": project_id}).status_code == 400
    assert invoke(api, "source.set", {"project_id": project_id, "content": ARTICLE}).status_code == 200
    preview = invoke(api, "storyboard.preview", {"project_id": project_id})
    assert preview.status_code == 200
    assert "测试主题" in preview.json()["user_content"]


def test_invoke_and_http_share_storyboard_rules_adapter(api):
    project_id = make_project(api, "通道一致场景")
    body = {"rules": "双通道规则内容。", "profile_yaml": ""}
    via_invoke = invoke(api, "storyboard.rules.update", {"project_id": project_id, **body}).json()
    via_http = api.put(f"/api/agent/v1/projects/{project_id}/storyboard/rules", json=body).json()
    assert via_invoke["rules"] == via_http["rules"] == "双通道规则内容。"


# ---- Step 2 planning ----

def test_script_plan_manual_edit_preserves_identity(api):
    project_id = seed_planned_project(api, "演讲稿编辑场景")

    plan = invoke(api, "storyboard.script.get", {"project_id": project_id}).json()
    assert [slide["slide_id"] for slide in plan["script_plan"]["slides"]] == ["slide_001", "slide_002"]

    edited = [dict(SCRIPT_SLIDES[0], narration="修改后的第一页演讲稿。"), SCRIPT_SLIDES[1]]
    saved = invoke(api, "storyboard.script.update", {"project_id": project_id, "slides": edited})
    assert saved.status_code == 200
    reread = invoke(api, "storyboard.script.get", {"project_id": project_id}).json()
    ids = [slide["slide_id"] for slide in reread["script_plan"]["slides"]]
    assert ids == ["slide_001", "slide_002"], "编辑一页不得影响其他页身份"
    assert reread["script_plan"]["slides"][0]["narration"] == "修改后的第一页演讲稿。"

    cleared = invoke(api, "storyboard.script.update", {"project_id": project_id, "slides": []})
    assert cleared.status_code == 200 and cleared.json()["script_plan"]["slides"] == []


def test_visual_plan_and_contract_lifecycle(api):
    project_id = seed_planned_project(api, "合约生命周期场景")

    saved = invoke(api, "storyboard.visual.update", {"project_id": project_id, **visual_slides_payload()})
    assert saved.status_code == 200, saved.text
    plan = invoke(api, "storyboard.visual.get", {"project_id": project_id}).json()
    assert plan["stale"] is False
    assert [slide["slide_id"] for slide in plan["visual_plan"]["slides"]] == ["slide_001", "slide_002"]
    # Narration fragments are re-bound deterministically from the script plan.
    narrations = "".join(
        element.get("narration", "")
        for slide in plan["visual_plan"]["slides"]
        for element in slide["visual_elements"]
    )
    assert "背景" in narrations and "结论" in narrations

    composed = invoke(api, "storyboard.compose", {"project_id": project_id})
    assert composed.status_code == 200, composed.text
    contract = composed.json()["contract"]
    assert [slide["slide_id"] for slide in contract["slides"]] == ["slide_001", "slide_002"]

    stored = invoke(api, "storyboard.contract.get", {"project_id": project_id}).json()
    assert stored["success"] is True and stored["contract_sha256"]
    baseline_sha = stored["contract_sha256"]

    noop = invoke(api, "storyboard.contract.update", {
        "project_id": project_id,
        "contract": stored["contract"],
        "expected_contract_sha256": baseline_sha,
    })
    assert noop.status_code == 200 and noop.json()["changed"] is False, noop.text

    # 修改一页（重排）：保存有效合约，其他页身份保持正确。
    reordered = dict(stored["contract"])
    reordered["slides"] = list(reversed(stored["contract"]["slides"]))
    changed = invoke(api, "storyboard.contract.update", {
        "project_id": project_id,
        "contract": reordered,
        "expected_contract_sha256": baseline_sha,
    })
    assert changed.status_code == 200, changed.text
    assert changed.json()["changed"] is True
    new_ids = [slide["slide_id"] for slide in changed.json()["contract"]["slides"]]
    assert sorted(new_ids) == ["slide_001", "slide_002"] and new_ids[0] == "slide_002"

    stale = invoke(api, "storyboard.contract.update", {
        "project_id": project_id,
        "contract": reordered,
        "expected_contract_sha256": baseline_sha,
    })
    assert stale.status_code == 409

    repair = invoke(api, "storyboard.contract.repair", {"project_id": project_id})
    assert repair.status_code == 200 and repair.json()["changed"] is False


def test_contract_get_before_compose_reports_missing(api):
    project_id = make_project(api, "空合约场景")
    stored = invoke(api, "storyboard.contract.get", {"project_id": project_id}).json()
    assert stored["success"] is False and "尚未生成" in stored["message"]


def test_manual_skeleton_sets_manual_mode(api):
    project_id = make_project(api, "手动骨架场景")
    result = invoke(api, "storyboard.skeleton.submit", {"project_id": project_id, "slides": [
        {"main_title": "第一页", "narration": "第一页的演讲内容。"},
        {"slide_id": "slide_002", "main_title": "第二页", "narration": "第二页的演讲内容。"},
    ]})
    assert result.status_code == 200, result.text
    assert result.json()["ai_mode"] == "manual"
    slides = result.json()["contract"]["slides"]
    assert [slide["slide_id"] for slide in slides] == ["slide_001", "slide_002"]
    assert slides[0]["narration_beats"][0]["spoken_text"] == "第一页的演讲内容。"
    assert slides[0]["visual_groups"] == []


# ---- template management ----

def test_storyboard_template_management(api, isolated_template_paths):
    saved = invoke(api, "storyboard.templates.save", {
        "name": "Agent场景模板", "rules": "模板规则内容。",
    })
    assert saved.status_code == 200, saved.text
    template = saved.json()["template"]
    assert template["name"] == "Agent场景模板" and template["rules"] == "模板规则内容。"
    listed = invoke(api, "storyboard.templates.list", {}).json()["templates"]
    assert any(item["id"] == template["id"] for item in listed)

    deleted = invoke(api, "storyboard.templates.delete", {"template_id": template["id"]})
    assert deleted.status_code == 200
    again = invoke(api, "storyboard.templates.delete", {"template_id": template["id"]})
    assert again.status_code == 404


def test_step2_prompt_template_management(api, isolated_template_paths):
    saved = invoke(api, "storyboard.prompt_templates.save", {
        "name": "Agent提示词模板", "prompt_type": "script",
        "script_system": "模板系统提示", "script_output_example": "模板输出示例",
    })
    assert saved.status_code == 200, saved.text
    template = saved.json()["template"]
    assert template["prompt_type"] == "script"

    detail = invoke(api, "storyboard.prompt_templates.get", {"template_id": template["id"]})
    assert detail.status_code == 200 and detail.json()["template"]["id"] == template["id"]

    listed = invoke(api, "storyboard.prompt_templates.list", {}).json()["templates"]
    assert any(item["id"] == template["id"] for item in listed)

    assert invoke(api, "storyboard.prompt_templates.delete", {"template_id": template["id"]}).status_code == 200


# ---- contract guardrails ----

def test_storyboard_invoke_rejects_unknown_arguments(api):
    project_id = make_project(api, "参数校验场景")
    detail = api.get("/api/agent/v1/capabilities/storyboard.rules.update").json()
    response = api.post("/api/agent/v1/invoke", json={
        "capability_id": "storyboard.rules.update",
        "expected_contract_revision": detail["contract_revision"],
        "arguments": {"project_id": project_id, "rules": "x", "unexpected_field": True},
    })
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
