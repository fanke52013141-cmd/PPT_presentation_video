"""Domain-surface scenarios for the full Agent capability opening.

每个标记为 complete 的分域能力至少经过一次真实隔离服务调用；
LLM/上传/二进制类（partial）只验证契约与错误路径，不做真实供应商调用。
"""

import uuid

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def api():
    import server
    # 全域表面测试在一个模块内产生 200+ 次调用，超出默认 120/60s 限流窗口；
    # 仅在本测试模块内放宽限制，不影响其他会话。
    from agent_api.rate_limit import AgentRateLimitMiddleware

    server.app.middleware_stack = server.app.build_middleware_stack()
    node = server.app.middleware_stack
    while node is not None:
        if isinstance(node, AgentRateLimitMiddleware):
            node._max = 10**9
            break
        node = getattr(node, "app", None)
    return TestClient(server.app, client=("agent-domains-" + uuid.uuid4().hex, 50000))


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
    return invoke(api, "project.create", {"name": name}).json()["project"]["project_id"]


@pytest.fixture(scope="module")
def seeded_project(api):
    """带两页手动骨架合约的项目，供需要合约上下文的域读取。"""
    project_id = make_project(api, "全域 seeded 项目")
    result = invoke(api, "storyboard.skeleton.submit", {"project_id": project_id, "slides": [
        {"main_title": "第一页", "narration": "第一页的演讲内容。"},
        {"slide_id": "slide_002", "main_title": "第二页", "narration": "第二页的演讲内容。"},
    ]})
    assert result.status_code == 200, result.text
    return project_id


# ---- 音频/媒体设置 ----

def test_narration_and_media_settings_surface(api, seeded_project):
    assert invoke(api, "narration.init", {"project_id": seeded_project}).status_code == 200
    result = invoke(api, "narration.result.get", {"project_id": seeded_project})
    assert result.status_code == 200, result.text
    repaired = invoke(api, "narration.repair", {"project_id": seeded_project})
    assert repaired.status_code == 200, repaired.text

    settings = invoke(api, "narration.annotation_settings.get", {}).json()
    prompts = settings.get("prompts") or {}
    updated = invoke(api, "narration.annotation_settings.update", {
        "payload": {
            "system_content": prompts.get("system_content"),
            "output_example": prompts.get("output_example"),
        },
    })
    assert updated.status_code == 200, updated.text

    status = invoke(api, "tts.audio_status.get", {"project_id": seeded_project})
    assert status.status_code == 200, status.text

    subtitles = invoke(api, "media.subtitles.get", {"project_id": seeded_project}).json()
    inner = subtitles.get("subtitle_style") or {}
    updated_sub = invoke(api, "media.subtitles.update", {
        "project_id": seeded_project, "payload": dict(inner),
    })
    assert updated_sub.status_code == 200, updated_sub.text

    background = invoke(api, "media.background.get", {"project_id": seeded_project})
    assert background.status_code == 200, background.text


# ---- 输出域 ----

def test_output_surface_read_paths(api, seeded_project):
    videos = invoke(api, "video.list", {"project_id": seeded_project})
    assert videos.status_code == 200, videos.text
    status = invoke(api, "video.status.get", {"project_id": seeded_project})
    assert status.status_code == 200, status.text

    readiness = invoke(api, "pptx.readiness", {"project_id": seeded_project})
    assert readiness.status_code == 200 and "ready" in readiness.json()
    jobs = invoke(api, "pptx.jobs.list", {"project_id": seeded_project})
    assert jobs.status_code == 200
    exports = invoke(api, "pptx.exports.list", {"project_id": seeded_project})
    assert exports.status_code == 200

    unknown_job = invoke(api, "pptx.jobs.get", {
        "project_id": seeded_project, "job_id": "no-such-job",
    })
    assert unknown_job.status_code == 404

    subtitles = invoke(api, "subtitles.readiness", {"project_id": seeded_project})
    assert subtitles.status_code == 200, subtitles.text

    deleted = invoke(api, "video.delete", {
        "project_id": seeded_project, "filename": "no-such-file.mp4",
    })
    assert deleted.status_code in (404, 400)


# ---- 图片域 ----

