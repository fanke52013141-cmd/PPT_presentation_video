"""Agent source request and response contracts."""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field, model_validator


class SourceSetRequest(BaseModel):
    content: Optional[str] = Field(None, description="直接提供文章内容（Markdown）")
    topic: Optional[str] = Field(None, description="主题描述，触发 AI 生成文章")
    idempotency_key: Optional[str] = None

    @model_validator(mode="after")
    def exactly_one_source(self):
        if bool(self.content and self.content.strip()) == bool(self.topic and self.topic.strip()):
            raise ValueError("Provide exactly one non-empty content or topic")
        return self


class SourceSetResult(BaseModel):
    project_id: str
    article_imported: bool
    article_preview: str = Field("", description="文章内容前 500 字")
    word_count: int = 0
