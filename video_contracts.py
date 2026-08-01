"""Shared contracts for the video rendering subsystem."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


class VideoRenderError(RuntimeError):
    """HTTP-aware application error raised by video services."""

    def __init__(self, status_code: int, detail: Any) -> None:
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class VideoRenderConfig:
    """Filesystem locations and subprocess timeouts for video output."""

    repo_root: Path
    runs_root: Path
    pipeline_version: str
    reveal_visual_lead_sec: float
    bind_timeout_sec: float
    build_props_timeout_sec: float
    npm_install_timeout_sec: float
    render_timeout_sec: float
    color_process_timeout_sec: float