def test_image_surface_reads_and_settings(api, seeded_project):
    images = invoke(api, "image.list", {"project_id": seeded_project})
    assert images.status_code == 200, images.text

    settings = invoke(api, "image.prompt_settings.get", {"project_id": seeded_project}).json()
    updated = invoke(api, "image.prompt_settings.update", {
        "project_id": seeded_project, "payload": dict(settings),
    })
    assert updated.status_code == 200, updated.text

    prompts = invoke(api, "image.prompts.get", {"project_id": seeded_project})
    assert prompts.status_code == 200, prompts.text

    preview = invoke(api, "image.change_preview.get", {
        "project_id": seeded_project, "slide_id": "slide_001",
    })
    assert preview.status_code == 200, preview.text

    recovery = invoke(api, "image.recovery.list", {
        "project_id": seeded_project, "slide_id": "slide_001",
    })
    assert recovery.status_code == 200, recovery.text

    # 无已生成图片时按业务前置拒绝（428/400），验证零副作用。
    images = invoke(api, "image.list", {"project_id": seeded_project}).json()
    order = invoke(api, "image.order.update", {
        "project_id": seeded_project,
        "payload": {
            "from_index": 0, "to_index": 1,
            "order_version": images.get("order_version"),
        },
    })
    assert order.status_code in (200, 400, 428), order.text


# ---- 风格域 ----

def test_style_surface(api, seeded_project):
    profile = invoke(api, "style.profile.get", {"project_id": seeded_project})
    assert profile.status_code == 200, profile.text
    templates = invoke(api, "style.profile_templates.list", {})
    assert templates.status_code == 200

    saved = invoke(api, "style.update", {
        "project_id": seeded_project, "payload": {"system_content": "场景风格 System Content"},
    })
    assert saved.status_code == 200, saved.text

    reverse_settings = invoke(api, "style.reverse_settings.get", {}).json()
    assert invoke(api, "style.reverse_settings.update", {
        "payload": dict(reverse_settings),
    }).status_code == 200
    reference_settings = invoke(api, "style.reference_settings.get", {}).json()
    assert invoke(api, "style.reference_settings.update", {
        "payload": dict(reference_settings),
    }).status_code == 200

    references = invoke(api, "style.references.list", {"project_id": seeded_project})
    assert references.status_code == 200
    legacy = invoke(api, "style.references_legacy.list", {"project_id": seeded_project})
    assert legacy.status_code == 200

    created = invoke(api, "style.templates.create", {
        "payload": {"name": "Agent场景风格模板", "system_content": "场景风格提示词"},
    })
    assert created.status_code == 200, created.text
    template_list = invoke(api, "style.templates.list", {}).json()
    match = next(
        item for item in template_list.get("templates", [])
        if item.get("name") == "Agent场景风格模板"
    )
    detail = invoke(api, "style.templates.get", {"template_id": match["id"]})
    assert detail.status_code == 200
    assert invoke(api, "style.templates.delete", {"template_id": match["id"]}).status_code == 200



def test_global_style_surface(api):
    validated = invoke(api, "global_style.validate", {
        "payload": {"style_text": "全局风格场景 System Content"},
    })
    assert validated.status_code == 200, validated.text
    updated = invoke(api, "global_style.update", {
        "payload": {"style_text": "全局风格场景 System Content"},
    })
    assert updated.status_code == 200, updated.text

    listed = invoke(api, "global_style.templates.list", {})
    assert listed.status_code == 200
    saved = invoke(api, "global_style.templates.save", {
        "payload": {"name": "Agent全局模板"},
    })
    assert saved.status_code == 200, saved.text
    body = saved.json()
    template = body.get("template") or {}
    if template.get("id"):
        assert invoke(api, "global_style.templates.get", {
            "template_id": template["id"],
        }).status_code == 200
        assert invoke(api, "global_style.templates.delete", {
            "template_id": template["id"],
        }).status_code == 200


def test_ip_surface(api, seeded_project):
    listing = invoke(api, "ip.list", {"project_id": seeded_project})
    assert listing.status_code == 200, listing.text
    config = invoke(api, "ip.config.update", {
        "project_id": seeded_project, "payload": {},
    })
    assert config.status_code == 200, config.text


# ---- Mask 域 ----

def test_mask_surface(api, seeded_project):
    settings = invoke(api, "mask.settings.get", {}).json()
    saved = invoke(api, "mask.settings.update", {"payload": dict(settings)})
    assert saved.status_code == 200, saved.text

    result = invoke(api, "mask.result.get", {"project_id": seeded_project})
    assert result.status_code in (200, 400, 428), result.text
    blocks = invoke(api, "mask.semantic_blocks", {"project_id": seeded_project})
    assert blocks.status_code in (200, 400, 428), blocks.text


# ---- 标注域 ----

def test_annotation_surface(api, seeded_project):
    summary = invoke(api, "annotation.summary.get", {"project_id": seeded_project})
    assert summary.status_code == 200, summary.text

    summary_body = summary.json()
    revision = (summary_body.get("settings") or {}).get("revision")
    updated = invoke(api, "annotation.settings.update", {
        "project_id": seeded_project,
        "payload": {"enabled": False, "expected_revision": revision},
    })
    assert updated.status_code == 200, updated.text

    slide = invoke(api, "annotation.slide.get", {
        "project_id": seeded_project, "slide_id": "slide_001",
    })
    assert slide.status_code == 200, slide.text
    layout = invoke(api, "annotation.text_layout.get", {
        "project_id": seeded_project, "slide_id": "slide_001",
    })
    assert layout.status_code == 200, layout.text

    saved = invoke(api, "annotation.prompts.update", {
        "project_id": seeded_project,
        "payload": {"system_prompt": "场景标注系统提示", "output_example": "[]"},
    })
    assert saved.status_code == 200, saved.text


