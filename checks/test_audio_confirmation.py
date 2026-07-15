import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database import Project
from server import (
    audio_confirmation_path,
    handle_step_navigation,
    mark_step_in_progress,
    project_audio_confirmed,
)
from tts_artifacts import artifact_paths, build_confirmation_payload


class DummyDb:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1


with tempfile.TemporaryDirectory() as run_dir:
    os.makedirs(os.path.join(run_dir, "planning"), exist_ok=True)
    project = Project(id="test", name="test", run_dir=run_dir, current_step=6)
    project.set_step_status({str(i): "pending" for i in range(1, 9)})
    db = DummyDb()

    mark_step_in_progress(project, 7, db)
    assert project.get_step_status()["7"] == "in_progress"

    paths = artifact_paths(run_dir, "slide_001")
    for key in ("text", "audio", "metadata", "srt", "timeline"):
        paths[key].parent.mkdir(parents=True, exist_ok=True)
        paths[key].write_text(f"{key}-content", encoding="utf-8")
    project.set_step_status({str(i): "pending" for i in range(1, 9)})
    (Path(run_dir) / "planning" / "visual_contract.json").write_text(
        json.dumps({"slides": [{"slide_id": "slide_001"}]}),
        encoding="utf-8",
    )
    with open(audio_confirmation_path(project), "w", encoding="utf-8") as f:
        json.dump(
            build_confirmation_payload(run_dir, ["slide_001"], confirmation_mode="user_reviewed"),
            f,
        )
    assert project_audio_confirmed(project)

    paths["text"].write_text("changed narration", encoding="utf-8")
    assert not project_audio_confirmed(project)
    with open(audio_confirmation_path(project), "w", encoding="utf-8") as f:
        json.dump(
            build_confirmation_payload(run_dir, ["slide_001"], confirmation_mode="user_reviewed"),
            f,
        )

    handle_step_navigation(project, 6, db)
    assert not project_audio_confirmed(project)
    assert project.get_step_status()["7"] == "pending"

print("audio confirmation checks passed")
