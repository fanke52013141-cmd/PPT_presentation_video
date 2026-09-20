"""Freeze the AI Mask benchmark baseline: sources, environment, model, prompts.

W0 of the handoff package: record everything an A/B comparison must keep
identical (source SHAs, interpreter/ORT versions, model digest, built-in AI
Mask settings and Prompt hashes, fixture digests) so later rounds can prove
that only the algorithm changed.  Read-only; never reads user credentials or
stored settings values.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BUNDLE = REPO_ROOT / "outputs" / "ai_mask_optimization_handoff_20260920"

PRODUCTION_SOURCES = (
    "ai_mask_component_detection.py",
    "ai_mask_engine.py",
    "ai_mask_semantic_matcher.py",
    "ai_mask_assignment.py",
    "ai_mask_manifest_apply.py",
    "ai_mask_doclayout.py",
    "ai_mask_service.py",
    "ai_mask_config.py",
    "ai_mask_contracts.py",
    "ai_mask_routes.py",
    # Step 5 Mask build paths that consume the annotation and carry the reveal
    # stage timing.
    "mask_manifest_service.py",
    "mask_preview_service.py",
    "scripts/build_reveal_scene.py",
)

FIXTURE_INPUT_FILES = ("visual_draft.png", "slide_context.json")
FIXTURE_ANSWER_FILES = (
    "ground_truth.json",
    "ownership.png",
    "ink.png",
    "protected_white.png",
    "ignore.png",
    "answer_overlay.png",
)


def sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def git_info() -> dict[str, object]:
    def run(*args: str) -> str:
        try:
            completed = subprocess.run(
                ["git", *args],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return completed.stdout.strip() if completed.returncode == 0 else ""

    commit = run("rev-parse", "HEAD")
    status = run("status", "--porcelain", "--", *[str(p) for p in PRODUCTION_SOURCES])
    return {
        "commit": commit,
        "tracked_source_dirty": bool(status),
        "source_status_detail": status,
    }


def environment_info() -> dict[str, object]:
    import numpy
    import PIL
    import onnxruntime

    return {
        "python": sys.version.split()[0],
        "platform": f"{os.name}",
        "numpy": numpy.__version__,
        "pillow": PIL.__version__,
        "onnxruntime": onnxruntime.__version__,
        "ort_available_providers": list(onnxruntime.get_available_providers()),
    }


def model_info() -> dict[str, object]:
    from ai_mask_doclayout import DocLayoutDetector

    detector = DocLayoutDetector("")
    path = Path(detector.model_path) if detector.model_path else None
    payload: dict[str, object] = {
        "path": str(path.relative_to(REPO_ROOT)) if path else "",
        "exists": bool(path and path.exists()),
    }
    if payload["exists"]:
        payload["sha256"] = sha256_file(path)
        payload["available"] = detector.available()
        payload["load_error"] = detector.load_error()
        if detector._session is not None:
            payload["session_providers"] = list(detector._session.get_providers())
    return payload


def prompt_info() -> dict[str, object]:
    import ai_mask_engine

    def digest(value: str) -> str:
        return sha256(value.encode("utf-8")).hexdigest()

    return {
        "builtin_methodology_sha256": digest(ai_mask_engine.DEFAULT_METHODOLOGY),
        "builtin_output_structure_sha256": digest(ai_mask_engine.DEFAULT_OUTPUT_STRUCTURE),
        "composed_full_prompt_sha256": digest(
            ai_mask_engine.DEFAULT_METHODOLOGY.strip()
            + "\n\n--- OUTPUT STRUCTURE / 输出结构 ---\n"
            + ai_mask_engine.DEFAULT_OUTPUT_STRUCTURE.strip()
        ),
        "note": (
            "Built-in defaults only. Stored user prompts must be hashed "
            "separately by each benchmark run and compared, never merged here."
        ),
    }


def settings_info() -> dict[str, object]:
    import ai_mask_engine

    return {"normalized_defaults": ai_mask_engine.normalize_settings({})}


def fixture_info(bundle: Path) -> dict[str, object]:
    index_path = bundle / "fixtures" / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    cases: dict[str, object] = {}
    for entry in index:
        case_id = str(entry["case_id"])
        folder = bundle / "fixtures" / case_id
        cases[case_id] = {
            "input": {
                name: sha256_file(folder / name) for name in FIXTURE_INPUT_FILES
            },
            "answer": {
                name: sha256_file(folder / name) for name in FIXTURE_ANSWER_FILES
            },
        }
    return {"count": len(cases), "cases": cases}


def build_baseline(bundle: Path) -> dict[str, object]:
    sys.path.insert(0, str(REPO_ROOT))
    return {
        "schema_version": "ai_mask_baseline_freeze_v1",
        "frozen_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "git": git_info(),
        "environment": environment_info(),
        "source_sha256": {
            relative: sha256_file(REPO_ROOT / relative) for relative in PRODUCTION_SOURCES
        },
        "doclayout_model": model_info(),
        "prompts": prompt_info(),
        "settings": settings_info(),
        "fixtures": fixture_info(bundle),
        "bundle_dir": str(bundle.relative_to(REPO_ROOT)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(os.environ.get("PPT_STUDIO_BENCHMARK_RESULTS", str(REPO_ROOT / "outputs" / "ai_mask_benchmark_results"))) / "frozen_baseline.json",
    )
    args = parser.parse_args()
    baseline = build_baseline(args.bundle)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"baseline frozen -> {args.out}")
    print(f"commit={baseline['git']['commit']} fixtures={baseline['fixtures']['count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
