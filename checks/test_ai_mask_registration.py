from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server
from route_inventory import iter_effective_routes


def test_ai_mask_routes_are_explicit_and_unique() -> None:
    expected = {
        ("/api/settings/ai-mask", "GET"),
        ("/api/settings/ai-mask", "PUT"),
        ("/api/projects/{project_id}/steps/5/ai-mask/annotate", "POST"),
    }
    actual = []
    for route in iter_effective_routes(server.app):
        for method in getattr(route, "methods", set()) or set():
            pair = (getattr(route, "path", ""), method)
            if pair in expected:
                actual.append(pair)
    assert set(actual) == expected
    assert len(actual) == len(expected)


def test_ai_mask_no_longer_auto_installs() -> None:
    assert not (ROOT / "runtime_bootstrap.py").exists()
    assert not (ROOT / "runtime_ai_mask.py").exists()
    assert not (ROOT / "runtime_ai_mask_semantic_patch.py").exists()
    source = (ROOT / "server.py").read_text(encoding="utf-8")
    assert "app.include_router(ai_mask_router)" in source
    assert "vision_matcher=semantic_vision_matcher" in source
    assert "runtime_ai_mask._register" not in source
    assert "def _register(" not in (ROOT / "ai_mask_routes.py").read_text(encoding="utf-8")
    matcher_source = (ROOT / "ai_mask_semantic_matcher.py").read_text(
        encoding="utf-8"
    )
    assert "def install(" not in matcher_source
    assert "ai_mask_engine._vision_match =" not in matcher_source


if __name__ == "__main__":
    test_ai_mask_routes_are_explicit_and_unique()
    test_ai_mask_no_longer_auto_installs()
    print("AI Mask registration checks passed")
