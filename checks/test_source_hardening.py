from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def main() -> None:
    server = read_text("server.py")
    app_js = read_text("static/app.js")
    ci = read_text(".github/workflows/ci.yml")

    assert 'npx_cmd, "remotion", "render", "src/index.tsx", "ArticleVideo", output_mp4_path' in server
    assert 'npx_cmd, "remotion", "render", "ArticleVideo", output_mp4_path' not in server

    worker_start = server.index("def _render_video_worker(project_id: str")
    worker_end = server.index('@app.post("/api/projects/{project_id}/steps/8/render")', worker_start)
    worker_source = server[worker_start:worker_end]
    assert "videos_dir = project_video_dir(project)" in worker_source
    assert "output_mp4_path = os.path.join(videos_dir, output_filename)" in worker_source
    assert "RENDER_TASK_HISTORY_LIMIT = 100" in server
    assert "_prune_render_tasks_locked()" in server

    render_start = server.index("def render_video(project_id: str")
    render_end = server.index('@app.get("/api/projects/{project_id}/steps/8/render-status")', render_start)
    render_source = server[render_start:render_end]

    assert "def mask_sensitive_settings" in server
    assert "return mask_sensitive_settings(get_all_settings())" in server
    assert 'if settings.get(key) == MASKED_SETTINGS_VALUE:' in server
    assert 'allow_origins=["*"]' not in server
    assert "configured_allowed_origins()" in server
    assert "build_config_export_bundle(mask_sensitive_settings(get_all_settings(), force=True), contains_secrets=False)" in server

    annotation_start = server.index("def annotate_step6_narration(")
    annotation_end = server.index('@app.put("/api/projects/{project_id}/steps/6/result")', annotation_start)
    assert "handle_step_navigation(project, 6, db)" in server[annotation_start:annotation_end]

    init_start = server.index("def init_step6_narration(")
    init_end = server.index('@app.get("/api/projects/{project_id}/steps/6/result")', init_start)
    assert '"--overwrite"' not in server[init_start:init_end]

    assert '"input_fingerprint": render_fingerprint' in worker_source
    assert "tts_confirmation_status(project.run_dir, slide_ids)" in render_source

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
    check_runner = read_text("scripts/run_checks.py")
    assert 'ROOT / "checks" / "test_source_hardening.py"' in check_runner
    assert "for path in QUICK_PYTHON_CHECKS[1:]:" in check_runner
    assert "npm ci" in ci
    assert "npx tsc --noEmit -p tsconfig.json" in ci

    print("source hardening checks passed")


if __name__ == "__main__":
    main()
