"""W3 checks: atomic semantic objects, budgeted batches, deterministic merge.

The pre-v4 matcher merged objects down to ``(beats + 3)`` spatial clusters and
dropped everything past the 120th object, which made it impossible for a slide
with many narrated groups to give each group its own candidate.  These tests pin
the new contract: every atomic object keeps a stable ID, a slide is split into
budgeted requests, and a cross-batch ownership conflict is resolved by evidence
rather than by which answer arrived last.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

import ai_mask_config
import ai_mask_engine
import ai_mask_semantic_matcher as sm

CANVAS = (1920, 1080)


def _element(element_id: str, x: int, y: int, w: int = 6, h: int = 6) -> dict[str, Any]:
    return {
        "element_id": element_id,
        "bbox": {"x": x, "y": y, "w": w, "h": h},
        "raw_bbox": {"x": x, "y": y, "w": w, "h": h},
        "center": {"x": x + w / 2, "y": y + h / 2},
        "area": w * h,
        "mask_rle": {
            "encoding": "row_runs_v1",
            "width": CANVAS[0],
            "height": CANVAS[1],
            "runs": [[row, x, x + w] for row in range(y, y + h)],
        },
    }


def _grid_elements(count: int) -> list[dict[str, Any]]:
    elements = []
    for index in range(count):
        row, column = divmod(index, 10)
        elements.append(_element(f"el_auto_{index + 1:03d}", 40 + column * 150, 40 + row * 40))
    return elements


def _settings(**overrides: Any) -> dict[str, Any]:
    return ai_mask_engine.normalize_settings(overrides)


def test_every_atomic_object_keeps_a_stable_id_without_a_truncation_cap() -> None:
    elements = _grid_elements(130)
    objects = sm._semantic_objects(elements, *CANVAS)

    assert len(objects) == 130, "objects past the old 120 cap must survive"
    ids = [obj["object_id"] for obj in objects]
    assert ids == [f"obj_{index:03d}" for index in range(1, 131)]
    assert len(set(ids)) == len(ids)
    # IDs are a function of geometry, so a re-run cannot silently renumber them.
    again = sm._semantic_objects(list(reversed(elements)), *CANVAS)
    assert [obj["object_id"] for obj in again] == ids
    assert all(len(obj["element_ids"]) == 1 for obj in objects)


def test_batches_stay_inside_the_request_budget_and_report_the_remainder() -> None:
    objects = sm._semantic_objects(_grid_elements(60), *CANVAS)

    batches, beyond = sm._plan_object_batches(objects, _settings())
    assert [len(batch) for batch in batches] == [12, 12, 12, 12]
    assert len(beyond) == 12
    sent = [obj["object_id"] for batch in batches for obj in batch]
    assert sent == [obj["object_id"] for obj in objects[:48]]

    tight = sm._plan_object_batches(objects, _settings(vision_object_batch_size=5, vision_max_requests=2))
    assert [len(batch) for batch in tight[0]] == [5, 5]
    assert len(tight[1]) == 50

    oversized = _settings(vision_object_batch_size=0, vision_max_requests=-3)
    assert (oversized["vision_object_batch_size"], oversized["vision_max_requests"]) == (1, 1)
    cramped = sm._plan_object_batches(objects, oversized)
    assert [len(batch) for batch in cramped[0]] == [1]
    assert len(cramped[1]) == 59
    # A settings dict that never went through normalisation still gets defaults.
    junk = sm._plan_object_batches(
        objects, {"vision_object_batch_size": "abc", "vision_max_requests": None}
    )
    assert junk == sm._plan_object_batches(objects, _settings())


def _match(group_id: str, object_ids: list[str], confidence: float, beat: str = "") -> dict[str, Any]:
    return {
        "group_id": group_id,
        "narration_beat_id": beat or f"beat_{group_id}",
        "object_ids": object_ids,
        "element_ids": [],
        "confidence": confidence,
        "reason": "test",
    }


def test_cross_batch_conflict_is_decided_by_confidence_not_arrival_order() -> None:
    groups = ["g_a", "g_b"]
    # The weaker claim arrives first and again last; the stronger one must win.
    merged = sm._merge_batch_results(
        [
            (0, {"slide_id": "s", "matches": [_match("g_b", ["obj_002"], 0.6)], "unmatched_objects": []}),
            (1, {"slide_id": "s", "matches": [_match("g_a", ["obj_002"], 0.91)], "unmatched_objects": ["obj_002"]}),
            (2, {"slide_id": "s", "matches": [_match("g_b", ["obj_002"], 0.5)], "unmatched_objects": []}),
        ],
        groups,
    )
    by_group = {item["group_id"]: item for item in merged["matches"]}
    assert by_group["g_a"]["object_ids"] == ["obj_002"]
    assert "g_b" not in by_group, "the losing match has no object left to claim"
    assert merged["unmatched_groups"] == ["g_b"]
    assert merged["vision_batches"]["ownership_conflicts"] == [
        {
            "object_id": "obj_002",
            "kept_group_id": "g_a",
            "competing_group_ids": ["g_b"],
            "decided_by": "confidence_then_group_order_then_batch",
        }
    ]
    # An object matched in any batch is no longer unmatched in another.
    assert "obj_002" not in merged["unmatched_objects"]


def test_equal_confidence_falls_back_to_group_order_then_batch_index() -> None:
    def merged_with(order: list[tuple[int, str]]) -> dict[str, Any]:
        return sm._merge_batch_results(
            [
                (batch, {"matches": [_match(group, ["obj_001"], 0.8)], "unmatched_objects": []})
                for batch, group in order
            ],
            ["g_first", "g_second"],
        )

    def ownership(merged: dict[str, Any]) -> list[tuple[str, list[str]]]:
        return [
            (str(item["group_id"]), list(item["object_ids"]))
            for item in merged["matches"]
            if item["object_ids"]
        ]

    first_wins = merged_with([(0, "g_first"), (1, "g_second")])
    reversed_wins = merged_with([(1, "g_second"), (0, "g_first")])
    assert ownership(first_wins) == [("g_first", ["obj_001"])]
    # Only the batch diagnostics may differ; the ownership decision may not.
    assert ownership(first_wins) == ownership(reversed_wins)


def test_groups_collect_objects_from_several_batches_and_empty_matches_drop() -> None:
    merged = sm._merge_batch_results(
        [
            (0, {"matches": [_match("g_a", ["obj_001"], 0.9)], "unmatched_objects": ["obj_002"],
                 "warnings": [{"type": "w", "group_id": "g_a", "object_ids": ["obj_001", "obj_002"]}]}),
            (1, {"matches": [_match("g_a", ["obj_003"], 0.8), _match("g_b", [], 0.77)],
                 "unmatched_objects": ["obj_002"],
                 "warnings": [{"type": "w", "group_id": "g_a", "object_ids": ["obj_002", "obj_001"]}]}),
        ],
        ["g_a", "g_b"],
    )
    by_group = {item["group_id"]: item for item in merged["matches"]}
    assert by_group["g_a"]["object_ids"] == ["obj_001", "obj_003"]
    assert by_group["g_a"]["merged_from_batches"] == [0, 1]
    assert by_group["g_a"]["confidence"] == 0.9
    assert "g_b" not in by_group, "an object-less match must not survive the merge"
    assert merged["unmatched_groups"] == ["g_b"]
    assert merged["unmatched_objects"] == ["obj_002"]
    assert len(merged["warnings"]) == 1, "identical warnings merge across batches"


def test_objects_beyond_the_budget_are_reported_as_unmatched() -> None:
    beyond = [{"object_id": "obj_049"}, {"object_id": "obj_050"}]
    merged = sm._merge_batch_results(
        [(0, {"matches": [_match("g_a", ["obj_001"], 0.9)], "unmatched_objects": []})],
        ["g_a"],
        beyond,
    )
    assert merged["unmatched_objects"] == ["obj_049", "obj_050"]
    assert merged["vision_batches"]["beyond_budget_object_ids"] == ["obj_049", "obj_050"]


def test_merge_rejects_ids_the_model_was_never_shown() -> None:
    merged = sm._merge_batch_results(
        [(0, {"matches": [
            _match("g_ghost", ["obj_001"], 0.95),
            _match("g_a", ["obj_999"], 0.9),
            _match("g_a", ["obj_001", "obj_999"], 0.8),
        ]})],
        ["g_a", "g_b"],
        None,
        {"obj_001"},
    )

    assert [match["group_id"] for match in merged["matches"]] == ["g_a"]
    assert merged["matches"][0]["object_ids"] == ["obj_001"]
    assert merged["vision_batches"]["rejected_group_ids"] == ["g_ghost"]
    assert merged["vision_batches"]["rejected_object_ids"] == ["obj_999"]
    # The real group the model never answered stays visible as an omission.
    assert merged["unmatched_groups"] == ["g_b"]


class _FakeCompletions:
    def __init__(self, handler: Any) -> None:
        self.handler = handler
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.handler(kwargs)


class _FakeClient:
    def __init__(self, handler: Any) -> None:
        self.chat = SimpleNamespace(completions=_FakeCompletions(handler))
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _FakeCapabilities:
    def __init__(self, handler: Any) -> None:
        self.handler = handler
        self.clients: list[_FakeClient] = []

    def clean_json_markdown(self, content: str) -> str:
        return content

    def get_setting(self, key: str) -> str:
        return {
            "llm_api_key": "test-key",
            "llm_base_url": "https://example.invalid/v1",
            "llm_provider": "volcengine",
            "vision_model": "gpt-4o",
            "llm_model": "vision-model",
        }.get(key, "")

    def get_openai_client(self, **_kwargs: Any) -> _FakeClient:
        client = _FakeClient(self.handler)
        self.clients.append(client)
        return client

    def step2_llm_vendor_options(self, *_args: Any) -> dict[str, Any]:
        return {}


def _response(payload: dict[str, Any]) -> Any:
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])


def _slide(object_groups: int) -> dict[str, Any]:
    groups = [{"id": f"g_{index}", "role": "content_body"} for index in range(object_groups)]
    return {
        "slide_id": "slide_001",
        "main_title": "标题",
        "subtitle": "",
        "core_message": "",
        "body_content": [],
        "visual_groups": groups,
        "narration_beats": [
            {"id": f"beat_{group['id']}", "group_id": group["id"], "spoken_text": "讲解"}
            for group in groups
        ],
    }


def _write_slide_image(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    (path.parent / "auto_mask").mkdir(parents=True, exist_ok=True)
    Image.new("RGB", CANVAS, "white").save(path)


def test_call_splits_objects_into_budgeted_requests_and_merges_them(tmp_path: Path) -> None:
    _write_slide_image(tmp_path / "visual_draft.png")
    elements = _grid_elements(30)
    sent: list[dict[str, Any]] = []
    systems: list[str] = []
    user_parts: list[list[dict[str, Any]]] = []

    def handler(kwargs: dict[str, Any]) -> Any:
        payload = json.loads(kwargs["messages"][1]["content"][0]["text"])
        sent.append(payload)
        systems.append(kwargs["messages"][0]["content"])
        user_parts.append(kwargs["messages"][1]["content"])
        ids = [obj["object_id"] for obj in payload["semantic_objects"]]
        return _response({
            "slide_id": "slide_001",
            "matches": [_match("g_0", ids[:1], 0.9)],
            "unmatched_objects": ids[1:],
        })

    capabilities = _FakeCapabilities(handler)
    result = sm.semantic_vision_matcher(
        capabilities,
        SimpleNamespace(run_dir=str(tmp_path)),
        _slide(3),
        elements,
        tmp_path / "visual_draft.png",
        tmp_path / "auto_mask" / "candidate_overlay.png",
        "methodology",
        "output structure",
        _settings(),
    )

    assert len(sent) == 3, "30 atomic objects at 12 per request need three requests"
    assert [payload["batch"] for payload in sent] == [
        {"index": 1, "total": 3}, {"index": 2, "total": 3}, {"index": 3, "total": 3},
    ]
    seen_ids = [obj["object_id"] for payload in sent for obj in payload["semantic_objects"]]
    assert len(seen_ids) == 30 and len(set(seen_ids)) == 30, "each object is asked about exactly once"
    assert all("cluster_member_count" not in obj for payload in sent for obj in payload["semantic_objects"])
    assert "其它批次" in sent[0]["instruction"]
    assert systems[0] == systems[1] == systems[2] == ai_mask_config.compose_ai_mask_full_prompt(
        "methodology", "output structure"
    )
    images_per_request = [
        sum(1 for part in parts if part.get("type") == "image_url") for parts in user_parts
    ]
    assert images_per_request == [13, 13, 7], "image_full once, then this batch's crops"
    crop_labels = [
        [part["text"] for part in parts if part.get("type") == "text"][2:] for parts in user_parts
    ]
    assert crop_labels[0] == [
        f"{obj['object_id']}（类型:{obj['type']}）：此对象的切片图。" for obj in sent[0]["semantic_objects"]
    ]
    assert result["vision_batches"]["request_count"] == 3
    assert result["matches"][0]["object_ids"] == ["obj_001", "obj_013", "obj_025"]
    assert result["matches"][0]["merged_from_batches"] == [0, 1, 2]
    assert result["matches"][0]["element_ids"] == ["el_auto_001", "el_auto_013", "el_auto_025"]
    diagnostics = json.loads((tmp_path / "auto_mask" / "semantic_objects.json").read_text(encoding="utf-8"))
    assert diagnostics["version"] == "semantic_objects_v3_atomic"
    assert diagnostics["pre_cluster_object_count"] == 30
    assert [batch["object_ids"] for batch in diagnostics["request_batches"]] == [
        [obj["object_id"] for obj in sent[index]["semantic_objects"]] for index in range(3)
    ]
    assert diagnostics["beyond_budget_object_ids"] == []
    assert diagnostics["vision_model"] == "vision-model"
    assert len(diagnostics["prompt_sha256"]) == 64
    assert capabilities.clients[0].closed is True


def test_call_rollback_still_merges_objects_into_one_clustered_request(tmp_path: Path) -> None:
    _write_slide_image(tmp_path / "visual_draft.png")
    elements = _grid_elements(30)
    sent: list[dict[str, Any]] = []

    def handler(kwargs: dict[str, Any]) -> Any:
        payload = json.loads(kwargs["messages"][1]["content"][0]["text"])
        sent.append(payload)
        return _response({"slide_id": "slide_001", "matches": [], "unmatched_objects": []})

    result = sm.semantic_vision_matcher(
        _FakeCapabilities(handler),
        SimpleNamespace(run_dir=str(tmp_path)),
        _slide(3),
        elements,
        tmp_path / "visual_draft.png",
        tmp_path / "auto_mask" / "candidate_overlay.png",
        "methodology",
        "output structure",
        _settings(atomic_object_matching=False),
    )

    assert len(sent) == 1
    assert len(sent[0]["semantic_objects"]) == 6, "three beats plus three keeps the old cap"
    assert "batch" not in sent[0]
    assert all("cluster_member_count" in obj for obj in sent[0]["semantic_objects"])
    diagnostics = json.loads((tmp_path / "auto_mask" / "semantic_objects.json").read_text(encoding="utf-8"))
    assert diagnostics["version"] == "semantic_objects_v2_clustered"
    assert diagnostics["pre_cluster_object_count"] == 30
    assert result["matches"] == []


def test_call_raises_when_the_first_batch_fails_so_the_engine_falls_back(tmp_path: Path) -> None:
    _write_slide_image(tmp_path / "visual_draft.png")

    def handler(_kwargs: dict[str, Any]) -> Any:
        raise RuntimeError("upstream unavailable")

    with pytest.raises(RuntimeError):
        sm.semantic_vision_matcher(
            _FakeCapabilities(handler),
            SimpleNamespace(run_dir=str(tmp_path)),
            _slide(3),
            _grid_elements(30),
            tmp_path / "visual_draft.png",
            tmp_path / "auto_mask" / "candidate_overlay.png",
            "methodology",
            "output structure",
            _settings(),
        )


def test_call_keeps_earlier_batches_when_a_later_one_fails(tmp_path: Path) -> None:
    _write_slide_image(tmp_path / "visual_draft.png")

    def handler(kwargs: dict[str, Any]) -> Any:
        payload = json.loads(kwargs["messages"][1]["content"][0]["text"])
        index = payload["batch"]["index"]
        if index == 3:
            raise RuntimeError("batch three is unavailable")
        ids = [obj["object_id"] for obj in payload["semantic_objects"]]
        return _response({
            "slide_id": "slide_001",
            "matches": [_match(f"g_{index}", ids[:1], 0.9)],
            "unmatched_objects": ids[1:],
        })

    result = sm.semantic_vision_matcher(
        _FakeCapabilities(handler),
        SimpleNamespace(run_dir=str(tmp_path)),
        _slide(3),
        _grid_elements(30),
        tmp_path / "visual_draft.png",
        tmp_path / "auto_mask" / "candidate_overlay.png",
        "methodology",
        "output structure",
        _settings(),
    )
    assert result["vision_batches"]["request_count"] == 3
    assert result["vision_batches"]["failed_batch_indices"] == [2]
    assert result["vision_batches"]["failed_batch_error_type"] == "RuntimeError"
    assert len(result["matches"]) == 2


def test_call_rejects_a_hallucinated_group_and_object_id(tmp_path: Path) -> None:
    _write_slide_image(tmp_path / "visual_draft.png")

    def handler(kwargs: dict[str, Any]) -> Any:
        payload = json.loads(kwargs["messages"][1]["content"][0]["text"])
        ids = [obj["object_id"] for obj in payload["semantic_objects"]]
        if payload["batch"]["index"] > 1:
            return _response({"slide_id": "slide_001", "unmatched_objects": ids})
        return _response({
            "slide_id": "slide_001",
            "matches": [
                _match("g_invented", ids[:1], 0.99),
                _match("g_0", ["obj_777"], 0.95),
                _match("g_0", ids[:1], 0.8),
            ],
            "unmatched_objects": ids[1:],
        })

    result = sm.semantic_vision_matcher(
        _FakeCapabilities(handler),
        SimpleNamespace(run_dir=str(tmp_path)),
        _slide(3),
        _grid_elements(30),
        tmp_path / "visual_draft.png",
        tmp_path / "auto_mask" / "candidate_overlay.png",
        "methodology",
        "output structure",
        _settings(),
    )

    assert [match["group_id"] for match in result["matches"]] == ["g_0"]
    assert result["matches"][0]["object_ids"] == ["obj_001"]
    assert result["matches"][0]["element_ids"] == ["el_auto_001"]
    assert result["vision_batches"]["rejected_group_ids"] == ["g_invented"]
    assert result["vision_batches"]["rejected_object_ids"] == ["obj_777"]
    assert sorted(result["unmatched_groups"]) == ["g_1", "g_2"]


def test_call_rejects_a_non_json_first_answer(tmp_path: Path) -> None:
    _write_slide_image(tmp_path / "visual_draft.png")

    class _BadCompletions:
        def create(self, **_kwargs: Any) -> Any:
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="我不是 JSON"))]
            )

    capabilities = _FakeCapabilities(lambda _kwargs: None)
    bad_client = _FakeClient(lambda _kwargs: None)
    bad_client.chat = SimpleNamespace(completions=_BadCompletions())
    capabilities.get_openai_client = lambda **_kwargs: bad_client

    with pytest.raises(ValueError):
        sm.semantic_vision_matcher(
            capabilities,
            SimpleNamespace(run_dir=str(tmp_path)),
            _slide(3),
            _grid_elements(30),
            tmp_path / "visual_draft.png",
            tmp_path / "auto_mask" / "candidate_overlay.png",
            "methodology",
            "output structure",
            _settings(),
        )


def test_stored_v3_builtin_migrates_but_a_custom_prompt_stays(monkeypatch, tmp_path: Path) -> None:
    stored = {
        ai_mask_engine.PROMPT_METHOD_KEY: ai_mask_engine.LEGACY_METHODOLOGY_V3,
        ai_mask_engine.PROMPT_OUTPUT_KEY: ai_mask_engine.LEGACY_OUTPUT_STRUCTURE_V3,
    }
    monkeypatch.setattr(ai_mask_config, "get_setting", lambda key, default="": stored.get(key, default))
    methodology, output_structure = ai_mask_config.read_ai_mask_prompts()
    assert "ai_mask_semantic_mapping_v4" in methodology
    assert "未出现在本批输入中的对象一律不要写" in output_structure

    custom = "我自己的归属规则，绝不自动覆盖"
    stored.update({
        ai_mask_engine.PROMPT_METHOD_KEY: custom,
        ai_mask_engine.PROMPT_OUTPUT_KEY: custom,
    })
    methodology, output_structure = ai_mask_config.read_ai_mask_prompts()
    assert methodology == custom and output_structure == custom
