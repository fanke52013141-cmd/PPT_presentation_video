"""Tests for review_policy automatic checkpoint resolution."""

from __future__ import annotations

from one_click_orchestrator import (
    _stop_at_from_policy,
    _next_stop_at_from_policy,
    _POLICY_CHECKPOINTS,
)


# ------------------------------------------------------------------
# _stop_at_from_policy
# ------------------------------------------------------------------

def test_none_policy_returns_empty():
    assert _stop_at_from_policy("none") == ""


def test_images_and_video_returns_image_review_first():
    assert _stop_at_from_policy("images_and_video") == "image_review"


def test_all_stages_returns_storyboard_review_first():
    assert _stop_at_from_policy("all_stages") == "storyboard_review"


def test_unknown_policy_returns_empty():
    assert _stop_at_from_policy("unknown") == ""


def test_empty_string_returns_empty():
    assert _stop_at_from_policy("") == ""


# ------------------------------------------------------------------
# _next_stop_at_from_policy
# ------------------------------------------------------------------

def test_next_stop_images_and_video():
    # After image_review, next is video_review
    assert _next_stop_at_from_policy("images_and_video", "image_review") == "video_review"
    # After video_review, no more
    assert _next_stop_at_from_policy("images_and_video", "video_review") == ""


def test_next_stop_all_stages():
    checkpoints = _POLICY_CHECKPOINTS["all_stages"]
    for i in range(len(checkpoints) - 1):
        assert _next_stop_at_from_policy("all_stages", checkpoints[i]) == checkpoints[i + 1]
    # Last checkpoint has no next
    assert _next_stop_at_from_policy("all_stages", checkpoints[-1]) == ""


def test_next_stop_none_policy():
    assert _next_stop_at_from_policy("none", "image_review") == ""


def test_next_stop_unknown_checkpoint():
    assert _next_stop_at_from_policy("all_stages", "nonexistent") == ""


# ------------------------------------------------------------------
# Policy checkpoint list integrity
# ------------------------------------------------------------------

def test_policy_checkpoints_complete():
    """Verify all expected checkpoint names exist in all_stages."""
    expected = {
        "storyboard_review",
        "image_review",
        "mask_review",
        "narration_review",
        "audio_review",
        "video_review",
    }
    assert set(_POLICY_CHECKPOINTS["all_stages"]) == expected


def test_images_and_video_subset_of_all_stages():
    iv = _POLICY_CHECKPOINTS["images_and_video"]
    all_stages = _POLICY_CHECKPOINTS["all_stages"]
    assert set(iv).issubset(set(all_stages))