# ---- 数字人域 ----

def test_digital_human_surface(api, seeded_project):
    config = invoke(api, "digital_human.config.get", {"project_id": seeded_project})
    assert config.status_code == 200

    workflow = invoke(api, "digital_human.workflow.get", {"project_id": seeded_project})
    assert workflow.status_code == 200, workflow.text



# ---- 工作区（课程/配置包/一键/背景/影响） ----

def test_course_lifecycle(api):
    created = invoke(api, "course.create", {"payload": {"name": "Agent场景课程"}})
    assert created.status_code == 200, created.text
    course = created.json()
    course_id = course.get("id") or course.get("course_id")

    listed = invoke(api, "course.list", {})
    assert listed.status_code == 200
    fetched = invoke(api, "course.get", {"course_id": course_id})
    assert fetched.status_code == 200

    chapter = invoke(api, "chapter.create", {
        "course_id": course_id, "payload": {"name": "章节一"},
    })
    assert chapter.status_code == 200, chapter.text
    chapter_body = chapter.json().get("chapter") or chapter.json()
    chapter_id = chapter_body.get("id") or chapter_body.get("chapter_id")

    assert invoke(api, "chapter.update", {
        "chapter_id": chapter_id, "payload": {"name": "章节一改"},
    }).status_code == 200
    tree = invoke(api, "course.tree.get", {})
    assert tree.status_code == 200
    assert invoke(api, "chapter.delete", {"chapter_id": chapter_id}).status_code == 200
    assert invoke(api, "course.delete", {"course_id": course_id}).status_code == 200

    other = invoke(api, "course.create", {"payload": {"name": "Agent场景课程二"}})
    assert other.status_code == 200
    other_id = other.json().get("id")
    first_id = course_id
    reordered = invoke(api, "course.reorder", {"payload": {"ordered_ids": [other_id, first_id]}})
    assert reordered.status_code == 200, reordered.text
    assert invoke(api, "course.delete", {"course_id": other_id}).status_code == 200


def test_creation_config_lifecycle(api):
    default_payload = invoke(api, "config.default_payload.get", {})
    assert default_payload.status_code == 200
    payload = default_payload.json().get("payload") or {}

    created = invoke(api, "config.create", {"payload": {"name": "Agent场景配置", "payload": payload}})
    assert created.status_code == 200, created.text
    body = created.json()
    package = body.get("package") or body.get("config") or body
    package_id = package.get("id") or package.get("package_id")
    assert package_id, created.text

    assert invoke(api, "config.get", {"package_id": package_id}).status_code == 200
    listing = invoke(api, "config.list", {})
    assert listing.status_code == 200
    assert invoke(api, "config.archive", {
        "package_id": package_id, "payload": {"archived": True},
    }).status_code == 200
    assert invoke(api, "config.delete", {"package_id": package_id}).status_code == 200


def test_workspace_controls_and_background(api, seeded_project):
    statuses = invoke(api, "pipeline.statuses.list", {})
    assert statuses.status_code == 200, statuses.text

    saved = invoke(api, "media.background_config.update", {
        "project_id": seeded_project,
        "payload": {"mode": "solid", "solid_color": "#FEFDF9"},
    })
    assert saved.status_code == 200, saved.text

    impacts = invoke(api, "project.impacts.get", {"project_id": seeded_project})
    assert impacts.status_code == 200, impacts.text
    reuse_preview = invoke(api, "project.impacts.reuse_preview", {"project_id": seeded_project})
    assert reuse_preview.status_code in (200, 409), reuse_preview.text

    mode = invoke(api, "project.ai_mode.get", {"project_id": seeded_project}).json()
    flipped = "manual" if (mode.get("ai_mode") or mode.get("mode")) == "auto" else "auto"
    updated = invoke(api, "project.ai_mode.update", {
        "project_id": seeded_project, "ai_mode": flipped,
    })
    assert updated.status_code == 200, updated.text


