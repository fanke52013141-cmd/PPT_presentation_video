"""Static contract check for runtime_bootstrap.py.

The runtime bootstrap is responsible for loading additive bridge modules before
FastAPI's root static mount can shadow their API routes. This check keeps the
critical Step 2 / Step 3 / AI Mask / One-click bridges and ready-route list from
regressing silently.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_PATH = ROOT / "runtime_bootstrap.py"

REQUIRED_MODULES = {
    "runtime_settings_mask",
    "runtime_ai_mask",
    "runtime_ai_mask_ui_cache_buster",
    "runtime_storyboard_background",
    "runtime_project_profile_lightweight",
    "runtime_project_profile_templates_override",
    "runtime_step3_image_style",
    "runtime_step3_image_style_state",
    "runtime_visual_draft_quality",
    "runtime_step2_storyboard_settings",
    "runtime_one_click_orchestrator",
    "runtime_one_click_step3_style_patch",
    "runtime_one_click_ui_cache_buster",
    "runtime_step5_flush_bridge",
    "runtime_diagnostics",
}

REQUIRED_READY_ROUTES = {
    ("/api/runtime/diagnostics", "GET"),
    ("/api/settings/ai-mask", "GET"),
    ("/api/project-profile/templates", "GET"),
    ("/api/projects/{project_id}/one-click-generate", "POST"),
    ("/api/projects/{project_id}/one-click-generate/status", "GET"),
    ("/api/projects/{project_id}/storyboard-background", "GET"),
    ("/api/projects/{project_id}/steps/3/image-style", "GET"),
    ("/api/projects/{project_id}/steps/3/image-style/reverse", "POST"),
    ("/api/projects/{project_id}/steps/3/image-style/reference-images", "GET"),
    ("/api/projects/{project_id}/steps/3/image-style/reference-images", "DELETE"),
    ("/api/projects/{project_id}/steps/3/image-style/reference-images/generate", "POST"),
    ("/api/projects/{project_id}/steps/3/image-style/reference-images/{index}", "GET"),
    ("/api/projects/{project_id}/steps/3/image-style/reference-images/{index}", "DELETE"),
    ("/api/projects/{project_id}/steps/3/visual-draft-quality", "GET"),
    ("/api/projects/{project_id}/steps/5/ai-mask/annotate", "POST"),
}

ROUTE_HOST_NAMES = {"app", "router"}
DECORATOR_METHODS = {
    "get": "GET",
    "post": "POST",
    "put": "PUT",
    "delete": "DELETE",
    "patch": "PATCH",
}
GENERIC_ROUTE_DECORATORS = {"api_route", "route"}


def _assignment_value(module: ast.Module, name: str) -> Any:
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            continue
        return ast.literal_eval(node.value)
    raise AssertionError(f"Missing {name} assignment in runtime_bootstrap.py")


def _literal_string_collection(module: ast.Module, name: str) -> set[str]:
    value = _assignment_value(module, name)
    if not isinstance(value, (list, tuple, set)):
        raise AssertionError(f"{name} must be a list/tuple/set literal")
    return {str(item) for item in value}


def _literal_route_mapping(module: ast.Module, name: str) -> set[tuple[str, str]]:
    value = _assignment_value(module, name)
    if not isinstance(value, dict):
        raise AssertionError(f"{name} must be a dict literal")
    routes: set[tuple[str, str]] = set()
    for path, methods in value.items():
        if not isinstance(methods, (list, tuple, set)):
            raise AssertionError(f"{name}[{path!r}] must be a list/tuple/set literal")
        for method in methods:
            routes.add((str(path), str(method).upper()))
    return routes


def _string_literal(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _literal_methods(node: ast.AST | None) -> set[str]:
    if node is None:
        return set()
    try:
        value = ast.literal_eval(node)
    except Exception:
        return set()
    if isinstance(value, str):
        return {value.upper()}
    if isinstance(value, (list, tuple, set)):
        return {str(item).upper() for item in value}
    return set()


def _keyword_value(call: ast.Call, name: str) -> ast.AST | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _call_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _is_known_route_host(call: ast.Call) -> bool:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id == "APIRoute"
    if isinstance(func, ast.Attribute):
        return isinstance(func.value, ast.Name) and func.value.id in ROUTE_HOST_NAMES
    return False


def _path_from_call(call: ast.Call) -> str | None:
    path_node: ast.AST | None = None
    if call.args:
        path_node = call.args[0]
    if path_node is None:
        path_node = _keyword_value(call, "path")
    path = _string_literal(path_node)
    if not path or not path.startswith("/api/"):
        return None
    return path


def _routes_from_call(call: ast.Call) -> set[tuple[str, str]]:
    if not _is_known_route_host(call):
        return set()

    name = _call_name(call)
    if name == "add_api_route" or name == "APIRoute":
        path = _path_from_call(call)
        if not path:
            return set()
        methods = _literal_methods(_keyword_value(call, "methods"))
        return {(path, method) for method in methods}

    if name in DECORATOR_METHODS:
        path = _path_from_call(call)
        if not path:
            return set()
        return {(path, DECORATOR_METHODS[name])}

    if name in GENERIC_ROUTE_DECORATORS:
        path = _path_from_call(call)
        if not path:
            return set()
        methods = _literal_methods(_keyword_value(call, "methods"))
        return {(path, method) for method in methods}

    return set()


def _routes_from_source(source: str) -> set[tuple[str, str]]:
    tree = ast.parse(source)
    routes: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            routes.update(_routes_from_call(node))
    return routes


def _registered_runtime_routes(module_names: set[str]) -> set[tuple[str, str]]:
    routes: set[tuple[str, str]] = set()
    for module_name in sorted(module_names):
        path = ROOT / f"{module_name}.py"
        if not path.exists():
            continue
        routes.update(_routes_from_source(path.read_text(encoding="utf-8")))
    return routes


def _check_route_scanner_smoke() -> None:
    source = '''
from fastapi.routing import APIRoute

app.add_api_route("/api/add", handler, methods=["GET", "POST"])
APIRoute(path="/api/apiroute", endpoint=handler, methods=["DELETE"])

@app.get("/api/decorator-get")
def decorator_get():
    pass

@app.api_route("/api/decorator-api-route", methods=["PATCH"])
def decorator_api_route():
    pass

payload.get("/api/not-a-route")
client.post("/api/not-a-route")
app.get("/static/not-api")
'''
    expected = {
        ("/api/add", "GET"),
        ("/api/add", "POST"),
        ("/api/apiroute", "DELETE"),
        ("/api/decorator-get", "GET"),
        ("/api/decorator-api-route", "PATCH"),
    }
    found = _routes_from_source(source)
    missing = expected - found
    extra = found - expected
    problems = []
    if missing:
        problems.append("Route scanner smoke test missed routes:\n" + "\n".join(_format_route(route) for route in sorted(missing, key=_format_route)))
    if extra:
        problems.append("Route scanner smoke test found false positives:\n" + "\n".join(_format_route(route) for route in sorted(extra, key=_format_route)))
    if problems:
        raise AssertionError("\n\n".join(problems))


def _check_step5_flush_bridge_contract() -> None:
    content = (ROOT / "runtime_step5_flush_bridge.py").read_text(encoding="utf-8")
    required = [
        "window.PPTStudio",
        "flushStep5Draft",
        "state.step5AutoSaveTimer",
        "state.step5AutoSavePromise",
        "AI_MASK_FLUSH_MARKER",
        "ai_mask_extension.js",
        "app.js",
        "app_has_native_step5_flush",
        "APP_FLUSH_MARKER in body or app_has_native_step5_flush(body)",
        "preferred long-term implementation is a native",
    ]
    missing = [snippet for snippet in required if snippet not in content]
    if missing:
        raise AssertionError("Step 5 flush bridge contract failed:\n" + "\n".join(missing))


def _check_ai_mask_cache_buster_contract() -> None:
    content = (ROOT / "runtime_ai_mask_ui_cache_buster.py").read_text(encoding="utf-8")
    required = [
        "ai_mask_extension.js",
        "SCRIPT_VERSION",
        "INSTALL_TIMEOUT_SEC = 120.0",
        "PPT_STUDIO_DISABLE_AI_MASK_UI_CACHE_BUSTER",
    ]
    missing = [snippet for snippet in required if snippet not in content]
    if missing:
        raise AssertionError("AI Mask UI cache buster contract failed:\n" + "\n".join(missing))


def _check_runtime_diagnostics_contract() -> None:
    content = (ROOT / "runtime_diagnostics.py").read_text(encoding="utf-8")
    required = [
        "/api/runtime/diagnostics",
        "missing_routes",
        "middleware_markers",
        "script_versions",
        "runtime_modules",
        "step5_flush_migration",
        "native_app_js",
        "fallback_bridge",
        "bridge_would_inject",
        "PPT_STUDIO_DISABLE_RUNTIME_DIAGNOSTICS",
        "INSTALL_TIMEOUT_SEC = 120.0",
    ]
    missing = [snippet for snippet in required if snippet not in content]
    if missing:
        raise AssertionError("Runtime diagnostics bridge contract failed:\n" + "\n".join(missing))


def _check_visual_draft_quality_contract() -> None:
    content = (ROOT / "runtime_visual_draft_quality.py").read_text(encoding="utf-8")
    required = [
        "/api/projects/{project_id}/steps/3/visual-draft-quality",
        "scripts.check_visual_draft_quality",
        "check_run_dir",
        "PPT_STUDIO_DISABLE_VISUAL_DRAFT_QUALITY",
        "INSTALL_TIMEOUT_SEC = 120.0",
    ]
    missing = [snippet for snippet in required if snippet not in content]
    if missing:
        raise AssertionError("Step 3 visual draft quality bridge contract failed:\n" + "\n".join(missing))


def _check_bootstrap_installs_before_ready() -> None:
    content = BOOTSTRAP_PATH.read_text(encoding="utf-8")
    forbidden = "if runtime_paths_ready(module):\n                    return\n                install_for_server_module(module)"
    required = "install_for_server_module(module)\n                if runtime_paths_ready(module):\n                    return"
    if forbidden in content:
        raise AssertionError("runtime_bootstrap must not return before installing middleware-only runtime bridges")
    if required not in content:
        raise AssertionError("runtime_bootstrap worker must install runtime bridges before checking route readiness")


def _check_bootstrap_logger_contract() -> None:
    content = BOOTSTRAP_PATH.read_text(encoding="utf-8")
    required = 'logger.warning("Failed to register runtime bridge %s: %s", module_name, exc)'
    forbidden = 'logger.warning("Failed to register runtime bridge %s: %s", exc)'
    if forbidden in content:
        raise AssertionError("runtime_bootstrap register warning must include module_name and exception")
    if required not in content:
        raise AssertionError("runtime_bootstrap register warning format changed unexpectedly")


def _format_route(route: tuple[str, str]) -> str:
    path, method = route
    return f"{method} {path}"


def main() -> None:
    _check_route_scanner_smoke()
    _check_step5_flush_bridge_contract()
    _check_ai_mask_cache_buster_contract()
    _check_runtime_diagnostics_contract()
    _check_visual_draft_quality_contract()
    _check_bootstrap_installs_before_ready()
    _check_bootstrap_logger_contract()
    tree = ast.parse(BOOTSTRAP_PATH.read_text(encoding="utf-8"), filename=str(BOOTSTRAP_PATH))
    modules = _literal_string_collection(tree, "RUNTIME_MODULES")
    routes = _literal_route_mapping(tree, "EXPECTED_RUNTIME_ROUTES")
    registered_routes = _registered_runtime_routes(modules)

    missing_modules = sorted(REQUIRED_MODULES - modules)
    missing_routes = sorted(REQUIRED_READY_ROUTES - routes, key=_format_route)
    unbacked_ready_routes = sorted(routes - registered_routes, key=_format_route)
    problems = []
    if missing_modules:
        problems.append("Missing runtime modules:\n" + "\n".join(missing_modules))
    if missing_routes:
        problems.append("Missing ready routes:\n" + "\n".join(_format_route(route) for route in missing_routes))
    if unbacked_ready_routes:
        problems.append("Ready routes without a matching runtime registration:\n" + "\n".join(_format_route(route) for route in unbacked_ready_routes))
    if problems:
        raise SystemExit("\n\n".join(problems))
    print("Runtime bootstrap contract passed.")


if __name__ == "__main__":
    main()
