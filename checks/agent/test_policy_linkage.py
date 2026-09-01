"""Tests for Agent capability ↔ review_policy dynamic linkage.

Covers:
- capabilities_for_policy annotation accuracy
- checkpoint.approve relevance under different policies
- Non-gated capabilities always have "always" relevance
- get_active_checkpoints returns correct checkpoints per policy
- Invalid/unknown policies normalize to "none"
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


# ---------------------------------------------------------------------------
# Policy relevance
# ---------------------------------------------------------------------------

def test_policy_none_marks_checkpoint_inactive():
    """Under review_policy=none, checkpoint.approve must be 'inactive'."""
    from agent_contract.capabilities import capabilities_for_policy

    caps = capabilities_for_policy("none")
    checkpoint_cap = next(c for c in caps if c["id"] == "checkpoint.approve")
    assert checkpoint_cap["policy_relevance"] == "inactive"


def test_policy_all_stages_marks_checkpoint_active():
    """Under review_policy=all_stages, checkpoint.approve must be 'active'."""
    from agent_contract.capabilities import capabilities_for_policy

    caps = capabilities_for_policy("all_stages")
    checkpoint_cap = next(c for c in caps if c["id"] == "checkpoint.approve")
    assert checkpoint_cap["policy_relevance"] == "active"


def test_policy_images_and_video_marks_checkpoint_active():
    """Under review_policy=images_and_video, checkpoint.approve must be 'active'."""
    from agent_contract.capabilities import capabilities_for_policy

    caps = capabilities_for_policy("images_and_video")
    checkpoint_cap = next(c for c in caps if c["id"] == "checkpoint.approve")
    assert checkpoint_cap["policy_relevance"] == "active"


def test_non_gated_capabilities_always_relevant():
    """Non-review-gated capabilities must always have 'always' relevance."""
    from agent_contract.capabilities import capabilities_for_policy

    for policy in ("none", "images_and_video", "all_stages"):
        caps = capabilities_for_policy(policy)
        for cap in caps:
            if cap["id"] != "checkpoint.approve":
                assert cap["policy_relevance"] == "always", \
                    f"Cap {cap['id']} should be 'always' under {policy}, got {cap['policy_relevance']}"


def test_capabilities_for_policy_returns_dicts():
    """Each entry must be a dict with required fields."""
    from agent_contract.capabilities import capabilities_for_policy

    caps = capabilities_for_policy("none")
    assert isinstance(caps, list)
    assert len(caps) > 0
    for cap in caps:
        assert isinstance(cap, dict)
        assert "id" in cap
        assert "status" in cap
        assert "policy_relevance" in cap
        assert "agent_api_method" in cap
        assert "agent_api_path" in cap
        assert "mcp_tool_name" in cap
        assert "cli_command" in cap


def test_invalid_policy_normalizes_to_none():
    """Unknown policy values must normalize to 'none'."""
    from agent_contract.capabilities import capabilities_for_policy

    caps = capabilities_for_policy("totally_invalid_policy")
    checkpoint_cap = next(c for c in caps if c["id"] == "checkpoint.approve")
    assert checkpoint_cap["policy_relevance"] == "inactive"


def test_empty_string_policy_normalizes_to_none():
    """Empty string policy must normalize to 'none'."""
    from agent_contract.capabilities import capabilities_for_policy

    caps = capabilities_for_policy("")
    checkpoint_cap = next(c for c in caps if c["id"] == "checkpoint.approve")
    assert checkpoint_cap["policy_relevance"] == "inactive"


def test_case_insensitive_policy():
    """Policy matching must be case-insensitive."""
    from agent_contract.capabilities import capabilities_for_policy

    caps = capabilities_for_policy("All_Stages")
    checkpoint_cap = next(c for c in caps if c["id"] == "checkpoint.approve")
    assert checkpoint_cap["policy_relevance"] == "active"


# ---------------------------------------------------------------------------
# Active checkpoints
# ---------------------------------------------------------------------------

def test_get_active_checkpoints_none():
    """get_active_checkpoints('none') must return empty list."""
    from agent_contract.capabilities import get_active_checkpoints

    assert get_active_checkpoints("none") == []


def test_get_active_checkpoints_images_and_video():
    """get_active_checkpoints('images_and_video') must return the two review checkpoints."""
    from agent_contract.capabilities import get_active_checkpoints

    checkpoints = get_active_checkpoints("images_and_video")
    assert "image_review" in checkpoints
    assert "video_review" in checkpoints
    assert len(checkpoints) == 2


def test_get_active_checkpoints_all_stages():
    """get_active_checkpoints('all_stages') must return all six review checkpoints."""
    from agent_contract.capabilities import get_active_checkpoints

    checkpoints = get_active_checkpoints("all_stages")
    expected = {
        "storyboard_review", "image_review", "mask_review",
        "narration_review", "audio_review", "video_review",
    }
    assert set(checkpoints) == expected
    assert len(checkpoints) == 6


def test_get_active_checkpoints_invalid_policy():
    """Invalid policy must return empty checkpoints."""
    from agent_contract.capabilities import get_active_checkpoints

    assert get_active_checkpoints("invalid") == []


# ---------------------------------------------------------------------------
# Policy relevance internal helper
# ---------------------------------------------------------------------------

def test_policy_relevance_helper():
    """The internal _policy_relevance function must return correct labels."""
    from agent_contract.capabilities import _policy_relevance

    assert _policy_relevance("checkpoint.approve", "none") == "inactive"
    assert _policy_relevance("checkpoint.approve", "all_stages") == "active"
    assert _policy_relevance("checkpoint.approve", "images_and_video") == "active"
    assert _policy_relevance("project.create", "none") == "always"
    assert _policy_relevance("pipeline.run", "all_stages") == "always"
