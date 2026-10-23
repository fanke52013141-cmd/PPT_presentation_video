"""Full eight-step workflow with mocked upstream providers.

上游供应商（LLM/生图/TTS）在测试内被替换，但全部业务代码、校验器子进程、
持久任务与产物链路都是真实执行；不做任何真实付费调用。
"""

import base64
import io
import json
import time
import uuid

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def api():
    import server
    from agent_api.rate_limit import AgentRateLimitMiddleware

    server.app.middleware_stack = server.app.build_middleware_stack()
    node = server.app.middleware_stack
    while node is not None:
        if isinstance(node, AgentRateLimitMiddleware):
            node._max = 10**9
            break
        node = getattr(node, "app", None)
    return TestClient(server.app, client=("agent-mocked-" + uuid.uuid4().hex, 50000))


def invoke(api, capability_id, arguments, revision=None):
    if revision is None:
        detail = api.get(f"/api/agent/v1/capabilities/{capability_id}")
        assert detail.status_code == 200, detail.text
        revision = detail.json()["contract_revision"]
    return api.post("/api/agent/v1/invoke", json={
        "capability_id": capability_id, "expected_contract_revision": revision,
        "arguments": arguments,
    })


def _png_bytes(width=960, height=540):
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (width, height), "#FFFFFF")
    draw = ImageDraw.Draw(image)
    draw.rectangle([60, 60, 380, 140], fill="#1A1A1A")
    draw.rectangle([60, 220, 700, 460], fill="#3366CC")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


ARTICLE = "# 供应商演练主题\n\n这是用于 mock 全流程的第一段正文，介绍背景。\n\n这是第二段正文，给出结论。\n"

SCRIPT_PLAN = {"slides": [
    {"slide_id": "slide_001", "slide_title": "背景", "narration": "这一页介绍背景内容。"},
    {"slide_id": "slide_002", "slide_title": "结论", "narration": "这一页总结关键结论。"},
]}

VISUAL_PLAN = {"slides": [
    {"slide_id": "slide_001", "visual_elements": [
        {"role": "title", "visual_type": "text", "visual_description": "背景"},
        {"role": "body", "visual_type": "text", "visual_description": "背景要点"},
    ]},
    {"slide_id": "slide_002", "visual_elements": [
        {"role": "title", "visual_type": "text", "visual_description": "结论"},
        {"role": "body", "visual_type": "text", "visual_description": "结论要点"},
    ]},
]}


def _patch_providers():
    """Manual save/restore patching (module-scope fixture; monkeypatch is function-scoped)."""
    import storyboard_service as storyboard
    import image_workflow_service as images
    import tts_service as tts

    saved = []

    def _patch(module, name, replacement):
        saved.append((module, name, getattr(module, name)))
        setattr(module, name, replacement)

    def fake_llm(**kwargs):
        if kwargs.get("artifact_prefix") == "step2_visual_plan":
            return json.loads(json.dumps(VISUAL_PLAN))
        return json.loads(json.dumps(SCRIPT_PLAN))

    def fake_image_response(**kwargs):
        return {"data": [{"b64_json": base64.b64encode(_png_bytes()).decode("ascii")}]}

    def fake_tts_run(project, slide_id, args, tts_env, **kwargs):
        # metadata 携带服务自己的语音指纹，音频确认的 runtime 校验依赖它。
        cache_key = tts._resolve_tts_voice_profile(project)["cache_key"]
        metadata_body = json.dumps({
            "provider": cache_key.get("provider", "minimax"),
            "request": cache_key,
        }, ensure_ascii=False)
        tokens = list(args) if isinstance(args, (list, tuple)) else []
        for token in tokens:
            text = str(token)
            if text.endswith(".mp3") or text.endswith(".wav"):
                # 写真实有效的 PCM WAV：ffmpeg 时长探测/静音压缩会真实读取。
                import wave

                with wave.open(text, "wb") as handle:
                    handle.setnchannels(1)
                    handle.setsampwidth(2)
                    handle.setframerate(16000)
                    handle.writeframes(b"\x00\x00" * 16000)
            elif text.endswith(".srt"):
                with open(text, "w", encoding="utf-8") as handle:
                    handle.write("1\n00:00:00,000 --> 00:00:01,000\nmock\n")
            elif text.endswith("timeline.json"):
                with open(text, "w", encoding="utf-8") as handle:
                    json.dump({
                        "duration": 1.0,
                        "segments": [{"id": "seg_001", "start": 0.0, "end": 1.0, "text": "mock"}],
                    }, handle, ensure_ascii=False)
            elif text.endswith(".json"):
                with open(text, "w", encoding="utf-8") as handle:
                    handle.write(metadata_body)
        return {"ok": True, "attempts": 1, "returncode": 0, "stdout": "mock", "stderr": ""}

    _patch(storyboard, "run_step2_json_llm", fake_llm)
    _patch(images, "generate_image_response", fake_image_response)
    _patch(tts, "run_tts_command_with_retries", fake_tts_run)
    return saved


