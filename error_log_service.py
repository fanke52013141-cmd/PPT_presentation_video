"""Structured pipeline error logging for easy diagnosis and sharing.

Every error entry is written as a JSON Lines record to
``logs/errors/error_log_YYYYMMDD.jsonl``.  The format is intentionally
human-readable so that users can open the file, copy the relevant entry,
and paste it directly into a bug report.

Each entry contains::

    {
        "timestamp": "2026-09-02T10:54:05",
        "project_id": "9bb33709_102011",
        "project_name": "三色法错题整理",
        "step": "Step 8 视频调速",
        "error_type": "VideoRenderError",
        "message": "生成调速视频失败：...",
        "details": { ... }
    }
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Optional

from repository_paths import LOGS_DIR


logger = logging.getLogger("PPTStudio.ErrorLog")

ERROR_LOG_DIR = os.path.join(LOGS_DIR, "errors")

# Human-readable step labels for known pipeline stages.
_STEP_LABELS: dict[str, str] = {
    "step1": "Step 1 文章导入",
    "step2": "Step 2 分镜规划",
    "step3": "Step 3 图片生成",
    "step4": "Step 4 AI Mask 标注",
    "step5": "Step 5 Mask 编辑",
    "step6": "Step 6 配音文案",
    "step7": "Step 7 语音合成",
    "step8": "Step 8 视频渲染",
    "step9": "Step 9 数字人",
    "speed": "Step 8 视频调速",
    "pptx": "Step 8 PPTX 导出",
    "render": "Step 8 视频渲染",
}

_PROJECT_ID_RE = re.compile(r"/projects/([^/^]+)")


def _resolve_step_label(step: str) -> str:
    """Map short step keys to human-readable labels."""
    return _STEP_LABELS.get(step, step)


def _extract_project_id_from_path(path: str) -> str:
    """Best-effort extraction of project_id from a URL path."""
    match = _PROJECT_ID_RE.search(path)
    if match:
        return match.group(1)
    return ""


def log_pipeline_error(
    *,
    project_id: str = "",
    project_name: str = "",
    step: str,
    error_message: str,
    error_type: str = "",
    details: dict[str, Any] | None = None,
    request_path: str = "",
) -> str:
    """Write a structured error entry to the daily error log.

    Parameters
    ----------
    project_id
        The project identifier (e.g. ``"9bb33709_102011"``).
    project_name
        The user-visible project name (e.g. ``"三色法错题整理"``).
    step
        A short step key (``"speed"``, ``"step8"``) or a full label.
    error_message
        The main error text shown to the user.
    error_type
        The exception class name (``"VideoRenderError"``, etc.).
    details
        Optional dictionary with extra diagnostic information
        (FFmpeg stderr, command, payload, …).
    request_path
        The HTTP request path, used to infer ``project_id`` when it
        was not supplied explicitly.

    Returns
    -------
    str
        Absolute path to the error log file that was written.
    """
    if not project_id and request_path:
        project_id = _extract_project_id_from_path(request_path)

    os.makedirs(ERROR_LOG_DIR, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    log_file = os.path.join(ERROR_LOG_DIR, f"error_log_{today}.jsonl")

    entry: dict[str, Any] = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "project_id": project_id,
        "project_name": project_name,
        "step": _resolve_step_label(step),
        "error_type": error_type,
        "message": error_message,
        "details": details or {},
    }

    try:
        with open(log_file, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as write_exc:
        logger.warning("Failed to write error log to %s: %s", log_file, write_exc)

    return log_file


def get_latest_error_log_path() -> Optional[str]:
    """Return the path to today's error log, or ``None`` if none exists."""
    today = datetime.now().strftime("%Y%m%d")
    log_file = os.path.join(ERROR_LOG_DIR, f"error_log_{today}.jsonl")
    return log_file if os.path.isfile(log_file) else None
