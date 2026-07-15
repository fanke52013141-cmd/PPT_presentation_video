import json
import sys
import tempfile
from pathlib import Path

from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server  # noqa: E402


class FakeProject:
    id = "order-project"

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = str(run_dir)
        self.current_step = 8
        self._statuses = {str(step): "completed" for step in range(1, 9)}

    def get_step_status(self, step=None):
        return dict(self._statuses) if step is None else self._statuses.get(str(step), "pending")

    def set_step_status(self, statuses):
        self._statuses = dict(statuses)


class FakeDb:
    def __init__(self, project: FakeProject) -> None:
        self.project = project
        self.commits = 0

    def query(self, *_args):
        return self

    def filter(self, *_args):
        return self

    def first(self):
        return self.project

    def commit(self):
        self.commits += 1


def test_reorder_uses_optimistic_version_and_invalidates_render() -> None:
    with tempfile.TemporaryDirectory() as value:
        run_dir = Path(value)
        planning = run_dir / "planning"
        planning.mkdir(parents=True)
        contract_path = planning / "visual_contract.json"
        contract_path.write_text(
            json.dumps({"slides": [{"slide_id": "a"}, {"slide_id": "b"}, {"slide_id": "c"}]}),
            encoding="utf-8",
        )
        (run_dir / "remotion_props.json").write_text("{}", encoding="utf-8")
        project = FakeProject(run_dir)
        db = FakeDb(project)
        version = server.slide_order_version(["a", "b", "c"])

        response = server.update_step3_order(
            project.id,
            {"slide_ids": ["c", "a", "b"], "order_version": version},
            db,
        )
        stored = json.loads(contract_path.read_text(encoding="utf-8"))
        assert [slide["slide_id"] for slide in stored["slides"]] == ["c", "a", "b"]
        assert response["order_version"] == server.slide_order_version(["c", "a", "b"])
        assert not (run_dir / "remotion_props.json").exists()
        assert project.get_step_status(8) == "pending_reconfirmation"
        assert db.commits == 1

        try:
            server.update_step3_order(
                project.id,
                {"slide_ids": ["b", "c", "a"], "order_version": version},
                db,
            )
        except HTTPException as exc:
            assert exc.status_code == 409
        else:
            raise AssertionError("stale reorder version unexpectedly succeeded")
