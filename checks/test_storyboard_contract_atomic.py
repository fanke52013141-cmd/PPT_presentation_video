"""visual_contract.json 必须经由 write_json_atomic 原子写入（审查 H-02）。

回归背景：finalize_step2_contract / update_step2_result 曾用裸 open+json.dump
直写全链路唯一输入文件，进程崩溃可产生截断文件。
"""

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server  # noqa: F401  与既有服务级测试保持一致的组合根导入
import storyboard_service as service


class FakeProject:
    id = "project-contract-atomic"
    name = "Contract atomic test"

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = str(run_dir)
        self.current_step = 2
        self._statuses = {"1": "completed", "2": "in_progress"}

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


def test_contract_source_has_no_bare_open_writes() -> None:
    """守护：契约写点只允许 write_json_atomic。"""
    source = Path(service.__file__).read_text(encoding="utf-8")
    assert 'open(contract_path, "w"' not in source
    assert source.count("write_json_atomic(contract_path") >= 2


def test_empty_storyboard_update_round_trips_atomically() -> None:
    with tempfile.TemporaryDirectory() as value:
        run_dir = Path(value)
        (run_dir / "planning").mkdir(parents=True)
        project = FakeProject(run_dir)
        db = FakeDb(project)

        response = service.update_step2_result(
            FakeProject.id,
            {"version": "visual_contract_v1", "slides": []},
            db,
        )

        assert response["success"] is True
        assert response["changed"] is True
        contract_path = run_dir / "planning" / "visual_contract.json"
        data = json.loads(contract_path.read_text(encoding="utf-8"))
        assert data["version"] == "visual_contract_v1"
        assert data["slides"] == []
        # 原子写正常路径不残留临时文件
        assert list(run_dir.glob("planning/*.tmp")) == []
        assert db.commits >= 1
