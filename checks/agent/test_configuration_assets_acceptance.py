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
