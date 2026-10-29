"""Agent scenarios using real project storage, revision checks and annotation builds."""

import copy
import json
import threading

from checks.agent.test_full_workflow_mocked import api, invoke, workflow  # noqa: F401


def test_project_metadata_noop_and_conflict_preserve_artifacts(api):
    from pathlib import Path
    from database import Project, SessionLocal

    created = invoke(api, "project.create", {"name": "State acceptance", "description": "original"})
    assert created.status_code == 200, created.text
    summary = created.json()["project"]
    pid = summary["project_id"]
    with SessionLocal() as db:
        root = Path(db.get(Project, pid).run_dir)
    sentinel = root / "retained-artifact.txt"
    sentinel.write_bytes(b"keep")
    original = sentinel.stat().st_mtime_ns
    changed = invoke(api, "project.update", {
        "project_id": pid, "name": "Renamed", "expected_revision": summary["revision"],
    })
    assert changed.status_code == 200, changed.text
    revision = changed.json()["project"]["revision"]
    assert revision > summary["revision"]
    repeated = invoke(api, "project.update", {
        "project_id": pid, "name": "Renamed", "expected_revision": revision,
    })
    assert repeated.status_code == 200 and repeated.json()["updated"] is False
    assert repeated.json()["project"]["revision"] == revision
    stale = invoke(api, "project.update", {
        "project_id": pid, "name": "Stale", "expected_revision": summary["revision"],
    })
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"]["code"] == "REVISION_CONFLICT"
    observed = invoke(api, "project.get", {"project_id": pid})
    assert observed.status_code == 200 and observed.json()["project"]["name"] == "Renamed"
    assert sentinel.read_bytes() == b"keep" and sentinel.stat().st_mtime_ns == original


def test_impact_decision_does_not_settle_or_hide_newer_changes(api):
    from database import Project, SessionLocal
    from project_impact_service import record_impact

    pid = invoke(api, "project.create", {"name": "Impact acceptance"}).json()["project"]["project_id"]
    with SessionLocal() as db:
        root = db.get(Project, pid).run_dir
    record_impact(root, reason="slide_image_changed", slide_ids=["slide_001", "slide_002"], source_version="v1")
    before = invoke(api, "project.impacts.get", {"project_id": pid}).json()["items"]
    target = next(item for item in before if item["scope_id"] == "slide_001")
    decided = invoke(api, "project.impacts.decision.update", {
        "project_id": pid, "payload": {"impact_id": target["id"], "decision": "reviewed"},
    })
    assert decided.status_code == 200, decided.text
    after = invoke(api, "project.impacts.get", {"project_id": pid}).json()["items"]
    assert len(after) == 2
    assert next(item for item in after if item["id"] == target["id"])["affected"] == target["affected"]
    record_impact(root, reason="slide_image_changed", slide_ids=["slide_001"], source_version="v2")
    updated = invoke(api, "project.impacts.get", {"project_id": pid}).json()["items"]
    reopened = next(item for item in updated if item["id"] == target["id"])
    assert reopened["decision"] == "defer" and reopened["generation"] == target["generation"] + 1
    assert next(item for item in updated if item["scope_id"] == "slide_002")["source_version"] == "v1"


def test_mask_draft_noop_keeps_manifest_and_audio(workflow, api):
    from pathlib import Path
    from database import Project, SessionLocal

    pid = workflow["project_id"]
    result = invoke(api, "mask.result.get", {"project_id": pid})
    assert result.status_code == 200 and result.json()["success"]
    manifest = result.json()["manifest"]
    first = invoke(api, "mask.draft.update", {"project_id": pid, "payload": manifest})
    assert first.status_code == 200, first.text
    with SessionLocal() as db:
        path = Path(db.get(Project, pid).run_dir) / "reveal_manifest.json"
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    audio = invoke(api, "tts.audio_status.get", {"project_id": pid}).json()
    repeated = invoke(api, "mask.draft.update", {"project_id": pid, "payload": manifest})
    assert repeated.status_code == 200 and repeated.json()["changed"] is False
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    assert invoke(api, "tts.audio_status.get", {"project_id": pid}).json() == audio
    finalized = invoke(api, "mask.result.update", {
        "project_id": pid, "payload": manifest, "build_assets": True,
    })
    assert finalized.status_code == 200, finalized.text
    assert finalized.json()["built_assets"] is True
    assert (path.parent / "slides/slide_001/animation_timeline.json").exists()
    damaged = json.loads(path.read_text(encoding="utf-8"))
    damaged["slides"].append({"slide_id": "removed_slide", "groups": []})
    path.write_text(json.dumps(damaged), encoding="utf-8")
    detected = invoke(api, "mask.result.get", {"project_id": pid})
    assert detected.json()["repair"]["stale_slide_ids"] == ["removed_slide"]
    repaired = invoke(api, "mask.result.repair", {"project_id": pid})
    assert repaired.status_code == 200, repaired.text
    assert repaired.json()["changed"] is True
    assert [s["slide_id"] for s in repaired.json()["manifest"]["slides"]] == ["slide_001", "slide_002"]
    assert invoke(api, "tts.audio_status.get", {"project_id": pid}).json() == audio


