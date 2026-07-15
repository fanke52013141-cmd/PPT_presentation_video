import hashlib
import json
from pathlib import Path

import server


class _Query:
    def __init__(self, project):
        self.project = project

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.project


class _Db:
    def __init__(self, project):
        self.project = project

    def query(self, *_args, **_kwargs):
        return _Query(self.project)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _project(tmp_path: Path) -> server.Project:
    return server.Project(
        id="read-only-project",
        name="read-only",
        run_dir=str(tmp_path),
        current_step=5,
    )


def test_project_result_gets_do_not_mutate_artifacts(tmp_path: Path) -> None:
    planning = tmp_path / "planning"
    planning.mkdir(parents=True)
    contract_path = planning / "visual_contract.json"
    manifest_path = tmp_path / "reveal_manifest.json"
    beats_path = planning / "narration_beats.json"
    contract_path.write_text(
        json.dumps({"topic": {"topic_name": "只读检查"}, "slides": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    manifest_path.write_text('{"slides": []}', encoding="utf-8")
    beats_path.write_text('{"slides": []}', encoding="utf-8")
    before = {path: _digest(path) for path in (contract_path, manifest_path, beats_path)}
    project = _project(tmp_path)
    db = _Db(project)

    assert server.get_step2_result(project.id, db)["success"] is True
    assert server.get_step5_result(project.id, db)["success"] is True
    assert server.get_step6_result(project.id, db)["success"] is True

    assert {path: _digest(path) for path in before} == before


def test_narration_repair_is_explicit_and_restores_contract_order(tmp_path: Path) -> None:
    planning = tmp_path / "planning"
    planning.mkdir(parents=True)
    (planning / "visual_contract.json").write_text(
        json.dumps({
            "slides": [
                {"slide_id": "slide_001", "narration_beats": [{"id": "beat_001", "spoken_text": "正文"}]},
                {"slide_id": "slide_002", "narration_beats": [{"id": "beat_002", "spoken_text": "结尾"}]},
            ]
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    beats_path = planning / "narration_beats.json"
    beats_path.write_text(
        json.dumps({"slides": [{"slide_id": "slide_old", "beats": []}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    project = _project(tmp_path)
    db = _Db(project)

    before = _digest(beats_path)
    read_result = server.get_step6_result(project.id, db)
    assert read_result["repair"]["required"] is True
    assert _digest(beats_path) == before

    repaired = server.repair_step6_result(project.id, db)
    assert repaired["changed"] is True
    assert [slide["slide_id"] for slide in repaired["beats"]["slides"]] == ["slide_001", "slide_002"]