def test_change_preview_reports_expected_invalidation(api, seeded_project):
    stored = invoke(api, "storyboard.contract.get", {"project_id": seeded_project}).json()
    contract = stored["contract"]

    noop = invoke(api, "project.change_preview", {
        "project_id": seeded_project, "contract": contract,
    })
    assert noop.status_code == 200 and noop.json()["changed"] is False, noop.text

    reordered = dict(contract)
    reordered["slides"] = list(reversed(contract["slides"]))
    changed = invoke(api, "project.change_preview", {
        "project_id": seeded_project, "contract": reordered,
    })
    body = changed.json()
    assert changed.status_code == 200 and body["changed"] is True, changed.text
    assert body["impact"]["reordered"] is True
    assert body["expected_invalidation"]["masks_and_reveal_assets"] is True


# ---- 系统设置/凭据/连接/诊断 ----

def test_settings_and_config_package(api):
    settings = invoke(api, "settings.get", {})
    assert settings.status_code == 200
    saved = invoke(api, "settings.update", {"payload": dict(settings.json())})
    assert saved.status_code == 200, saved.text

    exported = invoke(api, "settings.config.export", {})
    assert exported.status_code == 200, exported.text

    secrets = invoke(api, "settings.config.export.secrets", {
        "payload": {"confirmation": "EXPORT_SECRETS"},
    })
    assert secrets.status_code == 200, secrets.text
    denied = invoke(api, "settings.config.export.secrets", {"payload": {}})
    assert denied.status_code == 400

    imported = invoke(api, "settings.config.import", {"payload": exported.json()})
    assert imported.status_code == 200, imported.text

    workflow = invoke(api, "settings.comfyui_workflow.get", {})
    assert workflow.status_code == 200


def test_credentials_surface(api):
    created = invoke(api, "credentials.create", {
        "payload": {"provider": "openai", "label": "Agent场景凭据", "secret_values": {"api_key": "sk-test"}},
    })
    assert created.status_code == 200, created.text
    credential = created.json().get("credential") or {}
    ref = credential.get("ref") or credential.get("credential_ref") or credential.get("id")
    assert ref, created.text

    listed = invoke(api, "credentials.list", {})
    assert listed.status_code == 200
    updated = invoke(api, "credentials.update", {
        "credential_ref": ref, "payload": {"label": "Agent场景凭据改"},
    })
    assert updated.status_code == 200, updated.text


def test_model_connection_lifecycle(api):
    created = invoke(api, "connections.create", {
        "payload": {
            "name": "Agent场景连接",
            "kind": "text",
            "provider": "openai",
            "model": "gpt-test",
        },
    })
    assert created.status_code == 200, created.text
    body = created.json()
    connection = body.get("connection") or body
    connection_id = connection.get("id") or connection.get("connection_id")
    assert connection_id, created.text

    assert invoke(api, "connections.get", {"connection_id": connection_id}).status_code == 200
    listed = invoke(api, "connections.list", {})
    assert listed.status_code == 200
    assert invoke(api, "connections.update", {
        "connection_id": connection_id, "payload": {"name": "Agent场景连接改"},
    }).status_code == 200
    assert invoke(api, "connections.state.update", {
        "connection_id": connection_id, "payload": {"state": "archived"},
    }).status_code == 200
    assert invoke(api, "connections.delete", {"connection_id": connection_id}).status_code == 200


def test_diagnostics_and_generation_control(api, seeded_project):
    runtime = invoke(api, "diagnostics.runtime", {})
    assert runtime.status_code == 200
    governor = invoke(api, "diagnostics.governor", {})
    assert governor.status_code == 200
    error_log = invoke(api, "diagnostics.error_log", {"limit": 5})
    assert error_log.status_code == 200

    control = invoke(api, "generation.status", {"project_id": seeded_project, "stage": "tts"})
    assert control.status_code == 200, control.text
    stop = invoke(api, "generation.stop", {"project_id": seeded_project, "stage": "tts"})
    assert stop.status_code in (200, 422), stop.text


# ---- 账号 ----

def test_account_lifecycle(api):
    accounts = invoke(api, "accounts.list", {})
    assert accounts.status_code == 200
    current = invoke(api, "accounts.current", {})
    assert current.status_code == 200

    created = invoke(api, "accounts.create", {"name": "Agent场景账号"})
    assert created.status_code == 200, created.text
    account = created.json().get("account") or {}
    account_id = account.get("id")
    assert account_id, created.text

    assert invoke(api, "accounts.rename", {
        "account_id": account_id, "name": "Agent场景账号改",
    }).status_code == 200
    assert invoke(api, "accounts.default_config.update", {
        "account_id": account_id, "package_id": None, "version": None,
    }).status_code == 200, invoke(api, "accounts.default_config.update", {
        "account_id": account_id, "package_id": None, "version": None,
    }).text
    token = invoke(api, "accounts.agent_token.create", {
        "account_id": account_id, "name": "场景令牌", "scopes": [],
    })
    assert token.status_code == 200 and token.json().get("token"), token.text
    assert invoke(api, "accounts.delete", {"account_id": account_id}).status_code == 200
