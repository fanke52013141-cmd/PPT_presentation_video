"""Shared validation and timestamps for reusable configuration templates."""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any

from fastapi import HTTPException


def normalized_template_name(value: Any) -> str:
    name = re.sub(r"\s+", " ", str(value or "").strip())
    if not name:
        raise HTTPException(status_code=400, detail="模板名称不能为空")
    if len(name) > 60:
        raise HTTPException(status_code=400, detail="模板名称不能超过 60 个字符")
    return name


def template_timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")