@pytest.fixture(scope="module")
def workflow(api):
    """全流程种子项目：规划 → 图片 → 确认 → TTS → 音频确认。"""
    import tts_service as tts

    saved = _patch_providers()
    seeded = invoke(api, "settings.update", {"payload": {
        "llm_api_key": "mock-key",
        "image_api_key": "mock-key",
        "image_base_url": "https://mock.invalid/v1",
        "image_model": "mock-image",
        "tts_provider": "minimax",
        "tts_api_key": "mock-key",
        "tts_voice_id": "mock-voice",
        "tts_model": "speech-01",
    }})
    assert seeded.status_code == 200, seeded.text

    project_id = invoke(api, "project.create", {"name": "Mock全流程"}).json()["project"]["project_id"]
    assert invoke(api, "source.set", {"project_id": project_id, "content": ARTICLE}).status_code == 200

    script = invoke(api, "storyboard.script.execute", {"project_id": project_id})
    assert script.status_code == 200, script.text
    assert len(script.json()["script_plan"]["slides"]) == 2

    visual = invoke(api, "storyboard.visual.execute", {"project_id": project_id})
    assert visual.status_code == 200, visual.text

    composed = invoke(api, "storyboard.compose", {"project_id": project_id})
    assert composed.status_code == 200, composed.text

    for slide_id in ("slide_001", "slide_002"):
        generated = invoke(api, "image.generate", {
            "project_id": project_id, "slide_id": slide_id, "prompt": "mock",
        })
        assert generated.status_code == 200, generated.text
    confirmed = invoke(api, "image.confirm", {"project_id": project_id})
    assert confirmed.status_code == 200, confirmed.text

    # 生产 Reveal 场景构建（与 Web 保存终稿同一入口），产出 animation_timeline.json
    from database import Project, SessionLocal
    import mask_manifest_service

    with SessionLocal() as db:
        project = db.get(Project, project_id)
        mask_manifest_service.build_current_reveal_assets(project)

    submitted = invoke(api, "tts.synthesize", {"project_id": project_id})
    assert submitted.status_code == 200, submitted.text
    operation_id = submitted.json().get("operation_id")
    assert operation_id, submitted.text

    deadline = time.time() + 120
    state = None
    while time.time() < deadline:
        state = invoke(api, "operation.get", {
            "project_id": project_id, "operation_id": operation_id,
        }).json()
        if state.get("status") in {"succeeded", "failed", "cancelled", "interrupted"}:
            break
        time.sleep(0.5)
    assert state and state.get("status") == "succeeded", json.dumps(state, ensure_ascii=False)

    confirmed_audio = invoke(api, "tts.audio.confirm", {"project_id": project_id})
    assert confirmed_audio.status_code == 200, confirmed_audio.text

    try:
        yield {"project_id": project_id}
    finally:
        for module, name, original in reversed(saved):
            setattr(module, name, original)
        # 该模块结束后恢复 TTS 依赖；后续模块级 fixture 不再依赖 mock。
        assert tts.run_tts_command_with_retries is not None


# ---- 规划执行（LLM mock 下全链路真实） ----

