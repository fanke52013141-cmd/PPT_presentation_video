"""AgentClient — synchronous HTTP client for the Agent API.

Usage:
    client = AgentClient(base_url="http://127.0.0.1:8000")
    result = client.create_project(name="测试", canvas_profile="portrait_9_16")
    status = client.get_pipeline_status(project_id=result["project"]["project_id"])

The client handles:
- JSON serialization/deserialization
- Error normalization (raises AgentClientError on non-2xx)
- App token header injection
- Optional timeout configuration
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

DEFAULT_BASE_URL = os.environ.get("PPT_AGENT_API_URL", "http://127.0.0.1:8000")
DEFAULT_TIMEOUT = 30  # seconds for normal requests
# PPT_APP_TOKEN is retained only as a transition fallback for existing local
# launch scripts. Agent API authentication is configured by this variable.
DEFAULT_APP_TOKEN = os.environ.get("PPT_AGENT_API_KEY") or os.environ.get("PPT_APP_TOKEN", "")


class AgentClientError(Exception):
    """Raised when the Agent API returns an error."""

    def __init__(self, message: str, status_code: int = 0, details: Optional[dict] = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.details = details or {}


class AgentClient:
    """Synchronous HTTP client for the Agent API."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        app_token: str = DEFAULT_APP_TOKEN,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.app_token = app_token
        self.timeout = timeout

    # ---- Low-level HTTP ----

    def _request(
        self,
        method: str,
        path: str,
        body: Optional[dict] = None,
        params: Optional[dict] = None,
        timeout: Optional[int] = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        if params:
            from urllib.parse import urlencode
            query = urlencode({k: v for k, v in params.items() if v is not None})
            if query:
                url = f"{url}?{query}"

        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.app_token:
            headers["Authorization"] = f"Bearer {self.app_token}"

        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")

        req = Request(url, data=data, method=method, headers=headers)
        actual_timeout = self.timeout if timeout is None else timeout
        try:
            with urlopen(req, timeout=actual_timeout) as resp:
                raw = resp.read().decode("utf-8")
                if not raw:
                    return {}
                return json.loads(raw)
        except HTTPError as e:
            raw = e.read().decode("utf-8") if e.fp else ""
            try:
                err_body = json.loads(raw) if raw else {}
                err_msg = err_body.get("error", {}).get("message", raw or str(e))
                err_details = err_body.get("error", {}).get("details", {})
            except (json.JSONDecodeError, AttributeError):
                err_msg = raw or str(e)
                err_details = {}
            raise AgentClientError(err_msg, status_code=e.code, details=err_details)
        except URLError as e:
            raise AgentClientError(f"Connection failed: {e.reason}", status_code=0)

    def get_bytes(self, path: str) -> tuple[bytes, str]:
        """Fetch a binary Agent API resource with the usual authentication."""
        headers = {"Accept": "*/*"}
        if self.app_token:
            headers["Authorization"] = f"Bearer {self.app_token}"
        req = Request(f"{self.base_url}{path}", method="GET", headers=headers)
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                content_type = str(resp.headers.get_content_type() or "application/octet-stream")
                return resp.read(), content_type
        except HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace") if e.fp else ""
            raise AgentClientError(raw or str(e), status_code=e.code)
        except URLError as e:
            raise AgentClientError(f"Connection failed: {e.reason}", status_code=0)

    # ---- Project operations ----

    def create_project(
        self,
        name: str,
        description: str = "",
        canvas_profile: str = "landscape_16_9",
        automation_mode: str = "auto",
        review_policy: str = "none",
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "name": name,
            "description": description,
            "canvas_profile": canvas_profile,
            "automation_mode": automation_mode,
            "review_policy": review_policy,
        }
        if idempotency_key:
            body["idempotency_key"] = idempotency_key
        return self._request("POST", "/api/agent/v1/projects", body=body)

    def list_projects(self, status: Optional[str] = None, limit: int = 50) -> dict[str, Any]:
        return self._request("GET", "/api/agent/v1/projects", params={
            "status": status,
            "limit": limit,
        })

    def get_project(self, project_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/agent/v1/projects/{project_id}")

    def update_project(
        self,
        project_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        ai_mode: Optional[str] = None,
        expected_revision: Optional[int] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if description is not None:
            body["description"] = description
        if ai_mode is not None:
            body["ai_mode"] = ai_mode
        if expected_revision is not None:
            body["expected_revision"] = expected_revision
        if idempotency_key:
            body["idempotency_key"] = idempotency_key
        return self._request("PATCH", f"/api/agent/v1/projects/{project_id}", body=body)

    def delete_project(self, project_id: str) -> dict[str, Any]:
        return self._request("DELETE", f"/api/agent/v1/projects/{project_id}")

    # ---- Source ----

    def set_source(
        self,
        project_id: str,
        content: Optional[str] = None,
        topic: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if content:
            body["content"] = content
        if topic:
            body["topic"] = topic
        if idempotency_key:
            body["idempotency_key"] = idempotency_key
        return self._request("POST", f"/api/agent/v1/projects/{project_id}/source", body=body)

    # ---- Pipeline ----

    def start_pipeline(
        self,
        project_id: str,
        start_from: Optional[str] = None,
        stop_at: Optional[str] = None,
        mode: str = "resume",
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"mode": mode}
        if start_from:
            body["start_from"] = start_from
        if stop_at:
            body["stop_at"] = stop_at
        if idempotency_key:
            body["idempotency_key"] = idempotency_key
        return self._request("POST", f"/api/agent/v1/projects/{project_id}/runs", body=body)

    def get_pipeline_status(self, project_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/agent/v1/projects/{project_id}/runs/latest")

    def resume_pipeline(self, project_id: str, stop_at: Optional[str] = None, idempotency_key: Optional[str] = None) -> dict[str, Any]:
        body: dict[str, Any] = {"mode": "resume"}
        if stop_at:
            body["stop_at"] = stop_at
        if idempotency_key:
            body["idempotency_key"] = idempotency_key
        return self._request("POST", f"/api/agent/v1/projects/{project_id}/runs/latest/resume", body=body)

    # ---- Checkpoints ----

    def list_checkpoints(self, project_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/agent/v1/projects/{project_id}/checkpoints")

    def approve_checkpoint(self, project_id: str, checkpoint: str, approved: bool = True, notes: str = "", idempotency_key: Optional[str] = None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "checkpoint": checkpoint,
            "approved": approved,
        }
        if notes:
            body["notes"] = notes
        if idempotency_key:
            body["idempotency_key"] = idempotency_key
        return self._request("POST", f"/api/agent/v1/projects/{project_id}/checkpoints/{checkpoint}/approve", body=body)

    # ---- Stage data ----

    def get_stage(self, project_id: str, stage: str) -> dict[str, Any]:
        return self._request("GET", f"/api/agent/v1/projects/{project_id}/stages/{stage}")

    # ---- Image regenerate ----

    def regenerate_image(self, project_id: str, slide_id: str, instruction: str = "", idempotency_key: Optional[str] = None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "slide_id": slide_id,
            "instruction": instruction,
        }
        if idempotency_key:
            body["idempotency_key"] = idempotency_key
        return self._request("POST", f"/api/agent/v1/projects/{project_id}/images/{slide_id}/regenerate", body=body)

    # ---- Narration ----

    def update_narration(self, project_id: str, slide_id: str, narration_text: str, expected_revision: Optional[int] = None, idempotency_key: Optional[str] = None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "slide_id": slide_id,
            "narration_text": narration_text,
        }
        if expected_revision is not None:
            body["expected_revision"] = expected_revision
        if idempotency_key:
            body["idempotency_key"] = idempotency_key
        return self._request("PATCH", f"/api/agent/v1/projects/{project_id}/narration/{slide_id}", body=body)

    # ---- TTS ----

    def synthesize_tts(self, project_id: str, slide_ids: Optional[list[str]] = None, idempotency_key: Optional[str] = None) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if slide_ids:
            body["slide_ids"] = slide_ids
        if idempotency_key:
            body["idempotency_key"] = idempotency_key
        return self._request("POST", f"/api/agent/v1/projects/{project_id}/tts", body=body)

    # ---- Video ----

    def render_video(self, project_id: str, idempotency_key: Optional[str] = None) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if idempotency_key:
            body["idempotency_key"] = idempotency_key
        return self._request("POST", f"/api/agent/v1/projects/{project_id}/videos/render", body=body)

    # ---- Artifacts ----

    def list_artifacts(
        self,
        project_id: str,
        artifact_type: Optional[str] = None,
        slide_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self._request("GET", f"/api/agent/v1/projects/{project_id}/artifacts", params={
            "artifact_type": artifact_type,
            "slide_id": slide_id,
        })

    def get_artifact(self, project_id: str, artifact_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/agent/v1/projects/{project_id}/artifacts/{artifact_id}")

    # ---- Diagnostics ----

    def get_meta(self, timeout: Optional[int] = None) -> dict[str, Any]:
        return self._request("GET", "/api/agent/v1/meta", timeout=timeout)

    def get_diagnostics(self) -> dict[str, Any]:
        return self._request("GET", "/api/agent/v1/diagnostics")

    # ---- Digital Human ----

    def get_digital_human_config(self, project_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/agent/v1/projects/{project_id}/digital-human/config")

    def update_digital_human_config(self, project_id: str, config: dict) -> dict[str, Any]:
        return self._request(
            "PATCH",
            f"/api/agent/v1/projects/{project_id}/digital-human/config",
            body={"config": config},
        )

    def check_digital_human_health(self, project_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/agent/v1/projects/{project_id}/digital-human/health")

    def generate_digital_human(self, project_id: str) -> dict[str, Any]:
        return self._request("POST", f"/api/agent/v1/projects/{project_id}/digital-human/generate-full")
