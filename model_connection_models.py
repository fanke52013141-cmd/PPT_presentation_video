"""Typed request and response contracts for reusable model connections.

The registry deliberately stores a credential *reference*, never a raw API
key, secret, token, or authorization header.  The reference is private to the
service layer and is omitted from every HTTP response.
"""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field


ConnectionKind = Literal["text", "image", "tts"]
ConnectionState = Literal["active", "disabled", "archived"]


class ModelConnectionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    kind: ConnectionKind
    provider: str = Field(..., min_length=1, max_length=80)
    model: str = Field(..., min_length=1, max_length=160)
    endpoint: Optional[str] = Field(default=None, max_length=1000)
    credential_ref: Optional[str] = Field(default=None, max_length=500)
    public_config: Dict[str, Any] = Field(default_factory=dict)


class ModelConnectionUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    provider: Optional[str] = Field(default=None, min_length=1, max_length=80)
    model: Optional[str] = Field(default=None, min_length=1, max_length=160)
    endpoint: Optional[str] = Field(default=None, max_length=1000)
    credential_ref: Optional[str] = Field(default=None, max_length=500)
    public_config: Optional[Dict[str, Any]] = None


class ModelConnectionCopy(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)


class ModelConnectionStateUpdate(BaseModel):
    state: ConnectionState


class ModelConnectionRevisionResponse(BaseModel):
    revision: int
    provider: str
    model: str
    endpoint: Optional[str] = None
    public_config: Dict[str, Any] = Field(default_factory=dict)
    credential_configured: bool
    created_at: str


class ModelConnectionResponse(BaseModel):
    id: str
    name: str
    kind: ConnectionKind
    state: ConnectionState
    current_revision: int
    created_at: str
    updated_at: str
    archived_at: Optional[str] = None
    revision: ModelConnectionRevisionResponse


class ModelConnectionListResponse(BaseModel):
    connections: list[ModelConnectionResponse]

