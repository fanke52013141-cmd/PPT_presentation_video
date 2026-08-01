from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def line_count(path: str) -> int:
    return len((ROOT / path).read_text(encoding="utf-8").splitlines())


def test_extracted_modules_do_not_regress_into_monoliths() -> None:
    limits = {
        "static/workflow_state.js": 140,
        "ai_mask_engine.py": 750,
        "storyboard_service.py": 1350,
        "server.py": 1100,
    }

    for path, maximum in limits.items():
        actual = line_count(path)
        assert actual <= maximum, f"{path} grew to {actual} lines (limit: {maximum})"


def test_legacy_frontend_monolith_stays_retired() -> None:
    assert not (ROOT / "static" / "app.js").exists()
