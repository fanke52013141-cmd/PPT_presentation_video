"""Read-only annotation quality audit; never confirms or rewrites project artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from annotation_text_layout import candidate_tokens
from annotation_visual_quality import readable_ai_style
from annotation_contracts import AnnotationStyle
from project_storage import slide_dir


def audit(run_dir: Path) -> dict:
    contract = json.loads((run_dir / "planning/visual_contract.json").read_text(encoding="utf-8"))
    issues, slides = [], []
    for slide in contract.get("slides", []):
        sid = slide["slide_id"]
        directory = Path(slide_dir(str(run_dir), sid))
        image = directory / "visual_draft.png"
        layout_path = directory / "text_layout.json"
        tokens = candidate_tokens(json.loads(layout_path.read_text(encoding="utf-8"))) if layout_path.exists() else []
        for token in tokens:
            if any(char in str(token.get("text") or "") for char in ("▣", "�", "\ufffc")):
                issues.append({"slide_id": sid, "code": "ocr_unknown_glyph", "token_id": token["token_id"],
                    "action": "Compare the source pixels; correct OCR or regenerate the image if the source itself is wrong."})
        page_path = directory / "annotations.json"
        page = json.loads(page_path.read_text(encoding="utf-8")) if page_path.exists() else {}
        for item in page.get("items", []):
            if item.get("status", {}).get("content") == "disabled":
                continue
            aid = item.get("annotation_id")
            target = item.get("target") or {}
            if target.get("kind") == "region" and not item.get("anchor"):
                issues.append({"slide_id": sid, "annotation_id": aid, "code": "unbound_region_needs_visual_review",
                    "action": "Inspect the actual region; remove test-only marks explicitly, keep intentional manual marks."})
            if item.get("status", {}).get("content") != "confirmed":
                issues.append({"slide_id": sid, "annotation_id": aid, "code": "unconfirmed", "action": "Review and confirm the current revision."})
            if item.get("style", {}).get("type") == "highlighter":
                style = AnnotationStyle(**item["style"])
                if readable_ai_style(image, target.get("polygons") or [], style).type != "highlighter":
                    issues.append({"slide_id": sid, "annotation_id": aid, "code": "marker_background_conflict",
                        "action": "Choose a contrasting underline or revise marker color; preserve manual choices until reviewed."})
        timeline_path = directory / "annotation_timeline.json"
        timeline = json.loads(timeline_path.read_text(encoding="utf-8")) if timeline_path.exists() else {}
        times = {0.0}
        for event in timeline.get("events", []):
            for key in ("start_sec", "draw_end_sec", "exit_end_sec"):
                if key in event:
                    times.update((max(0, float(event[key]) - 1/30), float(event[key])))
        slides.append({"slide_id": sid, "sample_slide_relative_seconds": sorted(times)})
    return {"status": "needs_review" if issues else "automated_checks_passed",
        "issues": issues, "slides": slides, "limitations": "Requires per-slide visual and subjective audio review; does not certify source spelling or semantic correctness."}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(audit(args.run_dir), ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
