"""Candidate-capacity report: does every narrated group get its own object?

W3 removed the ``(beats + 3)`` spatial merge, so this measures the structural
effect without calling any model: for each fixture it compares the number of
narrated visual groups against the atomic objects the matcher can address, and
against what the retired merge strategy would have offered.  A slide where the
old strategy produced fewer candidates than groups could never be annotated
correctly, no matter how good the model was.

Run as a module so ``ai_mask_benchmark`` imports resolve:

    python -m checks.ai_mask_benchmark.object_capacity \
        --out outputs/ai_mask_benchmark_results/object_capacity_after_w3.json
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from checks.ai_mask_benchmark.project_fixture import (  # noqa: E402
    DEFAULT_BUNDLE,
    FixtureCase,
    discover_cases,
)
from ai_mask_component_detection import detect_elements  # noqa: E402
from ai_mask_engine import normalize_settings  # noqa: E402
from ai_mask_semantic_matcher import (  # noqa: E402
    _plan_object_batches,
    _semantic_objects,
    _spatial_cluster_objects,
)


def _slide(case: FixtureCase) -> dict[str, Any]:
    return json.loads(case.slide_context.read_text(encoding="utf-8"))


def _group_ids(slide: dict[str, Any], key: str) -> list[str]:
    ids: list[str] = []
    for entry in slide.get(key, []) or []:
        if not isinstance(entry, dict):
            continue
        group_id = str(entry.get("group_id") or entry.get("id") or "")
        if group_id and group_id not in ids:
            ids.append(group_id)
    return ids


def measure(
    bundle: Path,
    workdir: Path,
    *,
    detector: Any | None = None,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    settings = normalize_settings({})
    for case in discover_cases(Path(bundle)):
        slide = _slide(case)
        narrated_groups = _group_ids(slide, "narration_beats")
        visual_groups = _group_ids(slide, "visual_groups")
        with Image.open(case.visual_draft) as image:
            layout_boxes = detector.detect(image) if detector is not None else None
        elements_payload = detect_elements(
            case.visual_draft, Path(workdir) / case.case_id, settings, layout_boxes
        )
        elements = elements_payload["elements"] + elements_payload.get("residual_elements", [])
        width = int(elements_payload["canvas"]["width"])
        height = int(elements_payload["canvas"]["height"])
        objects = _semantic_objects(elements, width, height)
        # The retired strategy: one request holding at most 12 merged clusters.
        beat_count = len(slide.get("narration_beats", []) or [])
        target_count = max(1, min(12, beat_count + 3))
        legacy = _spatial_cluster_objects(objects, target_count)
        batches, beyond = _plan_object_batches(objects, settings)
        requested = {str(obj["object_id"]) for batch in batches for obj in batch}
        rows.append({
            "case_id": case.case_id,
            "image_sha256": sha256(case.visual_draft.read_bytes()).hexdigest()[:12],
            "detection_version": elements_payload["version"],
            "layout_box_count": len(layout_boxes) if layout_boxes is not None else 0,
            "element_count": len(elements),
            "narrated_group_count": len(narrated_groups),
            "visual_group_count": len(visual_groups),
            "atomic_object_count": len(objects),
            "legacy_target_cluster_count": target_count,
            "legacy_cluster_count": len(legacy),
            "legacy_addresses_every_group": len(legacy) >= len(visual_groups),
            "request_batches": len(batches),
            "requested_object_count": len(requested),
            "beyond_budget_object_count": len(beyond),
            "atomic_addresses_every_group": len(requested) >= len(visual_groups),
            "bridge_pixel_count": sum(
                int(element.get("bridge_pixel_count", 0)) for element in elements
            ),
        })
    return {
        "schema_version": "object_capacity_report_v1",
        "vision_object_batch_size": int(settings["vision_object_batch_size"]),
        "vision_max_requests": int(settings["vision_max_requests"]),
        "cases": rows,
        "summary": {
            "case_count": len(rows),
            "legacy_short_cases": sum(1 for row in rows if not row["legacy_addresses_every_group"]),
            "atomic_short_cases": sum(
                1 for row in rows if not row["atomic_addresses_every_group"]
            ),
            "short_case_ids": [
                row["case_id"] for row in rows if not row["legacy_addresses_every_group"]
            ],
            "total_request_count": sum(row["request_batches"] for row in rows),
            "max_requests_per_case": max((row["request_batches"] for row in rows), default=0),
            "total_beyond_budget_objects": sum(
                row["beyond_budget_object_count"] for row in rows
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument(
        "--workdir",
        type=Path,
        default=REPO_ROOT / "outputs" / "ai_mask_benchmark_results" / "capacity_workdir",
    )
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--layout",
        action="store_true",
        help="run the DocLayout-YOLO detector and bind its boxes first",
    )
    args = parser.parse_args()
    args.workdir.mkdir(parents=True, exist_ok=True)
    detector = None
    if args.layout:
        from ai_mask_doclayout import DocLayoutDetector

        detector = DocLayoutDetector(str(normalize_settings({})["doclayout_model_path"]))
    report = measure(args.bundle, args.workdir, detector=detector)
    report["layout"] = "doclayout_on" if args.layout else "doclayout_off"
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    header = (
        f"{'case':<20}{'groups':>7}{'atomic':>7}{'legacy':>7}{'batch':>6}"
        f"{'>budget':>8}{'legacy ok?':>11}{'atomic ok?':>11}"
    )
    print(header)
    print("-" * len(header))
    for row in report["cases"]:
        print(
            f"{row['case_id']:<20}{row['visual_group_count']:>7}{row['atomic_object_count']:>7}"
            f"{row['legacy_cluster_count']:>7}{row['request_batches']:>6}"
            f"{row['beyond_budget_object_count']:>8}"
            f"{('yes' if row['legacy_addresses_every_group'] else 'NO'):>11}"
            f"{('yes' if row['atomic_addresses_every_group'] else 'NO'):>11}"
        )
    print(json.dumps(report["summary"], ensure_ascii=False))
    if args.out is not None:
        print(f"report -> {args.out}")


if __name__ == "__main__":
    main()
