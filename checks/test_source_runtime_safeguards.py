import json
from pathlib import Path
import subprocess

import pytest

import reveal_manifest_service
import server


class FakeProject:
    id = "source-safeguard"
    name = "正式源码项目"
    description = ""

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = str(run_dir)


def test_manifest_reconciliation_is_source_owned(tmp_path: Path) -> None:
    planning = tmp_path / "planning"
    planning.mkdir()
    (planning / "article_brief.json").write_text(
        json.dumps({"summary": "来自文章摘要"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (planning / "visual_contract.json").write_text(
        json.dumps(
            {
                "slides": [
                    {
                        "slide_id": "slide_001",
                        "visual_groups": [
                            {"id": "g1", "visible_text": "保留"},
                            {"id": "g2", "visible_text": "新增"},
                        ],
                        "narration_beats": [
                            {"id": "beat_1", "group_id": "g1"},
                            {"id": "beat_2", "group_id": "g2"},
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (tmp_path / "reveal_manifest.json").write_text(
        json.dumps(
            {
                "slides": [
                    {
                        "slide_id": "slide_001",
                        "groups": [
                            {"id": "g1", "strokes": [{"x": 1, "y": 2}]},
                            {"id": "manual_group_keep", "manual_mask": {"strokes": [{}]}},
                        ],
                        "semantic_blocks": [],
                    },
                    {"slide_id": "stale_slide", "groups": []},
                ]
            }
        ),
        encoding="utf-8",
    )
    project = FakeProject(tmp_path)

    assert reveal_manifest_service.sync_reveal_manifest(
        project,
        ["slide_001"],
    )

    contract = json.loads(
        (planning / "visual_contract.json").read_text(encoding="utf-8")
    )
    assert contract["topic"]["topic_summary"] == "来自文章摘要"
    manifest = json.loads(
        (tmp_path / "reveal_manifest.json").read_text(encoding="utf-8")
    )
    assert [slide["slide_id"] for slide in manifest["slides"]] == ["slide_001"]
    slide = manifest["slides"][0]
    by_id = {group["id"]: group for group in slide["groups"]}
    assert set(by_id) == {"g1", "g2", "manual_group_keep"}
    assert by_id["g1"]["strokes"] == [{"x": 1, "y": 2}]
    assert by_id["g1"]["narration_beat_id"] == "beat_1"
    assert by_id["g2"]["narration_beat_id"] == "beat_2"


def test_explicit_empty_storyboard_clears_manifest_slides(tmp_path: Path) -> None:
    planning = tmp_path / "planning"
    planning.mkdir()
    (planning / "visual_contract.json").write_text(
        json.dumps({"slides": []}),
        encoding="utf-8",
    )
    (tmp_path / "reveal_manifest.json").write_text(
        json.dumps({"slides": [{"slide_id": "slide_001"}]}),
        encoding="utf-8",
    )

    assert reveal_manifest_service.sync_reveal_manifest(
        FakeProject(tmp_path),
        [],
        allow_empty=True,
    )
    manifest = json.loads(
        (tmp_path / "reveal_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["slides"] == []


def test_bounded_subprocess_returns_timeout_result(monkeypatch: pytest.MonkeyPatch) -> None:
    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(["demo"], timeout=12, stderr="still running")

    monkeypatch.setattr(server.subprocess, "run", timeout)
    result = server.run_subprocess_bounded(["demo"], timeout_sec=12)

    assert result.returncode == 124
    assert "Timed out after 12 seconds" in result.stderr
    assert "still running" in result.stderr


def test_validator_stdout_is_json_safe() -> None:
    valid = subprocess.CompletedProcess([], 0, '{"ok": true}', "")
    invalid = subprocess.CompletedProcess([], 0, "not-json", "")

    assert server.parse_json_process_stdout(valid) == {"ok": True}
    assert server.parse_json_process_stdout(invalid) == {
        "parse_warning": "validator stdout was not valid JSON",
        "raw_stdout": "not-json",
    }
