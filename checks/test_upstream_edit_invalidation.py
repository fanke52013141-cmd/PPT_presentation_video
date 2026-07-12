import json
import tempfile
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server


class FakeProject:
    id = "project-edit-test"
    name = "Edit test"

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = str(run_dir)
        self.current_step = 8
        self._statuses = {str(step): "completed" for step in range(1, 9)}

    def get_step_status(self, step=None):
        if step is None:
            return dict(self._statuses)
        return self._statuses.get(str(step), "pending")

    def set_step_status(self, value):
        self._statuses = dict(value)


class FakeQuery:
    def __init__(self, project: FakeProject) -> None:
        self.project = project

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.project


class FakeDb:
    def __init__(self, project: FakeProject) -> None:
        self.project = project
        self.commits = 0

    def query(self, *_args, **_kwargs):
        return FakeQuery(self.project)

    def commit(self):
        self.commits += 1


def test_step1_edit_invalidates_every_dependent_stage() -> None:
    with tempfile.TemporaryDirectory() as value:
        run_dir = Path(value)
        (run_dir / "planning").mkdir(parents=True)
        (run_dir / "inputs").mkdir(parents=True)
        (run_dir / "planning" / "article_brief.json").write_text("{}", encoding="utf-8")
        (run_dir / "planning" / "audio_confirmed.json").write_text("{}", encoding="utf-8")
        (run_dir / "remotion_props.json").write_text("{}", encoding="utf-8")
        project = FakeProject(run_dir)
        db = FakeDb(project)

        response = server.update_step1_result(
            project.id,
            {"content": "updated article"},
            db,
        )

        assert response["success"] is True
        assert project.current_step == 1
        assert project.get_step_status(1) == "completed"
        assert all(project.get_step_status(step) == "pending_reconfirmation" for step in range(2, 9))
        assert not (run_dir / "planning" / "audio_confirmed.json").exists()
        assert not (run_dir / "remotion_props.json").exists()
        assert (run_dir / "inputs" / "article.md").read_text(encoding="utf-8") == "updated article"
        brief = json.loads((run_dir / "planning" / "article_brief.json").read_text(encoding="utf-8"))
        assert brief["title"] == project.name
        assert db.commits == 1

        project.current_step = 8
        project._statuses = {str(step): "completed" for step in range(1, 9)}
        (run_dir / "planning" / "audio_confirmed.json").write_text("{}", encoding="utf-8")
        (run_dir / "remotion_props.json").write_text("{}", encoding="utf-8")
        server.update_step1_result(project.id, {"content": "updated article"}, db)
        assert project.current_step == 8
        assert all(project.get_step_status(step) == "completed" for step in range(1, 9))
        assert (run_dir / "planning" / "audio_confirmed.json").exists()
        assert (run_dir / "remotion_props.json").exists()
        assert db.commits == 1


def test_step2_autosave_only_invalidates_when_contract_changes() -> None:
    with tempfile.TemporaryDirectory() as value:
        run_dir = Path(value)
        (run_dir / "planning").mkdir(parents=True)
        project = FakeProject(run_dir)
        db = FakeDb(project)
        payload = {"version": "visual_contract_v1", "slides": []}

        first = server.update_step2_result(project.id, payload, db)
        assert first["changed"] is True
        assert project.current_step == 2
        assert project.get_step_status(2) == "completed"
        assert all(project.get_step_status(step) == "pending_reconfirmation" for step in range(3, 9))
        assert db.commits == 1

        project.current_step = 8
        project._statuses = {str(step): "completed" for step in range(1, 9)}
        (run_dir / "planning" / "audio_confirmed.json").write_text("{}", encoding="utf-8")
        second = server.update_step2_result(project.id, first["contract"], db)
        assert second["changed"] is False
        assert project.current_step == 8
        assert all(project.get_step_status(step) == "completed" for step in range(1, 9))
        assert (run_dir / "planning" / "audio_confirmed.json").exists()
        assert db.commits == 1


if __name__ == "__main__":
    test_step1_edit_invalidates_every_dependent_stage()
    test_step2_autosave_only_invalidates_when_contract_changes()
    print("upstream edit invalidation checks passed")
