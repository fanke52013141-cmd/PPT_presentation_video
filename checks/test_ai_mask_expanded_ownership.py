"""Resolved semantic objects must remain whole through assignment cleanup."""
import pytest

from ai_mask_assignment import _clean_match, _merge_match_results
from ai_mask_semantic_matcher import _expand_matches


def fixture():
    elements = [{"element_id": f"e{i}"} for i in range(90)]
    slide = {
        "visual_groups": [{"id": "body"}, {"id": "other"}],
        "narration_beats": [
            {"id": "beat", "group_id": "body"},
            {"id": "other_beat", "group_id": "other"},
        ],
    }
    fallback = {"matches": [], "warnings": []}
    return elements, slide, fallback


def clean(value, elements, slide, fallback):
    return _clean_match(
        _merge_match_results(value, fallback), slide, elements,
        {"max_group_elements": 60, "llm_confidence_threshold": .72}, fallback,
    )


def test_expanded_object_keeps_every_known_component_and_confidence():
    elements, slide, fallback = fixture()
    ids = [e["element_id"] for e in elements]
    value = _expand_matches(
        {"matches": [{"group_id": "body", "narration_beat_id": "beat",
                      "object_ids": ["card"], "confidence": .9}]},
        [{"object_id": "card", "element_ids": [*ids, "invented"]}], elements,
    )
    result = clean(value, elements, slide, fallback)
    match = result["matches"][0]
    assert match["element_ids"] == ids
    assert match["seed_element_ids"] == ids
    assert match["confidence"] == .9
    assert set(match["element_origins"].values()) == {"model"}
    assert result["unmatched_elements"] == []


@pytest.mark.parametrize("metadata", [
    {}, {"object_ids": ["card"]},
    {"object_ids": ["card"], "expanded_from_object_ids": ["another"]},
    {"object_ids": ["card"], "expanded_from_object_ids": ["card"], "assignment_source": "rule"},
])
def test_legacy_and_rule_component_limits_are_preserved(metadata):
    elements, slide, fallback = fixture()
    value = {"matches": [{"group_id": "body", "narration_beat_id": "beat",
        "element_ids": [e["element_id"] for e in elements], "confidence": .9, **metadata}]}
    result = clean(value, elements, slide, fallback)
    assert len(result["matches"][0]["element_ids"]) == 60
    assert len(result["unmatched_elements"]) == 30


def test_unknown_object_ids_cannot_remove_legacy_limit():
    elements, slide, fallback = fixture()
    value = _expand_matches({"matches": [{"group_id": "body",
        "object_ids": ["invented"], "expanded_from_object_ids": ["invented"],
        "element_ids": [e["element_id"] for e in elements], "confidence": .9}]}, [], elements)
    result = clean(value, elements, slide, fallback)
    assert len(result["matches"][0]["element_ids"]) == 60
    assert result["matches"][0]["object_ids"] == []


def test_expansion_preserves_exclusivity_and_low_confidence_gate():
    elements, slide, fallback = fixture()
    ids = [e["element_id"] for e in elements]
    value = _expand_matches({"matches": [
        {"group_id": "body", "object_ids": ["card"], "confidence": .5},
        {"group_id": "other", "object_ids": ["tail"], "confidence": .95},
    ]}, [{"object_id": "card", "element_ids": ids[:80]},
        {"object_id": "tail", "element_ids": ids[75:]}], elements)
    result = clean(value, elements, slide, fallback)
    first, second = result["matches"]
    assert first["element_ids"] == ids[:80]
    assert first["below_threshold"] is True
    assert second["element_ids"] == ids[80:]
    assert not set(first["element_ids"]) & set(second["element_ids"])
