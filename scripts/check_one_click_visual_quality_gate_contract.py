#!/usr/bin/env python3
"""Static contract for One-click Step 3 visual draft quality gate."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "runtime_bootstrap.py"
GATE = ROOT / "runtime_one_click_visual_quality_gate.py"
ONE_CLICK_UI = ROOT / "static" / "one_click_extension.js"
CACHE_BUSTER = ROOT / "runtime_one_click_ui_cache_buster.py"

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

REQUIRED_UI_SNIPPETS = [
    "检查 Step 3 图片质量",
    "白底、尺寸、边界和字幕安全区",
    "暂停并给出修复建议",
    "不合格时会暂停",
    "renderQualityReport",
    "quality_report",
    "issue_details",
    "one-click-quality-card",
    "one-click-quality-metrics",
    "detail.action",
]

REQUIRED_CACHE_SNIPPETS = [
    "SCRIPT_VERSION = \"20260627.7\"",
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
    for snippet in _missing(ONE_CLICK_UI, REQUIRED_UI_SNIPPETS):
        problems.append(f"static/one_click_extension.js missing {snippet!r}")
    for snippet in _missing(CACHE_BUSTER, REQUIRED_CACHE_SNIPPETS):
        problems.append(f"runtime_one_click_ui_cache_buster.py missing {snippet!r}")
    if problems:
        print("FAIL One-click visual quality gate contract:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("OK One-click visual quality gate contract passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
