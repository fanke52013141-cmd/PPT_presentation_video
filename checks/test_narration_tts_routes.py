from __future__ import annotations

from pathlib import Path

import server


ROOT = Path(__file__).resolve().parents[1]


def test_narration_and_tts_routes_preserve_public_contract() -> None:
    paths = {route.path for route in server.app.routes}
    assert {
        "/api/projects/{project_id}/steps/6/init",
        "/api/projects/{project_id}/steps/6/result",
        "/api/projects/{project_id}/steps/6/repair",
        "/api/settings/narration-annotation",
        "/api/projects/{project_id}/steps/6/annotate",
        "/api/projects/{project_id}/steps/7/synthesize",
        "/api/projects/{project_id}/steps/7/audio-status",
        "/api/projects/{project_id}/slides/{slide_id}/audio",
        "/api/projects/{project_id}/steps/7/confirm",
    } <= paths


def test_narration_and_tts_have_explicit_service_boundaries() -> None:
    server_source = (ROOT / "server.py").read_text(encoding="utf-8")
    sources = {
        name: (ROOT / name).read_text(encoding="utf-8")
        for name in (
            "narration_service.py",
            "narration_routes.py",
            "tts_service.py",
            "tts_routes.py",
        )
    }
    assert "app.include_router(narration_router)" in server_source
    assert "app.include_router(tts_router)" in server_source
    assert '@app.post("/api/projects/{project_id}/steps/6/' not in (
        server_source
    )
    assert '@app.post("/api/projects/{project_id}/steps/7/' not in (
        server_source
    )
    for name in ("narration_service.py", "tts_service.py"):
        assert "APIRouter" not in sources[name]
        assert "@router." not in sources[name]
    for name in ("narration_routes.py", "tts_routes.py"):
        assert "router = APIRouter()" in sources[name]
    for source in sources.values():
        assert "server_module" not in source
        assert "sys.modules" not in source
        assert "import server" not in source
