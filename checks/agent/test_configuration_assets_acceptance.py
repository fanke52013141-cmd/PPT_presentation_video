import io
import json
from pathlib import Path
import uuid
import wave

from PIL import Image

from checks.agent.test_full_workflow_mocked import api, invoke, _png_bytes  # noqa: F401


def test_template_creation_with_uploaded_references_applies_to_portrait_project(api):
    created = api.post("/api/agent/v1/style/templates/with-references", data={
        "name": "Uploaded " + uuid.uuid4().hex, "system_content": "白底蓝色线稿，信息分组清楚。",
        "style_summary": "Uploaded reference acceptance",
    }, files=[("files", ("example.png", _png_bytes(180, 320), "image/png"))])
    assert created.status_code == 200, created.text
    tid = created.json()["template"]["id"]
    library = api.get(f"/api/agent/v1/style/templates/{tid}/references/1/content")
    assert library.status_code == 200, library.text
    Image.open(io.BytesIO(library.content)).verify()
    pid = invoke(api, "project.create", {"name": "Portrait template", "canvas_profile": "portrait_9_16"}).json()["project"]["project_id"]
    applied = invoke(api, "style.project_template.apply", {"project_id": pid, "template_id": tid})
    assert applied.status_code == 200, applied.text
    reference = api.get(f"/api/agent/v1/projects/{pid}/style/references/1/content")
    assert reference.status_code == 200 and reference.content == library.content
    assert invoke(api, "style.templates.delete", {"template_id": tid}).status_code == 200
    assert api.get(f"/api/agent/v1/projects/{pid}/style/references/1/content").content == reference.content


def test_comfyui_workflow_rejects_invalid_replacement_and_keeps_saved_bytes(api, monkeypatch, tmp_path):
    import settings_routes

    path = tmp_path / "workflow.json"
    monkeypatch.setattr(settings_routes, "_COMFYUI_TTS_WORKFLOW_PATH", str(path))
    base = "/api/agent/v1/settings/comfyui-tts-workflow"
    workflow = {"1": {"class_type": "TestNode", "inputs": {"text": "reference"}}}
    saved = api.post(base, files={"file": ("workflow.json", json.dumps(workflow).encode(), "application/json")})
    assert saved.status_code == 200 and saved.json()["nodes"] == 1, saved.text
    before = path.read_bytes()
    for content in (b"{broken", b"{}", b'{"nodes": []}'):
        rejected = api.post(base, files={"file": ("invalid.json", content, "application/json")})
        assert rejected.status_code == 400, rejected.text
        assert path.read_bytes() == before
    assert api.get(base).json()["exists"] is True


def test_background_upload_fits_project_canvas_and_invalid_upload_preserves_image(api):
    for profile, size in (("landscape_16_9", (1920, 1080)), ("portrait_9_16", (1080, 1920))):
        pid = invoke(api, "project.create", {"name": "Background " + profile, "canvas_profile": profile}).json()["project"]["project_id"]
        base = f"/api/agent/v1/projects/{pid}/storyboard-background/image"
        saved = api.post(base, files={"file": ("background.png", _png_bytes(320, 180), "image/png")})
        assert saved.status_code == 200, saved.text
        image = api.get(base)
        assert image.status_code == 200 and Image.open(io.BytesIO(image.content)).size == size
        rejected = api.post(base, files={"file": ("bad.png", b"invalid", "image/png")})
        assert rejected.status_code == 400, rejected.text
        assert api.get(base).content == image.content


