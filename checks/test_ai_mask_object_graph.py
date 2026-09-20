"""Exact-pixel tests for layout-box binding (handoff W2, optimization B).

These cases pin the properties the previous centre-consume merge could not
guarantee: box order cannot change ownership, a container cannot swallow ink a
nested box claims, and every merged element stays traceable to atomic islands.
"""

from __future__ import annotations

import itertools
import random

from ai_mask_object_graph import (
    BINDING_MIN_INK_FRACTION,
    BINDING_WEIGHTS,
    bind_atoms_to_boxes,
    canonicalize_boxes,
)


def _atom(atom_id: str, x1: int, y1: int, x2: int, y2: int) -> dict:
    runs = [[y, x1, x2] for y in range(y1, y2)]
    area = (x2 - x1) * (y2 - y1)
    return {
        "element_id": atom_id,
        "bbox": {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1},
        "raw_bbox": {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1},
        "area": area,
        "source_ink_pixel_count": area,
        "source_ink_rle": {"encoding": "row_runs_v1", "width": 1000, "height": 1000, "runs": runs},
        "mask_rle": {"encoding": "row_runs_v1", "width": 1000, "height": 1000, "runs": runs},
    }


def _box(x: float, y: float, w: float, h: float, role: str = "figure", confidence: float = 0.9) -> dict:
    return {"box": {"x": x, "y": y, "w": w, "h": h}, "role": role, "confidence": confidence, "class_id": 3}


ATOMS = [
    _atom("el_atom_0001", 20, 20, 120, 120),    # inside the left card
    _atom("el_atom_0002", 220, 20, 320, 120),   # inside the right card
]
CARDS = [_box(10, 10, 120, 120), _box(210, 10, 120, 120)]


def _members_by_role(result: dict) -> dict[tuple[float, float], list[str]]:
    return {
        (group["box"]["x"], group["box"]["y"]): group["member_element_ids"]
        for group in result["groups"]
    }


def test_binding_is_independent_of_box_order() -> None:
    forward = bind_atoms_to_boxes(ATOMS, CARDS)
    expected = {
        (10.0, 10.0): ["el_atom_0001"],
        (210.0, 10.0): ["el_atom_0002"],
    }
    assert _members_by_role(forward) == expected
    for permutation in itertools.permutations([
        _box(210, 10, 120, 120),
        _box(10, 10, 120, 120),
        _box(0, 0, 400, 200, role="page"),
    ]):
        shuffled = list(permutation)
        random.Random(len(shuffled)).shuffle(shuffled)
        outcome = bind_atoms_to_boxes(ATOMS, shuffled)
        assert _members_by_role(outcome) == {
            (10.0, 10.0): ["el_atom_0001"],
            (210.0, 10.0): ["el_atom_0002"],
        }


def test_container_box_does_not_swallow_nested_children() -> None:
    page = _box(0, 0, 400, 200, role="figure", confidence=0.99)
    result = bind_atoms_to_boxes(ATOMS, [page, *CARDS])
    assert _members_by_role(result) == {
        (10.0, 10.0): ["el_atom_0001"],
        (210.0, 10.0): ["el_atom_0002"],
    }
    assert result["groups"][0]["box"] == {"x": 10.0, "y": 10.0, "w": 120.0, "h": 120.0}


def test_only_a_container_wins_ink_no_child_covers() -> None:
    page = _box(0, 0, 400, 200)
    stray = _atom("el_atom_0009", 150, 150, 180, 170)
    result = bind_atoms_to_boxes([*ATOMS, stray], [page, *CARDS])
    assert result["assignments"]["el_atom_0009"] is not None
    assert result["unbound_element_ids"] == []


def test_atom_outside_every_box_stays_unbound() -> None:
    outside = _atom("el_atom_0003", 800, 800, 850, 850)
    result = bind_atoms_to_boxes([*ATOMS, outside], CARDS)
    assert result["unbound_element_ids"] == ["el_atom_0003"]
    assert result["candidates_by_atom"]["el_atom_0003"] == []


