"""Shared digital-human presenter constants, defaults and config loading.

This module is source-owned and dependency-light: it must stay importable by
HTTP routes, the Agent contract, project-state observation and the render
service without importing FastAPI, a database session or the application
module.  The single source of truth for accepted enum values lives here so the
Web UI validation and the Agent capability schema cannot drift apart.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

DEFAULT_CIRCLE = {"cx": 0.85, "cy": 0.76, "r": 0.12}


class DigitalHumanMode(str, Enum):
    """Supported presenter modes (single source for Web and Agent schema)."""

    portrait = "portrait"
    comfyui = "comfyui"
    upload = "upload"
    generate = "generate"


class DigitalHumanMotionSource(str, Enum):
    default = "default"
    custom = "custom"


class DigitalHumanShortVideoPolicy(str, Enum):
    reject = "reject"
    loop = "loop"


#: Supported presenter modes. ``portrait`` is the default: a still photo plus a
#: driving motion video is transferred, then lip-synced with the course audio.
#: ``upload`` skips model generation and uses an uploaded finished presenter
#: video.  ``comfyui`` / ``generate`` remain accepted for older projects.
DIGITAL_HUMAN_MODES = tuple(mode.value for mode in DigitalHumanMode)
DIGITAL_HUMAN_DEFAULT_MODE = DigitalHumanMode.portrait.value

#: Driving motion source for portrait mode: the bundled platform template or a
#: project-owned custom upload.
MOTION_SOURCES = tuple(source.value for source in DigitalHumanMotionSource)
DEFAULT_MOTION_SOURCE = DigitalHumanMotionSource.default.value

#: Short uploaded-video handling: reject or loop the uploaded presenter video.
SHORT_VIDEO_POLICIES = tuple(policy.value for policy in DigitalHumanShortVideoPolicy)
DEFAULT_SHORT_VIDEO_POLICY = DigitalHumanShortVideoPolicy.reject.value

#: Presenter window shapes.
WINDOW_SHAPES = ("circle", "rect")
DEFAULT_WINDOW_SHAPE = "circle"

CONFIG_FILENAME = "digital_human.json"
DIGI_DIRNAME = "digital_human"


def default_config() -> dict[str, Any]:
    """Return a fresh project digital-human configuration with all defaults."""
    return {
        "enabled": False,
        "mode": DIGITAL_HUMAN_DEFAULT_MODE,  # 照片 + 动作视频 | upload 成品视频
        "motion_source": DEFAULT_MOTION_SOURCE,
        "upload_start_sec": 0.0,
        "upload_short_video_policy": DEFAULT_SHORT_VIDEO_POLICY,
        "shape": DEFAULT_WINDOW_SHAPE,  # 窗口形状 'circle' | 'rect'
        "avatar_id": "",
        "sync_mode": "accurate",
        "circle": dict(DEFAULT_CIRCLE),  # 框在页面位置(cx,cy) + 大小(r)
        "video": {"ox": 0.5, "oy": 0.5, "zoom": 1.0},  # 视频与框相对位置
        "position": None,
        "border": {"width": 2, "color": "#FFFFFF"},
        "slides": {},
    }


def config_path(run_dir: str | Path) -> Path:
    """Return the canonical project config path for a run directory."""
    return Path(run_dir).resolve() / "planning" / CONFIG_FILENAME


def load_config(run_dir: str | Path) -> dict[str, Any]:
    """Read, default and normalize a project presenter config by run directory.

    Unknown keys are dropped (matching the historical route behavior) so a
    corrupted or hand-edited file cannot leak arbitrary values into rendering.
    """
    from pipeline_lifecycle import read_json_file

    raw = read_json_file(config_path(run_dir))
    if not isinstance(raw, dict):
        raw = {}
    cfg = default_config()
    cfg.update({key: value for key, value in raw.items() if key in cfg})
    if not isinstance(cfg.get("circle"), dict):
        cfg["circle"] = dict(DEFAULT_CIRCLE)
    if not isinstance(cfg.get("video"), dict):
        cfg["video"] = {"ox": 0.5, "oy": 0.5, "zoom": 1.0}
    if cfg.get("shape") not in WINDOW_SHAPES:
        cfg["shape"] = DEFAULT_WINDOW_SHAPE
    if cfg.get("mode") not in DIGITAL_HUMAN_MODES:
        cfg["mode"] = DIGITAL_HUMAN_DEFAULT_MODE
    return cfg


def digital_human_render_config(config: dict) -> dict:
    """Project only active composition settings; generation inputs stay separate."""
    if not config.get("enabled"):
        return {"enabled": False}
    result = {key: config.get(key) for key in (
        "enabled", "mode", "shape", "circle", "video", "position", "border",
    )}
    if config.get("mode") == "upload":
        result["upload_start_sec"] = config.get("upload_start_sec", 0)
        result["upload_short_video_policy"] = config.get("upload_short_video_policy", "reject")
    return result
