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


def test_removed_slide_assets_are_archived_for_recovery() -> None:
    with tempfile.TemporaryDirectory() as value:
        run_dir = Path(value)
        (run_dir / "planning").mkdir()
        (run_dir / "planning" / "visual_contract.json").write_text(
            json.dumps({"version": "visual_contract_v1", "slides": [{"slide_id": "slide_001"}]}),
            encoding="utf-8",
        )
        slide_dir = run_dir / "slides" / "slide_001"
        slide_dir.mkdir(parents=True)
        (slide_dir / "visual_draft.png").write_bytes(b"user-image")
        project = FakeProject(run_dir)

        response = service.update_step2_result(
            project.id,
            {"version": "visual_contract_v1", "slides": []},
            FakeDb(project),
        )

        assert response["changed"] is True
        assert not slide_dir.exists()
        archived = list((run_dir / "archived_slides").glob("slide_001-*"))
        assert len(archived) == 1
        assert (archived[0] / "visual_draft.png").read_bytes() == b"user-image"


def _slide(slide_id: str, *, title: str = "标题", narration: str = "旁白") -> dict:
    return {
        "slide_id": slide_id,
        "main_title": title,
        "core_message": title,
        "body_content": [title],
        "visual_groups": [],
        "narration_beats": [
            {
                "id": f"{slide_id}_beat_001",
                "spoken_text": narration,
            }
        ],
    }


def _contract(*slides: dict) -> dict:
    return {"version": "visual_contract_v1", "slides": list(slides)}


def test_contract_diff_is_a_noop_for_identical_contract() -> None:
    contract = _contract(_slide("slide_001"), _slide("slide_002"))

    impact = service.diff_storyboard_contracts(contract, contract)

    assert impact.has_effect is False


def test_contract_diff_scopes_visual_and_narration_changes_independently() -> None:
    previous = _contract(_slide("slide_001"), _slide("slide_002"))
    current = _contract(
        _slide("slide_001", title="新标题"),
        _slide("slide_002", narration="新的旁白"),
    )

    impact = service.diff_storyboard_contracts(previous, current)

    assert impact.visual_slide_ids == ("slide_001",)
    assert impact.narration_slide_ids == ("slide_002",)
    assert impact.reordered is False


def test_contract_diff_treats_slide_order_as_output_only_structure() -> None:
    first = _slide("slide_001")
    second = _slide("slide_002")

    impact = service.diff_storyboard_contracts(
        _contract(first, second),
        _contract(second, first),
    )

    assert impact.visual_slide_ids == ()
    assert impact.narration_slide_ids == ()
    assert impact.reordered is True


def test_contract_diff_marks_added_and_removed_slides_without_touching_survivors() -> None:
    impact = service.diff_storyboard_contracts(
        _contract(_slide("slide_001"), _slide("slide_002")),
        _contract(_slide("slide_002"), _slide("slide_003")),
    )

    assert impact.added_slide_ids == ("slide_003",)
    assert impact.removed_slide_ids == ("slide_001",)
    assert impact.visual_slide_ids == ()
    assert impact.narration_slide_ids == ()


def test_manual_update_passes_only_changed_slide_capabilities(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as value:
        run_dir = Path(value)
        (run_dir / "planning").mkdir()
        previous = _contract(_slide("slide_001"), _slide("slide_002"))
        (run_dir / "planning" / "visual_contract.json").write_text(
            json.dumps(previous), encoding="utf-8"
        )
        project = FakeProject(run_dir)
        calls: list[dict] = []
        monkeypatch.setattr(
            service.invalidation_service,
            "storyboard_contract_changed",
            lambda _project, **kwargs: calls.append(kwargs),
        )

        service.update_step2_result(
            project.id,
            _contract(_slide("slide_001"), _slide("slide_002", narration="更新旁白")),
            FakeDb(project),
        )

        assert len(calls) == 1
        # previous_contract 是 narration-only provenance 迁移的证据输入,
        # 必须等于落盘前的旧合约(经 normalize_visual_contract 归一)。
        expected_previous = service.normalize_visual_contract(
            json.loads(json.dumps(previous)), service.read_project_pipeline_profile(project)
        )
        assert calls[0].pop("previous_contract") == expected_previous
        assert calls == [
            {
                "visual_slide_ids": (),
                "narration_slide_ids": ("slide_002",),
                "added_slide_ids": (),
                "removed_slide_ids": (),
                "reordered": False,
            }
        ]
