"""P1 fine-grained detection: original seed components + bounded diffusion."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

import ai_mask_config
import ai_mask_engine
import ai_mask_semantic_matcher as matcher
from ai_mask_component_detection import detect_elements

SIZE = (480, 360)


def _settings(**overrides):
    base = dict(
        white_threshold=245,
        color_tolerance=12,
        closing_radius=6,
        add_border=2,
        connectivity=8,
        min_element_area=120,
        component_padding_px=12,
        fine_grained_detection=False,
        pale_support_threshold=254,
        enclosed_support_max_area_px=20000,
    )
    base.update(overrides)
    return base


def _canvas():
    return Image.new("RGB", SIZE, "white")


def _detect(tmp_path, image, settings):
    tmp_path.mkdir(parents=True, exist_ok=True)
    image_path = tmp_path / "image.png"
    image.save(image_path)
    return detect_elements(image_path, tmp_path / "slide", settings)


def _rle_mask(rle):
    mask = np.zeros((SIZE[1], SIZE[0]), bool)
    for y, x1, x2 in rle["runs"]:
        mask[y, x1:x2] = True
    return mask


def _union_mask(payload):
    combined = np.zeros((SIZE[1], SIZE[0]), bool)
    for element in payload["elements"] + payload["residual_elements"]:
        combined |= _rle_mask(element["mask_rle"])
    return combined


def _element_containing(payload, x, y):
    owners = [
        element for element in payload["elements"] + payload["residual_elements"]
        if _rle_mask(element["mask_rle"])[y, x]
    ]
    return owners


def test_fine_grained_two_pixel_white_gap_keeps_groups_separate(tmp_path):
    image = _canvas()
    draw = ImageDraw.Draw(image)
    draw.rectangle((60, 120, 120, 160), fill=(40, 70, 120))
    draw.rectangle((123, 120, 183, 160), fill=(150, 60, 40))
    payload = _detect(tmp_path, image, _settings(fine_grained_detection=True))
    assert payload["version"] == "auto_elements_v4_fine_grained"
    left = _element_containing(payload, 90, 140)
    right = _element_containing(payload, 153, 140)
    assert len(left) == 1 and len(right) == 1
    assert left[0]["element_id"] != right[0]["element_id"]
    assert not (_rle_mask(left[0]["mask_rle"]) & _rle_mask(right[0]["mask_rle"])).any()


def test_default_closing_still_merges_gap_that_fine_grained_keeps_apart(tmp_path):
    image = _canvas()
    draw = ImageDraw.Draw(image)
    draw.rectangle((60, 120, 120, 160), fill=(40, 70, 120))
    draw.rectangle((123, 120, 183, 160), fill=(150, 60, 40))
    legacy = _detect(tmp_path, image, _settings())
    assert legacy["version"] == "auto_elements_v3_exact_rle_cached"
    assert len(_element_containing(legacy, 90, 140)) == 1
    assert _element_containing(legacy, 90, 140)[0]["element_id"] == \
        _element_containing(legacy, 153, 140)[0]["element_id"]
    assert "fine_grained" not in legacy
    assert "stage_timings_sec" not in legacy


def test_fine_grained_recovers_pale_fill_and_thin_lines(tmp_path):
    image = _canvas()
    draw = ImageDraw.Draw(image)
    draw.rectangle((60, 60, 260, 220), outline=(100, 60, 40), width=3, fill=(250, 250, 250))
    draw.line((80, 140, 240, 140), fill=(248, 248, 248), width=2)
    draw.rectangle((110, 90, 140, 110), fill=(60, 60, 60))
    payload = _detect(tmp_path, image, _settings(fine_grained_detection=True))
    foreground = np.asarray(image).min(axis=2) < 245
    source = np.asarray(image)
    scored = np.any(source != 255, axis=2)
    covered = _union_mask(payload)
    assert np.count_nonzero(scored & ~covered) / max(1, np.count_nonzero(scored)) < 0.005
    assert foreground.any()
    assert payload["fine_grained"]["unassigned_support_pixel_count"] == 0
    # The pale panel interior belongs to the panel component, not the inside box.
    panel = _element_containing(payload, 70, 200)[0]
    assert "element_id" in panel
    inner = _element_containing(payload, 125, 100)[0]
    assert inner["element_id"] != panel["element_id"]


def test_fine_grained_keeps_glyph_counters_but_drops_large_enclosed(tmp_path):
    image = _canvas()
    draw = ImageDraw.Draw(image)
    draw.ellipse((80, 80, 140, 140), outline=(50, 50, 50), width=6)
    draw.rectangle((200, 40, 440, 320), outline=(70, 70, 70), width=3)
    payload = _detect(tmp_path, image, _settings(fine_grained_detection=True))
    hole = _element_containing(payload, 110, 110)
    assert len(hole) == 1  # small enclosed counter is absorbed by the ring
    ring = hole[0]
    assert np.count_nonzero(_rle_mask(ring["mask_rle"])) > 1500
    excluded = payload["fine_grained"]["excluded_enclosed_regions"]
    assert excluded and excluded[0]["area"] > 20000
    interior_owners = _element_containing(payload, 320, 180)
    assert not interior_owners or interior_owners[0]["element_id"] != ring["element_id"]


def test_fine_grained_conflicts_are_deterministic_and_never_overlap(tmp_path):
    image = _canvas()
    draw = ImageDraw.Draw(image)
    draw.rectangle((60, 120, 100, 200), fill=(40, 70, 120))
    draw.rectangle((110, 120, 150, 200), fill=(150, 60, 40))
    draw.rectangle((101, 120, 109, 200), fill=(247, 247, 247))  # shared pale band
    first = _detect(tmp_path, image, _settings(fine_grained_detection=True))
    second = _detect(tmp_path / "again", image, _settings(fine_grained_detection=True))

    def signature(payload):
        return {
            element["element_id"]: sorted(map(str, element["mask_rle"]["runs"]))
            for element in payload["elements"] + payload["residual_elements"]
        }

    assert signature(first) == signature(second)
    counts = np.zeros(SIZE[::-1], np.uint16)
    for element in first["elements"] + first["residual_elements"]:
        counts += _rle_mask(element["mask_rle"]).astype(np.uint16)
    foreground = np.any(np.asarray(image) != 255, axis=2)
    assert not np.any(counts[foreground] > 1)
    band = np.asarray(image)[120:200, 101:110]
    assert (band == 247).all()
    band_counts = counts[120:200, 101:110]
    assert band_counts.sum() == band_counts.size  # every pale pixel owned exactly once


def test_fine_grained_closing_is_reported_only_as_merge_candidate(tmp_path):
    image = _canvas()
    draw = ImageDraw.Draw(image)
    draw.rectangle((60, 120, 110, 170), fill=(40, 70, 120))
    draw.rectangle((122, 120, 172, 170), fill=(150, 60, 40))
    payload = _detect(tmp_path, image, _settings(fine_grained_detection=True))
    left = _element_containing(payload, 85, 145)[0]
    right = _element_containing(payload, 147, 145)[0]
    radius_6 = payload["fine_grained"]["merge_candidates"]["radius_6"]
    pairs = [set(group["element_ids"]) for group in radius_6]
    assert {left["element_id"], right["element_id"]} in pairs
    radius_2 = payload["fine_grained"]["merge_candidates"]["radius_2"]
    assert {left["element_id"], right["element_id"]} not in [set(group["element_ids"]) for group in radius_2]
    # Candidate grouping must not move pixels: neither mask covers the other card.
    assert not _rle_mask(left["mask_rle"])[120:170, 122:172].any()
    assert not _rle_mask(right["mask_rle"])[120:170, 60:110].any()


def test_cache_invalidates_when_fine_grained_flag_or_threshold_changes(tmp_path):
    image = _canvas()
    draw = ImageDraw.Draw(image)
    draw.rectangle((60, 120, 200, 200), outline=(40, 70, 120), width=3, fill=(250, 250, 250))
    off = _detect(tmp_path, image, _settings())
    assert off["version"] == "auto_elements_v3_exact_rle_cached"
    on = _detect(tmp_path, image, _settings(fine_grained_detection=True))
    assert on["version"] == "auto_elements_v4_fine_grained"
    assert on["detection_settings_fingerprint"] != off["detection_settings_fingerprint"]
    again = _detect(tmp_path, image, _settings(fine_grained_detection=True))
    assert again["detection_settings_fingerprint"] == on["detection_settings_fingerprint"]
    tuned = _detect(tmp_path, image, _settings(fine_grained_detection=True, pale_support_threshold=248))
    assert tuned["detection_settings_fingerprint"] != on["detection_settings_fingerprint"]
    assert tuned["fine_grained"]["pale_support_threshold"] == 248
    # Cached v4 payload keeps algorithm/version metadata for the fingerprint.
    cached = json.loads((tmp_path / "slide" / "auto_mask" / "auto_elements.json").read_text(encoding="utf-8"))
    assert cached["algorithm_version"] == on["algorithm_version"]
    for key in ("seed_labeling_sec", "wave_expansion_sec", "component_build_sec"):
        assert key in cached["stage_timings_sec"]


def test_semantic_objects_keep_more_than_120_candidates():
    width, height = 1920, 1080
    elements = []
    columns, rows = 13, 10
    for index in range(columns * rows):
        row, column = divmod(index, columns)
        elements.append({
            "element_id": f"el_auto_{index + 1:03d}",
            "area": 400,
            "raw_bbox": {"x": 20 + column * 145, "y": 20 + row * 100, "w": 60, "h": 40},
        })
    objects = matcher._semantic_objects(elements, width, height)
    assert len(objects) > 20  # 130 components survive without silent truncation
    covered = {eid for obj in objects for eid in obj["element_ids"]}
    assert covered == {element["element_id"] for element in elements}
    ids = [obj["object_id"] for obj in objects]
    assert len(ids) == len(set(ids)) == len(objects)


def test_plan_object_pages_never_drops_objects():
    objects = [{"object_id": f"obj_{i:03d}"} for i in range(73)]
    plan = matcher._plan_object_pages(objects)
    assert plan["overflow"] is True
    assert [obj for page in plan["pages"] for obj in page] == objects
    assert len(plan["pages"]) <= 6
    small = matcher._plan_object_pages(objects[:13])
    assert small["overflow"] is False
    assert [len(page) for page in small["pages"]] == [12, 1]
    empty = matcher._plan_object_pages([])
    assert empty["pages"] == [] and empty["overflow"] is False


def test_merge_page_values_unions_and_reports_budget():
    pages = [
        {
            "matches": [{
                "group_id": "g1", "narration_beat_id": "b1", "object_ids": ["obj_001"],
                "element_ids": ["el_auto_001"], "confidence": 0.8, "reason": "A",
            }],
            "unmatched_objects": ["obj_002"], "unmatched_elements": [], "unmatched_groups": ["g9"],
            "warnings": [{"type": "x"}],
        },
        {
            "matches": [{
                "group_id": "g1", "narration_beat_id": "b1", "object_ids": ["obj_003"],
                "element_ids": ["el_auto_001", "el_auto_003"], "confidence": 0.95, "reason": "B",
            }],
            "unmatched_objects": [], "unmatched_elements": ["el_auto_009"], "unmatched_groups": [],
            "warnings": [],
        },
    ]
    merged = matcher._merge_page_values(pages, budget_exceeded=True, object_count=99)
    assert merged is not None and merged["pages_merged"] == 2
    assert len(merged["matches"]) == 1
    match = merged["matches"][0]
    assert match["object_ids"] == ["obj_001", "obj_003"]
    assert match["element_ids"] == ["el_auto_001", "el_auto_003"]
    assert match["confidence"] == 0.95
    assert merged["unmatched_objects"] == ["obj_002"]
    assert merged["unmatched_elements"] == ["el_auto_009"]
    assert merged["unmatched_groups"] == ["g9"]
    assert any(item["type"] == "object_page_budget_exceeded" for item in merged["warnings"])
    assert matcher._merge_page_values([]) is None


def test_normalize_settings_and_prompt_migration_for_fine_grained():
    settings = ai_mask_engine.normalize_settings({
        "fine_grained_detection": "true",
        "pale_support_threshold": 999,
        "enclosed_support_max_area_px": "5000",
    })
    assert settings["fine_grained_detection"] is True
    assert settings["pale_support_threshold"] == 255
    assert settings["enclosed_support_max_area_px"] == 5000
    assert ai_mask_engine.DEFAULT_SETTINGS["fine_grained_detection"] is False
    assert "cluster_member_count" not in ai_mask_engine.DEFAULT_METHODOLOGY


def test_prompt_migrates_cluster_field_rule(monkeypatch):
    stored = ai_mask_engine.DEFAULT_METHODOLOGY.replace(
        ai_mask_engine.CURRENT_OBJECT_FIELD_RULE,
        ai_mask_engine.PREVIOUS_OBJECT_FIELD_RULE,
    )
    assert "cluster_member_count" in stored
    monkeypatch.setattr(ai_mask_config, "get_setting", lambda key, default=None: stored if key == ai_mask_engine.PROMPT_METHOD_KEY else default)
    methodology, _ = ai_mask_config.read_ai_mask_prompts()
    assert "cluster_member_count" not in methodology
    assert "page.index" in methodology
    defaults, _ = (lambda: (ai_mask_engine.DEFAULT_METHODOLOGY, None))()
    assert "cluster_member_count" not in defaults
