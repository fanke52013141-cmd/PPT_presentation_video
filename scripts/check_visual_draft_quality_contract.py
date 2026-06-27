#!/usr/bin/env python3
"""Static contract for Step 3 visual draft quality output.

The UI and one-click quality gates depend on stable issue codes and actionable
Chinese recommendations. This check prevents the diagnostic from regressing to
opaque string-only output.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUALITY_SCRIPT = ROOT / "scripts" / "check_visual_draft_quality.py"

REQUIRED_SNIPPETS = [
    "ISSUE_CATALOG",
    "wrong_size",
    "non_white_background",
    "dirty_border",
    "subtitle_safe_area",
    "issue_details",
    "recommendations",
    "建议：",
    "白底不够干净",
    "字幕安全区占用过多",
    "边界存在非白内容",
    "图片尺寸不正确",
]


def main() -> int:
    content = QUALITY_SCRIPT.read_text(encoding="utf-8")
    missing = [snippet for snippet in REQUIRED_SNIPPETS if snippet not in content]
    if missing:
        print("FAIL visual draft quality output contract missing snippets:")
        for snippet in missing:
            print(f"  - {snippet}")
        return 1
    print("OK visual draft quality output contract passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
