"""Real multipart and media lifecycle acceptance in the isolated test data directory."""

import io
import json
import pytest

from PIL import Image

from checks.agent.test_full_workflow_mocked import api, invoke, _png_bytes  # noqa: F401


@pytest.mark.parametrize("capability,field", [
    ("style.references.delete", "index"), ("style.references_legacy.delete", "index"),
    ("annotation.editor_ink.get", "stroke_index"), ("annotation.ink.get", "frame_index"),
    ("config.version.get", "version"),
])
def test_numeric_path_contract_matches_runtime(capability, field):
    from agent_contract.capabilities import get_capability
    from agent_contract.discovery import input_model
    from agent_contract.schema import capability_input_schema
    from pydantic import ValidationError

    cap = get_capability(capability)
    schema = capability_input_schema(cap)
    assert schema["properties"][field]["type"] == "integer"
    arguments = {name: 1 if schema["properties"][name]["type"] == "integer" else "resource"
                 for name in schema.get("required", [])}
    assert getattr(input_model(cap).model_validate(arguments), field) == 1
    for invalid in ("1", True, 1.5):
        with pytest.raises(ValidationError):
            input_model(cap).model_validate({**arguments, field: invalid})


def test_project_style_reference_upload_download_delete(api):
    pid = invoke(api, "project.create", {"name": "Reference assets"}).json()["project"]["project_id"]
    base = f"/api/agent/v1/projects/{pid}/style/references"
    uploaded = api.post(base + "/upload", files=[
        ("files", ("one.png", _png_bytes(320, 180), "image/png")),
        ("files", ("two.png", _png_bytes(320, 180), "image/png")),
    ])
    assert uploaded.status_code == 200, uploaded.text
    for index in (1, 2):
        image = api.get(f"{base}/{index}/content")
        assert image.status_code == 200, image.text
        assert Image.open(io.BytesIO(image.content)).size == (1920, 1080)
    deleted = invoke(api, "style.references.delete", {"project_id": pid, "index": 1})
    assert deleted.status_code == 200, deleted.text
    assert api.get(base + "/1/content").status_code == 404
    assert api.get(base + "/2/content").status_code == 200
    cleared = invoke(api, "style.references.delete_all", {"project_id": pid})
    assert cleared.status_code == 200, cleared.text
    assert api.get(base + "/2/content").status_code == 404


def test_ip_image_upload_replace_delete_keeps_other_project_isolated(api):
    pid = invoke(api, "project.create", {"name": "IP assets"}).json()["project"]["project_id"]
    other = invoke(api, "project.create", {"name": "Other assets"}).json()["project"]["project_id"]
    base = f"/api/agent/v1/projects/{pid}/ip-characters"
    created = api.post(base, data={"data": json.dumps({"name": "Mascot"})},
        files={"file": ("mascot.png", _png_bytes(320, 180), "image/png")})
    assert created.status_code == 200, created.text
    character = created.json()["data"]["characters"][0]
    cid = character["id"]
    image = api.get(f"{base}/{cid}/image")
    assert image.status_code == 200, image.text
    assert Image.open(io.BytesIO(image.content)).size == (320, 180)
    assert api.get(f"/api/agent/v1/projects/{other}/ip-characters/{cid}/image").status_code == 404
    replaced = api.post(base, data={"data": json.dumps({"id": cid, "name": "Updated"})},
        files={"file": ("replacement.png", _png_bytes(160, 160), "image/png")})
    assert replaced.status_code == 200, replaced.text
    assert len(replaced.json()["data"]["characters"]) == 1
    assert Image.open(io.BytesIO(api.get(f"{base}/{cid}/image").content)).size == (160, 160)
    deleted = invoke(api, "ip.delete", {"project_id": pid, "character_id": cid})
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["data"]["characters"] == []
    assert api.get(f"{base}/{cid}/image").status_code == 404


def test_annotation_text_layout_correction_conflict_and_noop(api):
    from pathlib import Path
    from checks.test_annotation_routes import _make_project
    from annotation_text_layout import candidate_tokens

    pid, root = _make_project()
    sample = Path(__file__).resolve().parents[1] / "fixtures/annotations/sample_slide_layout.json"
    layout = json.loads(sample.read_text(encoding="utf-8"))
    target = root / "slides/slide_001/text_layout.json"
    target.write_text(json.dumps(layout, ensure_ascii=False), encoding="utf-8")
    token = candidate_tokens(layout)[0]["token_id"]
    args = {"project_id": pid, "slide_id": "slide_001"}
    stale = invoke(api, "annotation.text_layout.patch", {**args, "payload": {
        "expected_layout_revision": 0, "corrections": {token: "纠正文字"},
    }})
    assert stale.status_code == 409, stale.text
    updated = invoke(api, "annotation.text_layout.patch", {**args, "payload": {
        "expected_layout_revision": layout["layout_revision"], "corrections": {token: "纠正文字"},
    }})
    assert updated.status_code == 200, updated.text
    assert updated.json()["corrections"][token]
    before = (target.read_bytes(), target.stat().st_mtime_ns)
    repeated = invoke(api, "annotation.text_layout.patch", {**args, "payload": {
        "expected_layout_revision": updated.json()["layout_revision"], "corrections": {token: "纠正文字"},
    }})
    assert repeated.status_code == 200, repeated.text
    assert (target.read_bytes(), target.stat().st_mtime_ns) == before
