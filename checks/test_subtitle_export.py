from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import subtitle_export_routes as routes
from subtitle_export_service import SubtitleExportError, build_subtitle_export


def _write_slide(
    run_dir: Path,
    slide_id: str,
    *,
    srt: str,
    timeline: dict,
) -> None:
    slide_dir = run_dir / "slides" / slide_id
    slide_dir.mkdir(parents=True, exist_ok=True)
    (slide_dir / "subtitles.srt").write_text(srt, encoding="utf-8")
    (slide_dir / "audio_timeline.json").write_text(
        json.dumps(timeline), encoding="utf-8"
    )


def test_subtitle_export_merges_contract_order_offsets_and_reindexes(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "project-a"
    _write_slide(
        run_dir,
        "slide_002",
        srt="9\n00:00:00,000 --> 00:00:01,000\n第二页\n",
        timeline={"audio_start_sec": 0.5, "duration_sec": 2.0},
    )
    _write_slide(
        run_dir,
        "slide_001",
        srt=(
            "7\n00:00:00,000 --> 00:00:01,000\n第一页甲\n\n"
            "8\n00:00:01,100 --> 00:00:02,000\n第一页乙\n"
        ),
        timeline={
            "audio_start_sec": 0.25,
            "audio_content_duration_sec": 2.0,
            "duration_sec": 2.25,
            "segments": [{"start": 0, "end": 2.0}],
        },
    )

    result = build_subtitle_export(run_dir, ["slide_001", "slide_002"])

    assert result.slide_count == 2
    assert result.cue_count == 3
    assert result.content == (
        "1\n00:00:00,250 --> 00:00:01,250\n第一页甲\n\n"
        "2\n00:00:01,350 --> 00:00:02,250\n第一页乙\n\n"
        "3\n00:00:02,750 --> 00:00:03,750\n第二页\n"
    )


def test_subtitle_export_refuses_missing_or_invalid_subtitles(tmp_path: Path) -> None:
    run_dir = tmp_path / "project-a"
    _write_slide(
        run_dir,
        "slide_001",
        srt="not a subtitle",
        timeline={"duration_sec": 1},
    )
    with pytest.raises(SubtitleExportError, match="SRT 字幕块格式无效"):
        build_subtitle_export(run_dir, ["slide_001"])

    (run_dir / "slides" / "slide_001" / "subtitles.srt").unlink()
    with pytest.raises(SubtitleExportError, match="缺少字幕文件"):
        build_subtitle_export(run_dir, ["slide_001"])


def test_subtitle_export_treats_legacy_missing_audio_start_as_zero(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "project-a"
    _write_slide(
        run_dir,
        "slide_001",
        srt="1\n00:00:00,000 --> 00:00:01,000\n兼容旧时间线\n",
        timeline={"duration_sec": 1, "segments": [{"end": 1}]},
    )
    result = build_subtitle_export(run_dir, ["slide_001"])
    assert "00:00:00,000 --> 00:00:01,000" in result.content


def test_subtitle_export_rejects_path_escape_and_project_isolation(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "project-a"
    _write_slide(
        tmp_path / "runs" / "project-b",
        "slide_001",
        srt="1\n00:00:00,000 --> 00:00:01,000\n不应读取\n",
        timeline={"duration_sec": 1},
    )
    with pytest.raises(SubtitleExportError, match="无效页面"):
        build_subtitle_export(run_dir, ["../project-b"])
    with pytest.raises(SubtitleExportError, match="缺少字幕文件"):
        build_subtitle_export(run_dir, ["slide_001"])


def test_subtitle_download_route_returns_srt_headers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "route-project"
    _write_slide(
        run_dir,
        "slide_001",
        srt="1\n00:00:00,000 --> 00:00:01,000\n路由字幕\n",
        timeline={"audio_start_sec": 0, "duration_sec": 1},
    )
    project = SimpleNamespace(id="route-project", run_dir=str(run_dir))
    monkeypatch.setattr(routes, "project_or_404", lambda _db, _id: project)
    monkeypatch.setattr(routes, "project_run_dir_or_500", lambda _project: str(run_dir))
    monkeypatch.setattr(routes, "read_current_slide_ids_or_404", lambda _project: ["slide_001"])

    readiness = routes.get_subtitle_export_readiness("route-project", object())
    response = routes.download_subtitles_srt("route-project", object())

    assert readiness["ready"] is True
    assert response.headers["content-type"] == "text/srt; charset=utf-8"
    assert response.headers["content-disposition"] == (
        'attachment; filename="route-project-subtitles.srt"'
    )
    assert response.body.decode("utf-8").endswith("路由字幕\n")
