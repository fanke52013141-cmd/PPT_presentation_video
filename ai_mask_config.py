"""Persistent AI Mask settings and prompt configuration."""

from __future__ import annotations

from typing import Any

from config_store import get_setting, update_settings
from ai_mask_engine import (
    CURRENT_TITLE_AND_ISLAND_RULES,
    DEFAULT_METHODOLOGY,
    DEFAULT_OUTPUT_STRUCTURE,
    DEFAULT_SETTINGS,
    LEGACY_DEFAULT_METHODOLOGY_V2,
    LEGACY_DEFAULT_OUTPUT_STRUCTURE_V2,
    LEGACY_STORED_METHODOLOGY_V2,
    LEGACY_TITLE_RULE,
    PREVIOUS_TITLE_AND_ISLAND_RULES,
    PROMPT_METHOD_KEY,
    PROMPT_OUTPUT_KEY,
    SETTING_PREFIX,
    STATIC_TITLE_RULE,
    normalize_settings,
)


def compose_ai_mask_full_prompt(methodology: str, output_structure: str) -> str:
    return (
        methodology.strip()
        + "\n\n--- OUTPUT STRUCTURE / 输出结构 ---\n"
        + output_structure.strip()
    )


def read_ai_mask_prompts() -> tuple[str, str]:
    methodology = str(
        get_setting(PROMPT_METHOD_KEY, DEFAULT_METHODOLOGY) or DEFAULT_METHODOLOGY
    )
    output_structure = str(
        get_setting(PROMPT_OUTPUT_KEY, DEFAULT_OUTPUT_STRUCTURE)
        or DEFAULT_OUTPUT_STRUCTURE
    )
    if methodology in {
        LEGACY_DEFAULT_METHODOLOGY_V2,
        LEGACY_STORED_METHODOLOGY_V2,
    }:
        methodology = DEFAULT_METHODOLOGY
    if output_structure == LEGACY_DEFAULT_OUTPUT_STRUCTURE_V2:
        output_structure = DEFAULT_OUTPUT_STRUCTURE
    for old_rule in (
        LEGACY_TITLE_RULE,
        STATIC_TITLE_RULE,
        PREVIOUS_TITLE_AND_ISLAND_RULES,
    ):
        if old_rule in methodology:
            methodology = methodology.replace(
                old_rule,
                CURRENT_TITLE_AND_ISLAND_RULES,
            )
    return methodology, output_structure


def get_ai_mask_settings() -> dict[str, Any]:
    raw = {
        key: get_setting(SETTING_PREFIX + key, str(default))
        for key, default in DEFAULT_SETTINGS.items()
    }
    return normalize_settings(raw)


def save_ai_mask_settings(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    values = source.get("settings") if isinstance(source.get("settings"), dict) else source
    settings = normalize_settings(values if isinstance(values, dict) else {})
    updates: dict[str, Any] = {
        SETTING_PREFIX + key: value for key, value in settings.items()
    }
    prompts = source.get("prompts") if isinstance(source.get("prompts"), dict) else {}
    methodology = str(prompts.get("methodology") or "").strip()
    output_structure = str(prompts.get("output_structure") or "").strip()
    if methodology:
        updates[PROMPT_METHOD_KEY] = methodology
    if output_structure:
        updates[PROMPT_OUTPUT_KEY] = output_structure
    update_settings(updates)
    return settings


def ai_mask_config_payload() -> dict[str, Any]:
    methodology, output_structure = read_ai_mask_prompts()
    return {
        "success": True,
        "settings": get_ai_mask_settings(),
        "prompts": {
            "methodology": methodology,
            "output_structure": output_structure,
            "full_prompt": compose_ai_mask_full_prompt(
                methodology,
                output_structure,
            ),
        },
    }
