import json
import hashlib
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import runtime_ai_mask as ai_mask
import one_click_orchestrator as one_click
import server


def project_for(root: Path) -> SimpleNamespace:
    return SimpleNamespace(id="project-test", run_dir=str(root))


def test_atomic_status_write_and_resume() -> None:
    with tempfile.TemporaryDirectory() as value:
        root = Path(value)
        project = project_for(root)
        status = one_click._initial_status(project.id, "run-old")
        one_click._finish_stage(project, status, "preflight", "ok")
        one_click._finish_stage(project, status, "storyboard", "ok")
        one_click._fail_stage(project, status, "images", "provider failed")

        resumed, start_index = one_click._resume_status(project, project.id, "run-new", "resume")
        assert start_index == one_click._stage_index("images")
        assert resumed["run_id"] == "run-new"
        assert resumed["status"] == "running"
        assert one_click._stage(resumed, "preflight")["status"] == "done"
        assert one_click._stage(resumed, "storyboard")["status"] == "done"
        assert one_click._stage(resumed, "images")["status"] == "pending"
        assert not list((root / "planning").glob("*.tmp"))
        json.loads((root / "planning" / one_click.STATUS_FILENAME).read_text(encoding="utf-8"))

        one_click._save_status(project, resumed)
        thread_resumed, thread_start_index = one_click._resume_status(project, project.id, "run-new", "resume")
        assert thread_start_index == one_click._stage_index("images")
        assert thread_resumed["run_id"] == "run-new"


def test_restart_does_not_reuse_failed_stage_state() -> None:
    with tempfile.TemporaryDirectory() as value:
        project = project_for(Path(value))
        status = one_click._initial_status(project.id, "run-old")
        one_click._fail_stage(project, status, "ai_mask", "low quality")
        restarted, start_index = one_click._resume_status(project, project.id, "run-new", "restart")
        assert start_index == 0
        assert restarted["run_id"] == "run-new"
        assert all(stage["status"] == "pending" for stage in restarted["stages"])


def test_contract_and_narration_are_only_reused_when_fresh_and_validated() -> None:
    with tempfile.TemporaryDirectory() as value:
        root = Path(value)
        project = project_for(root)
        (root / "planning").mkdir(parents=True)
        (root / "inputs").mkdir(parents=True)
        article = root / "inputs" / "article.md"
        contract = root / "planning" / "visual_contract.json"
        narration = root / "planning" / "narration_beats.json"
        article.write_text("article", encoding="utf-8")
        contract.write_text('{"slides":[]}', encoding="utf-8")
        narration.write_text('{"slide_001":[]}', encoding="utf-8")
        for path, stamp in ((article, 10), (contract, 20), (narration, 30)):
            os.utime(path, (stamp, stamp))
        validation = {
            "valid": True,
            "contract_sha256": hashlib.sha256(contract.read_bytes()).hexdigest(),
        }
        (root / "planning" / "visual_contract.validation.json").write_text(
            json.dumps(validation),
            encoding="utf-8",
        )
        assert one_click._has_contract(project)
        assert one_click._has_fresh_narration(project)

        os.utime(article, (40, 40))
        assert not one_click._has_contract(project)
        contract.write_text('{"slides":[{"slide_id":"changed"}]}', encoding="utf-8")
        os.utime(contract, (50, 50))
        assert not one_click._has_contract(project), "changed contracts require a matching validation hash"
        assert not one_click._has_fresh_narration(project)


def test_disabled_quality_gate_marks_terminal_failure() -> None:
    with tempfile.TemporaryDirectory() as value:
        project = project_for(Path(value))
        status = one_click._initial_status(project.id, "run-old")
        one_click._fail_stage(project, status, "render", "render failed", pause=False)
        assert status["status"] == "failed"
        restarted, start_index = one_click._resume_status(project, project.id, "run-new", "resume")
        assert start_index == 0
        assert restarted["run_id"] == "run-new"


def test_only_uncorrected_ai_masks_are_replaceable() -> None:
    base = {
        "source": "ai_auto_mask",
        "review_status": "ai_matched",
        "manual_mask": {
            "source": "ai_auto_mask_v3_exact_rle",
            "rle": {"runs": [[1, 1, 5]]},
            "strokes": [],
        },
    }
    assert ai_mask._replaceable_ai_mask(base)

    corrected = {**base, "manual_mask": {**base["manual_mask"], "strokes": [{"mode": "erase", "points": [{"x": 2, "y": 2}]}]}}
    assert not ai_mask._replaceable_ai_mask(corrected)

    locked = {**base, "review_status": "locked"}
    assert not ai_mask._replaceable_ai_mask(locked)

    manual = {**base, "manual_mask": {**base["manual_mask"], "source": "manual_paint"}}
    assert not ai_mask._replaceable_ai_mask(manual)


def test_one_click_uses_safe_mask_and_audio_modes() -> None:
    source = Path("one_click_orchestrator.py").read_text(encoding="utf-8")
    services_source = Path("pipeline_services.py").read_text(encoding="utf-8")
    assert '"overwrite_existing_manual_mask": False' in source
    assert '"overwrite_existing_ai_mask": True' in source
    assert '"skip_locked_groups": True' in source
    assert '"confirmation_mode": "automatic_technical"' in services_source
    assert "ProjectPipelineServices" in source
    assert "services.narration" in source
    assert "services.save_narration" in source
    assert "TestClient" not in source
    assert "client.get(" not in source
    assert "client.post(" not in source
    assert "client.put(" not in source
    assert 'mode == "restart" or not _has_contract(project)' in source
    for gate_name in one_click.DEFAULT_QUALITY_GATES:
        assert source.count(gate_name) >= 2


def test_preflight_migrates_legacy_article_before_checking_source() -> None:
    with tempfile.TemporaryDirectory() as value:
        root = Path(value)
        project = project_for(root)
        calls = []

        def migrate_article(_project, *, required=True):
            calls.append(required)
            article_path = root / "inputs" / "article.md"
            article_path.parent.mkdir(parents=True, exist_ok=True)
            article_path.write_text("legacy article", encoding="utf-8")
            return {"content": "legacy article"}

        module = SimpleNamespace(
            read_project_article_source=migrate_article,
            get_setting=lambda _key: "configured",
            resolve_media_tool=lambda _name: "available",
            REPO_ROOT=str(ROOT),
        )

        errors = one_click._preflight_errors(module, project)

        assert calls == [False]
        assert not any("导入文章" in error for error in errors)


def test_one_click_routes_are_explicit_and_unique() -> None:
    route_methods = [
        (getattr(route, "path", ""), frozenset(getattr(route, "methods", set()) or set()))
        for route in server.app.routes
    ]
    assert route_methods.count(("/api/projects/{project_id}/one-click-generate", frozenset({"POST"}))) == 1
    assert route_methods.count(("/api/projects/{project_id}/one-click-generate/status", frozenset({"GET"}))) == 1
    assert not hasattr(one_click, "_install_when_ready")
    assert not hasattr(one_click, "_candidate_modules")


if __name__ == "__main__":
    test_atomic_status_write_and_resume()
    test_restart_does_not_reuse_failed_stage_state()
    test_contract_and_narration_are_only_reused_when_fresh_and_validated()
    test_disabled_quality_gate_marks_terminal_failure()
    test_only_uncorrected_ai_masks_are_replaceable()
    test_one_click_uses_safe_mask_and_audio_modes()
    test_preflight_migrates_legacy_article_before_checking_source()
    test_one_click_routes_are_explicit_and_unique()
    print("one-click orchestrator checks passed")
