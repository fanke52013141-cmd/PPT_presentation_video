"""Side-effect-free business entrypoint inventory and explicit coverage decisions."""

from __future__ import annotations

import ast
import json
from pathlib import Path

from repository_paths import REPO_ROOT, AGENT_FEATURES_PATH


def source_entrypoints() -> dict[str, dict]:
    """Read route declarations without importing server or recovering live jobs.

    This source guard complements effective-route tests; it is deliberately
    not used as the production HTTP route inspection API.
    """
    entries = {}
    for path in sorted(Path(REPO_ROOT).glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        routers = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                func = node.value.func
                if isinstance(func, ast.Name) and func.id == "APIRouter":
                    routers.update({target.id: ast.unparse(node.value)
                                    for target in node.targets if isinstance(target, ast.Name)})
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            declarations = []
            for dec in node.decorator_list:
                if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
                    continue
                if not isinstance(dec.func.value, ast.Name) or dec.func.value.id not in routers:
                    continue
                method = dec.func.attr.upper()
                if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "API_ROUTE"}:
                    continue
                declarations.append({"method": method, "declaration": ast.unparse(dec),
                                     "router": routers[dec.func.value.id]})
            if declarations:
                key = f"{path.stem}.{node.name}"
                entries[key] = {"source": path.name, "routes": declarations}
    return entries


def load_features() -> dict:
    return json.loads(Path(AGENT_FEATURES_PATH).read_text(encoding="utf-8"))


def coverage_errors() -> list[str]:
    from agent_contract.capabilities import CAPABILITIES
    entries = source_entrypoints()
    catalog = load_features()
    errors = []
    known_caps = {cap.id for cap in CAPABILITIES if cap.status.value != "removed"}
    if set(catalog) != set(entries):
        errors.append(f"Unregistered entrypoints: {sorted(set(entries) - set(catalog))}; removed: {sorted(set(catalog) - set(entries))}")
    for key in sorted(set(entries) & set(catalog)):
        feature = catalog[key]
        if feature.get("routes") != entries[key]["routes"]:
            errors.append(f"Business route changed without coverage review: {key}")
        if feature.get("coverage") not in {"pending", "partial", "complete", "exempt"}:
            errors.append(f"Invalid coverage status: {key}")
        if not feature.get("reason") or not feature.get("owner"):
            errors.append(f"Missing reason or owner: {key}")
        caps = set(feature.get("capabilities", []))
        if caps - known_caps:
            errors.append(f"Unknown capabilities: {key}: {sorted(caps - known_caps)}")
        if feature.get("coverage") in {"complete", "partial"} and not caps:
            errors.append(f"Covered feature without capability: {key}")
    return errors


def coverage_markdown() -> str:
    features = load_features()
    lines = ["# Business feature coverage", "", "Generated from config/agent_features.json; pending is an explicit implementation backlog.", "",
             "This source inventory covers business HTTP entrypoints. Background-only operations and field parity require additional scenario review.", "",
             "| Feature ID | Coverage | Capabilities | Owner | Reason |", "|---|---|---|---|---|"]
    for key, value in sorted(features.items()):
        lines.append(f"| `{key}` | {value['coverage']} | {', '.join(value['capabilities'])} | {value['owner']} | {value['reason']} |")
    return "\n".join(lines) + "\n"