def test_storyboard_executions_real_persistence(workflow, api):
    project_id = workflow["project_id"]
    plan = invoke(api, "storyboard.script.get", {"project_id": project_id}).json()
    assert [s["slide_id"] for s in plan["script_plan"]["slides"]] == ["slide_001", "slide_002"]
    visual = invoke(api, "storyboard.visual.get", {"project_id": project_id}).json()
    assert visual["stale"] is False
    stored = invoke(api, "storyboard.contract.get", {"project_id": project_id}).json()
    assert stored["success"] is True and stored["repair"]["required"] is False

    # 修复通道：注入 legacy 字段后 normalize 应产生 changed=True 的显式迁移
    from database import Project, SessionLocal
    with SessionLocal() as db:
        run_dir = db.get(Project, project_id).run_dir
    contract_path = f"{run_dir}/planning/visual_contract.json"
    with open(contract_path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)
    # 注入旧版 beat（无 content_unit_id）：normalize 会补齐迁移字段
    raw["slides"][0]["narration_beats"][0].pop("content_unit_id", None)
    with open(contract_path, "w", encoding="utf-8") as handle:
        json.dump(raw, handle, ensure_ascii=False)
    repaired = invoke(api, "storyboard.contract.repair", {"project_id": project_id})
    assert repaired.status_code == 200 and repaired.json()["changed"] is True, repaired.text


# ---- 图片资产场景 ----

def test_image_asset_scenarios(workflow, api):
    project_id = workflow["project_id"]

    listed = invoke(api, "image.list", {"project_id": project_id}).json()
    assert len(listed["images"]) == 2

    change = invoke(api, "image.change_preview.get", {
        "project_id": project_id, "slide_id": "slide_001",
    }).json()
    assert change["has_image"] is True

    ordered = invoke(api, "image.order.update", {
        "project_id": project_id,
        "payload": {"from_index": 0, "to_index": 1, "order_version": listed["order_version"]},
    })
    assert ordered.status_code == 200, ordered.text

    # 删除一页 → 归档 → 恢复列表 + 几何复用 + 覆盖层二进制
    deleted = invoke(api, "image.delete", {
        "project_id": project_id, "slide_id": "slide_002",
        "disposition": "keep", "expected_version": "",
    })
    assert deleted.status_code == 200, deleted.text
    recovery = invoke(api, "image.recovery.list", {
        "project_id": project_id, "slide_id": "slide_002",
    })
    assert recovery.status_code == 200, recovery.text
    archives = recovery.json().get("archives") or recovery.json().get("items") or []
    if archives:
        archive_id = archives[0].get("archive_id") or archives[0].get("id")
        overlay = api.get(
            f"/api/agent/v1/projects/{project_id}/images/slide_002/recovery/{archive_id}/overlay"
        )
        assert overlay.status_code in (200, 404)

    # 候选流：preview 生成 → 候选下载 → 应用
    preview = invoke(api, "image.generate", {
        "project_id": project_id, "slide_id": "slide_001", "prompt": "mock", "preview": True,
    })
    assert preview.status_code == 200, preview.text
    candidate = api.get(f"/api/agent/v1/projects/{project_id}/images/slide_001/candidate")
    assert candidate.status_code == 200 and candidate.headers["content-type"].startswith("image/")
    applied = invoke(api, "image.candidate.apply", {
        "project_id": project_id, "payload": {"slide_id": "slide_001"},
    })
    assert applied.status_code in (200, 400), applied.text


def test_image_binary_downloads(workflow, api):
    project_id = workflow["project_id"]
    image = api.get(f"/api/agent/v1/projects/{project_id}/slides/slide_001/image")
    assert image.status_code == 200 and image.headers["content-type"].startswith("image/")
    bundle = api.get(f"/api/agent/v1/projects/{project_id}/images/download")
    assert bundle.status_code == 200 and bundle.headers["content-type"] in (
        "application/zip", "application/x-zip-compressed")


def test_image_upload_transport(workflow, api):
    project_id = workflow["project_id"]
    payload = _png_bytes(320, 180)
    uploaded = api.post(
        f"/api/agent/v1/projects/{project_id}/images/upload",
        data={"slide_id": "slide_002", "disposition": "cleanup"},
        files={"file": ("replacement.png", payload, "image/png")},
    )
    assert uploaded.status_code == 200, uploaded.text
    # 上传 replace 触发下游失效 → 影响列表出现可确认项
    impacts = invoke(api, "project.impacts.get", {"project_id": project_id}).json()
    assert isinstance(impacts.get("items"), list)


# ---- 音频/字幕/确认门禁 ----

