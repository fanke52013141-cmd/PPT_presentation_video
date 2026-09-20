"""Stage C/D protocol tests: shared-container rebind, paged VL retry, island rows, gap completion."""
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_mask_assignment import _complete_component_coverage, _consolidate_title_regions, _rebind_shared_containers
import ai_mask_semantic_matcher as sm
from ai_mask_semantic_matcher import _semantic_objects


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


def test_request_object_batch_retries_once_on_truncated_json():
    with tempfile.TemporaryDirectory() as temp:
        image_path = Path(temp) / "image.png"
        Image.new("RGB", (1920, 1080), "white").save(image_path)
        batch = [{
            "object_id": "object_001",
            "type": "card",
            "element_ids": ["el_1"],
            "bbox": {"x": 10, "y": 10, "w": 100, "h": 50},
            "center": {"x": 60, "y": 35},
        }]
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
        value = sm._request_object_batch(
            capabilities,
            base_module,
            client,
            model="vision-test",
            settings={"llm_temperature": 0.1},
            vendor_options={},
            prompt="p",
            clean_bytes=b"",
            image_path=image_path,
            slide={"slide_id": "slide_010"},
            batch=batch,
            index=0,
            total=2,
            atomic=True,
        )
        assert client.chat.completions.calls == 2
        assert value["matches"][0]["object_ids"] == ["object_001"]


def _grid_elements():
    def element(eid, x, y, w, h, area):
        return {
            "element_id": eid,
            "bbox": {"x": x, "y": y, "w": w, "h": h},
            "raw_bbox": {"x": x, "y": y, "w": w, "h": h},
            "area": area,
        }

    glyphs = [element(f"el_g{i:02d}", 90 + i * 45, 62, 40, 44, 320) for i in range(6)]
    # 10_dense_20 实测：首行 5 张 334x151 卡片高 151 ≤ 0.14*1080，曾被并入 rank-0 文本行。
    cards = [element(f"el_card_{i:02d}", 100 + i * 346, 200, 334, 151, 50250) for i in range(4)]
    return glyphs + cards


def test_card_row_is_not_merged_into_text_line():
    objects = _semantic_objects(_grid_elements(), 1920, 1080)
    by_type = {}
    for obj in objects:
        by_type.setdefault(obj["type"], []).append(obj)
    assert len(by_type.get("text_line_or_label", [])) == 1
    title_line = by_type["text_line_or_label"][0]
    assert all(eid.startswith("el_g") for eid in title_line["element_ids"])
    cards = sorted(by_type["container_or_illustration"], key=lambda obj: obj["bbox"]["x"])
    assert [obj["element_ids"] for obj in cards] == [
        ["el_card_00"], ["el_card_01"], ["el_card_02"], ["el_card_03"],
    ]


def test_gap_completion_prefers_nearest_owned_member_box():
    def element(eid, x, y, w, h, area):
        return {
            "element_id": eid,
            "bbox": {"x": x, "y": y, "w": w, "h": h},
            "raw_bbox": {"x": x, "y": y, "w": w, "h": h},
            "area": area,
            "mask_rle": {"encoding": "row_runs_v1", "width": 1920, "height": 1080, "runs": [[y, x, x + w]]},
        }

    elements_payload = {
        "canvas": {"width": 1920, "height": 1080},
        "elements": [
            element("el_a_block", 100, 200, 540, 500, 65000),
            element("el_b_dominant", 936, 270, 294, 383, 65000),
            element("el_b_side", 689, 340, 60, 62, 2600),
            # 未归属碎片：距 A 包络 48px，距 B 包络 181px，但紧贴 B 自己的成员 3px。
            element("el_stray", 755, 270, 60, 60, 2600),
        ],
        "residual_elements": [],
    }
    payload = {
        "matches": [
            {"group_id": "group_002", "narration_beat_id": "beat_2", "element_ids": ["el_a_block"], "confidence": 0.97},
            {"group_id": "group_003", "narration_beat_id": "beat_3", "element_ids": ["el_b_dominant", "el_b_side"], "confidence": 0.97},
        ],
        "unmatched_elements": [],
        "unmatched_groups": [],
        "warnings": [],
    }
    result = _complete_component_coverage(payload, elements_payload, slide=None)
    owner = {
        element_id: item["group_id"]
        for item in result["matches"]
        for element_id in item.get("element_ids", []) or []
    }
    assert owner["el_stray"] == "group_003"


def test_moves_loop_rebinds_to_closer_envelope_despite_adjacent_member():
    # 08 复现：VL 把正文碎片错绑到 group_002，而 group_002 恰好拥有一个紧贴该
    # 碎片的成员框。若改绑判定纳入"当前拥有者的成员框距离"，错绑会自我保护、永不
    # 纠正；此路径必须只看冻结包络——group_003 的卡片包络更近，应改绑过去。
    def element(eid, x, y, w, h, area):
        return {
            "element_id": eid,
            "bbox": {"x": x, "y": y, "w": w, "h": h},
            "raw_bbox": {"x": x, "y": y, "w": w, "h": h},
            "area": area,
            "mask_rle": {"encoding": "row_runs_v1", "width": 1920, "height": 1080, "runs": [[y, x, x + w]]},
        }

    elements_payload = {
        "canvas": {"width": 1920, "height": 1080},
        "elements": [
            element("el_g2_card", 100, 200, 500, 450, 225000),
            # chip 远离主导卡片（超出包络吸收半径），却紧贴错绑的 el_body。
            # 只有"当前拥有者成员框距离"会看到它——用它做改绑判定就会自我保护。
            element("el_g2_chip", 700, 285, 55, 50, 1600),
            element("el_body", 760, 280, 40, 40, 1600),
            element("el_g3_card", 820, 200, 500, 450, 225000),
        ],
        "residual_elements": [],
    }
    payload = {
        "matches": [
            {"group_id": "group_002", "narration_beat_id": "beat_2", "element_ids": ["el_g2_card", "el_g2_chip", "el_body"], "confidence": 0.97},
            {"group_id": "group_003", "narration_beat_id": "beat_3", "element_ids": ["el_g3_card"], "confidence": 0.97},
        ],
        "unmatched_elements": [],
        "unmatched_groups": [],
        "warnings": [],
    }
    result = _complete_component_coverage(payload, elements_payload, slide=None)
    owner = {
        element_id: item["group_id"]
        for item in result["matches"]
        for element_id in item.get("element_ids", []) or []
    }
    assert owner["el_body"] == "group_003"


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
