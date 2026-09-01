"""Canonical repository, runtime data, and template paths."""

from __future__ import annotations

import os


REPO_ROOT = os.path.abspath(os.path.dirname(__file__))
RUNS_DIR = os.path.join(REPO_ROOT, "runs")
DATA_DIR = os.path.join(REPO_ROOT, "data")
LOGS_DIR = os.path.join(REPO_ROOT, "logs")

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