def test_annotation_prepare_confirm_conflict_and_noop(api):
    from checks.test_annotation_routes import _make_project, _make_audio, MANUAL_REGION_ITEM

    pid, root = _make_project()
    _make_audio(root)
    args = {"project_id": pid, "slide_id": "slide_001"}
    added = invoke(api, "annotation.slide.patch", {**args, "payload": {
        "expected_revision": 0, "operations": [{"op": "add", "item": copy.deepcopy(MANUAL_REGION_ITEM)}],
    }})
    assert added.status_code == 200, added.text
    revision = added.json()["revision"]
    stale = invoke(api, "annotation.slide.patch", {**args, "payload": {
        "expected_revision": 0, "operations": [{"op": "delete", "annotation_id": "ann_001"}],
    }})
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"]["code"] == "REVISION_CONFLICT"
    for capability in ("annotation.slide.prepare", "annotation.slide.confirm"):
        conflict = invoke(api, capability, {**args, "payload": {"expected_revision": 0}})
        assert conflict.status_code == 409, conflict.text
        assert conflict.json()["error"]["code"] == "REVISION_CONFLICT"
        assert conflict.json()["error"]["details"]
    invalid = invoke(api, "annotation.slide.patch", {**args, "payload": {
        "expected_revision": revision, "operations": [{"op": "update", "annotation_id": "ann_001",
            "patch": {"style": {"color": "#00AA00"}}}],
    }})
    assert invalid.status_code == 422, invalid.text
    assert invalid.json()["error"]["code"] == "VALIDATION_FAILED"
    assert invalid.json()["error"]["details"]["issues"]
    prepared = invoke(api, "annotation.slide.prepare", {**args, "payload": {"expected_revision": revision}})
    assert prepared.status_code == 200, prepared.text
    confirmed = invoke(api, "annotation.slide.confirm", {**args, "payload": {
        "expected_revision": revision, "prepared_build_id": prepared.json()["build_id"],
    }})
    assert confirmed.status_code == 200, confirmed.text
    page = invoke(api, "annotation.slide.get", args)
    assert page.status_code == 200, page.text
    assert page.json()["items"][0]["status"]["content"] == "confirmed"
    media_base = f"/api/agent/v1/projects/{pid}/annotations/slides/slide_001"
    ink = api.get(f"{media_base}/inks/{prepared.json()['build_id']}/ann_001/0/0")
    assert ink.status_code == 200 and ink.content.startswith(b"\x89PNG"), ink.text
    editor_ink = api.get(f"{media_base}/editor-inks/ann_001/0", params={"revision": confirmed.json()["revision"]})
    assert editor_ink.status_code == 200 and editor_ink.content.startswith(b"\x89PNG"), editor_ink.text
    timeline = root / "slides/slide_001/annotation_timeline.json"
    before = timeline.read_bytes()
    repeated = invoke(api, "annotation.slide.patch", {**args, "payload": {
        "expected_revision": confirmed.json()["revision"], "operations": [{
            "op": "update", "annotation_id": "ann_001", "patch": {"style": MANUAL_REGION_ITEM["style"]},
        }],
    }})
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["revision"] == confirmed.json()["revision"]
    assert timeline.read_bytes() == before
    assert json.loads(before)
    edited = invoke(api, "annotation.slide.patch", {**args, "payload": {
        "expected_revision": repeated.json()["revision"], "operations": [{
            "op": "update", "annotation_id": "ann_001", "patch": {"style": {**MANUAL_REGION_ITEM["style"], "color": "#00AA00"}},
        }],
    }})
    assert edited.status_code == 200, edited.text
    assert edited.json()["items"][0]["status"]["content"] == "draft"
    assert not timeline.exists()
    prepared_again = invoke(api, "annotation.slide.prepare", {**args, "payload": {
        "expected_revision": edited.json()["revision"],
    }})
    assert prepared_again.status_code == 200, prepared_again.text
    (root / "slides/slide_001/voice.mp3").write_bytes(b"changed after review")
    stale_audio = invoke(api, "annotation.slide.confirm", {**args, "payload": {
        "expected_revision": edited.json()["revision"],
        "prepared_build_id": prepared_again.json()["build_id"],
    }})
    assert stale_audio.status_code == 409, stale_audio.text
    assert not timeline.exists()


