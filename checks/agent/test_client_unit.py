"""Unit tests for AgentClient without a live server.

Tests URL construction, header injection, error normalization,
and method-to-path mapping using mocked HTTP responses.
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError, URLError
from io import BytesIO

from agent_client.client import AgentClient, AgentClientError, DEFAULT_TIMEOUT


class TestClientInitialization:
    """Test client construction."""

    def test_default_values(self):
        client = AgentClient()
        assert client.base_url  # non-empty
        assert client.timeout == DEFAULT_TIMEOUT

    def test_custom_values(self):
        client = AgentClient(base_url="http://example.com:9999", app_token="tok", timeout=60)
        assert client.base_url == "http://example.com:9999"
        assert client.app_token == "tok"
        assert client.timeout == 60

    def test_base_url_trailing_slash_stripped(self):
        client = AgentClient(base_url="http://example.com/")
        assert client.base_url == "http://example.com"


class TestUrlConstruction:
    """Verify URL building with params."""

    @patch("agent_client.client.urlopen")
    def test_get_with_params(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"ok": true}'
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        client = AgentClient(base_url="http://test")
        client.list_projects(status="active", limit=10)

        called_url = mock_urlopen.call_args[0][0].full_url
        assert "status=active" in called_url
        assert "limit=10" in called_url

    @patch("agent_client.client.urlopen")
    def test_post_with_body(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"project": {}}'
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        client = AgentClient(base_url="http://test")
        client.create_project(name="Test")

        req = mock_urlopen.call_args[0][0]
        assert req.method == "POST"
        body = req.data.decode("utf-8")
        assert json.loads(body)["name"] == "Test"

    @patch("agent_client.client.urlopen")
    def test_none_params_excluded(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"projects": []}'
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        client = AgentClient(base_url="http://test")
        client.list_projects(status=None)

        called_url = mock_urlopen.call_args[0][0].full_url
        # status=None should NOT appear in URL; only limit param
        assert "status=" not in called_url


class TestHeaderInjection:
    """Verify authentication headers."""

    @patch("agent_client.client.urlopen")
    def test_app_token_header(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{}'
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        client = AgentClient(base_url="http://test", app_token="secret-token")
        client.get_meta()

        req = mock_urlopen.call_args[0][0]
        assert req.headers["X-app-token"] == "secret-token"

    @patch("agent_client.client.urlopen")
    def test_no_token_no_header(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{}'
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        client = AgentClient(base_url="http://test", app_token="")
        client.get_meta()

        req = mock_urlopen.call_args[0][0]
        assert "X-app-token" not in req.headers


class TestErrorNormalization:
    """Test error handling for various HTTP failure modes."""

    def test_http_error_with_agent_json_body(self):
        """HTTPError with Agent API error JSON should extract message."""
        error_body = json.dumps({
            "error": {"code": "PROJECT_NOT_FOUND", "message": "Not found", "details": {}}
        }).encode("utf-8")

        mock_fp = BytesIO(error_body)
        with patch("agent_client.client.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = HTTPError(
                url="http://test/api/agent/v1/projects/xxx",
                code=404,
                msg="Not Found",
                hdrs={},
                fp=mock_fp,
            )
            client = AgentClient(base_url="http://test")
            with pytest.raises(AgentClientError) as exc_info:
                client.get_project("xxx")
            assert exc_info.value.status_code == 404
            assert "Not found" in str(exc_info.value)

    def test_http_error_with_plain_text_body(self):
        """HTTPError with non-JSON body should still produce AgentClientError."""
        mock_fp = BytesIO(b"Internal Server Error")
        with patch("agent_client.client.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = HTTPError(
                url="http://test",
                code=500,
                msg="Server Error",
                hdrs={},
                fp=mock_fp,
            )
            client = AgentClient(base_url="http://test")
            with pytest.raises(AgentClientError) as exc_info:
                client.get_meta()
            assert exc_info.value.status_code == 500

    def test_url_error_connection_refused(self):
        """URLError (connection refused) should produce AgentClientError with status 0."""
        with patch("agent_client.client.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = URLError("Connection refused")
            client = AgentClient(base_url="http://test")
            with pytest.raises(AgentClientError) as exc_info:
                client.get_meta()
            assert exc_info.value.status_code == 0
            assert "Connection" in str(exc_info.value)


class TestMethodPathMapping:
    """Verify each client method calls the correct API path."""

    @patch("agent_client.client.urlopen")
    def test_create_project_path(self, mock_urlopen):
        self._mock_response(mock_urlopen)
        client = AgentClient(base_url="http://test")
        client.create_project(name="t")
        url = mock_urlopen.call_args[0][0].full_url
        assert "/api/agent/v1/projects" in url

    @patch("agent_client.client.urlopen")
    def test_get_project_path(self, mock_urlopen):
        self._mock_response(mock_urlopen)
        client = AgentClient(base_url="http://test")
        client.get_project("proj_123")
        url = mock_urlopen.call_args[0][0].full_url
        assert "/api/agent/v1/projects/proj_123" in url

    @patch("agent_client.client.urlopen")
    def test_set_source_path(self, mock_urlopen):
        self._mock_response(mock_urlopen)
        client = AgentClient(base_url="http://test")
        client.set_source("p1", content="text")
        url = mock_urlopen.call_args[0][0].full_url
        assert "/api/agent/v1/projects/p1/source" in url

    @patch("agent_client.client.urlopen")
    def test_start_pipeline_path(self, mock_urlopen):
        self._mock_response(mock_urlopen)
        client = AgentClient(base_url="http://test")
        client.start_pipeline("p1")
        url = mock_urlopen.call_args[0][0].full_url
        assert "/api/agent/v1/projects/p1/runs" in url

    @patch("agent_client.client.urlopen")
    def test_pipeline_status_path(self, mock_urlopen):
        self._mock_response(mock_urlopen)
        client = AgentClient(base_url="http://test")
        client.get_pipeline_status("p1")
        url = mock_urlopen.call_args[0][0].full_url
        assert "/api/agent/v1/projects/p1/runs/latest" in url

    @patch("agent_client.client.urlopen")
    def test_resume_pipeline_path(self, mock_urlopen):
        self._mock_response(mock_urlopen)
        client = AgentClient(base_url="http://test")
        client.resume_pipeline("p1")
        url = mock_urlopen.call_args[0][0].full_url
        assert "/api/agent/v1/projects/p1/runs/latest/resume" in url

    @patch("agent_client.client.urlopen")
    def test_approve_checkpoint_path(self, mock_urlopen):
        self._mock_response(mock_urlopen)
        client = AgentClient(base_url="http://test")
        client.approve_checkpoint("p1", "image_review")
        url = mock_urlopen.call_args[0][0].full_url
        assert "/api/agent/v1/projects/p1/checkpoints/image_review/approve" in url

    @patch("agent_client.client.urlopen")
    def test_get_stage_path(self, mock_urlopen):
        self._mock_response(mock_urlopen)
        client = AgentClient(base_url="http://test")
        client.get_stage("p1", "storyboard")
        url = mock_urlopen.call_args[0][0].full_url
        assert "/api/agent/v1/projects/p1/stages/storyboard" in url

    @patch("agent_client.client.urlopen")
    def test_regenerate_image_path(self, mock_urlopen):
        self._mock_response(mock_urlopen)
        client = AgentClient(base_url="http://test")
        client.regenerate_image("p1", "slide_001")
        url = mock_urlopen.call_args[0][0].full_url
        assert "/api/agent/v1/projects/p1/images/slide_001/regenerate" in url

    @patch("agent_client.client.urlopen")
    def test_meta_path(self, mock_urlopen):
        self._mock_response(mock_urlopen)
        client = AgentClient(base_url="http://test")
        client.get_meta()
        url = mock_urlopen.call_args[0][0].full_url
        assert "/api/agent/v1/meta" in url

    @patch("agent_client.client.urlopen")
    def test_diagnostics_path(self, mock_urlopen):
        self._mock_response(mock_urlopen)
        client = AgentClient(base_url="http://test")
        client.get_diagnostics()
        url = mock_urlopen.call_args[0][0].full_url
        assert "/api/agent/v1/diagnostics" in url

    @staticmethod
    def _mock_response(mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{}'
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp


class TestPollingUnit:
    """Unit tests for polling utility."""

    def test_poll_returns_on_terminal_status(self):
        from agent_client.polling import poll_operation, PollConfig
        from agent_client.client import AgentClient

        mock_client = MagicMock(spec=AgentClient)
        mock_client.get_pipeline_status.return_value = {
            "status": "succeeded",
            "current_stage": "done",
        }
        result = poll_operation(
            mock_client,
            project_id="p1",
            poll_fn=mock_client.get_pipeline_status,
            config=PollConfig(timeout=5, interval=0),
        )
        assert result["status"] == "succeeded"

    def test_poll_times_out(self):
        from agent_client.polling import poll_operation, PollConfig
        from agent_client.client import AgentClient

        mock_client = MagicMock(spec=AgentClient)
        mock_client.get_pipeline_status.return_value = {
            "status": "running",
            "current_stage": "images",
        }
        with pytest.raises(TimeoutError, match="timed out"):
            poll_operation(
                mock_client,
                project_id="p1",
                poll_fn=mock_client.get_pipeline_status,
                config=PollConfig(timeout=1, interval=0),
            )

    def test_poll_returns_on_waiting_for_review(self):
        from agent_client.polling import poll_operation, PollConfig
        from agent_client.client import AgentClient

        mock_client = MagicMock(spec=AgentClient)
        mock_client.get_pipeline_status.return_value = {
            "status": "waiting_for_review",
            "current_stage": "image_review",
        }
        result = poll_operation(
            mock_client,
            project_id="p1",
            poll_fn=mock_client.get_pipeline_status,
            config=PollConfig(timeout=5, interval=0),
        )
        assert result["status"] == "waiting_for_review"
