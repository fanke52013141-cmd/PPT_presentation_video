"""A new business endpoint must not silently escape the Agent backlog."""

from agent_contract.features import coverage_errors, load_features, source_entrypoints


def test_all_business_entries_have_reviewed_coverage():
    assert coverage_errors() == []


def test_new_business_entrypoint_blocks_check(monkeypatch):
    import agent_contract.features as features
    current = source_entrypoints()
    current["new_domain.new_action"] = {"source": "new_domain.py", "routes": []}
    monkeypatch.setattr(features, "source_entrypoints", lambda: current)
    assert any("new_domain.new_action" in error for error in coverage_errors())


def test_route_change_requires_coverage_review(monkeypatch):
    import agent_contract.features as features
    current = source_entrypoints()
    key = next(iter(current))
    current[key]["routes"] = [{"method": "POST", "declaration": "router.post('/changed')"}]
    monkeypatch.setattr(features, "source_entrypoints", lambda: current)
    assert any("changed without coverage review" in error for error in coverage_errors())


def test_effective_business_routes_are_in_feature_catalog():
    # Only import composition root after pytest has selected isolated storage.
    import server
    from route_inventory import iter_effective_routes
    from repository_paths import REPO_ROOT
    from pathlib import Path
    catalog = load_features()
    missing = set()
    for route in iter_effective_routes(server.app):
        if not route.path.startswith("/api/") or route.path.startswith("/api/agent/"):
            continue
        endpoint = getattr(route.source, "endpoint", None)
        if endpoint is None:
            continue
        module = endpoint.__module__
        # Framework documentation, mounted applications and external routers
        # have no root-level source-owned business module.
        if "." in module or not (Path(REPO_ROOT) / (module + ".py")).is_file():
            continue
        key = f"{module}.{endpoint.__name__}"
        if key not in catalog:
            missing.add(key)
    assert missing == set(), f"Unregistered effective business routes: {sorted(missing)}"
