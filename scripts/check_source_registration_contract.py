"""Validate that production services are registered explicitly at startup."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    server = (ROOT / "server.py").read_text(encoding="utf-8")
    article_routes = (ROOT / "article_routes.py").read_text(encoding="utf-8")
    article_service = (ROOT / "article_service.py").read_text(encoding="utf-8")
    settings_routes = (ROOT / "settings_routes.py").read_text(
        encoding="utf-8"
    )
    settings_service = (ROOT / "settings_service.py").read_text(
        encoding="utf-8"
    )
    config_portability_service = (
        ROOT / "config_portability_service.py"
    ).read_text(encoding="utf-8")
    ai_provider_service = (
        ROOT / "ai_provider_service.py"
    ).read_text(encoding="utf-8")
    tts_provider_service = (
        ROOT / "tts_provider_service.py"
    ).read_text(encoding="utf-8")
    pipeline = (ROOT / "pipeline_services.py").read_text(encoding="utf-8")
    pptx_routes = (ROOT / "pptx_routes.py").read_text(encoding="utf-8")
    pptx_service = (ROOT / "pptx_service.py").read_text(encoding="utf-8")
    video_routes = (ROOT / "video_routes.py").read_text(encoding="utf-8")
    video_service = (ROOT / "video_render_service.py").read_text(encoding="utf-8")
    video_artifacts = (ROOT / "video_artifact_service.py").read_text(encoding="utf-8")
    video_jobs = (ROOT / "video_job_store.py").read_text(encoding="utf-8")
    remotion_runner = (ROOT / "remotion_runner.py").read_text(encoding="utf-8")
    storyboard_routes = (ROOT / "storyboard_routes.py").read_text(encoding="utf-8")
    storyboard_service = (ROOT / "storyboard_service.py").read_text(encoding="utf-8")
    narration_routes = (ROOT / "narration_routes.py").read_text(encoding="utf-8")
    narration_service = (ROOT / "narration_service.py").read_text(encoding="utf-8")
    narration_audio_service = (
        ROOT / "narration_audio_service.py"
    ).read_text(encoding="utf-8")
    visual_contract_service = (
        ROOT / "visual_contract_service.py"
    ).read_text(encoding="utf-8")
    runtime_support = (ROOT / "runtime_support.py").read_text(
        encoding="utf-8"
    )
    project_runtime_service = (
        ROOT / "project_runtime_service.py"
    ).read_text(encoding="utf-8")
    mask_routes = (ROOT / "mask_editor_routes.py").read_text(encoding="utf-8")
    mask_manifest = (ROOT / "mask_manifest_service.py").read_text(encoding="utf-8")
    mask_preview = (ROOT / "mask_preview_service.py").read_text(encoding="utf-8")
    tts_routes = (ROOT / "tts_routes.py").read_text(encoding="utf-8")
    tts_service = (ROOT / "tts_service.py").read_text(encoding="utf-8")
    project_routes = (ROOT / "project_routes.py").read_text(encoding="utf-8")
    project_service = (ROOT / "project_service.py").read_text(encoding="utf-8")
    global_image_style_routes = (
        ROOT / "global_image_style_routes.py"
    ).read_text(encoding="utf-8")
    global_image_style_service = (
        ROOT / "global_image_style_service.py"
    ).read_text(encoding="utf-8")
    image_workflow_routes = (
        ROOT / "image_workflow_routes.py"
    ).read_text(encoding="utf-8")
    image_workflow_service = (
        ROOT / "image_workflow_service.py"
    ).read_text(encoding="utf-8")
    visual_settings_routes = (
        ROOT / "visual_settings_routes.py"
    ).read_text(encoding="utf-8")
    visual_settings_service = (
        ROOT / "visual_settings_service.py"
    ).read_text(encoding="utf-8")
    project_style_context = (
        ROOT / "project_style_context.py"
    ).read_text(encoding="utf-8")
    project_profile_service = (
        ROOT / "project_profile_service.py"
    ).read_text(encoding="utf-8")
    project_style_reference_service = (
        ROOT / "project_style_reference_service.py"
    ).read_text(encoding="utf-8")
    image_style_reverse_service = (
        ROOT / "image_style_reverse_service.py"
    ).read_text(encoding="utf-8")
    step3_image_style_service = (
        ROOT / "step3_image_style_service.py"
    ).read_text(encoding="utf-8")
    ai_mask_engine = (ROOT / "ai_mask_engine.py").read_text(encoding="utf-8")
    ai_mask_semantic_matcher = (
        ROOT / "ai_mask_semantic_matcher.py"
    ).read_text(encoding="utf-8")
    ai_mask_service = (ROOT / "ai_mask_service.py").read_text(encoding="utf-8")
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert not (ROOT / "runtime_bootstrap.py").exists(), "empty runtime bootstrap should stay retired"
    assert "app.include_router(one_click_router)" in server, "one-click router is not explicitly registered"
    assert "app.include_router(article_router)" in server, "article router is not explicitly registered"
    assert "app.include_router(settings_router)" in server, "settings router is not explicitly registered"
    assert "app.include_router(diagnostics_router)" in server, "diagnostics router is not explicitly registered"
    assert "app.include_router(storyboard_background_router)" in server, "storyboard background router is not explicitly registered"
    assert "app.include_router(storyboard_router)" in server, "Step 2 storyboard router is not explicitly registered"
    assert "app.include_router(narration_router)" in server, "narration router is not explicitly registered"
    assert "app.include_router(tts_router)" in server, "TTS router is not explicitly registered"
    assert "app.include_router(project_router)" in server, "project router is not explicitly registered"
    assert "app.include_router(global_image_style_router)" in server, "global image-style router is not explicitly registered"
    assert "app.include_router(image_workflow_router)" in server, "Step 3 image workflow router is not explicitly registered"
    assert "app.include_router(visual_settings_router)" in server, "visual settings router is not explicitly registered"
    assert "app.include_router(mask_editor_router)" in server, "Mask editor router is not explicitly registered"
    assert "app.include_router(pptx_router)" in server, "PPTX router is not explicitly registered"
    assert "app.include_router(video_router)" in server, "video router is not explicitly registered"
    assert "one_click_orchestrator._register" not in server, "legacy one-click registration returned"
    assert "diagnostics_routes._register" not in server, "legacy diagnostics registration returned"
    assert "storyboard_background._register" not in server, "legacy storyboard background registration returned"
    assert '@app.post("/api/projects/{project_id}/steps/2/' not in server, "Step 2 route decorators returned to server"
    assert "APIRouter" not in storyboard_service, "storyboard service owns HTTP routing again"
    assert "router = APIRouter()" in storyboard_routes, "storyboard routes module is incomplete"
    for source in (storyboard_routes, storyboard_service):
        assert "server_module" not in source, "storyboard code receives the server module again"
        assert "sys.modules" not in source, "storyboard code receives a dynamic application namespace"
    for source in (
        narration_routes,
        narration_service,
        tts_routes,
        tts_service,
    ):
        assert "server_module" not in source, "narration/TTS code receives the server module again"
        assert "sys.modules" not in source, "narration/TTS code receives a dynamic application namespace"
    assert "APIRouter" not in narration_service, "narration service owns HTTP routing again"
    assert "APIRouter" not in tts_service, "TTS service owns HTTP routing again"
    for function_name in (
        "clean_tts_text",
        "prepare_narration_payload",
        "sync_narration_sources_from_contract",
        "rewrite_audio_timeline_by_beats",
    ):
        assert f"def {function_name}(" in narration_audio_service, (
            f"narration audio owner is missing {function_name}"
        )
        assert f"def {function_name}(" not in server, (
            f"{function_name} implementation returned to server"
        )
    for token in (
        "APIRouter",
        "Depends(",
        "get_db",
        "server_module",
        "import server",
    ):
        assert token not in narration_audio_service, (
            "narration audio service owns application wiring again"
        )
        assert token not in visual_contract_service, (
            "visual contract service owns application wiring again"
        )
        assert token not in runtime_support, (
            "runtime support owns application wiring again"
        )
        assert token not in project_runtime_service, (
            "project runtime service owns application wiring again"
        )
    for function_name in (
        "normalize_visual_type",
        "narration_dedupe_key",
        "normalize_visual_contract",
        "read_contract_slide_ids",
    ):
        assert f"def {function_name}(" in visual_contract_service, (
            f"visual contract owner is missing {function_name}"
        )
        assert f"def {function_name}(" not in server, (
            f"{function_name} implementation returned to server"
        )
    for function_name in (
        "run_subprocess_bounded",
        "parse_json_process_stdout",
        "read_json_file",
        "clean_json_markdown",
        "parse_int_setting",
        "is_timeout_exception",
        "parse_range_text",
    ):
        assert f"def {function_name}(" in runtime_support, (
            f"runtime support owner is missing {function_name}"
        )
        assert f"def {function_name}(" not in server, (
            f"{function_name} implementation returned to server"
        )
    for function_name in (
        "reveal_lock_for",
        "write_project_log",
        "all_current_slide_images_exist",
        "sync_reveal_manifest_to_contract",
        "audio_confirmation_path",
        "project_audio_confirmed",
        "slide_tts_artifact_paths",
        "slide_tts_artifact_status",
        "ensure_slide_tts_text_file",
        "mark_step_retry_needed",
        "mark_step_in_progress",
        "handle_step_navigation",
        "invalidate_after_upstream_edit",
        "clear_slide_visual_derivatives",
        "mark_slide_image_changed",
    ):
        assert f"def {function_name}(" in project_runtime_service, (
            f"project runtime owner is missing {function_name}"
        )
        assert f"def {function_name}(" not in server, (
            f"{function_name} implementation returned to server"
        )
    assert "router = APIRouter()" in article_routes, "article routes module is incomplete"
    assert "APIRouter" not in article_service, "article service owns HTTP routing again"
    assert "Depends(" not in article_service, "article service owns FastAPI dependency wiring again"
    assert "get_db" not in article_service, "article service imports the route database dependency again"
    assert '@app.post("/api/projects/{project_id}/steps/1/' not in server, "Step 1 route decorators returned to server"
    for source in (article_routes, article_service):
        assert "server_module" not in source, "article code receives the server module again"
        assert "import server" not in source, "article code imports the application module again"
    assert "router = APIRouter()" in settings_routes, "settings routes module is incomplete"
    assert "APIRouter" not in settings_service, "settings service owns HTTP routing again"
    assert "APIRouter" not in config_portability_service, "config service owns HTTP routing again"
    assert '@app.get("/api/settings")' not in server, "settings route decorator returned to server"
    assert '@app.post("/api/config/import")' not in server, "config route decorator returned to server"
    for source in (
        settings_routes,
        settings_service,
        config_portability_service,
    ):
        assert "server_module" not in source, "settings code receives the server module again"
        assert "import server" not in source, "settings code imports the application module again"
    for source in (settings_service, config_portability_service):
        assert "Depends(" not in source, "settings service owns FastAPI dependency wiring again"
        assert "get_db" not in source, "settings service imports the route database dependency again"
    assert "def get_openai_client(" in ai_provider_service, "AI provider client owner is incomplete"
    assert "def generate_image_response(" in ai_provider_service, "image provider adapter owner is incomplete"
    assert "def process_and_save_image(" in ai_provider_service, "image normalization owner is incomplete"
    assert "def get_openai_client(" not in server, "OpenAI client implementation returned to server"
    assert "def generate_image_response(" not in server, "image provider implementation returned to server"
    for token in (
        "APIRouter",
        "Depends(",
        "get_db",
        "server_module",
        "import server",
    ):
        assert token not in ai_provider_service, "AI provider service owns application wiring again"
    assert "def provider_tts_command(" in tts_provider_service, "TTS command owner is incomplete"
    assert "def run_tts_command_with_retries(" in tts_provider_service, "TTS retry owner is incomplete"
    assert "def provider_tts_command(" not in server, "TTS command implementation returned to server"
    assert "def run_tts_command_with_retries(" not in server, "TTS retry implementation returned to server"
    for token in (
        "APIRouter",
        "Depends(",
        "get_db",
        "server_module",
        "import server",
    ):
        assert token not in tts_provider_service, "TTS provider service owns application wiring again"
    assert "router = APIRouter()" in mask_routes, "Mask editor routes module is incomplete"
    assert "APIRouter" not in mask_manifest, "Mask Manifest service owns HTTP routing again"
    assert "APIRouter" not in mask_preview, "Mask preview service owns HTTP routing again"
    assert '@app.put("/api/projects/{project_id}/steps/5/' not in server, "Step 5 route decorators returned to server"
    for source in (mask_routes, mask_manifest, mask_preview):
        assert "server_module" not in source, "Mask code receives the server module again"
        assert "import server" not in source, "Mask code imports the application module again"
    assert '@app.post("/api/projects")' not in server, "project creation route returned to server"
    assert "APIRouter" not in project_service, "project service owns HTTP routing again"
    assert "router = APIRouter()" in project_routes, "project routes module is incomplete"
    for source in (
        global_image_style_service,
        image_workflow_service,
        visual_settings_service,
    ):
        assert "APIRouter" not in source, "Step 3 service owns HTTP routing again"
        assert "Depends(" not in source, "Step 3 service owns FastAPI dependency wiring again"
        assert "get_db" not in source, "Step 3 service imports the route database dependency again"
    for function_name in (
        "normalize_hex_color",
        "normalize_subtitle_style",
        "read_project_visual_settings",
        "write_project_visual_settings",
        "sync_project_background_color",
    ):
        assert f"def {function_name}(" in visual_settings_service, (
            f"visual settings owner is missing {function_name}"
        )
        assert f"def {function_name}(" not in server, (
            f"{function_name} implementation returned to server"
        )
    for callback_name in (
        "read_settings",
        "write_settings",
        "sync_background",
        "invalidate_background",
        "invalidate_subtitles",
        "preview_background_url",
    ):
        assert (
            f"{callback_name}: Callable" not in visual_settings_service
        ), "visual settings business callback injection returned"
    for source in (
        global_image_style_routes,
        image_workflow_routes,
        visual_settings_routes,
    ):
        assert "router = APIRouter()" in source, "Step 3 routes module is incomplete"
    for source in (
        global_image_style_routes,
        global_image_style_service,
        image_workflow_routes,
        image_workflow_service,
        visual_settings_routes,
        visual_settings_service,
    ):
        assert "server_module" not in source, "Step 3 code receives the server module again"
        assert "import server" not in source, "Step 3 code imports the application module again"
    assert "register_pptx_routes" not in server, "legacy PPTX registration returned"
    assert "app.include_router(project_style_router)" in server, "project style router is not explicitly registered"
    assert "register_project_style_routes" not in server, "legacy project style registration returned"
    assert "class ProjectStyleDependencies" in project_style_context, "project style dependency contract is missing"
    assert "SimpleNamespace" not in project_style_context, "project style context is mutable again"
    for source in (
        project_style_context,
        project_profile_service,
        project_style_reference_service,
        image_style_reverse_service,
        step3_image_style_service,
    ):
        assert "server_module" not in source, "project style code receives the server module again"
        assert "import server" not in source, "project style code imports the application module again"
    assert "class AiMaskEngineDependencies" in ai_mask_engine, "AI Mask engine dependency contract is missing"
    for source in (
        ai_mask_engine,
        ai_mask_semantic_matcher,
        ai_mask_service,
    ):
        assert "server_module" not in source, "AI Mask code receives the server module again"
        assert "SimpleNamespace" not in source, "AI Mask code receives a mutable application context again"
        assert "import server" not in source, "AI Mask code imports the application module again"
    assert "app.include_router(ai_mask_router)" in server, "AI Mask routes are not explicitly registered"
    assert "runtime_ai_mask._register" not in server, "legacy AI Mask registration returned"
    assert "runtime_ai_mask_semantic_patch" not in server, "semantic runtime patch returned"
    assert "vision_matcher=semantic_vision_matcher" in server, "semantic matcher is not explicitly injected"
    assert "pipeline_operations = PipelineOperations(" in server, "pipeline operations are not explicitly assembled"
    assert "ModuleType" not in pipeline, "pipeline facade receives a module again"
    assert "server_module" not in pipeline, "pipeline facade receives the server module again"
    assert "self.server" not in pipeline, "pipeline facade stores the server module again"
    for source in (pptx_routes, pptx_service):
        assert "server_module" not in source, "PPTX code receives the server module again"
        assert "sys.modules" not in source, "PPTX code receives a dynamic application namespace"
        assert "_SERVER" not in source, "PPTX code stores the application module again"
    for source in (
        video_routes,
        video_service,
        video_artifacts,
        video_jobs,
        remotion_runner,
    ):
        assert "server_module" not in source, "video code receives the server module again"
        assert "sys.modules" not in source, "video code receives a dynamic application namespace"
    assert "class VideoJobStore" not in video_service, "job persistence returned to the coordinator"
    assert "subprocess.run(" not in video_service, "Remotion execution returned to the coordinator"
    assert "record_artifact(" not in video_service, "artifact lifecycle returned to the coordinator"
    assert "class VideoJobStore" in video_jobs, "video job store module is incomplete"
    assert "class VideoArtifactService" in video_artifacts, "video artifact service module is incomplete"
    assert "class RemotionRunner" in remotion_runner, "Remotion runner module is incomplete"
    assert "def _render_video_worker(" not in server, "legacy video worker returned to server"
    assert '@app.post("/api/projects/{project_id}/steps/8/render")' not in server, "legacy video routes returned to server"
    for script in (
        "project_profile_extension.js",
        "storyboard_background_extension.js",
        "style_reference_manager_extension.js",
        "ai_mask_extension.js",
        "one_click_extension.js",
    ):
        assert script in html, f"direct script declaration missing: {script}"
    print("explicit source registration contract passed")


if __name__ == "__main__":
    main()
