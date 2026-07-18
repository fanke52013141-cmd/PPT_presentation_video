#!/usr/bin/env python3
"""Check key artifacts after a manual end-to-end smoke test.

Run from the repository root after creating a project:

    python scripts/check_smoke_artifacts.py --run-dir runs/<project_id> --stage step8

Stages are cumulative:

- step1: imported article and article brief
- step2: visual contract
- step3: visual draft images
- step5: reveal manifest and mask/reveal structure
- step6: narration beats/text
- step7: generated audio artifacts
- step8: Remotion props and rendered MP4 artifacts

The checker is intentionally structural. It does not validate visual quality or
semantic correctness; it catches missing files, malformed JSON, and obvious
pipeline regressions.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


STAGE_ORDER = ["step1", "step2", "step3", "step5", "step6", "step7", "step8"]
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".ogg"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".webm"}


@dataclass
class Finding:
    level: str
    message: str


class SmokeCheck:
    def __init__(self, run_dir: Path, stage: str) -> None:
        self.run_dir = run_dir
        self.stage = stage
        self.findings: list[Finding] = []
        self.contract: dict[str, Any] = {}
        self.manifest: dict[str, Any] = {}

    def fail(self, message: str) -> None:
        self.findings.append(Finding("FAIL", message))

    def warn(self, message: str) -> None:
        self.findings.append(Finding("WARN", message))

    def pass_(self, message: str) -> None:
        self.findings.append(Finding("PASS", message))

    def required(self, relative_path: str) -> Path:
        path = self.run_dir / relative_path
        if not path.exists():
            self.fail(f"missing required file: {relative_path}")
        else:
            self.pass_(f"found {relative_path}")
        return path

    def read_json(self, relative_path: str, required: bool = True) -> dict[str, Any]:
        path = self.run_dir / relative_path
        if not path.exists():
            if required:
                self.fail(f"missing JSON file: {relative_path}")
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            self.fail(f"invalid JSON in {relative_path}: {type(exc).__name__}: {exc}")
            return {}
        if not isinstance(value, dict):
            self.fail(f"JSON root must be an object: {relative_path}")
            return {}
        self.pass_(f"valid JSON {relative_path}")
        return value

    def slide_ids(self) -> list[str]:
        slides = self.contract.get("slides") if isinstance(self.contract.get("slides"), list) else []
        result: list[str] = []
        for index, slide in enumerate(slides, start=1):
            if not isinstance(slide, dict):
                self.fail(f"visual_contract slide #{index} is not an object")
                continue
            slide_id = str(slide.get("slide_id") or "").strip()
            if not slide_id:
                self.fail(f"visual_contract slide #{index} is missing slide_id")
                continue
            result.append(slide_id)
        return result

    def check_step1(self) -> None:
        self.required("inputs/article.md")
        article_path = self.run_dir / "inputs" / "article.md"
        if article_path.exists() and not article_path.read_text(encoding="utf-8-sig").strip():
            self.fail("inputs/article.md is empty")
        elif article_path.exists():
            self.pass_("article source is present")

    def check_step2(self) -> None:
        self.contract = self.read_json("planning/visual_contract.json")
        if not self.contract:
            return
        topic = self.contract.get("topic") if isinstance(self.contract.get("topic"), dict) else {}
        if not str(topic.get("topic_summary") or "").strip():
            self.fail("visual_contract.topic.topic_summary is missing")
        else:
            self.pass_("visual_contract topic_summary is present")
        slide_ids = self.slide_ids()
        if not slide_ids:
            self.fail("visual_contract has no valid slides")
            return
        self.pass_(f"visual_contract has {len(slide_ids)} slide(s)")
        for slide in self.contract.get("slides", []) or []:
            if not isinstance(slide, dict):
                continue
            slide_id = str(slide.get("slide_id") or "").strip()
            visual_groups = slide.get("visual_groups")
            if not isinstance(visual_groups, list) or not visual_groups:
                self.fail(f"{slide_id} has no visual_groups")
            else:
                self.pass_(f"{slide_id} has {len(visual_groups)} visual_group(s)")

    def check_step3(self) -> None:
        for slide_id in self.slide_ids():
            slide_dir = self.run_dir / "slides" / slide_id
            candidates = [
                slide_dir / "visual_draft.png",
                slide_dir / "visual_draft.jpg",
                slide_dir / "visual_draft.webp",
            ]
            if any(path.exists() and path.stat().st_size > 0 for path in candidates):
                self.pass_(f"{slide_id} visual draft image is present")
            else:
                images = [path for path in slide_dir.glob("*") if path.suffix.lower() in IMAGE_SUFFIXES and path.stat().st_size > 0]
                if images:
                    self.warn(f"{slide_id} has image(s), but no standard visual_draft.* name")
                else:
                    self.fail(f"{slide_id} has no generated/uploaded visual draft image")

    def check_step5(self) -> None:
        self.manifest = self.read_json("reveal_manifest.json")
        if not self.manifest:
            return
        slides = self.manifest.get("slides") if isinstance(self.manifest.get("slides"), list) else []
        manifest_ids = {str(slide.get("slide_id") or "").strip() for slide in slides if isinstance(slide, dict)}
        expected_ids = set(self.slide_ids())
        missing = sorted(expected_ids - manifest_ids)
        extra = sorted(manifest_ids - expected_ids)
        if missing:
            self.fail(f"reveal_manifest is missing slide(s): {missing}")
        if extra:
            self.warn(f"reveal_manifest contains non-contract slide(s): {extra}")
        if not missing:
            self.pass_("reveal_manifest slide ids cover visual_contract slides")
        for slide in slides:
            if not isinstance(slide, dict):
                self.fail("reveal_manifest contains a non-object slide")
                continue
            slide_id = str(slide.get("slide_id") or "").strip()
            groups = slide.get("groups") if isinstance(slide.get("groups"), list) else []
            semantic_blocks = slide.get("semantic_blocks") if isinstance(slide.get("semantic_blocks"), list) else []
            if not groups and not semantic_blocks:
                self.fail(f"{slide_id} has neither groups nor semantic_blocks in reveal_manifest")
            else:
                self.pass_(f"{slide_id} has reveal group structure")
            painted = [group for group in groups + semantic_blocks if isinstance(group, dict) and (group.get("strokes") or group.get("mask") or group.get("mask_path") or group.get("mask_data"))]
            if not painted:
                self.warn(f"{slide_id} has no painted mask data yet")

    def check_step6(self) -> None:
        global_beats = self.run_dir / "planning" / "narration_beats.json"
        if global_beats.exists():
            payload = self.read_json("planning/narration_beats.json")
            slides = payload.get("slides") if isinstance(payload.get("slides"), list) else []
            if slides:
                self.pass_(f"planning/narration_beats.json has {len(slides)} slide narration entry/entries")
            else:
                self.warn("planning/narration_beats.json exists but has no slides array")
        else:
            self.warn("planning/narration_beats.json is missing; checking per-slide narration files")
        for slide_id in self.slide_ids():
            slide_dir = self.run_dir / "slides" / slide_id
            has_text = (slide_dir / "narration.txt").exists() or (slide_dir / "tts_text.txt").exists()
            has_beats = (slide_dir / "narration_beats.json").exists()
            if has_text or has_beats:
                self.pass_(f"{slide_id} narration artifact is present")
            else:
                self.warn(f"{slide_id} has no per-slide narration artifact")

    def check_step7(self) -> None:
        audio_files = [path for path in self.run_dir.rglob("*") if path.is_file() and path.suffix.lower() in AUDIO_SUFFIXES and path.stat().st_size > 0]
        if audio_files:
            self.pass_(f"found {len(audio_files)} audio artifact(s)")
        else:
            self.fail("no non-empty audio artifact found under run_dir")
        timeline_files = [path for path in self.run_dir.rglob("animation_timeline.json") if path.is_file()]
        if timeline_files:
            self.pass_(f"found {len(timeline_files)} animation_timeline.json file(s)")
        else:
            self.warn("no animation_timeline.json files found")

    def check_step8(self) -> None:
        self.required("remotion_props.json")
        video_files = [path for path in self.run_dir.rglob("*") if path.is_file() and path.suffix.lower() in VIDEO_SUFFIXES and path.stat().st_size > 0]
        if video_files:
            self.pass_(f"found {len(video_files)} rendered video artifact(s)")
        else:
            self.fail("no non-empty rendered video artifact found under run_dir")

    def run(self) -> int:
        if not self.run_dir.exists() or not self.run_dir.is_dir():
            self.fail(f"run_dir does not exist or is not a directory: {self.run_dir}")
        stage_index = STAGE_ORDER.index(self.stage)
        for stage in STAGE_ORDER[: stage_index + 1]:
            getattr(self, f"check_{stage}")()
        for finding in self.findings:
            print(f"{finding.level} {finding.message}")
        failures = [finding for finding in self.findings if finding.level == "FAIL"]
        warnings = [finding for finding in self.findings if finding.level == "WARN"]
        if failures:
            print(f"SUMMARY failed with {len(failures)} failure(s), {len(warnings)} warning(s).")
            return 1
        print(f"SUMMARY passed with {len(warnings)} warning(s).")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, help="project run directory, e.g. runs/<project_id>")
    parser.add_argument("--stage", choices=STAGE_ORDER, default="step8", help="highest pipeline stage to check")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).expanduser().resolve()
    return SmokeCheck(run_dir=run_dir, stage=args.stage).run()


if __name__ == "__main__":
    raise SystemExit(main())
