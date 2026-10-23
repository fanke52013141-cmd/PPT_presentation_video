"""Canonical repository, runtime data, and template paths."""

from __future__ import annotations

import os


REPO_ROOT = os.path.abspath(os.path.dirname(__file__))
AGENT_FEATURES_PATH = os.path.join(REPO_ROOT, "config", "agent_features.json")
AGENT_CONTRACT_SNAPSHOT_PATH = os.path.join(REPO_ROOT, "docs", "agent", "contract-snapshot.json")
# 运行时产物根目录。可用 PPT_STUDIO_RUNS_DIR 覆盖，用于测试隔离与多环境并行；
# 未设置时行为不变（仓库根下的 runs/）。路径注册表本身不承担任何应用装配职责，
# 这里只提供"可被配置覆盖"的单一来源。
RUNS_DIR = os.path.abspath(
    os.environ.get("PPT_STUDIO_RUNS_DIR") or os.path.join(REPO_ROOT, "runs")
)
# 业务数据目录。可用 PPT_STUDIO_DATA_DIR 覆盖，用于测试隔离与多环境并行；
# 未设置时行为不变（仓库根下的 data/）。与 RUNS_DIR 同一覆盖约定。
DATA_DIR = os.path.abspath(
    os.environ.get("PPT_STUDIO_DATA_DIR") or os.path.join(REPO_ROOT, "data")
)
AGENT_RATE_LIMIT_DB_PATH = os.path.abspath(
    os.environ.get("PPT_STUDIO_AGENT_RATE_LIMIT_DB_PATH") or os.path.join(DATA_DIR, "agent_rate_limit.db")
)
MODEL_VOICE_REFERENCES_DIR = os.path.join(DATA_DIR, "model_voice_references")
LOGS_DIR = os.path.join(REPO_ROOT, "logs")
ANNOTATION_WORKER_PYTHON = os.environ.get("PPT_ANNOTATION_ALIGN_PYTHON") or os.path.join(
    REPO_ROOT, "runtime", "annotation_worker", "Scripts", "python.exe"
)
ANNOTATION_WORKER_SCRIPT = os.path.join(REPO_ROOT, "scripts", "align_annotation_audio.py")
ANNOTATION_ALIGNMENT_MODELS_DIR = os.path.join(REPO_ROOT, "runtime", "annotation_models")

# Versioned, user-managed registries.  These are JSON persistence adapters for
# the first configuration rollout; the services keep the storage boundary
# injectable so a database-backed adapter can be introduced without changing
# callers.
MODEL_CONNECTIONS_PATH = os.path.join(DATA_DIR, "model_connections.json")
CREATION_CONFIGS_PATH = os.path.join(DATA_DIR, "creation_configs.json")
CREDENTIALS_PATH = os.path.join(DATA_DIR, "credentials.json")

DEFAULT_STYLE_TOKENS_PATH = os.path.join(
    REPO_ROOT,
    "config",
    "style_tokens.yaml",
)
HANDDRAWN_STYLE_TOKENS_PATH = os.path.join(
    REPO_ROOT,
    "config",
    "style_tokens_handdrawn.yaml",
)
STYLE_TOKENS_PATH = os.path.join(
    DATA_DIR,
    "style_tokens.yaml",
)
DEFAULT_STYLE_REFERENCE_DIR = os.path.join(
    REPO_ROOT,
    "references",
    "style_reference",
)
STYLE_REFERENCE_DIR = os.path.join(
    DATA_DIR,
    "style_reference_active",
)
STYLE_REFERENCE_FILES = {
    "template": "PPT模板.png",
}
IMAGE_STYLE_TEMPLATES_DIR = os.path.join(
    DATA_DIR,
    "image_style_templates",
)
IMAGE_STYLE_TEMPLATES_INDEX = os.path.join(
    IMAGE_STYLE_TEMPLATES_DIR,
    "index.json",
)

STORYBOARD_TEMPLATES_PATH = os.path.join(
    DATA_DIR,
    "storyboard_templates.json",
)
STEP2_PROMPT_TEMPLATES_PATH = os.path.join(
    DATA_DIR,
    "step2_prompt_templates.json",
)
HANDDRAWN_STORYBOARD_RULES_PATH = os.path.join(
    REPO_ROOT,
    "templates",
    "prompts",
    "storyboard_rules_handdrawn.zh.md",
)
STEP2_PROMPT_TEMPLATE_FILES = {
    "script_system": os.path.join(
        REPO_ROOT,
        "templates",
        "prompts",
        "step2_script_system.md",
    ),
    "script_output_example": os.path.join(
        REPO_ROOT,
        "templates",
        "prompts",
        "step2_script_output_example.json",
    ),
    "visual_system": os.path.join(
        REPO_ROOT,
        "templates",
        "prompts",
        "step2_visual_system.md",
    ),
    "visual_output_example": os.path.join(
        REPO_ROOT,
        "templates",
        "prompts",
        "step2_visual_output_example.json",
    ),
}
STEP3_IMAGE_PROMPT_TEMPLATE_PATH = os.path.join(
    REPO_ROOT,
    "templates",
    "prompts",
    "step3_image_system.md",
)


def resolve_comfyui_tts_workflow_path(endpoint: str = "", repo_root=None):
    """Resolve a local override, then the legacy and bundled workflow candidates."""
    from pathlib import Path

    root = Path(repo_root or REPO_ROOT)
    value = str(endpoint or "").strip()
    if value and not value.lower().startswith(("http://", "https://")):
        path = Path(value)
        return path if path.is_absolute() else root / path
    candidates = (
        root / "data" / "digital_human" / "comfyui_tts_workflow.json",
        root / "config" / "indextts2_5_comfyui_workflow.json",
    )
    return next((path for path in candidates if path.is_file()), candidates[-1])