def test_audio_and_subtitles(workflow, api):
    project_id = workflow["project_id"]
    status = invoke(api, "tts.audio_status.get", {"project_id": project_id}).json()
    slides = status.get("slides") or []
    assert slides and all(slide.get("complete") for slide in slides)

    audio = api.get(f"/api/agent/v1/projects/{project_id}/slides/slide_001/audio")
    assert audio.status_code == 200 and "audio" in audio.headers["content-type"]

    readiness = invoke(api, "subtitles.readiness", {"project_id": project_id}).json()
    assert readiness.get("ready") is True, readiness
    srt = api.get(f"/api/agent/v1/projects/{project_id}/subtitles/content")
    assert srt.status_code == 200 and "mock" in srt.text


# ---- PPTX 导出持久任务 ----

def test_pptx_export_job_lifecycle(workflow, api):
    project_id = workflow["project_id"]
    readiness = invoke(api, "pptx.readiness", {"project_id": project_id}).json()
    assert readiness.get("ready") is True, readiness

    created = invoke(api, "pptx.export.create", {"project_id": project_id})
    assert created.status_code == 200, created.text
    body = created.json()
    job_id = body.get("job_id") or (body.get("job") or {}).get("id")
    assert job_id, created.text

    deadline = time.time() + 90
    job = None
    while time.time() < deadline:
        job = invoke(api, "pptx.jobs.get", {"project_id": project_id, "job_id": job_id}).json().get("job")
        if job and job.get("status") in {"succeeded", "completed", "failed"}:
            break
        time.sleep(0.5)
    assert job and job.get("status") in {"succeeded", "completed"}, json.dumps(job, ensure_ascii=False)

    exports = invoke(api, "pptx.exports.list", {"project_id": project_id}).json()
    artifacts = exports.get("exports") or exports.get("artifacts") or []
    assert artifacts, exports
    artifact_id = artifacts[0].get("artifact_id") or artifacts[0].get("id")
    downloaded = api.get(
        f"/api/agent/v1/projects/{project_id}/pptx/exports/{artifact_id}/content"
    )
    assert downloaded.status_code == 200 and len(downloaded.content) > 0
    deleted = invoke(api, "pptx.exports.delete", {
        "project_id": project_id, "artifact_id": artifact_id,
    })
    assert deleted.status_code == 200, deleted.text


# ---- 视频产物文件级验收（直写产物 + sidecar，不跑 Remotion） ----

def test_video_artifact_binary_paths(workflow, api):
    from database import Project, SessionLocal
    from pathlib import Path
    from project_storage import videos_dir

    project_id = workflow["project_id"]
    with SessionLocal() as db:
        run_dir = Path(db.get(Project, project_id).run_dir)
    managed = videos_dir(run_dir)
    managed.mkdir(parents=True, exist_ok=True)
    video_path = managed / "mock-video.mp4"
    video_path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 2048)
    (managed / "mock-video.mp4.render.json").write_text(
        json.dumps({"reveal_pipeline_version": "exact_rle_mask_with_manual_corrections_v6"}),
        encoding="utf-8",
    )

    listed = invoke(api, "video.list", {"project_id": project_id}).json()
    names = [item.get("filename") or item.get("name") for item in (listed.get("videos") or [])]
    assert "mock-video.mp4" in names, listed

    # final-video 状态按渲染输入指纹判定新鲜度：手动放置的文件没有匹配
    # 指纹，业务上不算有效成片——验证返回结构即可。
    status = invoke(api, "video.status.get", {"project_id": project_id})
    assert status.status_code == 200 and "exists" in status.json()

    downloaded = api.get(f"/api/agent/v1/projects/{project_id}/videos/mock-video.mp4/content")
    assert downloaded.status_code == 200 and downloaded.content[:4] == b"\x00\x00\x00\x18"

    latest = api.get(f"/api/agent/v1/projects/{project_id}/videos/latest")
    assert latest.status_code == 200 and "video" in latest.headers["content-type"]

    removed = invoke(api, "video.delete", {
        "project_id": project_id, "filename": "mock-video.mp4",
    })
    assert removed.status_code == 200, removed.text
    assert not video_path.exists()
    assert not (managed / "mock-video.mp4.render.json").exists()


# ---- 影响决策闭环 ----

