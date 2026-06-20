import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import mask_selection_diagnostics


def write_report(root: Path, slide_id: str, ratio: float, fallback: bool = False) -> None:
    slide_dir = root / "slides" / slide_id
    slide_dir.mkdir(parents=True, exist_ok=True)
    (slide_dir / "reveal_report.json").write_text(
        json.dumps(
            {
                "slide_id": slide_id,
                "fallback_full_slide": fallback,
                "foreground_diagnostics": {
                    "metric": "whole_slide_nonwhite_selection_ratio",
                    "selection_ratio": ratio,
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

    diagnostics = mask_selection_diagnostics(project)
    assert [item["slide_id"] for item in diagnostics] == ["slide_001", "slide_002"]
    assert diagnostics[0]["selection_ratio"] == 0.956
    assert diagnostics[1]["selection_ratio"] == 0.992
    assert diagnostics[0]["unselected_foreground_pixel_count"] == 120

print("mask selection diagnostics checks passed")