def test_pipeline_real_worker_pause_resume_and_exact_history(api, monkeypatch):
    import one_click_orchestrator as orchestrator
    from database import Project, SessionLocal

    pid = invoke(api, "project.create", {"name": "Pipeline boundaries"}).json()["project"]["project_id"]
    entered = threading.Event()
    release = threading.Event()

    def preflight(_dependencies, _project):
        entered.set()
        assert release.wait(10), "test must release the preflight boundary"
        return []

    monkeypatch.setattr(orchestrator, "_preflight_errors", preflight)
    previous_operation = None
    for attempt in range(2):
        entered.clear()
        release.clear()
        worker = None
        try:
            started = invoke(api, "pipeline.run", {"project_id": pid, "mode": "resume"})
            assert started.status_code == 200, started.text
            operation = started.json()["operation_id"]
            assert operation != previous_operation
            assert entered.wait(5)
            worker = orchestrator._registered_worker(pid)
            assert worker is not None
            status = invoke(api, "pipeline.status", {"project_id": pid})
            assert status.status_code == 200 and status.json()["operation_id"] == operation
            duplicate = invoke(api, "pipeline.run", {"project_id": pid})
            assert duplicate.status_code == 200 and duplicate.json()["operation_id"] == operation
            paused = invoke(api, "pipeline.pause", {"project_id": pid})
            assert paused.status_code == 200 and paused.json()["pause_requested"] is True
            # Request acceptance must not pretend that the still-running preflight stopped.
            assert worker.is_alive() and paused.json()["status"]["status"] == "running"
        finally:
            release.set()
            if worker is not None:
                worker.join(timeout=10)
        assert worker is not None and not worker.is_alive()
        with SessionLocal() as db:
            project = db.get(Project, pid)
            exact = orchestrator.get_one_click_run(project, operation.split(":", 1)[1])
            assert exact["status"] == "paused" and exact.get("interrupted") is not True
            if previous_operation:
                old = orchestrator.get_one_click_run(project, previous_operation.split(":", 1)[1])
                assert old["run_id"] != exact["run_id"] and old["status"] == "paused"
        previous_operation = operation


def test_storyboard_reuse_requires_current_article_and_contract_hashes(workflow, api):
    pid = workflow["project_id"]
    changed = invoke(api, "article.result.update", {
        "project_id": pid, "content": "# Reuse review\n\nChanged article requiring an explicit reuse decision.",
    })
    assert changed.status_code == 200, changed.text
    impacts = invoke(api, "project.impacts.get", {"project_id": pid}).json()["items"]
    impact = next(item for item in impacts if item["id"] == "article_changed:project")
    preview = invoke(api, "project.impacts.reuse_preview", {"project_id": pid})
    assert preview.status_code == 200, preview.text
    payload = {key: preview.json()[key] for key in ("article_sha256", "contract_sha256")}
    payload["source_version"] = impact["source_version"]
    stale = invoke(api, "project.impacts.reuse_confirm", {
        "project_id": pid, "payload": {**payload, "article_sha256": "0" * 64},
    })
    assert stale.status_code == 409, stale.text
    accepted = invoke(api, "project.impacts.reuse_confirm", {"project_id": pid, "payload": payload})
    assert accepted.status_code == 200 and accepted.json()["resolved"] is True, accepted.text
    remaining = invoke(api, "project.impacts.get", {"project_id": pid}).json()["items"]
    item = next((item for item in remaining if item["id"] == impact["id"]), None)
    if item:
        assert "storyboard" not in item["affected"]
