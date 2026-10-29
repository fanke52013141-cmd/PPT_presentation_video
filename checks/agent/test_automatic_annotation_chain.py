"""OCR and planning providers are controlled; jobs, storage and confirmation are real."""

from dataclasses import replace
import json
import time

from checks.agent.test_full_workflow_mocked import api, invoke  # noqa: F401


def test_ocr_plan_manual_review_confirm_and_replan_protection(api, monkeypatch):
    from annotation_service import get_annotation_service
    from annotation_ocr_baidu import BaiduOcrChar, BaiduOcrLine, BaiduOcrResult
    from checks.test_annotation_routes import _make_project, _make_audio

    pid, root = _make_project()
    _make_audio(root)
    service = get_annotation_service()
    manager = service._job_manager
    planner = manager._deps.planner
    monkeypatch.setattr(service, "_ocr_ready", lambda: True)
    ocr = BaiduOcrResult(lines=(BaiduOcrLine("报名", 100, 200, 100, 40,
        (BaiduOcrChar("报", 100, 200, 45, 40), BaiduOcrChar("名", 150, 200, 45, 40))),),
        direction=0, log_id=1, granularity="char")
    monkeypatch.setattr(manager, "_deps", replace(manager._deps, recognize=lambda *_: ocr))

    def plan(**kwargs):
        user = json.loads(kwargs["user_prompt"])
        chars = [candidate for candidate in user["candidates"] if candidate["granularity"] == "char"]
        return {"schema_version": "annotation_plan_v2", "suggestions": [{
            "beat_id": user["beats"][0]["beat_id"], "range": [0, 2], "quote": "报名",
            "target_candidate_ids": [candidate["token_id"] for candidate in chars[:2]],
            "category": "action", "priority": 1, "style": "ellipse", "reason": "报名行动", "ambiguous": False,
        }]}

    monkeypatch.setattr(planner, "_deps", replace(planner._deps, llm_generate=plan))

    def run_job(operation, expected="succeeded"):
        submitted = invoke(api, "annotation.jobs.submit", {"project_id": pid,
            "payload": {"operation": operation, "slide_ids": ["slide_001"]}})
        assert submitted.status_code == 200, submitted.text
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            polled = invoke(api, "annotation.jobs.get", {"project_id": pid, "job_id": submitted.json()["job_id"]})
            assert polled.status_code == 200, polled.text
            if polled.json()["status"] in {"succeeded", "failed", "interrupted", "cancelled"}:
                assert polled.json()["status"] == expected, polled.text
                return polled.json()
            time.sleep(.05)
        raise AssertionError("annotation job did not reach a terminal state")

    run_job("detect_text")
    assert (root / "slides/slide_001/text_layout.json").is_file()
    run_job("plan")
    args = {"project_id": pid, "slide_id": "slide_001"}
    page = invoke(api, "annotation.slide.get", args).json()
    assert len(page["items"]) == 1, page
    item = page["items"][0]
    assert item["anchor"]["quote"] == "报名"
    edited = invoke(api, "annotation.slide.patch", {**args, "payload": {
        "expected_revision": page["revision"], "operations": [{"op": "update",
            "annotation_id": item["annotation_id"], "patch": {"timing": {
                "trigger_mode": "manual", "manual_start_sec": .5, "offset_sec": 0,
                "draw_duration_sec": .6, "hold_mode": "slide_end", "exit_duration_sec": .15,
            }}}],
    }})
    assert edited.status_code == 200, edited.text
    before = edited.json()
    run_job("plan")
    protected = invoke(api, "annotation.slide.get", args).json()
    assert len(protected["items"]) == 1
    assert protected["items"][0]["timing"] == before["items"][0]["timing"]
    prepared = invoke(api, "annotation.slide.prepare", {**args, "payload": {
        "expected_revision": protected["revision"], "accepted_review": [item["annotation_id"]],
    }})
    assert prepared.status_code == 200, prepared.text
    confirmed = invoke(api, "annotation.slide.confirm", {**args, "payload": {
        "expected_revision": protected["revision"], "prepared_build_id": prepared.json()["build_id"],
        "accepted_review": [item["annotation_id"]],
    }})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["confirmed"] == 1
    timeline = json.loads((root / "slides/slide_001/annotation_timeline.json").read_text(encoding="utf-8"))
    assert timeline["events"]
    page_path = root / "slides/slide_001/annotations.json"
    timeline_path = root / "slides/slide_001/annotation_timeline.json"
    before_failure = (page_path.read_bytes(), timeline_path.read_bytes())
    timeout_calls = []

    def timeout(**_kwargs):
        timeout_calls.append(True)
        raise TimeoutError("controlled provider timeout")

    monkeypatch.setattr(planner, "_deps", replace(planner._deps, llm_generate=timeout))
    failure = run_job("plan", expected="failed")
    assert len(timeout_calls) == 2
    assert failure["error"] and failure["progress"] != 100
    assert (page_path.read_bytes(), timeline_path.read_bytes()) == before_failure
    layout = invoke(api, "annotation.text_layout.get", args).json()
    token_id = protected["items"][0]["target"]["token_ids"][0]
    audio_path = root / "slides/slide_001/audio_timeline.json"
    audio_before = audio_path.read_bytes()
    props = root / "remotion_props.json"
    props.write_text("{}", encoding="utf-8")
    corrected = invoke(api, "annotation.text_layout.patch", {**args, "payload": {
        "expected_layout_revision": layout["layout_revision"], "corrections": {token_id: "招"},
    }})
    assert corrected.status_code == 200, corrected.text
    refreshed = invoke(api, "annotation.slide.get", args).json()
    assert refreshed["items"][0]["target"]["quote"] == "招名"
    assert refreshed["items"][0]["anchor"]["quote"] == "报名"
    assert refreshed["items"][0]["status"]["content"] == "draft"
    assert not timeline_path.exists() and not props.exists()
    assert audio_path.read_bytes() == audio_before
    baseline = (page_path.read_bytes(), page_path.stat().st_mtime_ns)
    repeated = invoke(api, "annotation.text_layout.patch", {**args, "payload": {
        "expected_layout_revision": corrected.json()["layout_revision"], "corrections": {token_id: "招"},
    }})
    assert repeated.status_code == 200, repeated.text
    assert (page_path.read_bytes(), page_path.stat().st_mtime_ns) == baseline
