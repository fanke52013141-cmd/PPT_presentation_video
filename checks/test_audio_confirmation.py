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

    with open(audio_confirmation_path(project), "w", encoding="utf-8") as f:
        json.dump({"confirmed": True}, f)
    assert project_audio_confirmed(project)

    handle_step_navigation(project, 6, db)
    assert not project_audio_confirmed(project)
    assert project.get_step_status()["7"] == "pending"

print("audio confirmation checks passed")