def test_half_in_half_out_is_ambiguous_and_still_deterministic() -> None:
    # Two cards sharing an edge; this ink island straddles both exactly 50/50.
    left, right = _box(10, 10, 100, 100), _box(110, 10, 100, 100)
    straddling = _atom("el_atom_0004", 60, 20, 160, 110)
    result = bind_atoms_to_boxes([straddling], [left, right])
    group = result["groups"][0]
    assert group["ambiguous_element_ids"] == ["el_atom_0004"]
    assert len(group["member_element_ids"]) == 1
    candidates = result["candidates_by_atom"]["el_atom_0004"]
    assert [item["ink_fraction"] for item in candidates] == [0.5, 0.5]
    assert candidates[0]["eligible"] is True
    # The recorded candidate order is score then canonical box index, never the
    # order the model emitted the boxes in.
    assert bind_atoms_to_boxes([straddling], [right, left])["groups"] == result["groups"]


def test_nested_child_wins_over_its_container_even_at_lower_confidence() -> None:
    # Specificity outranks confidence: the container's ink belongs to whoever
    # describes that region most precisely.  Junk low-confidence boxes are
    # already filtered by the model threshold before binding.
    weak = _box(15, 15, 115, 115, confidence=0.2)
    strong = _box(10, 10, 120, 120, confidence=0.95)
    result = bind_atoms_to_boxes([ATOMS[0]], [weak, strong])
    assert result["groups"][0]["box"]["x"] == 15.0
    assert result["groups"][0]["confidence"] == 0.2


def test_similar_sized_boxes_are_decided_by_confidence() -> None:
    # Neither of these contains the other, so no nesting penalty applies and the
    # stronger detection owns the ink regardless of emission order.
    weak = _box(10, 10, 120, 120, confidence=0.4)
    strong = _box(18, 14, 118, 118, confidence=0.9)
    for order in ([weak, strong], [strong, weak]):
        result = bind_atoms_to_boxes([ATOMS[0]], order)
        assert [(group["box"]["x"], group["confidence"]) for group in result["groups"]] == [
            (18.0, 0.9)
        ]


def test_boxes_are_deduplicated_by_geometry_and_role() -> None:
    duplicates = [_box(10, 10, 120, 120), _box(10, 10, 120, 120), _box(210, 10, 120, 120)]
    result = bind_atoms_to_boxes(ATOMS, duplicates)
    assert result["box_count"] == 2
    assert len(result["groups"]) == 2


def test_canonicalize_boxes_ignores_input_order() -> None:
    boxes = [_box(210, 10, 120, 120), _box(10, 10, 120, 120), _box(0, 0, 400, 200)]
    forward = [box["key"] for box in canonicalize_boxes(boxes)]
    backward = [box["key"] for box in canonicalize_boxes(list(reversed(boxes)))]
    assert forward == backward
    # Smallest area first so a container is always evaluated after its children.
    assert [box["geometry"]["area"] for box in canonicalize_boxes(boxes)] == sorted(
        box["geometry"]["area"] for box in canonicalize_boxes(boxes)
    )


def test_binding_defaults_are_exposed_in_the_report() -> None:
    result = bind_atoms_to_boxes(ATOMS, CARDS)
    binding = result["binding"]
    assert binding["method"] == "layout_binding_v2"
    assert binding["weights"] == BINDING_WEIGHTS
    assert binding["min_ink_fraction"] == BINDING_MIN_INK_FRACTION


def test_settings_can_override_weights_for_ablation() -> None:
    result = bind_atoms_to_boxes(
        ATOMS,
        CARDS,
        {"layout_binding_weights": {"confidence": 0.0}, "layout_binding_min_ink_fraction": 0.9},
    )
    assert result["binding"]["weights"]["confidence"] == 0.0
    assert result["binding"]["min_ink_fraction"] == 0.9
