"""Agent article (visible Step 1) request and response contracts."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class ArticleSettingsUpdateRequest(BaseModel):
    system_content: str = Field(..., min_length=1, description="文章生成 System Content")


class ArticleSettingsResult(BaseModel):
    success: bool
    system_content: str


class ArticleSourceUpdateRequest(BaseModel):
    content: str = Field(..., description="完整文章内容（Markdown）；保存相同内容为 no-op，不触发下游失效")


class ArticleSourceResult(BaseModel):
    success: bool
    message: Optional[str] = None
    brief: Optional[Dict[str, Any]] = None