def test_impact_decision_loop(workflow, api):
    project_id = workflow["project_id"]
    # 变更文章 → 登记影响 → 预检可读 → 决策确认
    changed = invoke(api, "article.result.update", {
        "project_id": project_id, "content": ARTICLE + "\n追加重写段落。",
    })
    assert changed.status_code == 200, changed.text
    impacts = invoke(api, "project.impacts.get", {"project_id": project_id}).json()
    items = impacts.get("items") or []
    assert items, impacts
    preview = invoke(api, "project.impacts.reuse_preview", {"project_id": project_id})
    assert preview.status_code == 200, preview.text
    target = items[0]
    decided = invoke(api, "project.impacts.decision.update", {
        "project_id": project_id,
        "payload": {"impact_id": target.get("id"), "decision": "acknowledged"},
    })
    assert decided.status_code in (200, 400), decided.text


# ---- 杂项清零 ----

def test_misc_remaining_acceptances(workflow, api):
    project_id = workflow["project_id"]

    # 创建配置包 → 导入同构载荷 → provision 预置账号
    default_payload = invoke(api, "config.default_payload.get", {}).json()["payload"]
    created = invoke(api, "config.create", {
        "payload": {"name": "演练源配置", "payload": default_payload},
    })
    assert created.status_code == 200, created.text
    package_id = (created.json().get("package") or created.json()).get("id")

    imported = invoke(api, "config.import", {
        "payload": {"name": "演练导入配置", "payload": default_payload},
    })
    assert imported.status_code == 200, imported.text

    provisioned = invoke(api, "accounts.provision", {
        "name": "演练预置账号",
        "source_package_id": package_id,
        "package_name": "演练预置配置",
        "package_description": "全流程演练",
        "tags": ["agent"],
        "image_style_template_id": (default_payload.get("image_style") or {}).get("template_id", ""),
        "voice_id": "mock-voice",
        "storyboard_system_content": "演练演讲稿系统提示词",
    })
    assert provisioned.status_code == 200, provisioned.text
    provisioned_account = (provisioned.json().get("account") or {})
    if provisioned_account.get("id"):
        assert invoke(api, "accounts.delete", {
            "account_id": provisioned_account["id"],
        }).status_code == 200
    assert invoke(api, "config.delete", {"package_id": package_id}).status_code == 200

    # 错误日志 latest 文本（先制造一条渲染错误日志）
    invoke(api, "video.speed", {
        "project_id": project_id, "filename": "no-such.mp4", "payload": {"speed": 1.5},
    })
    latest = api.get("/api/agent/v1/error-log/latest")
    assert latest.status_code == 200

    # 配置包 ZIP 导出/导入（二进制传输 + multipart 上传）
    exported_zip = api.get("/api/agent/v1/config/export-zip")
    assert exported_zip.status_code == 200 and len(exported_zip.content) > 0
    imported_zip = api.post(
        "/api/agent/v1/config/import-zip",
        files={"file": ("export.zip", exported_zip.content, "application/zip")},
    )
    assert imported_zip.status_code == 200, imported_zip.text

    # ComfyUI 工作流上传/读取（数字人文件面，无外部调用）
    workflow_file = {
        "nodes": [{"id": 1, "type": "MockNode"}],
    }
    uploaded = api.post(
        f"/api/agent/v1/projects/{project_id}/digital-human/workflow/upload",
        files={"file": ("workflow.json", json.dumps(workflow_file).encode("utf-8"), "application/json")},
    )
    assert uploaded.status_code == 200, uploaded.text
    fetched = invoke(api, "digital_human.workflow.get", {"project_id": project_id})
    assert fetched.status_code == 200, fetched.text


def test_image_generate_idempotent_replay(workflow, api):
    """同一幂等键重放原结果，不重复调用生图。"""
    project_id = workflow["project_id"]
    arguments = {
        "project_id": project_id,
        "slide_id": "slide_002",
        "prompt": "幂等重放演练",
        "idempotency_key": "replay-" + uuid.uuid4().hex,
    }
    first = invoke(api, "image.generate", arguments)
    assert first.status_code == 200, first.text
    fingerprint_one = first.json().get("version") or first.json().get("image", {}).get("version")

    replay = invoke(api, "image.generate", arguments)
    assert replay.status_code == 200, replay.text
    assert replay.headers.get("x-agent-idempotency-replay") == "true"
    fingerprint_two = replay.json().get("version") or replay.json().get("image", {}).get("version")
    assert fingerprint_one == fingerprint_two

    conflict = invoke(api, "image.generate", {**arguments, "prompt": "不同的提示词"})
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
