from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def source(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_server_is_a_composition_root_without_business_definitions() -> None:
    server_source = source("server.py")
    tree = ast.parse(server_source)

    assert not [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    assert "from json_llm_service import (" in server_source
    assert "from project_path_service import (" in server_source
    assert "from template_utils import normalized_template_name, template_timestamp" in server_source


def test_extracted_helpers_have_single_source_ownership() -> None:
    server_source = source("server.py")
    owners = {
        "json_llm_service.py": (
            "parse_json_or_repair_with_llm",
            "generate_json_with_configured_llm",
        ),
        "project_path_service.py": (
            "read_current_slide_ids_or_404",
            "project_run_dir_or_500",
            "current_slide_file_or_404",
        ),
        "template_utils.py": (
            "normalized_template_name",
            "template_timestamp",
        ),
    }

    for module_name, function_names in owners.items():
        module_source = source(module_name)
        assert "import server" not in module_source
        assert "server_module" not in module_source
        for function_name in function_names:
            assert f"def {function_name}(" in module_source
            assert f"def {function_name}(" not in server_source


def test_application_middleware_is_installed_from_its_owner_module() -> None:
    server_source = source("server.py")
    middleware_source = source("app_middleware.py")

    assert "from app_middleware import install_static_asset_cache_policy" in server_source
    assert "install_static_asset_cache_policy(app)" in server_source
    assert "def no_cache_static_assets(" not in server_source
    assert "def install_static_asset_cache_policy(" in middleware_source
