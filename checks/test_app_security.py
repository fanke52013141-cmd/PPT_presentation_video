from pathlib import Path
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app_security import COOKIE_NAME, install_access_control


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/api/ping")
    def ping() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/")
    def index() -> str:
        return "ok"

    return app


def test_no_token_keeps_local_app_open() -> None:
    app = _app()
    assert install_access_control(app, {}) is False
    assert TestClient(app).get("/api/ping").status_code == 200


def test_token_protects_api_and_html() -> None:
    app = _app()
    assert install_access_control(app, {"PPT_STUDIO_ACCESS_TOKEN": "secret"}) is True
    client = TestClient(app)
    api_response = client.get("/api/ping")
    assert api_response.status_code == 401
    assert api_response.headers["www-authenticate"] == "Bearer"
    assert client.get("/").status_code == 401
    assert client.get("/api/ping", headers={"Authorization": "Bearer secret"}).json() == {"ok": True}


def test_query_token_sets_http_only_cookie() -> None:
    app = _app()
    install_access_control(app, {"PPT_STUDIO_ACCESS_TOKEN": "secret"})
    client = TestClient(app)
    response = client.get("/?access_token=secret&view=project")
    assert response.status_code == 200
    assert len(response.history) == 1
    assert response.history[0].status_code == 303
    assert "access_token" not in str(response.url)
    assert response.url.query == b"view=project"
    assert COOKIE_NAME in client.cookies
    assert "HttpOnly" in response.history[0].headers["set-cookie"]
    assert client.get("/api/ping").status_code == 200


def test_query_token_is_rejected_for_state_changing_requests() -> None:
    app = _app()

    @app.post("/api/write")
    def write() -> dict[str, bool]:
        return {"written": True}

    install_access_control(app, {"PPT_STUDIO_ACCESS_TOKEN": "secret"})
    response = TestClient(app).post("/api/write?token=secret")
    assert response.status_code == 400


def test_disallowed_origin_is_rejected() -> None:
    app = _app()
    install_access_control(
        app,
        {
            "PPT_STUDIO_ACCESS_TOKEN": "secret",
            "PPT_STUDIO_ALLOWED_ORIGINS": "http://127.0.0.1:8000",
        },
    )
    response = TestClient(app).get(
        "/api/ping",
        headers={"Authorization": "Bearer secret", "Origin": "https://evil.example"},
    )
    assert response.status_code == 403


if __name__ == "__main__":
    test_no_token_keeps_local_app_open()
    test_token_protects_api_and_html()
    test_query_token_sets_http_only_cookie()
    test_query_token_is_rejected_for_state_changing_requests()
    test_disallowed_origin_is_rejected()
    print("application security checks passed")
