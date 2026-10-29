import io

from PIL import Image

from checks.agent.test_full_workflow_mocked import api, invoke, workflow  # noqa: F401


def test_recovery_overlay_and_geometry_reuse_require_current_version(workflow, api):
    from checks.test_annotation_routes import MANUAL_REGION_ITEM
    pid = workflow["project_id"]
    args = {"project_id": pid, "slide_id": "slide_001"}
    initialized = invoke(api, "narration.init", {"project_id": pid})
    assert initialized.status_code == 200, initialized.text
    annotated = invoke(api, "annotation.slide.patch", {**args, "payload": {
        "expected_revision": 0, "operations": [{"op": "add", "item": MANUAL_REGION_ITEM}],
    }})
    assert annotated.status_code == 200, annotated.text
    original = api.get(f"/api/agent/v1/projects/{pid}/slides/slide_001/image")
    assert original.status_code == 200, original.text
    preview = invoke(api, "image.change_preview.get", args).json()
    deleted = invoke(api, "image.delete", {**args, "disposition": "keep", "expected_version": preview["version"]})
    assert deleted.status_code == 200, deleted.text
    uploaded = api.post(f"/api/agent/v1/projects/{pid}/images/upload",
        data={"slide_id": "slide_001", "disposition": "cleanup"},
        files={"file": ("restored.png", original.content, "image/png")})
    assert uploaded.status_code == 200, uploaded.text
    assert invoke(api, "image.confirm", {"project_id": pid}).status_code == 200
    recovery = invoke(api, "image.recovery.list", args)
    assert recovery.status_code == 200 and recovery.json()["items"], recovery.text
    archive = recovery.json()["items"][0]
    assert archive["annotation_items"] == 1
    overlay = api.get(f"/api/agent/v1/projects/{pid}/images/slide_001/recovery/{archive['archive_id']}/overlay")
    assert overlay.status_code == 200, overlay.text
    assert Image.open(io.BytesIO(overlay.content)).size == (1920, 1080)
    payload = {"archive_id": archive["archive_id"], "expected_version": "stale", "reuse_annotations": True}
    stale = invoke(api, "image.geometry.reuse", {**args, "payload": payload})
    assert stale.status_code == 409, stale.text
    payload["expected_version"] = recovery.json()["version"]
    restored = invoke(api, "image.geometry.reuse", {**args, "payload": payload})
    assert restored.status_code == 200, restored.text
    page = invoke(api, "annotation.slide.get", args)
    assert page.status_code == 200, page.text
    assert page.json()["items"][0]["status"]["spatial"] == "needs_review"
    audio = invoke(api, "tts.audio_status.get", {"project_id": pid})
    assert audio.status_code == 200 and all(item["complete"] for item in audio.json()["slides"])
