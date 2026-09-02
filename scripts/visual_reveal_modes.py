"""Shared reveal-intent vocabulary for storyboard planning and validation.

The value is deliberately small and backwards compatible: old contracts that
do not carry an explicit intent retain the historical sequential behaviour.
"""

from __future__ import annotations

from typing import Any


REVEAL_MODE_SEQUENTIAL = "sequential"
REVEAL_MODE_TOGETHER = "together"
ALLOWED_REVEAL_MODES = {REVEAL_MODE_SEQUENTIAL, REVEAL_MODE_TOGETHER}


def normalize_reveal_mode(value: Any, *, default: str = REVEAL_MODE_SEQUENTIAL) -> str:
    """Return a supported reveal mode without making old contracts permissive."""
    text = str(value or "").strip().lower()
    aliases = {
        "sequential": REVEAL_MODE_SEQUENTIAL,
        "sequence": REVEAL_MODE_SEQUENTIAL,
        "依次展示": REVEAL_MODE_SEQUENTIAL,
        "逐步展示": REVEAL_MODE_SEQUENTIAL,
        "together": REVEAL_MODE_TOGETHER,
        "simultaneous": REVEAL_MODE_TOGETHER,
        "同时展示": REVEAL_MODE_TOGETHER,
        "整体展示": REVEAL_MODE_TOGETHER,
    }
    return aliases.get(text, default if default in ALLOWED_REVEAL_MODES else REVEAL_MODE_SEQUENTIAL)
