import io
import uuid

from PIL import Image

from checks.agent.test_full_workflow_mocked import api, invoke, _png_bytes  # noqa: F401


def test_project_template_copies_style_and_references_to_another_project(api):
    source = invoke(api, "project.create", {"name": "Template source"}).json()["project"]["project_id"]
    target = invoke(api, "project.create", {"name": "Template destination"}).json()["project"]["project_id"]
    style = invoke(api, "style.update", {"project_id": source, "payload": {"system_content": "蓝色线稿、白色底、统一卡片边距。"}})
    assert style.status_code == 200, style.text
    uploaded = api.post(f"/api/agent/v1/projects/{source}/style/references/upload",
        files=[("files", ("reference.png", _png_bytes(320, 180), "image/png"))])
    assert uploaded.status_code == 200, uploaded.text
    original = api.get(f"/api/agent/v1/projects/{source}/style/references/1/content").content
    saved = invoke(api, "style.project_template.save", {"project_id": source,
        "payload": {"name": "Reusable-" + uuid.uuid4().hex}})
    assert saved.status_code == 200, saved.text
    tid = saved.json()["template"]["id"]
    library = api.get(f"/api/agent/v1/style/templates/{tid}/references/1/content")
    assert library.status_code == 200 and library.content == original
    assert invoke(api, "style.references.delete_all", {"project_id": source}).status_code == 200
    applied = invoke(api, "style.project_template.apply", {"project_id": target, "template_id": tid})
    assert applied.status_code == 200, applied.text
    assert applied.json()["style"]["system_content"] == style.json()["style"]["system_content"]
    copied = api.get(f"/api/agent/v1/projects/{target}/style/references/1/content")
    assert copied.status_code == 200 and copied.content == original
    assert invoke(api, "style.templates.delete", {"template_id": tid}).status_code == 200
    # Deletion archives the template to preserve existing creation-package references.
    listed = invoke(api, "style.templates.list", {})
    assert listed.status_code == 200, listed.text
    assert tid not in str(listed.json())
    retired = invoke(api, "style.project_template.apply", {"project_id": source, "template_id": tid})
    assert retired.status_code == 409, retired.text
    assert api.get(f"/api/agent/v1/projects/{target}/style/references/1/content").content == original


def test_global_template_reference_is_independent_of_project_template_library(api):
    upload = api.put("/api/agent/v1/global-image-style/reference/template",
        files={"file": ("reference.png", _png_bytes(320, 180), "image/png")})
    assert upload.status_code == 200, upload.text
    original = api.get("/api/agent/v1/global-image-style/reference/template/content")
    assert original.status_code == 200, original.text
    Image.open(io.BytesIO(original.content)).verify()
    name = "Global-" + uuid.uuid4().hex
    saved = invoke(api, "global_style.templates.save", {"payload": {"name": name}})
    assert saved.status_code == 200, saved.text
    tid = next(t["id"] for t in saved.json()["templates"] if t["name"] == name)
    reference = api.get(f"/api/agent/v1/global-image-style/templates/{tid}/references/template/content")
    assert reference.status_code == 200 and reference.content == original.content
    replacement = io.BytesIO()
    Image.new("RGB", (320, 180), "red").save(replacement, "PNG")
    assert api.put("/api/agent/v1/global-image-style/reference/template",
        files={"file": ("replacement.png", replacement.getvalue(), "image/png")}).status_code == 200
    invalid = invoke(api, "global_style.template_references.apply", {"payload": {"template_id": {"id": tid}}})
    assert invalid.status_code == 422, invalid.text
    applied = invoke(api, "global_style.template_references.apply", {"payload": {"template_id": tid}})
    assert applied.status_code == 200, applied.text
    assert api.get("/api/agent/v1/global-image-style/reference/template/content").content == original.content
    assert invoke(api, "global_style.templates.delete", {"template_id": tid}).status_code == 200
