"""Unified Operation status model for long-running Agent tasks.

All long-running operations (pipeline runs, TTS synthesis, video rendering)
return an OperationResult with a consistent status vocabulary. This replaces
the heterogeneous task_id / job_id / run_id patterns with a single model.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class OperationStatus(str, Enum):
    queued = "queued"
    running = "running"
    waiting_for_review = "waiting_for_review"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"
    interrupted = "interrupted"


# Map one-click orchestrator statuses to unified OperationStatus
_ONE_CLICK_STATUS_MAP = {
    "idle": OperationStatus.succeeded,
    "running": OperationStatus.running,
    "waiting_for_review": OperationStatus.waiting_for_review,
    "paused": OperationStatus.waiting_for_review,
    "succeeded": OperationStatus.succeeded,
    "completed": OperationStatus.succeeded,
    "failed": OperationStatus.failed,
    "interrupted": OperationStatus.interrupted,
    "cancelled": OperationStatus.cancelled,
}


def normalize_status(raw: str) -> OperationStatus:
    """Convert any internal status string to the unified OperationStatus."""
    if raw in _ONE_CLICK_STATUS_MAP:
        return _ONE_CLICK_STATUS_MAP[raw]
    # Job-level statuses
    if raw in ("100", "done", "ok"):
        return OperationStatus.succeeded
    if raw in ("error", "0"):
        return OperationStatus.failed
    return OperationStatus.running


def unwrap_one_click_status(result: dict[str, Any]) -> dict[str, Any]:
    """Return the inner status document from a one-click result.

    The orchestrator wraps public responses as ``{"success": true,
    "status": {...}}``.  Older callers may already provide the inner status,
    so this adapter intentionally accepts both shapes.
    """
    nested_status = result.get("status") if isinstance(result, dict) else None
    if isinstance(nested_status, dict):
        return nested_status
    return result if isinstance(result, dict) else {}


class OperationResult(BaseModel):
    """Unified long-running operation result."""

    operation_id: str
    project_id: str
    operation_type: str = Field("", description="pipeline_run / tts_synthesize / video_render")
    status: OperationStatus = OperationStatus.queued
    stage: str = Field("", description="当前阶段标识")
    progress: int = Field(0, ge=0, le=100)
    message: str = ""
    blocking_errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


# Checkpoint stages — review gates the Agent can pause at
CHECKPOINT_STAGES = {
    "storyboard_review": {
        "label": "分镜审查",
        "internal_stage": "storyboard",
        "description": "分镜规划完成，等待确认后再生成图片",
    },
    "image_review": {
        "label": "图片审查",
        "internal_stage": "confirm_images",
        "description": "图片生成完成，等待确认后再进行 Mask 标注",
    },
    "mask_review": {
        "label": "Mask 审查",
        "internal_stage": "mask_assets",
        "description": "Mask 标注完成，等待确认后再生成旁白",
    },
    "narration_review": {
        "label": "旁白审查",
        "internal_stage": "narration",
        "description": "旁白生成完成，等待确认后再合成音频",
    },
    "audio_review": {
        "label": "音频审查",
        "internal_stage": "tts",
        "description": "音频合成完成，等待确认后再渲染视频",
    },
    "video_review": {
        "label": "视频审查",
        "internal_stage": "render",
        "description": "视频渲染完成，等待最终确认",
    },
}


def get_checkpoint(checkpoint: str) -> dict[str, str]:
    """Get checkpoint metadata or raise ValueError."""
    if checkpoint not in CHECKPOINT_STAGES:
        raise ValueError(
            f"Unknown checkpoint '{checkpoint}'. Valid: {', '.join(CHECKPOINT_STAGES.keys())}"
        )
    return CHECKPOINT_STAGES[checkpoint]


def operation_from_one_click(status_dict: dict[str, Any], project_id: str) -> OperationResult:
    """Convert a one-click orchestrator status dict to unified OperationResult."""
    status_dict = unwrap_one_click_status(status_dict)
    raw_status = status_dict.get("status", "idle")
    op_status = normalize_status(raw_status)
    run_id = status_dict.get("run_id", "")
    stages = status_dict.get("stages", [])
    current_stage = status_dict.get("current_stage", "")

    blocking_errors: list[str] = []
    warnings: list[str] = []
    progress = 0
    for stage in stages:
        if isinstance(stage, dict):
            errs = stage.get("blocking_errors", [])
            if isinstance(errs, list):
                blocking_errors.extend(str(e) for e in errs if e)
            warns = stage.get("warnings", [])
            if isinstance(warns, list):
                warnings.extend(str(w) for w in warns if w)

    # Calculate progress from completed stages
    if stages:
        completed = sum(
            1 for s in stages
            if isinstance(s, dict) and s.get("status") in {"done", "succeeded"}
        )
        progress = int(completed / len(stages) * 100)

    return OperationResult(
        operation_id=run_id or "unknown",
        project_id=project_id,
        operation_type="pipeline_run",
        status=op_status,
        stage=current_stage,
        progress=progress,
        message=status_dict.get("message", ""),
        blocking_errors=blocking_errors,
        warnings=warnings,
        started_at=status_dict.get("started_at"),
        finished_at=status_dict.get("completed_at") or None,
    )
