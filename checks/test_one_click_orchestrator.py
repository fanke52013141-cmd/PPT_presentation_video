import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import runtime_ai_mask as ai_mask
import runtime_one_click_orchestrator as one_click


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
    source = Path("runtime_one_click_orchestrator.py").read_text(encoding="utf-8")
    assert '"overwrite_existing_manual_mask": False' in source
    assert '"overwrite_existing_ai_mask": True' in source
    assert '"skip_locked_groups": True' in source
    assert '"confirmation_mode": "automatic_technical"' in source
    assert 'client.get(f"/api/projects/{project_id}/steps/6/result")' in source


if __name__ == "__main__":
    test_atomic_status_write_and_resume()
    test_restart_does_not_reuse_failed_stage_state()
    test_only_uncorrected_ai_masks_are_replaceable()
    test_one_click_uses_safe_mask_and_audio_modes()
    print("one-click orchestrator checks passed")
