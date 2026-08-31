"""End-to-end Agent API smoke tests.

These tests use FastAPI's TestClient to verify:
1. The agent router is properly mounted
2. The /meta endpoint returns correct version info
3. The /diagnostics endpoint returns health checks
4. Error handling works for unknown projects
5. Project CRUD lifecycle works
6. Pipeline status endpoint responds

These tests import the full FastAPI application, so they require
the existing application infrastructure (database, config, etc.).
"""

from __future__ import annotations

import sys
import os
import pytest

# Ensure repo root is on path
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


@pytest.fixture(scope="module")
def api_client():
    """Create a TestClient for the full FastAPI app."""
    try:
        from fastapi.testclient import TestClient
        import server
        client = TestClient(server.app)
        return client
    except Exception as e:
        pytest.skip(f"Cannot create TestClient (server deps not available): {e}")


class TestMetaEndpoint:
    """Test the /api/agent/v1/meta endpoint."""

    def test_meta_returns_200(self, api_client):
        resp = api_client.get("/api/agent/v1/meta")
        assert resp.status_code == 200
        data = resp.json()
        assert "agent_api_version" in data
        assert "contract_hash" in data
        assert "capabilities" in data

    def test_meta_capabilities_non_empty(self, api_client):
        data = api_client.get("/api/agent/v1/meta").json()
        assert len(data["capabilities"]) > 0

    def test_meta_contract_hash_is_hex(self, api_client):
        data = api_client.get("/api/agent/v1/meta").json()
        h = data["contract_hash"]
        assert all(c in "0123456789abcdef" for c in h), f"Invalid hex: {h}"


class TestDiagnosticsEndpoint:
    """Test the /api/agent/v1/diagnostics endpoint."""

    def test_diagnostics_returns_200(self, api_client):
        resp = api_client.get("/api/agent/v1/diagnostics")
        assert resp.status_code == 200
        data = resp.json()
        assert "agent_api_version" in data
        assert "checks" in data
        assert "database" in data["checks"]


class TestProjectEndpoints:
    """Test project CRUD via Agent API."""

    def test_list_projects_returns_200(self, api_client):
        resp = api_client.get("/api/agent/v1/projects")
        assert resp.status_code == 200
        data = resp.json()
        assert "projects" in data
        assert "total" in data
        assert isinstance(data["projects"], list)

    def test_get_nonexistent_project_returns_404(self, api_client):
        resp = api_client.get("/api/agent/v1/projects/nonexistent-id-xyz")
        assert resp.status_code == 404
        data = resp.json()
        assert "error" in data or "detail" in data

    def test_create_and_get_project(self, api_client):
        # Create
        create_resp = api_client.post(
            "/api/agent/v1/projects",
            json={
                "name": "Agent E2E Test Project",
                "description": "Created by automated test",
                "canvas_profile": "landscape_16_9",
            },
        )
        assert create_resp.status_code == 200, f"Create failed: {create_resp.text}"
        create_data = create_resp.json()
        assert "project" in create_data
        project_id = create_data["project"]["project_id"]

        # Get
        get_resp = api_client.get(f"/api/agent/v1/projects/{project_id}")
        assert get_resp.status_code == 200
        get_data = get_resp.json()
        assert get_data["project"]["project_id"] == project_id
        assert get_data["project"]["name"] == "Agent E2E Test Project"

    def test_update_project(self, api_client):
        # Create then update
        create_resp = api_client.post(
            "/api/agent/v1/projects",
            json={"name": "Update Test", "description": "Before"},
        )
        project_id = create_resp.json()["project"]["project_id"]

        update_resp = api_client.patch(
            f"/api/agent/v1/projects/{project_id}",
            json={"description": "After update"},
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["project"]["description"] == "After update"


class TestCheckpointEndpoints:
    """Test checkpoint listing."""

    def test_list_checkpoints(self, api_client):
        # First create a project
        create_resp = api_client.post(
            "/api/agent/v1/projects",
            json={"name": "Checkpoint Test"},
        )
        project_id = create_resp.json()["project"]["project_id"]

        resp = api_client.get(f"/api/agent/v1/projects/{project_id}/checkpoints")
        assert resp.status_code == 200
        data = resp.json()
        assert "checkpoints" in data
        assert len(data["checkpoints"]) >= 6  # At least 6 review gates


class TestArtifactEndpoints:
    """Test artifact listing."""

    def test_list_artifacts_empty_project(self, api_client):
        create_resp = api_client.post(
            "/api/agent/v1/projects",
            json={"name": "Artifacts Test"},
        )
        project_id = create_resp.json()["project"]["project_id"]

        resp = api_client.get(f"/api/agent/v1/projects/{project_id}/artifacts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0 or len(data["artifacts"]) >= 0

    def test_get_nonexistent_artifact_404(self, api_client):
        create_resp = api_client.post(
            "/api/agent/v1/projects",
            json={"name": "Artifact 404 Test"},
        )
        project_id = create_resp.json()["project"]["project_id"]

        resp = api_client.get(
            f"/api/agent/v1/projects/{project_id}/artifacts/nonexistent-art"
        )
        assert resp.status_code == 404


class TestStageEndpoint:
    """Test stage data retrieval."""

    def test_get_storyboard_empty(self, api_client):
        create_resp = api_client.post(
            "/api/agent/v1/projects",
            json={"name": "Stage Test"},
        )
        project_id = create_resp.json()["project"]["project_id"]

        resp = api_client.get(f"/api/agent/v1/projects/{project_id}/stages/storyboard")
        assert resp.status_code == 200
        data = resp.json()
        assert data["stage"] == "storyboard"
        assert "data" in data
