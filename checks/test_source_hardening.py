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

    assert "def mask_sensitive_settings" in server
    assert "return mask_sensitive_settings(get_all_settings())" in server
    assert 'if settings.get(key) == MASKED_SETTINGS_VALUE:' in server
    assert 'allow_origins=["*"]' not in server
    assert "configured_allowed_origins()" in server
    assert "build_config_export_bundle(mask_sensitive_settings(get_all_settings(), force=True), contains_secrets=False)" in server

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

    step5_start = server.index('def update_step5_result(')
    step5_end = server.index("# ==================== 步骤 6", step5_start)
    step5_source = server[step5_start:step5_end]
    assert "built_assets = False" in step5_source
    assert "if build_assets:" in step5_source
    assert 'return {"success": True, "built_assets": built_assets}' in step5_source

    assert 'def synthesize_tts(project_id: str' not in server
    assert 'steps/7/synthesize-legacy' not in server
    assert "timeout=STEP7_TTS_PROCESS_TIMEOUT_SEC" in server
    assert "except subprocess.TimeoutExpired" in server

    assert app_js.count("async function runStep7TTS()") == 1

    assert "python scripts/run_checks.py --level full" in ci
    assert 'python_check(ROOT / "checks" / "test_source_hardening.py")' in read_text("scripts/run_checks.py")
    assert "npm ci" in ci
    assert "npx tsc --noEmit -p tsconfig.json" in ci

    print("source hardening checks passed")


if __name__ == "__main__":
    main()
