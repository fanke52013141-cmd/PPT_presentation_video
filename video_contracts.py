"""Shared contracts for the video rendering subsystem."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


class VideoRenderError(RuntimeError):
    """HTTP-aware application error raised by video services.

    ``repair_actions`` lets the Agent adapter describe the actual recovery
    without parsing the human-readable message (for example confirming audio
    versus regenerating a stale digital-human presenter).
    """

    def __init__(
        self,
        status_code: int,
        detail: Any,
        *,
        repair_actions: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail
        self.repair_actions = list(repair_actions or [])


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
    # The value is parsed by video_acceleration.normalize_render_acceleration.
    # Keeping a default preserves existing render configuration construction.
    render_acceleration: str = "auto"
