import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

import pytest
from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database import Project
from project_storage import (
    UnsafeProjectPath,
    safe_child,
    safe_identifier,
    project_run_dir,
    slide_file,
    video_file,
    video_sidecar,
)
from server import current_slide_file_or_404


def test_normal_project_paths_stay_under_root() -> None:
    with tempfile.TemporaryDirectory() as value:
        root = Path(value).resolve()
        image = slide_file(root, "slide_001", "visual_draft.png")
        video = video_file(root, "render_2026-07-11.mp4")
        assert image.relative_to(root) == Path("slides/slide_001/visual_draft.png")
        assert video.relative_to(root) == Path("videos/render_2026-07-11.mp4")
        assert video_sidecar(video) == Path(f"{video}.render.json")


@pytest.mark.parametrize(
    "value",
    ("../outside", "..\\outside", "/absolute", "C:\\outside", ".", "", "slide/001", "slide\\001"),
)
def test_unsafe_slide_identifiers_are_rejected(value: str) -> None:
    with pytest.raises(UnsafeProjectPath):
        safe_identifier(value, label="slide_id")


@pytest.mark.parametrize(
    "filename",
    ("../video.mp4", "..\\video.mp4", "/tmp/video.mp4", "video.mov", "video.mp4/extra", ""),
)
def test_unsafe_video_names_are_rejected(filename: str) -> None:
    with tempfile.TemporaryDirectory() as value:
        with pytest.raises(UnsafeProjectPath):
            video_file(value, filename)


def test_safe_child_rejects_resolved_escape() -> None:
    with tempfile.TemporaryDirectory() as value:
        with pytest.raises(UnsafeProjectPath):
            safe_child(value, "..", "outside.txt")


def test_project_run_dir_must_be_direct_id_matching_child() -> None:
    with tempfile.TemporaryDirectory() as value:
        runs_root = Path(value) / "runs"
        runs_root.mkdir()
        expected = runs_root / "project_001"
        assert project_run_dir(runs_root, expected, "project_001") == expected.resolve()
        with pytest.raises(UnsafeProjectPath):
            project_run_dir(runs_root, runs_root, "project_001")
        with pytest.raises(UnsafeProjectPath):
            project_run_dir(runs_root, runs_root / "other", "project_001")
        with pytest.raises(UnsafeProjectPath):
            project_run_dir(runs_root, runs_root / "nested" / "project_001", "project_001")


def test_polluted_contract_slide_id_cannot_escape() -> None:
    with tempfile.TemporaryDirectory() as value:
        root = Path(value)
        planning = root / "planning"
        planning.mkdir()
        (planning / "visual_contract.json").write_text(
            json.dumps({"slides": [{"slide_id": "../outside"}]}),
            encoding="utf-8",
        )
        project = Project(id=root.name, name="unsafe", run_dir=str(root), current_step=3)
        with patch("server.RUNS_DIR", str(root.parent)):
            with pytest.raises(HTTPException) as exc_info:
                current_slide_file_or_404(project, "../outside", "visual_draft.png")
        assert exc_info.value.status_code == 400


if __name__ == "__main__":
    test_normal_project_paths_stay_under_root()
    for value in ("../outside", "..\\outside", "/absolute", "C:\\outside", ".", "", "slide/001", "slide\\001"):
        test_unsafe_slide_identifiers_are_rejected(value)
    for filename in ("../video.mp4", "..\\video.mp4", "/tmp/video.mp4", "video.mov", "video.mp4/extra", ""):
        test_unsafe_video_names_are_rejected(filename)
    test_safe_child_rejects_resolved_escape()
    test_project_run_dir_must_be_direct_id_matching_child()
    test_polluted_contract_slide_id_cannot_escape()
    print("project storage security checks passed")
