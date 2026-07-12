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

    render_start = server.index('def render_video(project_id: str')
    render_end = server.index('@app.get("/api/projects/{project_id}/videos")', render_start)
    render_source = server[render_start:render_end]
    assert "videos_dir = project_video_dir(project)" in render_source
    assert "output_mp4_path = os.path.join(videos_dir, output_filename)" in render_source

    assert "def mask_sensitive_settings" in server
    assert "return mask_sensitive_settings(get_all_settings())" in server
    assert 'if settings.get(key) == MASKED_SETTINGS_VALUE:' in server

    step5_start = server.index('def update_step5_result(')
    step5_end = server.index("# ==================== 步骤 6", step5_start)
    step5_source = server[step5_start:step5_end]
    assert "built_assets = False" in step5_source
    assert "if build_assets:" in step5_source
    assert 'return {"success": True, "built_assets": built_assets}' in step5_source

    legacy_start = server.index('def synthesize_tts(project_id: str')
    legacy_end = server.index("# 获取音频文件接口", legacy_start)
    legacy_tts_source = server[legacy_start:legacy_end]
    assert "timeout=STEP7_TTS_PROCESS_TIMEOUT_SEC" in legacy_tts_source
    assert "except subprocess.TimeoutExpired" in legacy_tts_source

    assert app_js.count("async function runStep7TTS()") == 1

    assert "python scripts/run_checks.py --level full" in ci
    assert 'python_check(ROOT / "checks" / "test_source_hardening.py")' in read_text("scripts/run_checks.py")
    assert "npm ci" in ci
    assert "npx tsc --noEmit -p tsconfig.json" in ci

    print("source hardening checks passed")


if __name__ == "__main__":
    main()
