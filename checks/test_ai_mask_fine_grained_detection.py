"""P1 fine-grained detection: original seed components + bounded diffusion."""
from __future__ import annotations

import json

import numpy as np
from PIL import Image, ImageDraw

import ai_mask_config
import ai_mask_engine
import ai_mask_semantic_matcher as matcher
from ai_mask_component_detection import _build_atom, _connected_sets, _neighbors, detect_elements

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


def _save(tmp_path, image):
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "image.png"
    image.save(path)
    return path


def _detect(tmp_path, image, settings, layout_boxes=None):
    image_path = _save(tmp_path, image)
    return detect_elements(image_path, tmp_path / "slide", settings, layout_boxes)


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


def test_atomic_recovery_uses_exact_row_runs_for_4_and_8_connectivity():
    coords = [(1, 1), (2, 1), (2, 2), (5, 3), (6, 4)]
    four_way = _connected_sets(coords, _neighbors(4))
    assert four_way == [
        [[1, 1, 3], [2, 2, 3]],
        [[3, 5, 6]],
        [[4, 6, 7]],
    ]
    eight_way = _connected_sets(coords, _neighbors(8))
    assert eight_way == [
        [[1, 1, 3], [2, 2, 3]],
        [[3, 5, 6], [4, 6, 7]],
    ]
    atom = _build_atom([[2, 2, 4], [3, 3, 4]], border=2, ow=480, oh=360, index=1, padding=0)
    assert atom["raw_bbox"] == {"x": 0, "y": 0, "w": 2, "h": 2}
    assert atom["mask_pixel_count"] == 3


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
    assert legacy["version"] == "auto_elements_v5_box_label_only"
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


def test_fine_grained_layout_binding_does_not_undo_seed_components(tmp_path):
    image = _canvas()
    draw = ImageDraw.Draw(image)
    draw.rectangle((60, 120, 110, 170), fill=(40, 70, 120))
    draw.rectangle((122, 120, 172, 170), fill=(150, 60, 40))
    layout_boxes = [{
        "box": {"x": 40, "y": 100, "w": 160, "h": 90},
        "role": "text", "confidence": 0.9, "class_id": 0,
    }]
    settings = _settings(fine_grained_detection=True)
    plain = detect_elements(_save(tmp_path, image), tmp_path / "a", settings)
    with_boxes = detect_elements(_save(tmp_path, image), tmp_path / "b", settings, layout_boxes)
    assert len(plain["elements"]) == len(with_boxes["elements"]) == 2
    assert with_boxes["fine_grained"]["layout_binding_skipped"] is True
    legacy = detect_elements(_save(tmp_path, image), tmp_path / "c", _settings(), layout_boxes)
    assert [e["element_id"] for e in legacy["elements"]] == ["el_auto_001"]


def test_cache_invalidates_when_fine_grained_flag_or_threshold_changes(tmp_path):
    image = _canvas()
    draw = ImageDraw.Draw(image)
    draw.rectangle((60, 120, 200, 200), outline=(40, 70, 120), width=3, fill=(250, 250, 250))
    off = _detect(tmp_path, image, _settings())
    assert off["version"] == "auto_elements_v5_box_label_only"
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


def test_plan_atomic_requests_grows_batch_instead_of_dropping_objects():
    objects = [{"object_id": f"obj_{i:03d}"} for i in range(73)]
    settings = {"vision_object_batch_size": 12, "vision_max_requests": 4}
    batches, beyond, expanded = matcher._plan_atomic_requests(objects, settings)
    assert beyond == []
    assert expanded == 19  # ceil(73 / 4): every object still reaches the model
    assert [obj for batch in batches for obj in batch] == objects
    assert len(batches) <= 4
    small, small_beyond, small_expanded = matcher._plan_atomic_requests(objects[:13], settings)
    assert small_expanded == 0 and small_beyond == []
    assert [len(batch) for batch in small] == [12, 1]
    empty, empty_beyond, empty_expanded = matcher._plan_atomic_requests([], settings)
    assert empty == [] and empty_beyond == [] and empty_expanded == 0


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
    assert methodology == ai_mask_engine.DEFAULT_METHODOLOGY

    for stored_builtin in (
        ai_mask_engine.LEGACY_METHODOLOGY_V3,
        ai_mask_engine.LEGACY_METHODOLOGY_V3_PAGED,
    ):
        monkeypatch.setattr(
            ai_mask_config,
            "get_setting",
            lambda key, default=None, value=stored_builtin: value
            if key == ai_mask_engine.PROMPT_METHOD_KEY else default,
        )
        methodology, _ = ai_mask_config.read_ai_mask_prompts()
        assert methodology == ai_mask_engine.DEFAULT_METHODOLOGY

    custom = "自定义规则保留 page.index，绝不迁移"
    monkeypatch.setattr(
        ai_mask_config,
        "get_setting",
        lambda key, default=None: custom if key == ai_mask_engine.PROMPT_METHOD_KEY else default,
    )
    methodology, _ = ai_mask_config.read_ai_mask_prompts()
    assert methodology == custom
