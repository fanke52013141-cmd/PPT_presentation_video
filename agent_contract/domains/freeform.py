"""Shared free-form payload envelopes for business-owned request bodies.

Web 前端把整段业务载荷直接交给 source-owned 服务校验；Agent 契约用这个
显式信封承载这类载荷。字段级规则仍由业务层负责，不在这里复制。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class FreeFormRequest(BaseModel):
    """Required business payload envelope (body dict validated by the service)."""

    payload: Dict[str, Any] = Field(default_factory=dict, description="业务载荷；字段由业务层校验")


class OptionalFreeFormRequest(BaseModel):
    """Optional business payload envelope."""

    payload: Optional[Dict[str, Any]] = Field(None, description="可选业务载荷；字段由业务层校验")
