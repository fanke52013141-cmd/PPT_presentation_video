from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import narration_audio_service as service  # noqa: E402


def _read_json(path: str, fallback: Any) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return fallback


def _write_json(path: str, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _read_slide_ids(run_dir: str) -> list[str]:
    contract = _read_json(
        str(Path(run_dir) / "planning" / "visual_contract.json"),
        {},
    )
    return [
        str(slide.get("slide_id") or "").strip()
        for slide in contract.get("slides", [])
        if isinstance(slide, dict)
        and str(slide.get("slide_id") or "").strip()
    ]


def _dedupe(beats: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for beat in beats if isinstance(beats, list) else []:
        if not isinstance(beat, dict):
            continue
        beat_id = str(beat.get("id") or "").strip()
        if beat_id and beat_id in seen:
            continue
        if beat_id:
            seen.add(beat_id)
        result.append(dict(beat))
    return result


@pytest.fixture(autouse=True)
def configured_dependencies() -> None:
    original = service._dependencies
    service.configure_narration_audio_dependencies(
        service.NarrationAudioDependencies(
            dedupe_narration_beats=_dedupe,
            probe_media_duration_sec=lambda *_args, **_kwargs: None,
            read_contract_slide_ids=_read_slide_ids,
            read_json_file=_read_json,
            write_json_atomic=_write_json,
            repo_root=ROOT,
        )
    )
    try:
        yield
    finally:
        service._dependencies = original


def _contract(text: str) -> dict[str, Any]:
    return {
        "slides": [
            {
                "slide_id": "slide_001",
                "narration_beats": [
                    {
                        "id": "beat_001",
                        "group_id": "group_001",
                        "spoken_text": text,
                    }
                ],
            }
        ]
    }


def test_module_owns_narration_audio_logic_without_app_wiring() -> None:
    source = (ROOT / "narration_audio_service.py").read_text(
        encoding="utf-8"
    )
    server_source = (ROOT / "server.py").read_text(encoding="utf-8")
    for forbidden in (
        "APIRouter",
        "Depends(",
        "get_db",
        "server_module",
        "import server",
    ):
        assert forbidden not in source
    for function_name in (
        "clean_tts_text",
        "prepare_narration_payload",
        "sync_narration_sources_from_contract",
        "rewrite_audio_timeline_by_beats",
    ):
        assert f"def {function_name}(" in source
        assert f"def {function_name}(" not in server_source
    assert "configure_narration_audio_dependencies(" in server_source


def test_markup_normalization_and_pause_parts_preserve_plain_tags() -> None:
    text = "说明 (REST) API，<#0.30#><#0.5#>(breath)继续。"
    assert service.normalize_minimax_tts_markup(text) == (
        "说明 (REST) API，<#0.3#> (breath)继续。"
    )
    assert service.clean_tts_text(text) == "说明 (REST) API，继续。"
    assert service.tts_text_parts_with_pauses(text) == [
        {"type": "text", "text": "说明 (REST) API，"},
        {"type": "pause", "duration": 0.3},
        {"type": "pause", "duration": 0.5},
        {"type": "text", "text": "继续。"},
    ]
    annotated = service.ensure_minimax_delivery_markup(
        "这是一段足够长的演讲稿，需要自然地添加停顿。"
    )
    assert "<#0.35#>" in annotated


def test_source_sync_preserves_custom_tts_until_source_changes(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    planning = run_dir / "planning"
    planning.mkdir(parents=True)
    previous = _contract("原始旁白。")
    current = _contract("原始旁白。")
    _write_json(str(planning / "visual_contract.json"), current)
    _write_json(
        str(planning / "narration_beats.json"),
        {
            "slides": [
                {
                    "slide_id": "slide_001",
                    "beats": [
                        {
                            **current["slides"][0]["narration_beats"][0],
                            "source_text": "原始旁白。",
                            "spoken_text": "原始旁白。",
                            "tts_text": "原始旁白。<#0.4#>(breath)",
                        }
                    ],
                }
            ]
        },
    )
    project = SimpleNamespace(run_dir=str(run_dir))

    assert (
        service.sync_narration_sources_from_contract(
            project,
            previous,
            current,
        )
        is False
    )
    unchanged = _read_json(
        str(planning / "narration_beats.json"),
        {},
    )
    assert unchanged["slides"][0]["beats"][0]["tts_text"] == (
        "原始旁白。<#0.4#>(breath)"
    )

    changed = _contract("修改后的完整旁白。")
    assert service.sync_narration_sources_from_contract(
        project,
        previous,
        changed,
    )
    updated = _read_json(str(planning / "narration_beats.json"), {})
    beat = updated["slides"][0]["beats"][0]
    assert beat["source_text"] == "修改后的完整旁白。"
    assert beat["spoken_text"] == "修改后的完整旁白。"
    assert beat["tts_text"] == "修改后的完整旁白。"


def test_persistence_writes_global_and_per_slide_contracts(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    planning = run_dir / "planning"
    planning.mkdir(parents=True)
    _write_json(
        str(planning / "visual_contract.json"),
        _contract("第一句，第二句。"),
    )
    project = SimpleNamespace(run_dir=str(run_dir))
    payload = {
        "slides": [
            {
                "slide_id": "slide_001",
                "beats": [
                    {
                        "id": "beat_001",
                        "group_id": "group_001",
                        "spoken_text": "第一句，第二句。",
                        "tts_text": "第一句，<#0.35#>第二句。",
                    }
                ],
            }
        ]
    }

    persisted = service.persist_narration_beats(project, payload)

    assert persisted["slides"][0]["beats"][0]["source_text"] == (
        "第一句，第二句。"
    )
    assert (planning / "narration_beats.json").exists()
    assert (planning / "narration.txt").read_text(
        encoding="utf-8"
    ) == "=== slide_001 ===\n[group_001] 第一句，第二句。\n"
    assert "<#0.35#>" in (planning / "tts_text.txt").read_text(
        encoding="utf-8"
    )
    slide_dir = run_dir / "slides" / "slide_001"
    assert (slide_dir / "narration.txt").read_text(
        encoding="utf-8"
    ) == "第一句，第二句。\n"
    assert (slide_dir / "tts_text.txt").read_text(
        encoding="utf-8"
    ) == "第一句，<#0.35#>第二句。\n"
    assert _read_json(
        str(slide_dir / "narration_beats.json"),
        {},
    )["slide_id"] == "slide_001"


def test_persistence_is_idempotent_when_content_unchanged(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    planning = run_dir / "planning"
    planning.mkdir(parents=True)
    _write_json(
        str(planning / "visual_contract.json"),
        _contract("第一句，第二句。"),
    )
    project = SimpleNamespace(run_dir=str(run_dir))
    payload = {
        "slides": [
            {
                "slide_id": "slide_001",
                "beats": [
                    {
                        "id": "beat_001",
                        "group_id": "group_001",
                        "spoken_text": "第一句，第二句。",
                        "tts_text": "第一句，<#0.35#>第二句。",
                    }
                ],
            }
        ]
    }

    service.persist_narration_beats(project, payload)
    slide_dir = run_dir / "slides" / "slide_001"
    tts_text_path = slide_dir / "tts_text.txt"
    narration_path = slide_dir / "narration.txt"
    beats_path = slide_dir / "narration_beats.json"

    # 模拟 Step 7 已生成的音频产物（晚于 tts_text.txt）。
    audio_path = slide_dir / "voice.mp3"
    audio_path.write_bytes(b"fake-audio")
    text_mtime = tts_text_path.stat().st_mtime_ns
    beats_mtime = beats_path.stat().st_mtime_ns
    narration_mtime = narration_path.stat().st_mtime_ns

    # 同一内容重复持久化：不得触碰任何触发过期判定的文件 mtime。
    service.persist_narration_beats(project, dict(payload))
    assert tts_text_path.stat().st_mtime_ns == text_mtime
    assert narration_path.stat().st_mtime_ns == narration_mtime
    assert beats_path.stat().st_mtime_ns == beats_mtime
    assert tts_text_path.read_text(encoding="utf-8") == (
        "第一句，<#0.35#>第二句。\n"
    )

    # 内容真正变化时必须重写：先把文本 mtime 回拨 1 秒，
    # 使“重写后 mtime 前移”成为跨文件系统的确定性断言。
    backdated_ns = text_mtime - 1_000_000_000
    os.utime(tts_text_path, ns=(backdated_ns, backdated_ns))
    changed = {
        "slides": [
            {
                "slide_id": "slide_001",
                "beats": [
                    {
                        "id": "beat_001",
                        "group_id": "group_001",
                        "spoken_text": "全新的演讲稿内容。",
                        "tts_text": "全新的<#0.35#>演讲稿内容。",
                    }
                ],
            }
        ]
    }
    service.persist_narration_beats(project, changed)
    assert tts_text_path.stat().st_mtime_ns > backdated_ns
    assert tts_text_path.read_text(encoding="utf-8") == (
        "全新的<#0.35#>演讲稿内容。\n"
    )
    assert audio_path.read_bytes() == b"fake-audio"


def test_provider_timestamps_map_to_beats_and_use_probed_duration(
    tmp_path: Path,
) -> None:
    timeline_path = tmp_path / "audio_timeline.json"
    _write_json(
        str(timeline_path),
        {
            "audio_start_sec": 0.5,
            "audio_content_duration_sec": 3.0,
            "duration_sec": 3.5,
            "timing_source": "provider_sentence_timestamps",
            "segments": [
                {"id": "old_1", "text": "第一段", "start": 0.0, "end": 1.0},
                {"id": "old_2", "text": "第二段", "start": 1.0, "end": 3.0},
            ],
        },
    )
    original = service._deps()
    service.configure_narration_audio_dependencies(
        replace(
            original,
            probe_media_duration_sec=(
                lambda *_args, **_kwargs: 4.25
            ),
        )
    )

    service.rewrite_audio_timeline_by_beats(
        str(timeline_path),
        "slide_001",
        [
            {"id": "beat_001", "spoken_text": "这是第一段。"},
            {"id": "beat_002", "spoken_text": "这是第二段。"},
        ],
    )

    timeline = _read_json(str(timeline_path), {})
    assert [item["beat_id"] for item in timeline["segments"]] == [
        "beat_001",
        "beat_002",
    ]
    assert timeline["audio_content_duration_sec"] == 4.25
    assert timeline["duration_sec"] == 4.75
    assert timeline["duration_source"] == "local_audio_ffprobe"
    assert timeline["probed_audio_duration_sec"] == 4.25


def test_estimated_timeline_caps_pause_budget_and_fills_duration(
    tmp_path: Path,
) -> None:
    timeline_path = tmp_path / "audio_timeline.json"
    _write_json(
        str(timeline_path),
        {
            "audio_content_duration_sec": 2.0,
            "duration_sec": 2.0,
        },
    )

    service.rewrite_audio_timeline_by_beats(
        str(timeline_path),
        "slide_001",
        [
            {
                "id": "beat_001",
                "tts_text": (
                    "前半段清晰说明。<#10#>"
                    "后半段继续补充完整内容。"
                ),
            }
        ],
    )

    timeline = _read_json(str(timeline_path), {})
    assert timeline["timing_source"] == (
        "beat_pause_aware_estimated_split"
    )
    assert timeline["explicit_pause_sec"] == 0.9
    assert timeline["segments"][0]["start"] == 0.0
    assert timeline["segments"][-1]["end"] == 2.0
    assert timeline["subtitle_display"] == {
        "max_lines": 1,
        "max_cjk_chars": 26,
    }
    assert all(
        segment["timing_source"]
        == "beat_pause_aware_estimated_split"
        for segment in timeline["segments"]
    )
