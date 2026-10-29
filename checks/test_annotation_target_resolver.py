# -*- coding: utf-8 -*-
"""annotation_target_resolver 单测(R2 方案 5.1/8.1):同行合并、跨行拆分、
重复词独立、乱序/重复 token、退化框、layout 过期。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


def test_token_identifiers_do_not_override_ocr_reading_order():
    layout = {"layout_revision": 1, "lines": [{"line_id": "l", "text": "甲乙", "tokens": [
        {"token_id": "z", "char": "甲", "polygon": [[0, 0], [10, 0], [10, 20], [0, 20]]},
        {"token_id": "a", "char": "乙", "polygon": [[12, 0], [22, 0], [22, 20], [12, 20]]},
    ]}]}
    result = resolve_phrase_target(layout=layout, token_ids=["a", "z"])
    assert result["ordered_token_ids"] == ["z", "a"]
    assert result["screen_quote"] == "甲乙"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from annotation_target_resolver import (  # noqa: E402
    TargetResolutionError,
    resolve_phrase_target,
)


def _layout():
    """模拟两张卡片,各有"9月30日";字符 token 带行归属与阅读顺序。"""
    lines = []
    tokens = []
    # 卡片 A:line_a,"报名截止:9月30日"
    for i, ch in enumerate("报名截止:9月30日"):
        tokens.append({
            "token_id": f"ta_{i:02d}", "line_id": "line_a", "text": ch,
            "original_text": ch, "granularity": "char",
            "polygon": [[100 + i * 30, 300], [130 + i * 30, 300], [130 + i * 30, 340], [100 + i * 30, 340]],
        })
    # 卡片 B:line_b,"缴费截止:9月30日"
    for i, ch in enumerate("缴费截止:9月30日"):
        tokens.append({
            "token_id": f"tb_{i:02d}", "line_id": "line_b", "text": ch,
            "original_text": ch, "granularity": "char",
            "polygon": [[100 + i * 30, 500], [130 + i * 30, 500], [130 + i * 30, 540], [100 + i * 30, 540]],
        })
    # 跨行标题:line_t 两段
    for i, ch in enumerate("秋季"):
        tokens.append({
            "token_id": f"tt_{i:02d}", "line_id": "line_t", "text": ch,
            "original_text": ch, "granularity": "char",
            "polygon": [[100 + i * 40, 100], [140 + i * 40, 100], [140 + i * 40, 160], [100 + i * 40, 160]],
        })
    for token in tokens:
        lines.append({"line_id": token["line_id"], "tokens": None})
    return {
        "schema_version": 1, "layout_revision": 3, "lines": [], "corrections": {},
        "_candidates": tokens,
    }


def _with_candidates(layout):

    class _Layout(dict):
        pass

    payload = dict(layout)
    payload["lines"] = []
    result = dict(payload)
    # 直接给 candidate_tokens 打桩不可行;改为构造真实 lines 结构
    by_line = {}
    for token in layout["_candidates"]:
        by_line.setdefault(token["line_id"], []).append(token)
    ordered = sorted(by_line.items(), key=lambda kv: min(tok["polygon"][0][1] for tok in kv[1]))
    result["lines"] = [
        {"line_id": line_id, "text": "".join(tok["text"] for tok in toks), "polygon": toks[0]["polygon"], "tokens": [
            {"token_id": tok["token_id"], "char": tok["text"], "polygon": tok["polygon"]} for tok in toks
        ]}
        for line_id, toks in ordered
    ]
    return result


def _resolve(layout, token_ids, **kwargs):
    return resolve_phrase_target(layout=_with_candidates(layout), token_ids=token_ids, **kwargs)


def test_same_line_consecutive_chars_merge_to_one_phrase():
    layout = _layout()
    # 乱序返回"9月30日"五个字 → 排序后合并为一个片段,圈整个日期
    result = _resolve(layout, ["ta_09", "ta_07", "ta_05", "ta_08", "ta_06"])
    assert result["screen_quote"] == ":9月30日" or result["screen_quote"] == "9月30日"
    # 连续 06..10 → 一个片段
    assert len(result["fragments"]) == 1
    fragment = result["fragments"][0]
    assert fragment["token_ids"] == ["ta_05", "ta_06", "ta_07", "ta_08", "ta_09"]
    assert fragment["text"] == ":9月30日" or fragment["text"] == "9月30日"
    assert len(fragment["polygons"]) == 5  # 保留原始四边形,不合成大框
    assert result["granularity"] == "word"  # 多字合并按词处理


def test_gap_in_middle_splits_fragments():
    layout = _layout()
    # 选中 0,1,2,4(跳过 3)→ 拆两段
    result = _resolve(layout, ["ta_00", "ta_01", "ta_02", "ta_04"])
    assert len(result["fragments"]) == 2
    assert result["fragments"][0]["token_ids"] == ["ta_00", "ta_01", "ta_02"]
    assert result["fragments"][1]["token_ids"] == ["ta_04"]
    assert any(issue["code"] == "multi_fragment" for issue in result["quality_issues"])


def test_same_text_different_cards_stay_independent():
    layout = _layout()
    a = _resolve(layout, ["ta_05", "ta_06", "ta_07", "ta_08", "ta_09"])
    b = _resolve(layout, ["tb_05", "tb_06", "tb_07", "tb_08", "tb_09"])
    assert a["fragments"][0]["line_id"] == "line_a"
    assert b["fragments"][0]["line_id"] == "line_b"
    assert a["screen_quote"] == b["screen_quote"]  # 文字相同但目标独立
    assert a["fragments"][0]["polygons"] != b["fragments"][0]["polygons"]


def test_cross_line_text_splits():
    layout = _layout()
    result = _resolve(layout, ["tt_00", "tt_01", "ta_06", "ta_07"])
    assert len(result["fragments"]) == 2
    assert result["fragments"][0]["line_id"] == "line_t"
    assert result["fragments"][1]["line_id"] == "line_a"


def test_unknown_and_duplicate_tokens_rejected():
    layout = _layout()
    with pytest.raises(TargetResolutionError) as unknown:
        _resolve(layout, ["ta_06", "ghost"])
    assert unknown.value.code == "unknown_token"
    with pytest.raises(TargetResolutionError) as dup:
        _resolve(layout, ["ta_06", "ta_06"])
    assert dup.value.code == "duplicate_token"


def test_stale_layout_revision_rejected():
    layout = _layout()
    with pytest.raises(TargetResolutionError) as stale:
        _resolve(layout, ["ta_06"], expected_layout_revision=99)
    assert stale.value.code == "stale_layout"


def test_correction_text_used_for_screen_quote():
    layout = _layout()
    payload = _with_candidates(layout)
    payload["corrections"] = {"ta_05": {"text": "从", "chars_changed": False}}
    result = resolve_phrase_target(layout=payload, token_ids=["ta_05", "ta_06"])
    assert result["screen_quote"].startswith("从月")
