from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import server
from scripts.write_narration_from_visual_contract import spoken_text_for_beat


ROOT = Path(__file__).resolve().parents[1]


def _contract(text: str) -> dict:
    return {
        "version": "visual_contract_v1",
        "presentation_policy": {
            "subtitle_policy": "no_slides_have_subtitle",
            "subtitle_decided_by": "system_no_subtitle_contract",
            "visual_narration_mapping": "manual_free_v1",
        },
        "slides": [
            {
                "slide_id": "slide_001",
                "main_title": "标题",
                "visual_groups": [],
                "narration_beats": [
                    {
                        "id": "slide_001_beat_001",
                        "group_id": None,
                        "content_unit_id": "slide_001_unit_001",
                        "spoken_intent": "说明标题",
                        "spoken_text": text,
                    }
                ],
            }
        ],
    }


def test_existing_manual_narration_is_never_truncated() -> None:
    source = "这是一段由用户完整写入的长演讲稿，" * 20
    assert spoken_text_for_beat({"spoken_text": source}, None, 40) == source


def test_manual_contract_rejects_empty_spoken_text(tmp_path: Path) -> None:
    contract_path = tmp_path / "visual_contract.json"
    contract_path.write_text(json.dumps(_contract(""), ensure_ascii=False), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "validate_visual_contract.py"), "--contract", str(contract_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode != 0
    assert "empty spoken_text" in result.stderr


def test_step2_source_sync_preserves_unchanged_tts_and_updates_changed_text(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    planning = run_dir / "planning"
    planning.mkdir(parents=True)
    previous = _contract("原始旁白。")
    current = _contract("原始旁白。")
    (planning / "visual_contract.json").write_text(
        json.dumps(current, ensure_ascii=False), encoding="utf-8"
    )
    existing = {
        "slides": [{
            "slide_id": "slide_001",
            "beats": [{
                **current["slides"][0]["narration_beats"][0],
                "source_text": "原始旁白。",
                "spoken_text": "原始旁白。",
                "tts_text": "原始旁白。<#0.4#>(breath)",
            }],
        }],
    }
    (planning / "narration_beats.json").write_text(
        json.dumps(existing, ensure_ascii=False), encoding="utf-8"
    )
    project = SimpleNamespace(run_dir=str(run_dir))

    assert server.sync_narration_sources_from_contract(project, previous, current) is False
    unchanged = json.loads((planning / "narration_beats.json").read_text(encoding="utf-8"))
    assert unchanged["slides"][0]["beats"][0]["tts_text"] == "原始旁白。<#0.4#>(breath)"

    changed = _contract("修改后的完整旁白。")
    (planning / "visual_contract.json").write_text(
        json.dumps(changed, ensure_ascii=False), encoding="utf-8"
    )
    assert server.sync_narration_sources_from_contract(project, previous, changed) is True
    updated = json.loads((planning / "narration_beats.json").read_text(encoding="utf-8"))
    beat = updated["slides"][0]["beats"][0]
    assert beat["source_text"] == "修改后的完整旁白。"
    assert beat["spoken_text"] == "修改后的完整旁白。"
    assert beat["tts_text"] == "修改后的完整旁白。"


def test_subtitle_style_round_trips_all_user_controls() -> None:
    normalized = server.normalize_subtitle_style({
        "font_key": "noto_serif_sc",
        "font_size": 54,
        "font_weight": 700,
        "bottom": 80,
        "horizontal_margin": 240,
        "color": "#223344",
        "highlight_color": "#AABBCC",
        "paging_window_ms": 900,
        "token_highlight": False,
        "max_lines": 3,
        "line_height": 1.6,
    })
    assert normalized["font_size"] == 54
    assert normalized["color"] == "#223344"
    assert normalized["highlight_color"] == "#AABBCC"
    assert normalized["paging_window_ms"] == 900
    assert normalized["token_highlight"] is False
    assert normalized["max_lines"] == 3
    assert normalized["line_height"] == 1.6
