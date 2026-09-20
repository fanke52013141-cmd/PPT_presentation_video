"""Isolated end-to-end AI Mask benchmark runner (handoff W0).

Runs the real production annotation pipeline (DocLayout + detection +
semantic matcher + assignment + manifest apply) against the 16 fixed synthetic
fixtures inside a throw-away database and runs directory, exports
``mask_prediction_v1`` files, and scores them with the bundle evaluator.

By default no remote vision model is configured (fresh isolated settings store
-> empty ``llm_api_key`` -> the semantic matcher returns None and the
deterministic fallback path is measured).  Pass ``--vision-base-url`` +
``--vision-api-key`` + ``--vision-model`` to run the real multimodal path;
the estimated request budget is printed and stored in the report.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import secrets
import shutil
import time
from typing import Any

from checks.ai_mask_benchmark.project_fixture import (
    DEFAULT_BUNDLE,
    REPO_ROOT,
    FixtureCase,
    configure_isolation,
    create_case_project,
    discover_cases,
    export_prediction,
    load_composition_root,
    rle_fingerprint,
    score_prediction,
    side_effect_free_preflight,
)


def settings_override_summary(args: argparse.Namespace) -> dict[str, Any]:
    """Record exactly which AI Mask settings a run deviated from defaults."""
    if args.settings_json:
        return {
            "source": Path(args.settings_json).name,
            "override": json.loads(Path(args.settings_json).read_text(encoding="utf-8")),
        }
    if args.layout is not None:
        return {"source": "--layout", "override": {"doclayout_enabled": args.layout == "on"}}
    return {"source": "production_defaults", "override": {}}


def _code_fingerprint() -> dict[str, Any]:
    """Record what the numbers were produced by, so A/B rounds stay honest."""
    from checks.ai_mask_benchmark.freeze_baseline import (
        PRODUCTION_SOURCES,
        git_info,
        sha256_file,
    )

    return {
        "git": git_info(),
        "source_sha256": {
            relative: sha256_file(REPO_ROOT / relative) for relative in PRODUCTION_SOURCES
        },
    }


def _mean(values: list[float]) -> float | None:
    finite = [float(value) for value in values if value is not None]
    return round(sum(finite) / len(finite), 6) if finite else None


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return round(ordered[index], 3)


def _merge_counts(counts: list[dict[str, int]]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for entry in counts:
        for key, value in entry.items():
            merged[key] = merged.get(key, 0) + int(value)
    return merged


SCORE_MEANS = (
    "macro_group_recall",
    "macro_ownership_iou_on_truth",
    "correct_ownership_ratio",
    "ink_recall",
    "correct_ink_ownership",
    "protected_white_recall",
    "overlap_pixels_all_canvas",
    "exterior_mask_pixels",
)


def _aggregate(reports: list[dict[str, Any]], repeats: int) -> dict[str, Any]:
    per_case: dict[str, Any] = {}
    for case_id in sorted({str(report["case_id"]) for report in reports}):
        rows = [report for report in reports if report["case_id"] == case_id]
        means = {
            key: _mean([float(row["score"][key]) for row in rows if row["score"].get(key) is not None])
            for key in SCORE_MEANS
        }
        per_case[case_id] = {
            "repeats": len(rows),
            **means,
            "truth_groups_total": max(
                int(row["score"].get("group_count") or 0) for row in rows
            ),
            "missing_group_ids": sorted(
                {gid for row in rows for gid in row["score"].get("missing_group_ids") or []}
            ),
            "unknown_group_ids": sorted(
                {gid for row in rows for gid in row["score"].get("unknown_group_ids") or []}
            ),
            "review_required": any(bool(row.get("review_required")) for row in rows),
            "review_assertion_passed": all(
                row["score"].get("review_assertion_passed") is True for row in rows
            ),
            "annotate_seconds": _mean(
                [float(row["annotate_seconds"]) for row in rows]
            ),
        }
    timings = [float(report["annotate_seconds"]) for report in reports]
    return {
        "case_count": len(per_case),
        "repeats": repeats,
        "cases_passed_review_assertion": sum(
            1 for entry in per_case.values() if entry["review_assertion_passed"]
        ),
        "cases_requiring_review": sum(1 for entry in per_case.values() if entry["review_required"]),
        "cases_with_missing_groups": sum(
            1 for entry in per_case.values() if entry["missing_group_ids"]
        ),
        "mean": {key: _mean([entry[key] for entry in per_case.values()]) for key in SCORE_MEANS},
        "stage_ms_mean": {
            stage: _mean([(report.get("stage_ms") or {}).get(stage) for report in reports])
            for stage in sorted({
                stage for report in reports for stage in (report.get("stage_ms") or {})
            })
        },
        "layout_status_counts": _merge_counts(
            [report.get("layout_status_counts") or {} for report in reports]
        ),
        "annotate_seconds": {
            "median": _percentile(timings, 0.5),
            "p95": _percentile(timings, 0.95),
            "max": round(max(timings), 3) if timings else None,
        },
        "per_case": per_case,
    }


def _configure_vision_settings(server_module: Any, args: argparse.Namespace) -> dict[str, Any]:
    from config_store import update_settings

    updates: dict[str, Any] = {}
    if args.vision_api_key:
        updates["llm_api_key"] = args.vision_api_key
    if args.vision_base_url:
        updates["llm_base_url"] = args.vision_base_url
    if args.vision_model:
        updates["vision_model"] = args.vision_model
        updates["llm_model"] = args.vision_model
    if updates:
        update_settings(updates)
    return {
        "remote_vision_configured": bool(args.vision_api_key and args.vision_base_url and args.vision_model),
        "vision_model": args.vision_model or "",
        "provider": args.vision_provider or "",
    }


def _run_case(
    server_module: Any,
    case: FixtureCase,
    args: argparse.Namespace,
    runs_dir: Path,
    out_dir: Path,
    repeat: int,
) -> dict[str, Any]:
    from ai_mask_service import get_ai_mask_task_service
    from database import SessionLocal

    db = SessionLocal()
    try:
        project_id = f"maskbench_{case.case_id}_{args.run_id}_r{repeat}"
        project = create_case_project(server_module, db, case, runs_dir, project_id)
        settings_override: dict[str, Any] | None = None
        if args.settings_json:
            settings_override = json.loads(Path(args.settings_json).read_text(encoding="utf-8"))
        elif args.layout is not None:
            settings_override = {"doclayout_enabled": args.layout == "on"}
        started = time.perf_counter()
        result = get_ai_mask_task_service().annotate_project(
            project, settings_override, [case.case_id]
        )
        annotate_seconds = time.perf_counter() - started
        prediction_path = out_dir / "prediction.json"
        prediction = export_prediction(Path(project.run_dir), case.case_id, prediction_path)
        score = score_prediction(case, prediction_path, args.bundle)
        report: dict[str, Any] = {
            "case_id": case.case_id,
            "repeat": repeat,
            "project_id": project_id,
            "annotate_seconds": round(annotate_seconds, 3),
            "quality_status": result.get("quality_status"),
            "review_required": result.get("review_required"),
            "review_issue_count": result.get("review_issue_count"),
            "processed_slide_count": result.get("processed_slide_count"),
            "updated_group_count": result.get("updated_group_count"),
            "stage_ms": result.get("timing_ms") or {},
            "layout_status_counts": result.get("layout_status_counts") or {},
            # Full per-slide detail (including every review message) stays in
            # pipeline_result.json; the aggregate report only carries counts.
            "slides": [
                {
                    **{key: value for key, value in slide.items() if key != "review_issues"},
                    "review_issue_ids": [
                        str(issue.get("group_id") or "")
                        for issue in slide.get("review_issues") or []
                        if isinstance(issue, dict)
                    ],
                }
                for slide in result.get("slides", []) or []
                if isinstance(slide, dict)
            ],
            "rle_fingerprint": rle_fingerprint(prediction),
            "exported_group_ids": [group["group_id"] for group in prediction["groups"]],
            "unmasked_group_ids": prediction.get("unmasked_group_ids", []),
            "score": {k: v for k, v in score.items() if k != "groups"},
            "group_scores": score.get("groups", []),
            "expected_review": score.get("expected_review"),
        }
        (out_dir / "score.json").write_text(
            json.dumps(score, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (out_dir / "pipeline_result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return report
    finally:
        db.close()


def run(args: argparse.Namespace) -> int:
    problems = side_effect_free_preflight(args.bundle)
    if problems:
        for problem in problems:
            print(f"PREFLIGHT FAIL: {problem}")
        return 2
    env = configure_isolation(Path(args.workdir) if args.workdir else None)
    server_module = load_composition_root()
    if not args.verbose:
        # The production logger emits one multi-kilobyte annotation event per
        # slide; keep it in the app logs out of the benchmark console.
        logging.getLogger().setLevel(logging.WARNING)
    vision = _configure_vision_settings(server_module, args)

    cases = discover_cases(args.bundle)
    selected = [c for c in cases if not args.cases or c.case_id in set(args.cases)]
    if not selected:
        print("no fixture cases selected")
        return 2
    if vision["remote_vision_configured"]:
        estimate = len(selected) * args.repeats
        print(
            f"[budget] remote vision: {len(selected)} pages x {args.repeats} repeats "
            f"= {estimate} AI Mask requests (each request carries 1 overview + <=12 crops)"
        )
        vision["estimated_requests"] = estimate
    out_root = Path(args.out).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "vision_mode.json").write_text(
        json.dumps(vision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    reports: list[dict[str, Any]] = []
    for case in selected:
        for repeat in range(1, args.repeats + 1):
            out_dir = out_root / case.case_id / f"repeat_{repeat}"
            report = _run_case(server_module, case, args, env.runs_dir, out_dir, repeat)
            reports.append(report)
            print(
                f"{case.case_id} r{repeat}: macro_recall="
                f"{report['score']['macro_group_recall']:.4f} "
                f"own_iou={report['score']['macro_ownership_iou_on_truth']:.4f} "
                f"correct_ink={report['score']['correct_ink_ownership']:.4f} "
                f"missing={len(report['score'].get('missing_group_ids') or [])} "
                f"overlap={report['score']['overlap_pixels_all_canvas']} "
                f"status={report['quality_status']} "
                f"{report['annotate_seconds']:.1f}s"
            )

    determinism: dict[str, Any] = {"checked": args.repeats >= 2, "consistent": True, "cases": {}}
    if args.repeats >= 2:
        for case in selected:
            fingerprints = sorted(
                {r["rle_fingerprint"] for r in reports if r["case_id"] == case.case_id}
            )
            consistent = len(fingerprints) == 1
            determinism["cases"][case.case_id] = consistent
            determinism["consistent"] = determinism["consistent"] and consistent

    aggregate = {
        "schema_version": "ai_mask_benchmark_report_v1",
        "label": args.label or "",
        "run_id": args.run_id,
        "bundle": str(args.bundle),
        "vision": vision,
        "layout_override": args.layout,
        "settings_override": settings_override_summary(args),
        "code": _code_fingerprint(),
        "cases": reports,
        "summary": _aggregate(reports, args.repeats),
        "determinism": determinism,
        "isolated_root": str(env.root),
        "workdir_retained": bool(args.keep_workdir or not env.owns_directory),
    }
    (out_root / "report.json").write_text(
        json.dumps(aggregate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    summary = aggregate["summary"]
    print(
        f"[summary] macro_recall={summary['mean']['macro_group_recall']} "
        f"own_iou={summary['mean']['macro_ownership_iou_on_truth']} "
        f"correct_ink={summary['mean']['correct_ink_ownership']} "
        f"protected_white={summary['mean']['protected_white_recall']} "
        f"overlap={summary['mean']['overlap_pixels_all_canvas']} "
        f"median_time={summary['annotate_seconds']['median']}s "
        f"review_assertions={summary['cases_passed_review_assertion']}/{summary['case_count']}"
    )
    print(f"benchmark report -> {out_root / 'report.json'}")
    if env.owns_directory and not args.keep_workdir:
        shutil.rmtree(env.root, ignore_errors=True)
    else:
        print(f"isolated project runs kept under {env.root}")
    if not determinism["consistent"]:
        print("WARNING: repeated runs produced different pixel results")
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--out", type=Path, required=True, help="result directory")
    parser.add_argument("--label", default=None, help="A/B arm name recorded in report.json")
    parser.add_argument(
        "--run-id",
        default=None,
        help="nonce used in project ids; a fresh one is generated per process",
    )
    parser.add_argument("--cases", nargs="*", default=None)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--layout", choices=["on", "off"], default=None, help="override doclayout_enabled")
    parser.add_argument("--settings-json", default=None, help="frozen AI Mask settings JSON override")
    parser.add_argument("--workdir", default=None, help="reuse a specific isolated workdir")
    parser.add_argument("--keep-workdir", action="store_true")
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="keep the production INFO annotation event log on the console",
    )
    parser.add_argument("--vision-api-key", default=None)
    parser.add_argument("--vision-base-url", default=None)
    parser.add_argument("--vision-model", default=None)
    parser.add_argument("--vision-provider", default=None)
    args = parser.parse_args()
    if not args.run_id:
        # Project ids must stay unique even when an isolated workdir is reused.
        args.run_id = f"{time.strftime('%H%M%S')}_{secrets.token_hex(2)}"
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
