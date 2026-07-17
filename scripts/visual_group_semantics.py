#!/usr/bin/env python3
"""Shared semantic checks for Mask/Reveal visual-group atomicity."""

from __future__ import annotations

import re
from typing import Any


_UNIFIED_STRUCTURE_PATTERN = re.compile(
    r"(?:统一|一体化|不可分割|同一(?:个)?(?:连续|完整)?(?:外框|容器|视觉岛|场景|图表|流程|结构)|"
    r"single\s+unified|one\s+continuous|shared\s+outer\s+(?:container|boundary))",
    flags=re.IGNORECASE,
)

_INDEPENDENCE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "left_and_right_visual_islands",
        re.compile(
            r"(?:左侧|左边|left).{0,120}(?:视觉岛|独立(?:场景|卡片|面板)|visual\s+island|independent\s+(?:scene|card|panel))"
            r".{0,260}(?:右侧|右边|right).{0,120}(?:视觉岛|独立(?:场景|卡片|面板)|visual\s+island|independent\s+(?:scene|card|panel))",
            flags=re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "multiple_independent_units",
        re.compile(
            r"(?:[二三四五六七八九十]|[2-9]|多个|若干)个(?:彼此|相互)?独立(?:的)?"
            r"(?:视觉岛|卡片|场景|环节|步骤|对象|模块|面板|区域|标签|插图|信息标签)|"
            r"\b(?:two|three|four|five|six|seven|eight|nine|multiple|several)\s+independent\s+"
            r"(?:visual\s+islands?|cards?|scenes?|steps?|objects?|modules?|panels?|regions?|labels?|illustrations?)\b",
            flags=re.IGNORECASE,
        ),
    ),
    (
        "arranged_multiple_cards_or_panels",
        re.compile(
            r"(?:横向|纵向|从左到右|从上到下|依次)(?:排列|放置|展示|呈现).{0,50}"
            r"(?:[二三四五六七八九十]|[2-9]|多个|若干)个.{0,24}(?:卡片|面板|模块|场景|环节|视觉岛)|"
            r"(?:arrange|show|place|display).{0,40}(?:two|three|four|five|six|seven|eight|nine|multiple|several|[2-9])"
            r".{0,24}(?:cards?|panels?|modules?|scenes?|stages?|visual\s+islands?)",
            flags=re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "separate_upper_and_lower_card_regions",
        re.compile(
            r"(?:上半部分|上方|upper).{0,180}(?:卡片|面板|cards?|panels?).{0,260}"
            r"(?:下半部分|下方|lower).{0,180}(?:卡片|面板|cards?|panels?)",
            flags=re.IGNORECASE | re.DOTALL,
        ),
    ),
)


def independent_visual_island_signals(description: Any) -> list[str]:
    """Return strong signals that one description contains multiple Mask atoms."""
    text = " ".join(str(description or "").split())
    if not text or _UNIFIED_STRUCTURE_PATTERN.search(text):
        return []
    return [name for name, pattern in _INDEPENDENCE_PATTERNS if pattern.search(text)]


def visual_group_atomicity_issues(slide: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(slide, dict):
        return []
    issues: list[dict[str, Any]] = []
    for group in slide.get("visual_groups", []) or []:
        if not isinstance(group, dict):
            continue
        role = str(group.get("role") or "").strip().lower()
        if role in {"title", "subtitle", "decoration"}:
            continue
        description = str(
            group.get("visual_anchor")
            or group.get("mask_target")
            or group.get("visible_text")
            or ""
        ).strip()
        signals = independent_visual_island_signals(description)
        if signals:
            issues.append(
                {
                    "type": "group_contains_multiple_independent_visual_islands",
                    "group_id": str(group.get("id") or ""),
                    "signals": signals,
                    "description": description,
                }
            )
    return issues
