"""W4 acceptance: ownership provenance, coverage-vs-semantics gate split."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ai_mask_assignment as assignment
import ai_mask_manifest_apply as manifest_apply
import ai_mask_service as service
from ai_mask_contracts import (
    ASSIGNMENT_SOURCE_COMPLETION,
    ASSIGNMENT_SOURCE_MANUAL,
    ASSIGNMENT_SOURCE_MODEL,
    ASSIGNMENT_SOURCE_RULE,
)
from ai_mask_engine import normalize_settings


def _element(element_id: str, x: int, y: int, w: int, h: int) -> dict:
    return {
        "element_id": element_id,
        "bbox": {"x": x, "y": y, "w": w, "h": h},
        "raw_bbox": {"x": x, "y": y, "w": w, "h": h},
        "center": {"x": x + w / 2, "y": y + h / 2},
        "area": w * h,
        "mask_rle": {
            "encoding": "row_runs_v1",
            "width": 320,
            "height": 180,
            "runs": [[row, x, x + w] for row in range(y, y + h)],
        },
    }


def _canvas(*elements: dict) -> dict:
    return {
        "canvas": {"width": 320, "height": 180},
        "elements": list(elements),
        "residual_elements": [],
    }


def _slide(*group_ids: str) -> dict:
    return {
        "slide_id": "slide_001",
        "visual_groups": [{"id": gid, "role": "body"} for gid in group_ids],
        "narration_beats": [
            {"id": f"beat_{gid}", "group_id": gid, "spoken_text": f"讲 {gid}"}
            for gid in group_ids
        ],
    }


def _provenance_by_group(completed: dict) -> dict:
    return {
        str(record["group_id"]): record
        for record in completed["assignment_provenance"]["groups"]
    }


def _issues(match_payload: dict) -> dict:
    return {
        str(issue["type"]): issue
        for issue in manifest_apply._review_issues(match_payload)
    }


def test_full_pixel_coverage_with_rule_only_ownership_is_a_semantic_risk():
    """100% coverage must not be able to launder an unconfirmed grouping."""
    elements = _canvas(
        _element("model_claimed", 20, 50, 140, 80),
        _element("rule_seeded", 230, 70, 60, 40),
    )
    slide = _slide("group_a", "group_b")
    # The multimodal answer did run here: group_a is its claim, and group_b is
    # where only a rule placed a component.  That combination is the actionable
    # risk, and it is what a person should be shown.
    anchored = assignment._ensure_narrated_group_anchors(
        {
            "matching_method": "multimodal_with_deterministic_fallback",
            "matches": [{
                "group_id": "group_a",
                "narration_beat_id": "beat_group_a",
                "element_ids": ["model_claimed"],
                "confidence": 0.95,
            }],
            "unmatched_groups": ["group_b"],
        },
        elements,
        slide,
    )
    completed = assignment._complete_component_coverage(anchored, elements, slide)

    assert completed["quality"]["foreground_coverage_ratio"] == 1.0
    assert completed["quality"]["unassigned_component_count"] == 0
    assert completed["quality"]["overlap_pixel_count"] == 0
    assert completed["quality"]["pixel_contract_passed"] is True

    records = _provenance_by_group(completed)
    assert records["group_a"]["assignment_source"] == ASSIGNMENT_SOURCE_MODEL
    assert records["group_a"]["semantically_confirmed"] is True
    assert records["group_b"]["assignment_source"] == ASSIGNMENT_SOURCE_RULE
    assert records["group_b"]["model_element_count"] == 0
    assert records["group_b"]["model_ownership_ratio"] == 0.0
    assert records["group_b"]["semantically_confirmed"] is False

    # The pixel contract passed, so the Mask is still usable; the semantic
    # contract reports the risk instead of hiding behind the coverage number.
    assert completed["semantic_quality"]["unconfirmed_group_ids"] == ["group_b"]
    assert completed["semantic_quality"]["confirmed_group_count"] == 1
    assert completed["semantic_quality"]["passed"] is True
    assert completed["quality"]["passed"] is True
    assert not completed["semantic_quality"]["blocking_errors"]

    check = {
        item["group_id"]: item["narration"]
        for item in completed["semantic_quality"]["group_checks"]
    }
    assert check["group_b"]["semantically_confirmed"] is False
    assert check["group_b"]["rule_element_count"] == 1

    issues = _issues(completed)
    assert "unconfirmed_semantic_ownership" in issues
    assert issues["unconfirmed_semantic_ownership"]["group_id"] == "group_b"
    assert issues["unconfirmed_semantic_ownership"]["severity"] == "warning"


def test_title_and_subtitle_bands_are_not_reported_as_unconfirmed():
    """Geometry owns the header band on purpose; that is not an ambiguity."""
    elements = _canvas(_element("title_a", 40, 5, 80, 12), _element("body", 120, 60, 80, 60))
    slide = {
        "slide_id": "slide_001",
        "visual_groups": [
            {"id": "opening", "role": "title"},
            {"id": "body_group", "role": "body"},
        ],
        "narration_beats": [
            {"id": "beat_opening", "group_id": "opening"},
            {"id": "beat_body", "group_id": "body_group"},
        ],
    }
    completed = assignment._complete_component_coverage(
        {
            "matches": [
                {"group_id": "opening", "element_ids": ["title_a"], "confidence": 0.9,
                 "assignment_source": ASSIGNMENT_SOURCE_RULE},
                {"group_id": "body_group", "element_ids": ["body"], "confidence": 0.9,
                 "assignment_source": ASSIGNMENT_SOURCE_MODEL},
            ],
            "unmatched_groups": [],
        },
        elements,
        slide,
    )
    assert completed["assignment_provenance"]["unconfirmed_group_ids"] == []
    assert "unconfirmed_semantic_ownership" not in _issues(completed)


def test_coverage_completion_never_raises_confidence():
    """White-box guard: a later closer inflating confidence is clamped back."""
    by_id = {"a": {"area": 100}, "b": {"area": 100}}
    accepted = [{
        "group_id": "group_a",
        "element_ids": ["a", "b"],
        "confidence": 0.92,
        "confidence_before_completion": 0.41,
        "element_origins": {"a": ASSIGNMENT_SOURCE_MODEL, "b": ASSIGNMENT_SOURCE_COMPLETION},
    }]
    provenance = assignment._finalize_ownership_provenance(
        accepted, by_id, {"group_a": "body"}, True
    )
    record = provenance["groups"][0]
    assert accepted[0]["confidence"] == 0.41
    assert accepted[0]["confidence_capped"] is True
    assert record["confidence"] == 0.41
    assert record["confidence_capped"] is True
    assert provenance["confidence_policy"] == "completion_never_raises_semantic_confidence"
    assert record["semantically_confirmed"] is False
    assert record["assignment_source"] == "mixed"


def test_completion_keeps_the_pre_completion_confidence_on_the_real_path():
    elements = _canvas(_element("anchor", 120, 60, 40, 40), _element("leftover", 165, 40, 90, 100))
    slide = _slide("group_a")
    completed = assignment._complete_component_coverage(
        {
            "matches": [{"group_id": "group_a", "element_ids": ["anchor"], "confidence": 0.55}],
            "unmatched_groups": [],
        },
        elements,
        slide,
    )
    match = completed["matches"][0]
    assert match["confidence"] == 0.55
    assert match["confidence_before_completion"] == 0.55
    assert match.get("confidence_capped") is not True


def test_forced_completion_of_a_large_component_is_prominently_marked():
    elements = _canvas(_element("anchor", 120, 60, 40, 40), _element("big_leftover", 165, 40, 90, 100))
    slide = _slide("group_a")
    completed = assignment._complete_component_coverage(
        {
            "matches": [{"group_id": "group_a", "element_ids": ["anchor"], "confidence": 0.95}],
            "unmatched_groups": [],
        },
        elements,
        slide,
    )
    record = _provenance_by_group(completed)["group_a"]
    assert record["completion_element_count"] == 1
    assert record["model_ownership_ratio"] < 1.0

    forced = completed["assignment_provenance"]["large_forced_components"]
    assert [item["element_id"] for item in forced] == ["big_leftover"]
    assert forced[0]["group_area_ratio"] >= assignment.LARGE_FORCED_COMPONENT_AREA_RATIO

    issues = _issues(completed)
    assert "forced_large_component_completed" in issues
    assert issues["forced_large_component_completed"]["element_id"] == "big_leftover"
    assert issues["forced_large_component_completed"]["group_id"] == "group_a"
    # Coverage is still exact: the flag is a review prompt, not a pixel failure.
    assert completed["quality"]["pixel_contract_passed"] is True


def test_small_completion_fragment_is_not_escalated():
    elements = _canvas(_element("island", 100, 40, 120, 100), _element("dot", 230, 70, 8, 8))
    slide = _slide("group_a")
    completed = assignment._complete_component_coverage(
        {
            "matches": [{"group_id": "group_a", "element_ids": ["island"], "confidence": 0.95}],
            "unmatched_groups": [],
        },
        elements,
        slide,
    )
    assert completed["assignment_provenance"]["large_forced_components"] == []
    assert "forced_large_component_completed" not in _issues(completed)


def test_legitimate_cross_column_group_warns_without_blocking():
    elements = _canvas(_element("left_half", 20, 60, 60, 60), _element("right_half", 240, 60, 60, 60))
    slide = _slide("group_a")
    completed = assignment._complete_component_coverage(
        {
            "matches": [{
                "group_id": "group_a",
                "element_ids": ["left_half", "right_half"],
                "confidence": 0.95,
            }],
            "unmatched_groups": [],
        },
        elements,
        slide,
    )
    warnings = completed["semantic_quality"]["warnings"]
    assert any(w["type"] == "group_crosses_left_and_right_regions" for w in warnings)
    assert completed["semantic_quality"]["blocking_errors"] == []
    assert completed["semantic_quality"]["passed"] is True
    assert completed["quality"]["passed"] is True
    assert _provenance_by_group(completed)["group_a"]["semantically_confirmed"] is True


def test_subtitle_safe_zone_violation_still_blocks():
    """case_16 style: coverage must never excuse body text in the subtitle band."""
    elements = _canvas(_element("safe_body", 120, 60, 80, 60), _element("in_subtitle", 120, 160, 80, 14))
    slide = _slide("group_a", "group_b")
    completed = assignment._complete_component_coverage(
        {
            "matches": [
                {"group_id": "group_a", "element_ids": ["safe_body"], "confidence": 0.95},
                {"group_id": "group_b", "element_ids": ["in_subtitle"], "confidence": 0.95},
            ],
            "unmatched_groups": [],
        },
        elements,
        slide,
    )
    blocking = completed["semantic_quality"]["blocking_errors"]
    assert any(item["type"] == "dynamic_group_enters_subtitle_safe_zone" for item in blocking)
    assert completed["semantic_quality"]["narration_contract_passed"] is False
    assert completed["semantic_quality"]["passed"] is False
    assert completed["quality"]["pixel_contract_passed"] is True
    assert completed["quality"]["passed"] is False
    issues = _issues(completed)
    assert issues["dynamic_group_enters_subtitle_safe_zone"]["severity"] == "blocking"


def test_grouping_policy_and_versions_are_stable():
    elements = _canvas(_element("only", 120, 60, 80, 60))
    completed = assignment._complete_component_coverage(
        {"matches": [{"group_id": "group_a", "element_ids": ["only"], "confidence": 0.9}],
         "unmatched_groups": []},
        elements,
        _slide("group_a"),
    )
    assert completed["component_assignment_policy"] == "dominant_island_2d_absorption_v2"
    assert completed["quality"]["version"] == "ai_mask_quality_v3"
    assert completed["semantic_quality"]["version"] == "ai_mask_semantic_quality_v3"
    assert completed["assignment_provenance"]["version"] == "ai_mask_assignment_provenance_v1"


def test_manual_strokes_keep_ownership_and_are_marked_manual():
    elements = _canvas(_element("body", 120, 60, 80, 60))
    slide = _slide("group_a")
    completed = assignment._complete_component_coverage(
        {"matches": [{"group_id": "group_a", "element_ids": ["body"], "confidence": 0.95}],
         "unmatched_groups": []},
        elements,
        slide,
    )
    painted_runs = [[70, 10, 40]]
    manifest_slide = {
        "slide_id": "slide_001",
        "groups": [{
            "id": "group_a",
            "group_id": "group_a",
            "visual_group_id": "group_a",
            "source": "manual",
            "review_status": "pending",
            "manual_mask": {
                "encoding": "row_runs_v1",
                "width": 320,
                "height": 180,
                "runs": painted_runs,
                "strokes": [{"points": [[10, 70], [40, 70]]}],
            },
        }],
        "semantic_blocks": [],
    }
    manifest_apply._apply(
        {"slides": [manifest_slide]},
        slide,
        elements,
        completed,
        normalize_settings({"overwrite_existing_ai_mask": True}),
    )
    group = manifest_slide["groups"][0]
    assert group["manual_mask"]["runs"] == painted_runs
    assert group["manual_mask"]["strokes"] == [{"points": [[10, 70], [40, 70]]}]
    assert group["ai_match"]["assignment_source"] == ASSIGNMENT_SOURCE_MANUAL
    assert group["ai_match"]["ownership_preserved"] is True
    assert group.get("auto_mask") is None


def test_locked_group_is_left_untouched_by_a_rerun():
    elements = _canvas(_element("body", 120, 60, 80, 60))
    slide = _slide("group_a")
    completed = assignment._complete_component_coverage(
        {"matches": [{"group_id": "group_a", "element_ids": ["body"], "confidence": 0.95}],
         "unmatched_groups": []},
        elements,
        slide,
    )
    approved_runs = [[80, 5, 25]]
    manifest_slide = {
        "slide_id": "slide_001",
        "groups": [{
            "id": "group_a",
            "group_id": "group_a",
            "review_status": "approved",
            "manual_mask": {"encoding": "row_runs_v1", "width": 320, "height": 180, "runs": approved_runs},
        }],
        "semantic_blocks": [],
    }
    manifest_apply._apply(
        {"slides": [manifest_slide]},
        slide,
        elements,
        completed,
        normalize_settings({"overwrite_existing_ai_mask": True}),
    )
    group = manifest_slide["groups"][0]
    assert group["review_status"] == "approved"
    assert group["manual_mask"]["runs"] == approved_runs
    assert group.get("ai_match") is None


def test_unconfirmed_group_is_routed_to_review_even_with_high_confidence():
    elements = _canvas(_element("model_claimed", 20, 50, 140, 80), _element("rule_seeded", 230, 70, 60, 40))
    slide = _slide("group_a", "group_b")
    anchored = assignment._ensure_narrated_group_anchors(
        {
            "matches": [{"group_id": "group_a", "element_ids": ["model_claimed"], "confidence": 0.95}],
            "unmatched_groups": ["group_b"],
        },
        elements,
        slide,
    )
    completed = assignment._complete_component_coverage(anchored, elements, slide)
    manifest_slide = {"slide_id": "slide_001", "groups": [], "semantic_blocks": []}
    manifest_apply._apply(
        {"slides": [manifest_slide]},
        slide,
        elements,
        completed,
        normalize_settings({"overwrite_existing_ai_mask": True}),
    )
    by_group = {group["visual_group_id"]: group for group in manifest_slide["groups"]}
    assert by_group["group_b"]["review_status"] == "ai_review_required"
    assert by_group["group_b"]["ai_match"]["needs_review"] is True
    assert by_group["group_b"]["ai_match"]["model_ownership_ratio"] == 0.0
    assert set(by_group["group_b"]["auto_mask"]["element_origins"].values()) == {ASSIGNMENT_SOURCE_RULE}
    assert by_group["group_a"]["review_status"] == "ai_matched"
    assert by_group["group_a"]["auto_mask"]["assignment_source"] == ASSIGNMENT_SOURCE_MODEL
    assert manifest_slide["ai_mask_status"]["version"] == "ai_mask_annotation_v4_provenance"
    assert manifest_slide["ai_mask_status"]["assignment_provenance"]["unconfirmed_group_ids"] == ["group_b"]


def test_vision_batch_facts_survive_cleanup_and_reach_review_issues():
    slide = _slide("group_a")
    elements = [_element("body", 120, 60, 80, 60)]
    cleaned = assignment._clean_match(
        {
            "matches": [{"group_id": "group_a", "element_ids": ["body"], "confidence": 0.9}],
            "matching_method": "vision_object_batch",
            "vision_batches": {
                "request_count": 4,
                "beyond_budget_object_ids": ["el_atom_0042", "el_atom_0043"],
                "failed_batch_indices": [2],
                "failed_batch_error_type": "provider_error",
                "rejected_group_ids": ["ghost_group"],
                "rejected_object_ids": ["ghost_object"],
            },
        },
        slide,
        elements,
        normalize_settings({}),
        {"matches": [], "matching_method": "fallback"},
    )
    assert cleaned["vision_batches"]["beyond_budget_object_ids"] == ["el_atom_0042", "el_atom_0043"]
    assert cleaned["matches"][0]["assignment_source"] == ASSIGNMENT_SOURCE_RULE
    issues = _issues(cleaned)
    assert issues["object_beyond_review_budget"]["metrics"]["object_count"] == 2
    assert issues["vision_batch_failed"]["metrics"]["failed_batch_indices"] == [2]
    assert issues["vision_batch_failed"]["metrics"]["failed_batch_error_type"] == "provider_error"


def test_vision_model_claims_are_stamped_as_model_ownership():
    slide = _slide("group_a")
    elements = [_element("body", 120, 60, 80, 60)]
    cleaned = assignment._clean_match(
        {
            "matches": [{
                "group_id": "group_a",
                "element_ids": ["body"],
                "confidence": 0.9,
                "assignment_source": ASSIGNMENT_SOURCE_MODEL,
            }],
            "matching_method": "vision_object_batch",
        },
        slide,
        elements,
        normalize_settings({}),
        {"matches": [], "matching_method": "fallback"},
    )
    completed = assignment._complete_component_coverage(cleaned, _canvas(*elements), slide)
    record = _provenance_by_group(completed)["group_a"]
    assert record["assignment_source"] == ASSIGNMENT_SOURCE_MODEL
    assert record["semantically_confirmed"] is True
    assert completed["semantic_quality"]["unconfirmed_group_ids"] == []


def _high_confidence_rule_owned_slide() -> tuple[dict, dict, dict]:
    """A group the rules placed with a high number but no model claim."""
    elements = _canvas(_element("body", 120, 60, 80, 60))
    slide = _slide("group_a")
    completed = assignment._complete_component_coverage(
        {
            "matching_method": "multimodal_with_deterministic_fallback",
            "matches": [{
                "group_id": "group_a",
                "element_ids": ["body"],
                "confidence": 0.95,
                "assignment_source": ASSIGNMENT_SOURCE_RULE,
                "element_origins": {"body": ASSIGNMENT_SOURCE_RULE},
            }],
            "unmatched_groups": [],
        },
        elements,
        slide,
    )
    assert completed["assignment_provenance"]["model_participated"] is True
    assert completed["semantic_quality"]["unconfirmed_group_ids"] == ["group_a"]
    return elements, slide, completed


def test_no_model_page_records_evidence_without_flooding_review():
    """A deterministic-prior page is already reported page-wide, not per group."""
    elements = _canvas(_element("body", 120, 60, 80, 60))
    slide = _slide("group_a")
    completed = assignment._complete_component_coverage(
        {
            "matching_method": "deterministic_prior",
            "matches": [{
                "group_id": "group_a",
                "element_ids": ["body"],
                "confidence": 0.95,
                "assignment_source": ASSIGNMENT_SOURCE_RULE,
                "element_origins": {"body": ASSIGNMENT_SOURCE_RULE},
            }],
            "unmatched_groups": [],
        },
        elements,
        slide,
    )
    # Evidence layer: still recorded, so a later report can see what was guessed.
    provenance = completed["assignment_provenance"]
    assert provenance["model_participated"] is False
    assert provenance["unconfirmed_group_ids"] == ["group_a"]
    assert provenance["groups"][0]["semantically_confirmed"] is False
    # Routing layer: no per-group noise on top of the page-wide degradation.
    assert completed["semantic_quality"]["warnings"] == []
    assert _issues(completed) == {}
    manifest_slide = {"slide_id": "slide_001", "groups": [], "semantic_blocks": []}
    manifest_apply._apply(
        {"slides": [manifest_slide]},
        slide,
        elements,
        completed,
        normalize_settings({"overwrite_existing_ai_mask": True}),
    )
    group = manifest_slide["groups"][0]
    assert group["review_status"] == "ai_matched"
    assert group["ai_match"]["model_ownership_ratio"] == 0.0
    assert service._degradation_events({
        "slide_id": "slide_001",
        "quality": completed["quality"],
        "semantic_quality": completed["semantic_quality"],
        "vision_status": "deterministic_fallback",
        "layout_detection": {"status": "ok"},
    }) == [("ai_mask_vision_degraded", {"status": "deterministic_fallback", "reason": ""})]


def test_review_routing_rollback_keeps_the_diagnostics():
    elements, slide, completed = _high_confidence_rule_owned_slide()
    manifest_slide = {"slide_id": "slide_001", "groups": [], "semantic_blocks": []}
    manifest_apply._apply(
        {"slides": [manifest_slide]},
        slide,
        elements,
        completed,
        normalize_settings({"overwrite_existing_ai_mask": True, "provenance_review_routing": False}),
    )
    group = manifest_slide["groups"][0]
    assert group["review_status"] == "ai_matched"
    assert group["ai_match"]["needs_review"] is False
    # Diagnostics survive the rollback: the evidence is still written and still
    # reported, only the automatic routing into the review queue is disabled.
    assert group["auto_mask"]["assignment_source"] == ASSIGNMENT_SOURCE_RULE
    assert group["ai_match"]["model_ownership_ratio"] == 0.0
    assert manifest_slide["ai_mask_status"]["assignment_provenance"]["unconfirmed_group_ids"] == ["group_a"]
    assert "unconfirmed_semantic_ownership" in _issues(completed)


def test_semantic_risk_is_its_own_log_event():
    elements, slide, completed = _high_confidence_rule_owned_slide()
    events = dict(service._degradation_events({
        "slide_id": "slide_001",
        "quality": completed["quality"],
        "semantic_quality": completed["semantic_quality"],
        "vision_status": "ok",
        "layout_detection": {"status": "ok"},
    }))
    assert "ai_mask_layout_degraded" not in events
    assert "ai_mask_vision_degraded" not in events
    payload = events["ai_mask_semantic_risk"]
    assert payload["unconfirmed_group_ids"] == ["group_a"]
    assert payload["pixel_contract_passed"] is True
    assert payload["narration_contract_passed"] is True

    confirmed = assignment._complete_component_coverage(
        {
            "matching_method": "multimodal_with_deterministic_fallback",
            "matches": [{
                "group_id": "group_a",
                "element_ids": ["body"],
                "confidence": 0.95,
                "assignment_source": ASSIGNMENT_SOURCE_MODEL,
            }],
            "unmatched_groups": [],
        },
        elements,
        slide,
    )
    assert service._degradation_events({
        "slide_id": "slide_001",
        "quality": confirmed["quality"],
        "semantic_quality": confirmed["semantic_quality"],
        "vision_status": "ok",
        "layout_detection": {"status": "ok"},
    }) == []
