from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import runtime_ai_mask
import runtime_bootstrap
import server


def test_ai_mask_routes_are_explicit_and_unique() -> None:
    expected = {
        ("/api/settings/ai-mask", "GET"),
        ("/api/settings/ai-mask", "PUT"),
        ("/api/projects/{project_id}/steps/5/ai-mask/annotate", "POST"),
        ("/api/projects/{project_id}/steps/4/ai-mask/annotate", "POST"),
    }
    actual = []
    for route in server.app.routes:
        for method in getattr(route, "methods", set()) or set():
            pair = (getattr(route, "path", ""), method)
            if pair in expected:
                actual.append(pair)
    assert set(actual) == expected
    assert len(actual) == len(expected)


def test_ai_mask_no_longer_auto_installs() -> None:
    assert runtime_bootstrap.RUNTIME_MODULES == []
    source = (ROOT / "runtime_ai_mask.py").read_text(encoding="utf-8").rstrip()
    assert not source.endswith("_install_when_ready()")


if __name__ == "__main__":
    test_ai_mask_routes_are_explicit_and_unique()
    test_ai_mask_no_longer_auto_installs()
    print("AI Mask registration checks passed")
