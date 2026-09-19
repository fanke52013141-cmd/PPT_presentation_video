"""Stage C protocol tests: shared-container geometry rebind and paged VL retry."""
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_mask_assignment import _consolidate_title_regions, _rebind_shared_containers
from ai_mask_semantic_matcher import SemanticVisionMatcher


def _slide():
    return {
        "slide_id": "slide_007",
        "visual_groups": [
            {"id": "group_001", "role": "title"},
            {"id": "group_002", "role": "content_body"},
            {"id": "group_003", "role": "content_body"},
            {"id": "group_004", "role": "content_body"},
        ],
        "narration_beats": [
            {"id": "beat_1", "group_id": "group_001"},
            {"id": "beat_2", "group_id": "group_002"},
            {"id": "beat_3", "group_id": "group_003"},
            {"id": "beat_4", "group_id": "group_004"},
        ],
    }


def _elements_payload():
    def element(eid, x, y, w, h, area):
        return {"element_id": eid, "bbox": {"x": x, "y": y, "w": w, "h": h}, "area": area}

    return {
        "canvas": {"width": 1920, "height": 1080},
        "elements": [
            element("el_title", 90, 71, 432, 53, 6000),
            # 07 实测：公共外框 bbox 覆盖三张卡片，像素填充率约 1.6%。
            element("el_frame", 53, 208, 1815, 685, 19332),
            element("el_card_a", 88, 258, 565, 455, 232727),
            element("el_card_b", 677, 258, 565, 455, 232727),
            element("el_card_c", 1266, 258, 565, 455, 232727),
        ],
        "residual_elements": [],
    }


def test_shared_frame_rebinds_to_title_group():
    payload = {
        "matches": [
            {"group_id": "group_001", "narration_beat_id": "beat_1", "element_ids": ["el_title"], "confidence": 0.95},
            {"group_id": "group_002", "narration_beat_id": "beat_2", "element_ids": ["el_card_a", "el_frame"], "confidence": 0.9},
            {"group_id": "group_003", "narration_beat_id": "beat_3", "element_ids": ["el_card_b"], "confidence": 0.9},
            {"group_id": "group_004", "narration_beat_id": "beat_4", "element_ids": ["el_card_c"], "confidence": 0.9},
        ],
        "unmatched_elements": [],
        "unmatched_groups": [],
        "warnings": [],
    }
    result = _rebind_shared_containers(payload, _elements_payload(), _slide())
    by_group = {item["group_id"]: item["element_ids"] for item in result["matches"]}
    assert by_group["group_001"] == ["el_title", "el_frame"]
    assert by_group["group_002"] == ["el_card_a"]
    assert result["forced_element_owners"]["el_frame"] == "group_001"
    assert any(issue["type"] == "shared_container_rebound" for issue in result["warnings"])
    assert result["unmatched_elements"] == []


def test_dense_or_solitary_components_are_untouched():
    payload = {
        "matches": [
            {"group_id": "group_001", "narration_beat_id": "beat_1", "element_ids": ["el_title"], "confidence": 0.95},
            # 卡片填充率高（0.9），即使包含其他组也不是"框"。
            {"group_id": "group_002", "narration_beat_id": "beat_2", "element_ids": ["el_card_a"], "confidence": 0.9},
            {"group_id": "group_003", "narration_beat_id": "beat_3", "element_ids": ["el_card_b"], "confidence": 0.9},
            {"group_id": "group_004", "narration_beat_id": "beat_4", "element_ids": ["el_card_c"], "confidence": 0.9},
        ],
        "unmatched_elements": [],
        "unmatched_groups": [],
        "warnings": [],
    }
    result = _rebind_shared_containers(payload, _elements_payload(), _slide())
    assert result is payload or result["warnings"] == []
    by_group = {item["group_id"]: item["element_ids"] for item in result["matches"]}
    assert by_group["group_002"] == ["el_card_a"]


