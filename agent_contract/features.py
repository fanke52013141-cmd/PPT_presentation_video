"""Side-effect-free business entrypoint inventory and explicit coverage decisions."""

from __future__ import annotations

import ast
import json
from pathlib import Path

from repository_paths import REPO_ROOT, AGENT_FEATURES_PATH

# 扫描排除目录：Agent 自有面（适配器不是业务入口）与无业务路由的目录。
# 未列入排除的新目录会被扫描——业务路由搬进子目录包不能再逃逸门禁
# （审查 2026-10-24 G2/G3）。
_SCAN_EXCLUDED_DIRS = {
    ".venv", ".git", ".github", ".pytest_cache", ".ruff_cache", ".tmp",
    "__pycache__", "node_modules",
    "agent_api", "agent_contract", "agent_client", "cli", "mcp_server",
    "checks", "docs", "scripts", "migrations", "tools", "static",
    "outputs", "runs", "data", "logs", "runtime", "config",
    "schemas", "templates", "references", "bad_cases",
}

# 文件级排除：独立进程部署的微服务，其 FastAPI app 不挂载进主服务。
# digital_human_service.py 是 LatentSync 数字人 Worker（自带独立
# FastAPI），Agent 面经主服务 digital_human_routes 适配器代理覆盖，
# 其内部路由不是主服务的业务入口。
_SCAN_EXCLUDED_FILES = {"digital_human_service.py"}


def _business_python_files() -> list[Path]:
    root = Path(REPO_ROOT)
    candidates = list(root.glob("*.py"))
    candidates.extend(root.rglob("*.py"))
    files = []
    for path in sorted(dict.fromkeys(candidates)):
        if path.name in _SCAN_EXCLUDED_FILES:
            continue
        relative = path.relative_to(root)
        if any(part in _SCAN_EXCLUDED_DIRS for part in relative.parts):
            continue
        files.append(path)
    return files


def source_entrypoints() -> dict[str, dict]:
    """Read route declarations without importing server or recovering live jobs.

    This source guard complements effective-route tests; it is deliberately
    not used as the production HTTP route inspection API.

    识别三类路由声明（审查 2026-10-24 G2/G3 加固）：
    1. 本文件模块级 ``router = APIRouter(...)`` / ``app = FastAPI(...)`` 赋值
       上的装饰器（router 字段保持构造调用原文，与 agent_features.json 兼容）；
    2. 从其他模块导入的 router 名（``from x import router`` 后 ``@router.get``）；
    3. 仓库根目录与未被排除的子目录包（递归扫描）。
    """
    parsed = []
    for path in _business_python_files():
        parsed.append((path, ast.parse(path.read_text(encoding="utf-8-sig"))))
    stems = [path.stem for path, _ in parsed]
    colliding_stems = {stem for stem in stems if stems.count(stem) > 1}

    entries = {}
    for path, tree in parsed:
        routers = {}
        imported_names = set()
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imported_names.add(alias.asname or alias.name)
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                func = node.value.func
                if isinstance(func, ast.Name) and func.id in {"APIRouter", "FastAPI"}:
                    routers.update({target.id: ast.unparse(node.value)
                                    for target in node.targets if isinstance(target, ast.Name)})
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            declarations = []
            for dec in node.decorator_list:
                if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
                    continue
                bound = dec.func.value
                bound_name = bound.id if isinstance(bound, ast.Name) else None
                if bound_name is None:
                    continue
                if bound_name in routers:
                    router_repr = routers[bound_name]
                elif bound_name in imported_names:
                    router_repr = bound_name
                else:
                    continue
                method = dec.func.attr.upper()
                if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "API_ROUTE"}:
                    continue
                declarations.append({"method": method, "declaration": ast.unparse(dec),
                                     "router": router_repr})
            if declarations:
                if path.stem in colliding_stems:
                    # 同名文件在不同包中：用完整相对路径消歧，保持确定性。
                    key_base = path.relative_to(REPO_ROOT).with_suffix("").as_posix()
                else:
                    key_base = path.stem
                key = f"{key_base}.{node.name}"
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
