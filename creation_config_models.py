"""Public data models for reusable creation configuration packages.

The models deliberately contain connection *references* only.  Connection
credentials live in the model-connection registry and must never be copied
into a creation package or a project snapshot.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ConnectionReference(BaseModel):
    """An immutable reference to a configured provider connection revision."""

    connection_id: str
    revision: int = Field(ge=1)


class CreationConfigCreate(BaseModel):
    name: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    payload: dict[str, Any]


class CreationConfigCopy(BaseModel):
    name: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    version: int | None = Field(default=None, ge=1)


class CreationConfigVersionCreate(BaseModel):
    payload: dict[str, Any]


class CreationConfigArchive(BaseModel):
    archived: bool = True


class CreationConfigResolve(BaseModel):
    version: int | None = Field(default=None, ge=1)
    overrides: dict[str, Any] = Field(default_factory=dict)


class CreationConfigImport(BaseModel):
    """Import one package as a fresh local package and version 1."""

    name: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    payload: dict[str, Any]

