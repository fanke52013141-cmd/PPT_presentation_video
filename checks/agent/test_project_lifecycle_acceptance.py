import uuid
from pathlib import Path

from checks.agent.test_full_workflow_mocked import api, invoke  # noqa: F401


def test_project_fields_list_cas_state_account_isolation_and_delete(api):
    from database import Project, SessionLocal
    from account_service import create_account, create_agent_token

    payload = {"name": "Project lifecycle " + uuid.uuid4().hex, "description": "Field parity",
        "canvas_profile": "portrait_9_16", "automation_mode": "manual",
        "review_policy": "all_stages", "production_mode": "guided", "presentation_mode": "reveal", "target_duration_sec": 120,
        "manual_pause_steps": ["images", "annotation"], "image_style_template": "default"}
    created = invoke(api, "project.create", payload)
    assert created.status_code == 200, created.text
    summary = created.json()["project"]
    pid = summary["project_id"]
    for key in ("name", "description", "canvas_profile", "review_policy", "production_mode", "presentation_mode", "target_duration_sec", "manual_pause_steps", "image_style_template"):
        assert summary[key] == payload[key]
    assert summary["ai_mode"] == "manual" and summary["mask_enabled"] is True
    detail = invoke(api, "project.get", {"project_id": pid})
    assert detail.status_code == 200 and detail.json()["project"] == summary
    assert not detail.json()["has_article"] and not detail.json()["has_contract"]
    listing = invoke(api, "project.list", {"status_filter": "active", "limit": 200})
    assert listing.status_code == 200, listing.text
    assert next(p for p in listing.json()["projects"] if p["project_id"] == pid) == summary
    with SessionLocal() as db:
        root = Path(db.get(Project, pid).run_dir)
        account = create_account(db, name="Isolated " + uuid.uuid4().hex)
        outsider = create_agent_token(db, account["id"], scopes=["project:read", "project:write"])["token"]
    headers = {"Authorization": "Bearer " + outsider}
    assert api.get(f"/api/agent/v1/projects/{pid}", headers=headers).status_code == 404
    assert api.get(f"/api/agent/v1/projects/{pid}/state", headers=headers).status_code == 404
    assert api.delete(f"/api/agent/v1/projects/{pid}", headers=headers).status_code == 404
    changed = invoke(api, "project.update", {"project_id": pid, "expected_revision": summary["revision"],
        "production_mode": "one_click", "name": "Changed"})
    assert changed.status_code == 200, changed.text
    updated = changed.json()["project"]
    assert updated["presentation_mode"] == "full_frame" and updated["mask_enabled"] is False
    stale = invoke(api, "project.delete", {"project_id": pid, "expected_revision": summary["revision"]})
    assert stale.status_code == 409 and root.exists(), stale.text
    state = invoke(api, "project.state", {"project_id": pid})
    assert state.status_code == 200 and len(state.json()["stages"]) == 8
    deleted = invoke(api, "project.delete", {"project_id": pid, "expected_revision": updated["revision"],
        "idempotency_key": "delete-" + pid})
    assert deleted.status_code == 200 and deleted.json()["deleted"] is True, deleted.text
    assert not root.exists()
    assert invoke(api, "project.get", {"project_id": pid}).status_code == 404
