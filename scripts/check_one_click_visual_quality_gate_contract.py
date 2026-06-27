#!/usr/bin/env python3
"""Static contract for One-click Step 3 visual draft quality gate."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "runtime_bootstrap.py"
GATE = ROOT / "runtime_one_click_visual_quality_gate.py"

REQUIRED_BOOTSTRAP_SNIPPETS = [
    "runtime_one_click_visual_quality_gate",
]

REQUIRED_GATE_SNIPPETS = [
    "GATE_STAGE_ID = \"image_quality\"",
    "GATE_STAGE_TITLE = \"检查 Step 3 图片质量\"",
    "GATE_KEY = \"pause_on_visual_draft_quality_failure\"",
    "scripts.check_visual_draft_quality",
    "check_run_dir",
    "quality_report",
    "issue_details",
    "_patch_finish_stage",
    "stage_id == \"images\"",
    "Step 3 图片质量门暂停",
]


def _missing(path: Path, snippets: list[str]) -> list[str]:
    content = path.read_text(encoding="utf-8")
    return [snippet for snippet in snippets if snippet not in content]


def main() -> int:
    problems: list[str] = []
    for snippet in _missing(BOOTSTRAP, REQUIRED_BOOTSTRAP_SNIPPETS):
        problems.append(f"runtime_bootstrap.py missing {snippet!r}")
    for snippet in _missing(GATE, REQUIRED_GATE_SNIPPETS):
        problems.append(f"runtime_one_click_visual_quality_gate.py missing {snippet!r}")
    if problems:
        print("FAIL One-click visual quality gate contract:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("OK One-click visual quality gate contract passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
