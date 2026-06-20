import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import ensure_mask_coverage_ready, mask_coverage_failures


def write_report(root: Path, slide_id: str, ratio: float, fallback: bool = False) -> None:
    slide_dir = root / "slides" / slide_id
    slide_dir.mkdir(parents=True, exist_ok=True)
    (slide_dir / "reveal_report.json").write_text(
        json.dumps(
            {
                "slide_id": slide_id,
                "fallback_full_slide": fallback,
                "foreground_diagnostics": {
                    "coverage_ratio": ratio,
                    "required_coverage_ratio": 0.999,
                    "uncovered_foreground_pixel_count": 120,
                },
            }
        ),
        encoding="utf-8",
    )


with tempfile.TemporaryDirectory() as temp_dir_value:
    root = Path(temp_dir_value)
    planning = root / "planning"
    planning.mkdir()
    (planning / "visual_contract.json").write_text(
        json.dumps(
            {
                "slides": [
                    {"slide_id": "slide_001"},
                    {"slide_id": "slide_002"},
                    {"slide_id": "slide_003"},
                ]
            }
        ),
        encoding="utf-8",
    )
    write_report(root, "slide_001", 0.956)
    write_report(root, "slide_002", 0.992)
    write_report(root, "slide_003", 0.0, fallback=True)
    project = SimpleNamespace(run_dir=str(root))

    failures = mask_coverage_failures(project)
    assert [item["slide_id"] for item in failures] == ["slide_001", "slide_002"]
    try:
        ensure_mask_coverage_ready(project)
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "slide_001" in str(exc.detail)
        assert "slide_002" in str(exc.detail)
        assert "不会向外扩大 Mask" in str(exc.detail)
        assert "完全封闭的内部空洞" in str(exc.detail)
    else:
        raise AssertionError("incomplete mask coverage was not blocked")

    write_report(root, "slide_001", 0.9995)
    write_report(root, "slide_002", 0.9995)
    ensure_mask_coverage_ready(project)

print("mask coverage gate checks passed")
