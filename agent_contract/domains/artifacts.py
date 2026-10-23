"""Agent artifacts request and response contracts."""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class ArtifactsListRequest(BaseModel):
    artifact_type: Optional[str] = Field(None, description="image / audio / video / pptx / all")
    slide_id: Optional[str] = None


class ArtifactInfo(BaseModel):
    artifact_id: str
    artifact_type: str
    filename: str
    mime_type: str
    size_bytes: int = 0
    resource_uri: str = ""
    slide_id: Optional[str] = None
    revision: int = 0
    created_at: Optional[str] = None
    sha256: Optional[str] = Field(None, pattern=r"^[0-9a-f]{64}$", description="Current file hash from artifact.get; null when unavailable or not computed")


class ArtifactsListResult(BaseModel):
    project_id: str
    artifacts: list[ArtifactInfo]
    total: int


class ArtifactGetResult(BaseModel):
    artifact: ArtifactInfo
    download_url: str = ""
