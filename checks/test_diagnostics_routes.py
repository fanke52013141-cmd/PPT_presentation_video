from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import diagnostics_routes
import server


def test_diagnostics_route_is_explicit_and_unique() -> None:
    matches = [
        route
        for route in server.app.routes
        if getattr(route, "path", "") == "/api/runtime/diagnostics"
        and "GET" in (getattr(route, "methods", set()) or set())
    ]
    assert len(matches) == 1
    assert not hasattr(diagnostics_routes, "_install_when_ready")
    assert not hasattr(diagnostics_routes, "_candidate_modules")


def test_diagnostics_payload_reports_current_bootstrap() -> None:
    payload = diagnostics_routes._diagnostics_payload(server)
    assert payload["success"] is True
    assert payload["runtime_bootstrap_loaded"] is False
    assert payload["registration_mode"] == "explicit_source"
    assert payload["missing_routes"] == []
    assert "/api/runtime/diagnostics" in payload["routes"]
    module_names = {item["name"] for item in payload["runtime_modules"]}
    assert "runtime_diagnostics" not in module_names
    assert "runtime_one_click_orchestrator" not in module_names


if __name__ == "__main__":
    test_diagnostics_route_is_explicit_and_unique()
    test_diagnostics_payload_reports_current_bootstrap()
    print("diagnostics route checks passed")