def test_voice_reference_upload_validates_audio_and_preserves_previous_on_bad_replacement(api):
    from reference_audio_paths import resolve_reference_audio_path

    created = invoke(api, "connections.create", {"payload": {"name": "Voice reference " + uuid.uuid4().hex,
        "kind": "tts", "provider": "comfyui_tts", "model": "IndexTTS-2.5", "public_config": {}}})
    assert created.status_code == 200, created.text
    cid = created.json()["id"]
    audio = io.BytesIO()
    with wave.open(audio, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 16000)
    base = f"/api/agent/v1/model-connections/{cid}/reference-audio"
    saved = api.post(base, files={"file": ("voice.wav", audio.getvalue(), "audio/wav")})
    assert saved.status_code == 200, saved.text
    assert .9 <= saved.json()["reference_audio"]["duration_sec"] <= 1.1
    portable = saved.json()["connection"]["revision"]["public_config"]["clone_voice_id"]
    path = Path(resolve_reference_audio_path(portable))
    assert path.read_bytes() == audio.getvalue()
    rejected = api.post(base, files={"file": ("invalid.wav", b"not audio", "audio/wav")})
    assert rejected.status_code == 400, rejected.text
    assert path.read_bytes() == audio.getvalue()
    assert not [item for item in path.parent.glob(f"{cid}.*") if ".upload" in item.name or item.suffix == ".rollback"]


def test_secret_exports_use_request_injection_and_explicit_confirmation(api, monkeypatch):
    import config_portability_service as portability
    from dataclasses import replace
    import zipfile

    original = portability._deps()
    portability.configure_config_portability_dependencies(replace(original, get_all_settings=lambda: {"llm_api_key": "isolated-test-secret"}))
    try:
        for suffix in ("", "-zip"):
            path = "/api/agent/v1/config/export-with-secrets" + suffix
            refused = api.post(path, json={"payload": {}})
            assert refused.status_code == 400, refused.text
            exported = api.post(path, json={"payload": {"confirmation": "EXPORT_SECRETS"}})
            assert exported.status_code == 200, exported.text
            if suffix:
                with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
                    body = json.loads(archive.read("config.json"))
            else:
                body = exported.json()
            assert body["contains_secrets"] is True
            assert body["settings"]["llm_api_key"] == "isolated-test-secret"
        monkeypatch.setenv("PPT_STUDIO_ACCESS_TOKEN", "isolated-access-token")
        denied = api.post("/api/agent/v1/config/export-with-secrets-zip", json={"payload": {"confirmation": "EXPORT_SECRETS"}})
        assert denied.status_code == 401, denied.text
    finally:
        portability.configure_config_portability_dependencies(original)


def test_presenter_upload_rejects_corrupt_replacement_and_keeps_valid_video(api, tmp_path):
    import subprocess
    from scripts.media_tools import resolve_media_tool
    path = tmp_path / "presenter.mp4"
    subprocess.run([resolve_media_tool("ffmpeg"), "-y", "-f", "lavfi", "-i", "color=c=blue:s=160x120:d=1",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True, capture_output=True, timeout=30)
    pid = invoke(api, "project.create", {"name": "Presenter media validation"}).json()["project"]["project_id"]
    base = f"/api/agent/v1/projects/{pid}/digital-human/upload"
    valid = api.post(base, files={"file": ("presenter.mp4", path.read_bytes(), "video/mp4")})
    assert valid.status_code == 200, valid.text
    before = api.get(base + "/content")
    assert before.status_code == 200 and before.content == path.read_bytes()
    broken = api.post(base, files={"file": ("broken.mp4", b"invalid-video", "video/mp4")})
    assert broken.status_code == 400, broken.text
    assert api.get(base + "/content").content == before.content


def test_full_presenter_generation_reports_actual_source_preconditions(api, monkeypatch):
    import digital_human_routes
    monkeypatch.setattr(digital_human_routes, "get_digital_human_client", lambda: __import__("pytest").fail("invalid generation contacted engine"))
    pid = invoke(api, "project.create", {"name": "Full presenter preconditions"}).json()["project"]["project_id"]
    args = {"project_id": pid}
    missing_avatar = invoke(api, "digital_human.generate", args)
    assert missing_avatar.status_code == 400, missing_avatar.text
    invoke(api, "digital_human.config.update", {**args, "config": {"avatar_id": "selected", "mode": "comfyui"}})
    unowned_avatar = invoke(api, "digital_human.generate", args)
    assert unowned_avatar.status_code == 403, unowned_avatar.text
    monkeypatch.setattr(digital_human_routes, "project_avatars", lambda run_dir: {"selected": "fixture-digest"})
    stale_audio = invoke(api, "digital_human.generate", args)
    assert stale_audio.status_code == 409, stale_audio.text
