import tempfile
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline_lifecycle import (
    clear_all_reveal_artifacts,
    clear_audio_confirmation,
    clear_slide_reveal_artifacts,
    mark_downstream_pending,
    mark_selected_stale,
)


def _write(path: Path, content: str = "generated") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_slide_cleanup_is_scoped() -> None:
    with tempfile.TemporaryDirectory() as value:
        run_dir = Path(value)
        slide_one = run_dir / "slides" / "slide_001"
        slide_two = run_dir / "slides" / "slide_002"
        for filename in ("scene.json", "animation_timeline.json", "reveal_report.json"):
            _write(slide_one / filename)
            _write(slide_two / filename)
        _write(slide_one / "assets" / "layer.png")
        _write(slide_two / "assets" / "layer.png")
        _write(slide_one / "visual_draft.png")
        _write(run_dir / "remotion_props.json")

        clear_slide_reveal_artifacts(run_dir, "slide_001")

        assert (slide_one / "visual_draft.png").exists()
        assert not (slide_one / "assets").exists()
        assert not (slide_one / "scene.json").exists()
        assert (slide_two / "assets" / "layer.png").exists()
        assert (slide_two / "scene.json").exists()
        assert not (run_dir / "remotion_props.json").exists()


def test_project_reveal_cleanup_keeps_sources() -> None:
    with tempfile.TemporaryDirectory() as value:
        run_dir = Path(value)
        for slide_id in ("slide_001", "slide_002"):
            slide_dir = run_dir / "slides" / slide_id
            _write(slide_dir / "scene.json")
            _write(slide_dir / "assets" / "layer.png")
            _write(slide_dir / "visual_draft.png")
            _write(slide_dir / "voice.mp3")
        _write(run_dir / "remotion_props.json")

        clear_all_reveal_artifacts(run_dir, ("slide_001", "slide_002"))

        for slide_id in ("slide_001", "slide_002"):
            slide_dir = run_dir / "slides" / slide_id
            assert (slide_dir / "visual_draft.png").exists()
            assert (slide_dir / "voice.mp3").exists()
            assert not (slide_dir / "scene.json").exists()
            assert not (slide_dir / "assets").exists()


def test_audio_confirmation_cleanup_is_idempotent() -> None:
    with tempfile.TemporaryDirectory() as value:
        run_dir = Path(value)
        confirmation = run_dir / "planning" / "audio_confirmed.json"
        _write(confirmation, "{}")
        assert clear_audio_confirmation(run_dir) is True
        assert clear_audio_confirmation(run_dir) is False


def test_status_transitions_preserve_stale_distinction() -> None:
    statuses = {
        "3": "completed",
        "4": "completed",
        "5": "in_progress",
        "6": "pending_reconfirmation",
        "7": "pending",
        "8": "completed",
    }
    mark_downstream_pending(statuses, from_step=4)
    assert statuses == {
        "3": "completed",
        "4": "pending_reconfirmation",
        "5": "pending",
        "6": "pending",
        "7": "pending",
        "8": "pending_reconfirmation",
    }

    selected = {"5": "completed", "8": "in_progress", "7": "completed"}
    mark_selected_stale(selected, (5, 8))
    assert selected == {"5": "pending_reconfirmation", "8": "pending", "7": "completed"}


if __name__ == "__main__":
    test_slide_cleanup_is_scoped()
    test_project_reveal_cleanup_keeps_sources()
    test_audio_confirmation_cleanup_is_idempotent()
    test_status_transitions_preserve_stale_distinction()
    print("pipeline lifecycle checks passed")
