"""Agent video request and response contracts."""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel


class VideoRenderRequest(BaseModel):
    idempotency_key: Optional[str] = None


class VideoRenderResult(BaseModel):
    operation_id: str
    project_id: str
    status: str
    job_id: str = ""
