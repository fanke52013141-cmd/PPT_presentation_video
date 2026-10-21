# -*- coding: utf-8 -*-
"""Step 2 保存 CAS 回归(R4/Step2 并发遗留项):

- GET /steps/2/result 返回契约摘要;
- PUT 携带过期摘要时返回可恢复 409,且不产生任何落盘/归档/影响副作用;
- 相同摘要或无摘要(旧客户端)行为保持兼容。
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import storyboard_service
from storyboard_service import update_step2_result


CONTRACT = {
    "version": "visual_contract_v1",
    "topic": {"topic_id": "topic_p", "topic_name": "T", "topic_summary": ""},
    "slides": [
        {"slide_id": "slide_001", "main_title": "A", "core_message": "a", "body_content": ["a"], "visual_groups": []},
        {"slide_id": "slide_002", "main_title": "B", "core_message": "b", "body_content": ["b"], "visual_groups": []},
    ],
}


def _setup(tmp_path: Path):
    (tmp_path / "inputs").mkdir()
    (tmp_path / "planning").mkdir()
    contract_path = tmp_path / "planning" / "visual_contract.json"
    contract_path.write_text(json.dumps(CONTRACT, ensure_ascii=False), encoding="utf-8")
    return contract_path


def _baseline_sha(contract_path: Path) -> str:
    """CAS 基线 = GET 返回的规范化契约摘要(与前端拿到的 contract_sha256 一致)。"""
    from visual_contract_service import normalize_visual_contract

    stored = json.loads(contract_path.read_text(encoding="utf-8"))
    return storyboard_service.contract_canonical_sha256(
        normalize_visual_contract(stored, None)
    )


@pytest.mark.parametrize("valid", [False, True])
def test_manual_draft_completion_follows_validation(tmp_path, monkeypatch, valid):
    path = _setup(tmp_path)
    project = _project(tmp_path)
    statuses = {str(i): "completed" for i in range(1, 9)}
    project.get_step_status = lambda: dict(statuses)
    project.set_step_status = lambda value: statuses.update(value)
    _wire_real_dependencies(monkeypatch)
    monkeypatch.setattr(storyboard_service, "validate_visual_contract_file", lambda *a, **kw: {"valid": valid})
    synced = []
    for name in ("sync_reveal_manifest_to_contract", "sync_narration_beats_to_contract", "sync_narration_sources_from_contract"):
        monkeypatch.setattr(storyboard_service, name, lambda *a: synced.append(True))
    payload = json.loads(json.dumps(CONTRACT))
    payload["slides"][0]["main_title"] = "edited draft"
    db = SimpleNamespace(commit=lambda: None)
    storyboard_service._persist_step2_result_locked(
        project, payload, CONTRACT, ["slide_001", "slide_002"], str(path), db,
    )
    assert statuses["2"] == ("completed" if valid else "in_progress")
    assert bool(synced) is valid
    assert json.loads(path.read_text(encoding="utf-8"))["slides"][0]["main_title"] == "edited draft"


def _project(tmp_path: Path):
    return SimpleNamespace(
        id="p",
        name="T",
        run_dir=str(tmp_path),
        target_duration_sec=None,
        get_step_status=lambda: {"1": "completed"},
        set_step_status=lambda statuses: None,
        current_step=2,
    )


def _wire_real_dependencies(monkeypatch) -> None:
    """把服务层注入点接回真实实现(不导入 server 组合根)。"""
    import pipeline_lifecycle
    from visual_contract_service import (
        contract_slide_ids_from_payload as real_ids,
        normalize_visual_contract as real_normalize,
    )

    def read_json_file_with_fallback(path, fallback=None):
        value = pipeline_lifecycle.read_json_file(path)
        return fallback if value is None else value

    monkeypatch.setattr(storyboard_service, "read_json_file", read_json_file_with_fallback)
    monkeypatch.setattr(storyboard_service, "normalize_visual_contract", real_normalize)
    monkeypatch.setattr(storyboard_service, "contract_slide_ids_from_payload", real_ids)


def _service_call(tmp_path: Path, monkeypatch, payload: dict):
    project = _project(tmp_path)
    monkeypatch.setattr(storyboard_service, "project_or_404", lambda _db, _pid: project)
    monkeypatch.setattr(storyboard_service, "read_project_pipeline_profile", lambda _project: None)
    monkeypatch.setattr(storyboard_service, "validate_visual_contract_file", lambda *a, **k: {"valid": True})
    monkeypatch.setattr(storyboard_service, "sync_reveal_manifest_to_contract", lambda *a, **k: None)
    monkeypatch.setattr(storyboard_service, "sync_narration_beats_to_contract", lambda *a, **k: None)
    monkeypatch.setattr(storyboard_service, "sync_narration_sources_from_contract", lambda *a, **k: None)
    monkeypatch.setattr(storyboard_service, "apply_storyboard_contract_impact", lambda *a, **k: None)
    monkeypatch.setattr(storyboard_service, "write_project_log", lambda *a, **k: None)
    _wire_real_dependencies(monkeypatch)
    from database import SessionLocal

    db = SessionLocal()
    try:
        return update_step2_result("p", payload, db)
    finally:
        db.close()


def test_get_result_exposes_contract_sha256(tmp_path: Path, monkeypatch) -> None:
    _setup(tmp_path)
    monkeypatch.setattr(storyboard_service, "project_or_404", lambda _db, _pid: _project(tmp_path))
    monkeypatch.setattr(storyboard_service, "read_project_pipeline_profile", lambda _project: None)
    _wire_real_dependencies(monkeypatch)
    result = storyboard_service.get_step2_result("p", None)
    assert result["success"] is True
    assert result["contract_sha256"] == storyboard_service.contract_canonical_sha256(result["contract"])


def test_stale_snapshot_save_rejected_with_409_and_no_side_effects(tmp_path: Path, monkeypatch) -> None:
    contract_path = _setup(tmp_path)
    original_sha = _baseline_sha(contract_path)
    # 基线:与其他窗口并发,先保存一版新内容
    changed = json.loads(json.dumps(CONTRACT, ensure_ascii=False))
    changed["slides"][0]["main_title"] = "A2"
    first = _service_call(tmp_path, monkeypatch, {**changed, "expected_contract_sha256": original_sha})
    assert first["changed"] is True
    fresh_sha = first["contract_sha256"]
    archived = tmp_path / "archived_slides"
    impacts_dir_before = sorted(p.name for p in (tmp_path).rglob("*") if p.is_file())

    # 过期快照(仍带旧基线摘要)后到:必须 409,不允许覆盖
    stale = json.loads(json.dumps(CONTRACT, ensure_ascii=False))
    stale["slides"][0]["main_title"] = "STALE-OVERWRITE"
    with pytest.raises(HTTPException) as exc:
        _service_call(tmp_path, monkeypatch, {**stale, "expected_contract_sha256": original_sha})
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "storyboard_conflict"
    assert exc.value.detail["current_contract_sha256"] == fresh_sha

    # 无任何副作用:文件未回退、无归档产生
    on_disk = json.loads(contract_path.read_text(encoding="utf-8"))
    assert on_disk["slides"][0]["main_title"] == "A2"
    assert not archived.exists()
    assert sorted(p.name for p in (tmp_path).rglob("*") if p.is_file()) == impacts_dir_before

    # 携带最新摘要的保存正常落盘
    ok = _service_call(tmp_path, monkeypatch, {**stale, "expected_contract_sha256": fresh_sha})
    assert ok["changed"] is True
    assert json.loads(contract_path.read_text(encoding="utf-8"))["slides"][0]["main_title"] == "STALE-OVERWRITE"


def test_blank_slide_id_rejected_at_user_write(tmp_path: Path, monkeypatch) -> None:
    from visual_contract_service import validate_slide_identifiers

    contract_path = _setup(tmp_path)
    # 共享 normalize(旧工件修复路径)保持对空白 ID 宽容
    validate_slide_identifiers({"slides": [{"slide_id": "slide_001"}, {}]})
    # 用户手写保存入口拒绝空白 ID,且不落盘
    bad = json.loads(json.dumps(CONTRACT, ensure_ascii=False))
    bad["slides"][1]["slide_id"] = "   "
    with pytest.raises(HTTPException) as exc:
        _service_call(tmp_path, monkeypatch, bad)
    assert exc.value.status_code == 400
    on_disk = json.loads(contract_path.read_text(encoding="utf-8"))
    assert on_disk["slides"][0]["main_title"] == "A"


def test_save_without_hash_stays_compatible(tmp_path: Path, monkeypatch) -> None:
    contract_path = _setup(tmp_path)
    changed = json.loads(json.dumps(CONTRACT, ensure_ascii=False))
    changed["slides"][0]["main_title"] = "A3"
    result = _service_call(tmp_path, monkeypatch, changed)
    assert result["changed"] is True
    assert json.loads(contract_path.read_text(encoding="utf-8"))["slides"][0]["main_title"] == "A3"
