"""Exercise the actual frontend import through backend normalization/validation."""

import json
import shutil
import subprocess
from pathlib import Path

from scripts.validate_visual_contract import validate_contract
from visual_contract_service import normalize_visual_contract


def test_manual_import_preserves_narration_and_visual_types():
    root = Path(__file__).resolve().parents[1]
    node = shutil.which("node")
    assert node, "Node is required to check the actual manual storyboard importer"
    result = subprocess.run(
        [node, str(root / "checks/test_manual_storyboard_import.js"), "--contract"],
        cwd=root,
        capture_output=True,
        encoding="utf-8",
        check=True,
        timeout=30,
    )
    contract = json.loads(result.stdout)
    expected_speech = [
        [beat["spoken_text"] for beat in slide["narration_beats"]]
        for slide in contract["slides"]
    ]
    normalized = normalize_visual_contract(contract)
    validate_contract(normalized, min_groups=1, max_groups=10, profile={})
    for slide, expected in zip(normalized["slides"], expected_speech):
        assert [beat["spoken_text"] for beat in slide["narration_beats"]] == expected
    assert normalized["slides"][0]["visual_groups"][2]["visual_type"] == "picture"
    assert normalized["slides"][0]["visual_groups"][2]["display_text"] == ""
    assert normalize_visual_contract(json.loads(json.dumps(normalized))) == normalized
