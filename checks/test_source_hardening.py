from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def main() -> None:
    server = read_text("server.py")
    video_service = read_text("video_render_service.py")
    remotion_runner = read_text("remotion_runner.py")
    video_artifacts = read_text("video_artifact_service.py")
    video_routes = read_text("video_routes.py")
    narration_service = read_text("narration_service.py")
    narration_audio_service = read_text(
        "narration_audio_service.py"
    )
    visual_contract_service = read_text(
        "visual_contract_service.py"
    )
    visual_settings_service = read_text(
        "visual_settings_service.py"
    )
    runtime_support = read_text("runtime_support.py")
    project_runtime_service = read_text(
        "project_runtime_service.py"
    )
    mask_manifest_service = read_text("mask_manifest_service.py")
    settings_routes = read_text("settings_routes.py")
    settings_service = read_text("settings_service.py")
    config_service = read_text("config_portability_service.py")
    provider_service = read_text("ai_provider_service.py")
    tts_provider_service = read_text("tts_provider_service.py")
    app_js = read_text("static/app.js")
    ci = read_text(".github/workflows/ci.yml")

    assert '"src/index.tsx",' in remotion_runner
    assert '"ArticleVideo",' in remotion_runner
    assert "output_path = output_dir / output_filename" in remotion_runner
    assert "def run_render_job(" in video_service
    assert "def start_render(" in video_service
    assert "tts_confirmation_status(" in video_service
    assert "subprocess.run(" not in video_service
    assert "record_artifact(" not in video_service
    assert "class VideoJobStore" not in video_service
    assert "class VideoArtifactService" in video_artifacts
    assert "class RemotionRunner" in remotion_runner
    assert "router = APIRouter()" in video_routes
    assert "app.include_router(video_router)" in server
    assert "def _render_video_worker(" not in server

    assert "def mask_sensitive_settings" in settings_service
    assert "return mask_sensitive_settings(_deps().get_all_settings())" in settings_service
    assert "preserve_masked_secrets(" in settings_service
    assert 'allow_origins=["*"]' not in server
    assert "configured_allowed_origins()" in server
    assert "force=True" in config_service
    assert "app.include_router(settings_router)" in server
    assert "router = APIRouter()" in settings_routes
    assert '@app.get("/api/settings")' not in server
    assert '@app.post("/api/config/import")' not in server
    assert "def get_openai_client(" in provider_service
    assert "def process_and_save_image(" in provider_service
    assert "def generate_image_response(" in provider_service
    assert "def get_openai_client(" not in server
    assert "def process_and_save_image(" not in server
    assert "def generate_image_response(" not in server
    assert "def clean_tts_text(" in narration_audio_service
    assert "def prepare_narration_payload(" in narration_audio_service
    assert (
        "def rewrite_audio_timeline_by_beats("
        in narration_audio_service
    )
    assert "def clean_tts_text(" not in server
    assert "def prepare_narration_payload(" not in server
    assert "def rewrite_audio_timeline_by_beats(" not in server
    for token in (
        "APIRouter",
        "Depends(",
        "get_db",
        "server_module",
        "import server",
    ):
        assert token not in narration_audio_service
        assert token not in visual_contract_service
    assert "def normalize_visual_contract(" in visual_contract_service
    assert "def read_contract_slide_ids(" in visual_contract_service
    assert "def normalize_visual_contract(" not in server
    assert "def read_contract_slide_ids(" not in server
    for function_name in (
        "normalize_hex_color",
        "normalize_subtitle_style",
        "read_project_visual_settings",
        "write_project_visual_settings",
        "subtitle_preview_background_url",
        "sync_project_background_color",
    ):
        assert f"def {function_name}(" in visual_settings_service
        assert f"def {function_name}(" not in server
    assert "read_settings: Callable" not in visual_settings_service
    assert "write_settings: Callable" not in visual_settings_service
    assert "sync_background: Callable" not in visual_settings_service
    for function_name in (
        "run_subprocess_bounded",
        "parse_json_process_stdout",
        "read_json_file",
        "clean_json_markdown",
        "parse_int_setting",
        "is_timeout_exception",
        "parse_range_text",
    ):
        assert f"def {function_name}(" in runtime_support
        assert f"def {function_name}(" not in server
    for token in (
        "APIRouter",
        "Depends(",
        "get_db",
        "server_module",
        "import server",
    ):
        assert token not in runtime_support
        assert token not in project_runtime_service
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
        assert f"def {function_name}(" in project_runtime_service
        assert f"def {function_name}(" not in server

    annotation_start = narration_service.index(
        "def annotate_step6_narration("
    )
    annotation_end = narration_service.index(
        "def update_step6_result(",
        annotation_start,
    )
    assert "handle_step_navigation(project, 6, db)" in (
        narration_service[annotation_start:annotation_end]
    )

    init_start = narration_service.index("def init_step6_narration(")
    init_end = narration_service.index(
        "def get_step6_result(",
        init_start,
    )
    assert '"--overwrite"' not in narration_service[init_start:init_end]

    assert '"input_fingerprint": render_fingerprint' in video_service
    assert "def record_rendered_video(" in video_artifacts

    step5_start = mask_manifest_service.index('def update_step5_result(')
    step5_source = mask_manifest_service[step5_start:]
    assert "built_assets = False" in step5_source
    assert "if build_assets:" in step5_source
    assert 'return {"success": True, "built_assets": built_assets}' in step5_source
    assert "def update_step5_result(" not in server

    assert 'def synthesize_tts(project_id: str' not in server
    assert 'steps/7/synthesize-legacy' not in server
    assert "timeout=STEP7_TTS_PROCESS_TIMEOUT_SEC" in tts_provider_service
    assert "except subprocess.TimeoutExpired" in tts_provider_service
    assert "def provider_tts_command(" not in server
    assert "def run_tts_command_with_retries(" not in server

    assert app_js.count("async function runStep7TTS()") == 1

    assert "python scripts/run_checks.py --level full" in ci
    assert 'python_check(ROOT / "checks" / "test_source_hardening.py")' in read_text("scripts/run_checks.py")
    assert "npm ci" in ci
    assert "npx tsc --noEmit -p tsconfig.json" in ci

    print("source hardening checks passed")


if __name__ == "__main__":
    main()
