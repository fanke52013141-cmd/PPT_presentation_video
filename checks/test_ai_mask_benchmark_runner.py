"""Pure-function tests for the isolated benchmark runner (handoff W0).

Importing ``checks.ai_mask_benchmark.runner`` must not touch the database, the
real runs directory or the network, so this module doubles as the guard for that
import-order requirement.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from checks.ai_mask_benchmark import runner


def _report(case_id: str, repeat: int, **overrides) -> dict:
    base = {
        "case_id": case_id,
        "repeat": repeat,
        "annotate_seconds": 5.0,
        "review_required": False,
        "rle_fingerprint": f"{case_id}-{repeat}",
        "score": {
            "group_count": 4,
            "macro_group_recall": 0.5,
            "macro_ownership_iou_on_truth": 0.4,
            "correct_ownership_ratio": 0.3,
            "ink_recall": 1.0,
            "correct_ink_ownership": 0.25,
            "protected_white_recall": None,
            "overlap_pixels_all_canvas": 0,
            "exterior_mask_pixels": 0,
            "missing_group_ids": ["g_2"],
            "unknown_group_ids": [],
            "review_assertion_passed": True,
        },
    }
    base.update(overrides)
    return base


def test_importing_the_runner_stays_side_effect_free() -> None:
    # No isolated environment was configured by this test module, so a bare
    # import must not have created the live database or runs directory handles.
    import os

    assert "PPT_STUDIO_DB_PATH" not in os.environ or Path(
        os.environ["PPT_STUDIO_DB_PATH"]
    ).exists()


def test_aggregate_averages_repeats_and_flags_review_mismatch() -> None:
    reports = [
        _report("case_a", 1),
        _report("case_a", 2, annotate_seconds=7.0),
        _report(
            "case_b",
            1,
            review_required=True,
            score={
                **_report("case_b", 1)["score"],
                "macro_group_recall": 1.0,
                "missing_group_ids": [],
                "review_assertion_passed": False,
            },
        ),
    ]
    summary = runner._aggregate(reports, repeats=2)
    assert summary["case_count"] == 2
    assert summary["cases_requiring_review"] == 1
    assert summary["cases_passed_review_assertion"] == 1
    assert summary["cases_with_missing_groups"] == 1
    assert summary["per_case"]["case_a"]["repeats"] == 2
    assert summary["per_case"]["case_a"]["annotate_seconds"] == 6.0
    assert summary["per_case"]["case_a"]["missing_group_ids"] == ["g_2"]
    # ``protected_white_recall`` stays None when no case defines protected white.
    assert summary["mean"]["protected_white_recall"] is None
    assert summary["mean"]["macro_group_recall"] == 0.75
    assert summary["annotate_seconds"] == {"median": 5.0, "p95": 7.0, "max": 7.0}


def test_settings_override_records_the_abet_config() -> None:
    layout_off = argparse.Namespace(settings_json=None, layout="off")
    assert runner.settings_override_summary(layout_off) == {
        "source": "--layout",
        "override": {"doclayout_enabled": False},
    }
    frozen = Path(__file__).parent / "ai_mask_benchmark" / "_frozen_settings.json"
    frozen.write_text('{"closing_radius": 3}', encoding="utf-8")
    try:
        override = runner.settings_override_summary(
            argparse.Namespace(settings_json=str(frozen), layout="on")
        )
        assert override == {"source": frozen.name, "override": {"closing_radius": 3}}
    finally:
        frozen.unlink()
    defaults = argparse.Namespace(settings_json=None, layout=None)
    assert runner.settings_override_summary(defaults)["source"] == "production_defaults"


def test_aggregate_reports_stage_timing_and_layout_states() -> None:
    reports = [
        _report("case_a", 1, stage_ms={"foreground": 100.0, "vision": 900.0},
                layout_status_counts={"disabled": 1}),
        _report("case_a", 2, stage_ms={"foreground": 200.0, "vision": 300.0},
                layout_status_counts={"disabled": 1}),
        _report("case_b", 1, stage_ms={"foreground": 50.0},
                layout_status_counts={"no_boxes": 1}),
    ]
    summary = runner._aggregate(reports, repeats=2)
    # A stage only measured on some pages averages over the pages that reported
    # it, so a missing stage never dilutes the comparison between A/B arms.
    assert summary["stage_ms_mean"]["vision"] == 600.0
    assert summary["stage_ms_mean"]["foreground"] == round(350.0 / 3.0, 6)
    # The mean hides the slow page, so the tail is reported per stage as well.
    assert summary["stage_ms_percentiles"] == {
        "foreground": {"p50": 100.0, "p95": 200.0},
        "vision": {"p50": 300.0, "p95": 900.0},
    }
    assert summary["layout_status_counts"] == {"disabled": 2, "no_boxes": 1}

    # Reports written before the stage-timing work package must still aggregate.
    legacy = runner._aggregate([_report("case_a", 1)], repeats=1)
    assert legacy["stage_ms_mean"] == {}
    assert legacy["stage_ms_percentiles"] == {}
    assert legacy["layout_status_counts"] == {}
