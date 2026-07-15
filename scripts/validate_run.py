#!/usr/bin/env python3
"""Unified validation entrypoint for article-to-video runs.

This script intentionally wraps the existing validators instead of replacing
or weakening them. It gives operators a small set of stage names while keeping
all existing validator scripts available for detailed debugging.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
STAGE_CHOICES = ("contract", "image", "reveal", "render_ready", "all")
DEFAULT_ALLOWED_IMAGE_PROVIDERS = ("codex_image_gen", "openai_compatible", "manual_upload")
PRODUCTION_ALLOWED_IMAGE_PROVIDERS = ("codex_image_gen", "openai_compatible")


class StageError(RuntimeError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise StageError(f"Missing JSON file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise StageError(f"Invalid JSON file: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise StageError(f"JSON file must contain an object: {path}")
    return value


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def production_allowed_image_providers() -> tuple[str, ...]:
    configured = tuple(
        value.strip()
        for value in os.environ.get("PPT_STUDIO_PRODUCTION_IMAGE_PROVIDERS", "").split(",")
        if value.strip()
    )
    return configured or PRODUCTION_ALLOWED_IMAGE_PROVIDERS


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[1]


def script_path(repo_root: Path, name: str) -> Path:
    path = repo_root / "scripts" / name
    if not path.exists():
        raise StageError(f"Missing validator script: {path}")
    return path


def run_step(label: str, command: Sequence[str], cwd: Path) -> None:
    printable = " ".join(str(part) for part in command)
    print(f"\n==> {label}\n{printable}")
    result = subprocess.run(command, cwd=cwd, text=True)
    if result.returncode != 0:
        raise StageError(f"{label} failed with exit code {result.returncode}")


def contract_path(run_dir: Path) -> Path:
    return run_dir / "planning" / "visual_contract.json"


def manifest_path(run_dir: Path) -> Path:
    return run_dir / "reveal_manifest.json"


def slide_ids_from_contract(run_dir: Path) -> list[str]:
    contract = read_json(contract_path(run_dir))
    if contract.get("version") != "visual_contract_v1":
        raise StageError("Contract version must be visual_contract_v1")
    slides = contract.get("slides")
    if not isinstance(slides, list) or not slides:
        raise StageError("Contract must contain non-empty slides[]")
    slide_ids: list[str] = []
    for slide in slides:
        if not isinstance(slide, dict):
            raise StageError("Each contract slide must be an object")
        slide_id = str(slide.get("slide_id", "")).strip()
        if not slide_id:
            raise StageError("Contract slide missing slide_id")
        slide_ids.append(slide_id)
    if len(slide_ids) != len(set(slide_ids)):
        raise StageError("Contract contains duplicate slide_id values")
    return slide_ids


def validate_png(path: Path, width: int | None = None, height: int | None = None) -> None:
    # Import Pillow lazily so contract-only validation does not require image deps.
    from PIL import Image

    if not path.exists():
        raise StageError(f"Missing PNG file: {path}")
    if path.suffix.lower() != ".png":
        raise StageError(f"Expected PNG file: {path}")
    with Image.open(path) as image:
        actual = image.size
    if width is not None and height is not None and actual != (width, height):
        raise StageError(f"PNG has wrong dimensions: {path} is {actual[0]}x{actual[1]}, expected {width}x{height}")


def validate_image_provenance(slide_dir: Path, allowed_providers: set[str]) -> None:
    path = slide_dir / "visual_provenance.json"
    provenance = read_json(path)
    provider = str(provenance.get("provider", "")).strip()
    if not provider:
        raise StageError(f"visual_provenance.json missing provider: {path}")
    if provider not in allowed_providers:
        allowed = ", ".join(sorted(allowed_providers))
        raise StageError(f"visual_provenance.json has unsupported provider: {path}: {provider} not in [{allowed}]")
    copied_to = str(provenance.get("copied_to", "")).replace("\\", "/")
    if copied_to and not copied_to.endswith("visual_draft.png"):
        raise StageError(f"visual_provenance.json copied_to does not point to visual_draft.png: {path}")
    if provenance.get("schema_version") == "visual_provenance_v2":
        image_path = slide_dir / "visual_draft.png"
        expected_output_hash = str(provenance.get("output_sha256") or "")
        if not expected_output_hash or expected_output_hash != sha256_path(image_path):
            raise StageError(f"visual_provenance.json output hash does not match visual_draft.png: {path}")
        contract = slide_dir.parent.parent / "planning" / "visual_contract.json"
        expected_contract_hash = str(provenance.get("contract_sha256") or "")
        if not expected_contract_hash or expected_contract_hash != sha256_path(contract):
            raise StageError(f"visual_provenance.json contract hash is stale: {path}")
        if provider != "manual_upload" and not str(provenance.get("prompt_sha256") or ""):
            raise StageError(f"visual_provenance.json missing prompt hash for generated image: {path}")


def validate_image_stage(
    run_dir: Path,
    width: int,
    height: int,
    require_image_provenance: bool,
    allowed_image_providers: set[str],
) -> None:
    slide_ids = slide_ids_from_contract(run_dir)
    for slide_id in slide_ids:
        slide_dir = run_dir / "slides" / slide_id
        validate_png(slide_dir / "visual_draft.png", width=width, height=height)
        if require_image_provenance:
            validate_image_provenance(slide_dir, allowed_providers=allowed_image_providers)
    print(f"Validated image assets for {len(slide_ids)} slide(s)")


def validate_contract_stage(run_dir: Path, repo_root: Path, min_groups: int, max_groups: int) -> None:
    run_step(
        "Validate visual contract",
        [
            sys.executable,
            str(script_path(repo_root, "validate_visual_contract.py")),
            "--contract",
            str(contract_path(run_dir)),
            "--min-groups",
            str(min_groups),
            "--max-groups",
            str(max_groups),
        ],
        cwd=repo_root,
    )


def validate_reveal_stage(run_dir: Path, repo_root: Path, require_reviewed: bool, max_overlap: float, allow_blocking_warnings: bool) -> None:
    manifest_args = [
        sys.executable,
        str(script_path(repo_root, "validate_reveal_manifest.py")),
        "--manifest",
        str(manifest_path(run_dir)),
        "--contract",
        str(contract_path(run_dir)),
        "--max-overlap",
        str(max_overlap),
    ]
    if require_reviewed:
        manifest_args.append("--require-reviewed")
    run_step("Validate reveal manifest", manifest_args, cwd=repo_root)

    scene_args = [
        sys.executable,
        str(script_path(repo_root, "validate_reveal_scene.py")),
        "--run-dir",
        str(run_dir),
        "--repo-root",
        str(repo_root),
    ]
    if allow_blocking_warnings:
        scene_args.append("--allow-blocking-warnings")
    run_step("Validate reveal scene", scene_args, cwd=repo_root)


def validate_render_ready_stage(run_dir: Path, repo_root: Path, require_layered: bool, strict_literal: bool) -> None:
    grounding_args = [
        sys.executable,
        str(script_path(repo_root, "validate_narration_grounding.py")),
        "--run-dir",
        str(run_dir),
    ]
    if strict_literal:
        grounding_args.append("--strict-literal")
    run_step("Validate narration grounding", grounding_args, cwd=repo_root)

    asset_args = [
        sys.executable,
        str(script_path(repo_root, "validate_run_assets.py")),
        "--run-dir",
        str(run_dir),
        "--repo-root",
        str(repo_root),
    ]
    if require_layered:
        asset_args.append("--require-layered")
    run_step("Validate render-ready assets", asset_args, cwd=repo_root)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run staged validation checks for an article-to-video run.")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--stage", choices=STAGE_CHOICES, default=None, help="Defaults to all; --production also defaults to all.")
    parser.add_argument("--production", action="store_true", help="Production preset: stage all plus layered, provenance, and review gates.")
    parser.add_argument("--repo-root", type=Path, default=None, help="Defaults to the repository root inferred from this script.")
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument("--min-groups", type=int, default=3)
    parser.add_argument("--max-groups", type=int, default=8)
    parser.add_argument("--max-overlap", type=float, default=0.18)
    parser.add_argument("--require-reviewed", action="store_true", help="Require reveal groups to have an approved review_status.")
    parser.add_argument("--require-layered", action="store_true", help="Pass --require-layered to validate_run_assets.py.")
    parser.add_argument("--require-image-provenance", action="store_true", help="Require slides/<slide_id>/visual_provenance.json.")
    parser.add_argument(
        "--allowed-image-provider",
        action="append",
        default=None,
        help="Allowed visual_provenance provider. May be repeated. Production defaults to codex_image_gen and openai_compatible, configurable via PPT_STUDIO_PRODUCTION_IMAGE_PROVIDERS.",
    )
    parser.add_argument("--allow-blocking-warnings", action="store_true", help="Pass through to validate_reveal_scene.py.")
    parser.add_argument("--strict-literal", action="store_true", help="Pass through to validate_narration_grounding.py.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = (args.repo_root or repo_root_from_script()).resolve()
    run_dir = args.run_dir.resolve()

    stage = args.stage or "all"
    require_layered = bool(args.require_layered)
    require_image_provenance = bool(args.require_image_provenance)
    require_reviewed = bool(args.require_reviewed)

    if args.production:
        stage = args.stage or "all"
        require_layered = True
        require_image_provenance = True
        require_reviewed = True

    default_providers = production_allowed_image_providers() if args.production else DEFAULT_ALLOWED_IMAGE_PROVIDERS
    allowed_image_providers = set(args.allowed_image_provider or default_providers)

    try:
        stages = ["contract", "image", "reveal", "render_ready"] if stage == "all" else [stage]
        for current_stage in stages:
            print(f"\n# Stage: {current_stage}")
            if current_stage == "contract":
                validate_contract_stage(run_dir, repo_root, min_groups=args.min_groups, max_groups=args.max_groups)
            elif current_stage == "image":
                validate_image_stage(
                    run_dir,
                    width=args.width,
                    height=args.height,
                    require_image_provenance=require_image_provenance,
                    allowed_image_providers=allowed_image_providers,
                )
            elif current_stage == "reveal":
                validate_reveal_stage(
                    run_dir,
                    repo_root,
                    require_reviewed=require_reviewed,
                    max_overlap=args.max_overlap,
                    allow_blocking_warnings=args.allow_blocking_warnings,
                )
            elif current_stage == "render_ready":
                validate_render_ready_stage(run_dir, repo_root, require_layered=require_layered, strict_literal=args.strict_literal)
            else:
                raise StageError(f"Unsupported stage: {current_stage}")
    except StageError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("\nValidation completed successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