def test_frame_without_narrated_title_group_is_left_alone():
    slide = _slide()
    slide["visual_groups"][0]["role"] = "content_body"
    payload = {
        "matches": [
            {"group_id": "group_001", "narration_beat_id": "beat_1", "element_ids": ["el_title"], "confidence": 0.95},
            {"group_id": "group_002", "narration_beat_id": "beat_2", "element_ids": ["el_card_a", "el_frame"], "confidence": 0.9},
            {"group_id": "group_003", "narration_beat_id": "beat_3", "element_ids": ["el_card_b"], "confidence": 0.9},
        ],
        "unmatched_elements": [],
        "unmatched_groups": [],
        "warnings": [],
    }
    result = _rebind_shared_containers(payload, _elements_payload(), slide)
    by_group = {item["group_id"]: item["element_ids"] for item in result["matches"]}
    assert by_group["group_002"] == ["el_card_a", "el_frame"]


def test_rebind_survives_title_consolidation_order():
    payload = {
        "matches": [
            {"group_id": "group_001", "narration_beat_id": "beat_1", "element_ids": ["el_title"], "confidence": 0.95},
            {"group_id": "group_002", "narration_beat_id": "beat_2", "element_ids": ["el_card_a", "el_frame"], "confidence": 0.9},
            {"group_id": "group_003", "narration_beat_id": "beat_3", "element_ids": ["el_card_b"], "confidence": 0.9},
            {"group_id": "group_004", "narration_beat_id": "beat_4", "element_ids": ["el_card_c"], "confidence": 0.9},
        ],
        "unmatched_elements": [],
        "unmatched_groups": [],
        "warnings": [],
    }
    regions = {
        "main_title": {"x": 0, "y": 60, "w": 1920, "h": 100},
        "subtitle": {"x": 0, "y": 160, "w": 1920, "h": 60},
    }
    consolidated = _consolidate_title_regions(payload, _elements_payload(), _slide(), regions)
    rebound = _rebind_shared_containers(consolidated, _elements_payload(), _slide())
    title = next(item for item in rebound["matches"] if item["group_id"] == "group_001")
    assert "el_title" in title["element_ids"]
    assert "el_frame" in title["element_ids"]
    assert rebound["forced_element_owners"]["el_frame"] == "group_001"


class _FakeCompletions:
    def __init__(self, contents):
        self.contents = list(contents)
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        content = self.contents.pop(0)
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
        return response


def test_match_page_retries_once_on_truncated_json():
    with tempfile.TemporaryDirectory() as temp:
        image_path = Path(temp) / "image.png"
        Image.new("RGB", (1920, 1080), "white").save(image_path)
        objects = [{
            "object_id": "object_001",
            "type": "card",
            "element_ids": ["el_1"],
            "bbox": {"x": 10, "y": 10, "w": 100, "h": 50},
            "center": {"x": 60, "y": 35},
        }]
        elements = [{"element_id": "el_1", "bbox": {"x": 10, "y": 10, "w": 100, "h": 50}}]
        good = json.dumps({"matches": [{
            "group_id": "group_002",
            "narration_beat_id": "beat_2",
            "object_ids": ["object_001"],
            "confidence": 0.9,
            "reason": "卡片",
        }]}, ensure_ascii=False)
        client = SimpleNamespace(chat=SimpleNamespace(completions=_FakeCompletions(['{\n  "matches": [ {"group_id": "g', good])))
        capabilities = SimpleNamespace(
            clean_json_markdown=lambda text: text,
        )
        base_module = SimpleNamespace(_is_timeout=lambda caps, exc: False, AI_MASK_VISION_TIMEOUT_SEC=60)
        matcher = SemanticVisionMatcher()
        value = matcher._match_page(
            client=client,
            capabilities=capabilities,
            base_module=base_module,
            model="vision-test",
            vendor_options={},
            settings={"llm_temperature": 0.1},
            prompt="p",
            clean_url="data:image/png;base64,x",
            slide_context={"slide_id": "slide_010"},
            image_path=image_path,
            page=objects,
            page_index=1,
            page_count=2,
            objects=objects,
            elements=elements,
        )
        assert client.chat.completions.calls == 2
        assert value["matches"][0]["element_ids"] == ["el_1"]
        assert value["matches"][0]["object_ids"] == ["object_001"]


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
