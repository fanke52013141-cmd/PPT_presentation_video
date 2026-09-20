"""Isolated project skeleton, prediction export and scoring for the AI Mask benchmark.

Import order matters (AGENTS.md): call :func:`configure_isolation` and
:func:`side_effect_free_preflight` before importing ``database``/``server``.
Everything below then runs against a throw-away DB + runs directory.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BUNDLE = REPO_ROOT / "outputs" / "ai_mask_optimization_handoff_20260920"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@dataclass(frozen=True)
class IsolatedEnv:
    root: Path
    db_path: Path
    runs_dir: Path
    owns_directory: bool


@dataclass(frozen=True)
class FixtureCase:
    case_id: str
    folder: Path

    @property
    def visual_draft(self) -> Path:
        return self.folder / "visual_draft.png"

    @property
    def slide_context(self) -> Path:
        return self.folder / "slide_context.json"

    @property
    def ground_truth(self) -> Path:
        return self.folder / "ground_truth.json"


def configure_isolation(root: Path | None = None) -> IsolatedEnv:
    """Point DB/runs env vars at a private directory before any app import."""
    owns = root is None
    base = Path(root).resolve() if root else Path(
        tempfile.mkdtemp(prefix="ai_mask_benchmark_")
    )
    env = IsolatedEnv(
        root=base,
        db_path=base / "data" / "projects.db",
        runs_dir=base / "runs",
        owns_directory=owns,
    )
    env.db_path.parent.mkdir(parents=True, exist_ok=True)
    env.runs_dir.mkdir(parents=True, exist_ok=True)
    os.environ["PPT_STUDIO_DB_PATH"] = str(env.db_path)
    os.environ["PPT_STUDIO_RUNS_DIR"] = str(env.runs_dir)
    os.environ.setdefault("PPT_STUDIO_DISABLE_ONE_CLICK_ORCHESTRATOR", "1")
    return env


def side_effect_free_preflight(bundle: Path = DEFAULT_BUNDLE) -> list[str]:
    """Cheap guard rails that must pass before the composition root loads."""
    problems: list[str] = []
    try:
        import numpy  # noqa: F401
        import PIL.Image  # noqa: F401
    except Exception as exc:  # pragma: no cover - environment guard
        problems.append(f"numpy/Pillow import failed: {exc}")
    if not (REPO_ROOT / "scripts" / "write_reveal_manifest_template.py").exists():
        problems.append("scripts/write_reveal_manifest_template.py is missing")
    if not (Path(bundle) / "scripts" / "evaluate.py").exists():
        problems.append(f"evaluation bundle missing at {bundle}")
    return problems


def load_composition_root():
    import server

    return server


def discover_cases(bundle: Path = DEFAULT_BUNDLE) -> list[FixtureCase]:
    index = json.loads(
        (Path(bundle) / "fixtures" / "index.json").read_text(encoding="utf-8")
    )
    return [
        FixtureCase(str(entry["case_id"]), Path(bundle) / "fixtures" / str(entry["case_id"]))
        for entry in index
    ]


def build_contract_slide(case: FixtureCase) -> dict[str, Any]:
    context = json.loads(case.slide_context.read_text(encoding="utf-8"))
    slide = dict(context)
    slide.setdefault("slide_purpose", "ai_mask_benchmark")
    slide.setdefault("visual_intent", "benchmark fixture")
    if not str(slide.get("narration") or "").strip():
        slide["narration"] = "\n".join(
            str(beat.get("spoken_text") or "")
            for beat in slide.get("narration_beats", []) or []
            if isinstance(beat, dict)
        )
    return slide


def build_contract(case: FixtureCase) -> dict[str, Any]:
    from visual_contract_service import normalize_visual_contract

    contract = {
        "version": "visual_contract_v1",
        "topic": {
            "topic_id": case.case_id,
            "topic_name": f"AI Mask benchmark {case.case_id}",
            "topic_summary": "Synthetic fixed fixture from the optimization handoff bundle.",
        },
        "slides": [build_contract_slide(case)],
    }
    return normalize_visual_contract(contract)


def create_case_project(
    server_module: Any,
    db: Any,
    case: FixtureCase,
    runs_root: Path,
    project_id: str,
) -> Any:
    from pipeline_lifecycle import write_json_atomic
    from project_storage import slide_dir
    from visual_provenance import write_visual_provenance

    run_dir = (Path(runs_root) / project_id).resolve()
    for child in ("inputs", "planning", "slides", "review"):
        (run_dir / child).mkdir(parents=True, exist_ok=True)
    project = server_module.Project(
        id=project_id,
        name=f"ai-mask-benchmark-{case.case_id}",
        description="Isolated AI Mask benchmark project (handoff W0).",
        run_dir=str(run_dir),
        current_step=4,
        status="active",
        step_status=json.dumps({str(i): "pending" for i in range(1, 9)}),
        account_id="default",
    )
    db.add(project)
    db.commit()

    contract = build_contract(case)
    write_json_atomic(run_dir / "planning" / "visual_contract.json", contract)
    destination = slide_dir(run_dir, case.case_id) / "visual_draft.png"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(case.visual_draft, destination)

    subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "write_reveal_manifest_template.py"),
            "--run-dir",
            str(run_dir),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    synced = server_module.sync_reveal_manifest_to_contract(project)
    if not synced:
        raise RuntimeError(f"reveal manifest sync failed for {case.case_id}")
    write_visual_provenance(
        run_dir,
        case.case_id,
        image_path=destination,
        provider="manual_upload",
        source_type="benchmark_fixture",
        source_bytes=case.visual_draft.read_bytes(),
        source_filename=case.visual_draft.name,
    )
    return project


def export_prediction(
    run_dir: Path,
    case_id: str,
    out_path: Path,
    *,
    canvas: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """Convert one annotated manifest slide into the ``mask_prediction_v1`` file."""
    manifest = json.loads((Path(run_dir) / "reveal_manifest.json").read_text(encoding="utf-8"))
    slide = next(
        (
            item
            for item in manifest.get("slides", []) or []
            if isinstance(item, dict) and str(item.get("slide_id") or "") == case_id
        ),
        None,
    )
    if slide is None:
        raise RuntimeError(f"manifest has no slide {case_id}")
    groups: list[dict[str, Any]] = []
    unmasked: list[str] = []
    for group in slide.get("groups", []) or []:
        if not isinstance(group, dict) or group.get("is_static_header"):
            continue
        group_id = str(
            group.get("visual_group_id") or group.get("group_id") or group.get("id") or ""
        )
        if not group_id:
            raise RuntimeError(f"group without usable visual_group_id in {case_id}")
        manual = group.get("manual_mask") if isinstance(group.get("manual_mask"), dict) else {}
        if manual.get("strokes"):
            raise RuntimeError(
                f"group {group_id} has manual strokes; export applied full-canvas masks instead"
            )
        rle = manual.get("rle") if isinstance(manual.get("rle"), dict) else None
        if not rle or not rle.get("runs"):
            # A group the annotator never masked is a real accuracy failure, so
            # export it as an absent prediction and let the scorer report it in
            # ``missing_group_ids`` instead of aborting the whole run.
            unmasked.append(group_id)
            continue
        entry: dict[str, Any] = {"group_id": group_id, "rle": rle}
        if str(group.get("visual_group_id") or ""):
            entry["visual_group_id"] = group_id
        groups.append(entry)
    status = slide.get("ai_mask_status")
    payload: dict[str, Any] = {
        "schema_version": "mask_prediction_v1",
        "case_id": case_id,
        "coordinate_space": "full_slide",
        "groups": groups,
        "unmasked_group_ids": unmasked,
    }
    if isinstance(status, dict) and "review_issues" in status:
        payload["review_required"] = bool(status.get("review_issues"))
    if canvas:
        payload["canvas"] = {"width": canvas[0], "height": canvas[1]}
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def load_eval(bundle: Path = DEFAULT_BUNDLE):
    script = Path(bundle) / "scripts" / "evaluate.py"
    spec = importlib.util.spec_from_file_location("ai_mask_bundle_evaluate", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def score_prediction(case: FixtureCase, prediction_path: Path, bundle: Path = DEFAULT_BUNDLE) -> dict[str, Any]:
    eval_module = load_eval(bundle)
    truth = json.loads(case.ground_truth.read_text(encoding="utf-8"))
    shape = (int(truth["height"]), int(truth["width"]))
    masks, payload = eval_module.masks_from_prediction(prediction_path, case.case_id, shape)
    report = eval_module.score(case.folder, masks)
    expected = bool(truth.get("expected_review"))
    reported = payload.get("review_required")
    report["expected_review"] = truth.get("expected_review")
    report["reported_review_required"] = reported
    # A missing signal means the annotator raised no review issue, so it can
    # only satisfy a truth entry that also expects no review.
    report["review_assertion_passed"] = (expected if reported is None else bool(reported)) == expected
    return report


def rle_fingerprint(prediction: dict[str, Any]) -> str:
    """Stable digest of group ownership only (no timestamps, no file paths)."""
    rows = sorted(
        (str(group["group_id"]), json.dumps(group["rle"], sort_keys=True))
        for group in prediction.get("groups", []) or []
    )
    import hashlib

    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode("utf-8")).hexdigest()
