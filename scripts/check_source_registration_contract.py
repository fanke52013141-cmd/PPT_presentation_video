"""Validate that production services are registered explicitly at startup."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    server = (ROOT / "server.py").read_text(encoding="utf-8")
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
    tts_routes = (ROOT / "tts_routes.py").read_text(encoding="utf-8")
    tts_service = (ROOT / "tts_service.py").read_text(encoding="utf-8")
    project_routes = (ROOT / "project_routes.py").read_text(encoding="utf-8")
    project_service = (ROOT / "project_service.py").read_text(encoding="utf-8")
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert not (ROOT / "runtime_bootstrap.py").exists(), "empty runtime bootstrap should stay retired"
    assert "app.include_router(one_click_router)" in server, "one-click router is not explicitly registered"
    assert "app.include_router(diagnostics_router)" in server, "diagnostics router is not explicitly registered"
    assert "app.include_router(storyboard_background_router)" in server, "storyboard background router is not explicitly registered"
    assert "app.include_router(storyboard_router)" in server, "Step 2 storyboard router is not explicitly registered"
    assert "app.include_router(narration_router)" in server, "narration router is not explicitly registered"
    assert "app.include_router(tts_router)" in server, "TTS router is not explicitly registered"
    assert "app.include_router(project_router)" in server, "project router is not explicitly registered"
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
    assert '@app.post("/api/projects")' not in server, "project creation route returned to server"
    assert "APIRouter" not in project_service, "project service owns HTTP routing again"
    assert "router = APIRouter()" in project_routes, "project routes module is incomplete"
    assert "register_pptx_routes" not in server, "legacy PPTX registration returned"
    assert "app.include_router(project_style_router)" in server, "project style router is not explicitly registered"
    assert "register_project_style_routes" not in server, "legacy project style registration returned"
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
