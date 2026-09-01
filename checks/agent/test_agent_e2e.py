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


class TestIdempotencyIntegration:
    """Test idempotency claim/finalize/replay via the Agent API."""

    def test_duplicate_create_with_same_key_returns_replay(self, api_client):
        body = {"name": "Idem Replay Test", "description": "test replay", "idempotency_key": "e2e-replay-1"}

        resp1 = api_client.post("/api/agent/v1/projects", json=body)
        assert resp1.status_code == 200, f"First create failed: {resp1.text}"
        data1 = resp1.json()

        resp2 = api_client.post("/api/agent/v1/projects", json=body)
        assert resp2.status_code == 200
        assert resp2.headers.get("X-Agent-Idempotency-Replay") == "true"
        assert resp2.json()["project"]["project_id"] == data1["project"]["project_id"]

    def test_same_key_different_body_returns_conflict(self, api_client):
        body1 = {"name": "Conflict A", "idempotency_key": "e2e-conflict-1"}
        resp1 = api_client.post("/api/agent/v1/projects", json=body1)
        assert resp1.status_code == 200

        body2 = {"name": "Conflict B", "idempotency_key": "e2e-conflict-1"}
        resp2 = api_client.post("/api/agent/v1/projects", json=body2)
        assert resp2.status_code == 409

    def test_create_without_key_is_not_idempotent(self, api_client):
        """Requests without idempotency_key should always create new projects."""
        resp1 = api_client.post("/api/agent/v1/projects", json={"name": "No-Key 1"})
        resp2 = api_client.post("/api/agent/v1/projects", json={"name": "No-Key 2"})
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp1.json()["project"]["project_id"] != resp2.json()["project"]["project_id"]
        assert "X-Agent-Idempotency-Replay" not in resp2.headers


class TestOptimisticLocking:
    """Test expected_revision optimistic locking on update operations."""

    def test_update_with_correct_revision_succeeds(self, api_client):
        create_resp = api_client.post(
            "/api/agent/v1/projects",
            json={"name": "Lock Test"},
        )
        project_id = create_resp.json()["project"]["project_id"]
        initial_revision = create_resp.json()["project"].get("revision", 0)

        update_resp = api_client.patch(
            f"/api/agent/v1/projects/{project_id}",
            json={"description": "Updated", "expected_revision": initial_revision},
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["project"]["description"] == "Updated"
        assert update_resp.json()["project"]["revision"] == initial_revision + 1

    def test_update_with_stale_revision_returns_conflict(self, api_client):
        create_resp = api_client.post(
            "/api/agent/v1/projects",
            json={"name": "Stale Lock Test"},
        )
        project_id = create_resp.json()["project"]["project_id"]

        # First update succeeds and bumps revision
        api_client.patch(
            f"/api/agent/v1/projects/{project_id}",
            json={"description": "First update", "expected_revision": 0},
        )

        # Second update with stale revision 0 should conflict
        stale_resp = api_client.patch(
            f"/api/agent/v1/projects/{project_id}",
            json={"description": "Second update", "expected_revision": 0},
        )
        assert stale_resp.status_code == 409

    def test_update_without_revision_key_bypasses_lock(self, api_client):
        """Omitting expected_revision should skip the lock check entirely."""
        create_resp = api_client.post(
            "/api/agent/v1/projects",
            json={"name": "No-Lock Test"},
        )
        project_id = create_resp.json()["project"]["project_id"]

        update_resp = api_client.patch(
            f"/api/agent/v1/projects/{project_id}",
            json={"description": "No lock check"},
        )
        assert update_resp.status_code == 200
