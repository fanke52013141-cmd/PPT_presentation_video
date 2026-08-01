from __future__ import annotations

from pathlib import Path

from route_inventory import iter_effective_routes
import server


ROOT = Path(__file__).resolve().parents[1]


EXPECTED_STORYBOARD_PATHS = {
    "/api/step2-prompt-templates",
    "/api/step2-prompt-templates/{template_id}",
    "/api/storyboard-templates",
    "/api/storyboard-templates/{template_id}",
    "/api/projects/{project_id}/steps/2/rules",
    "/api/projects/{project_id}/steps/2/prompts",
    "/api/projects/{project_id}/steps/2/script/execute",
    "/api/projects/{project_id}/steps/2/script/result",
    "/api/projects/{project_id}/steps/2/visual/execute",
    "/api/projects/{project_id}/steps/2/visual/result",
    "/api/projects/{project_id}/steps/2/compose",
    "/api/projects/{project_id}/steps/2/prompt-preview",
    "/api/projects/{project_id}/steps/2/execute",
    "/api/projects/{project_id}/steps/2/result",
    "/api/projects/{project_id}/steps/2/repair",
    "/api/projects/{project_id}/steps/2/manual-skeleton",
}


def test_storyboard_router_preserves_all_public_paths() -> None:
    actual = {
        route.path
        for route in iter_effective_routes(server.app)
        if (
            "/steps/2/" in route.path
            or "step2-prompt-templates" in route.path
            or "storyboard-templates" in route.path
        )
    }
    assert actual == EXPECTED_STORYBOARD_PATHS


def test_storyboard_service_and_routes_have_explicit_boundaries() -> None:
    server_source = (ROOT / "server.py").read_text(encoding="utf-8")
    service_source = (ROOT / "storyboard_service.py").read_text(
        encoding="utf-8"
    )
    planning_source = (ROOT / "storyboard_planning.py").read_text(
        encoding="utf-8"
    )
    llm_source = (ROOT / "storyboard_llm.py").read_text(encoding="utf-8")
    profiles_source = (ROOT / "storyboard_profiles.py").read_text(
        encoding="utf-8"
    )
    prompt_templates_source = (
        ROOT / "storyboard_prompt_templates.py"
    ).read_text(encoding="utf-8")
    routes_source = (ROOT / "storyboard_routes.py").read_text(
        encoding="utf-8"
    )

    assert "app.include_router(storyboard_router)" in server_source
    assert '@app.post("/api/projects/{project_id}/steps/2/' not in (
        server_source
    )
    assert "@router." not in service_source
    assert "APIRouter" not in service_source
    assert "router = APIRouter()" in routes_source
    for source in (service_source, routes_source):
        assert "server_module" not in source
        assert "sys.modules" not in source
        assert "import server" not in source

    for owner in (
        "normalize_slide_script_plan",
        "normalize_slide_visual_plan",
        "build_step2_script_user_prompt",
        "build_step2_visual_user_prompt",
        "compose_visual_contract_from_plans",
    ):
        assert f"def {owner}(" in planning_source
        assert f"def {owner}(" not in service_source
    assert "from storyboard_planning import (" in service_source
    assert "server_module" not in planning_source
    assert "import server" not in planning_source

    for owner in (
        "sanitize_storyboard_profile",
        "parse_storyboard_profile_text",
        "apply_storyboard_profile_patch",
        "read_project_pipeline_profile",
    ):
        assert f"def {owner}(" in profiles_source
        assert f"def {owner}(" not in service_source
    assert "from storyboard_profiles import (" in service_source
    assert "server_module" not in profiles_source
    assert "import server" not in profiles_source

    for owner in (
        "read_step2_prompts",
        "built_in_step2_prompt_templates",
        "save_step2_prompt_template",
        "migrate_legacy_step2_prompt",
        "step2_prompt_response",
    ):
        assert f"def {owner}(" in prompt_templates_source
        assert f"def {owner}(" not in service_source
    assert "from storyboard_prompt_templates import (" in service_source
    assert "configure_storyboard_prompt_templates(" in service_source
    assert "server_module" not in prompt_templates_source
    assert "import server" not in prompt_templates_source

    assert "class StoryboardLlmCapabilities" in llm_source
    assert "def execute_step2_json_llm(" in llm_source
    assert "client.chat.completions.create(" in llm_source
    assert "execute_step2_json_llm(" in service_source
    assert "client.chat.completions.create(" not in service_source
    assert "server_module" not in llm_source
    assert "import server" not in llm_source
