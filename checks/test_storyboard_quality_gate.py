import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server


def test_validation_result_is_persisted_and_gate_defaults_to_pause() -> None:
    with tempfile.TemporaryDirectory() as value:
        run_dir = Path(value)
        planning = run_dir / "planning"
        planning.mkdir(parents=True)
        contract = planning / "visual_contract.json"
        contract.write_text('{"slides":[]}', encoding="utf-8")
        project = SimpleNamespace(run_dir=str(run_dir))

        result = server.validate_visual_contract_file(
            project,
            str(contract),
            source="test",
        )

        assert result["valid"] is False
        marker = json.loads((planning / "visual_contract.validation.json").read_text(encoding="utf-8"))
        assert marker["valid"] is False
        assert marker["contract_sha256"] == result["contract_sha256"]
        assert server.storyboard_validation_gate_enabled(project) is True


if __name__ == "__main__":
    test_validation_result_is_persisted_and_gate_defaults_to_pause()
    print("storyboard quality gate checks passed")
