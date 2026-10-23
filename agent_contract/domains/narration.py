"""Agent narration request and response contracts."""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class NarrationUpdateRequest(BaseModel):
    slide_id: str
    narration_text: str
    expected_revision: Optional[int] = None
    idempotency_key: Optional[str] = None


class TtsSynthesizeRequest(BaseModel):
    slide_ids: Optional[list[str]] = Field(None, description="指定 slide，None 表示全部")
    idempotency_key: Optional[str] = None


class TtsSynthesizeResult(BaseModel):
    operation_id: str
    project_id: str
    status: str
    job_id: str = ""
