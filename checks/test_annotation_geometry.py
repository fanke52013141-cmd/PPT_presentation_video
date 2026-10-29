# -*- coding: utf-8 -*-
"""annotation_geometry v2 单测:确定性、局部非对称、笔宽曲线、保护区、
分笔时序、退化守卫、采样量上限下收笔完整。"""
from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from annotation_geometry import (  # noqa: E402
    STROKES_VERSION_V2,
    FragmentInput,
    GeometryInputV2,
    build_strokes_v2,
    build_manual_path_stroke,
    _deform_ellipse,
    _pick_template,
)


def _fragment(style="ellipse", polygons=(((800, 400), (960, 400), (960, 445), (800, 445)),), width=5, padding=8, seed=1382):
    return FragmentInput(
        polygons=tuple(tuple((p[0], p[1]) for p in poly) for poly in polygons),
        style_type=style,
        width=width,
        padding=padding,
        seed=seed,
    )


def _build(fragments):
    return build_strokes_v2(GeometryInputV2(fragments=tuple(fragments)))


def test_ellipse_v2_path_deterministic():
    a = _build([_fragment()])
    b = _build([_fragment()])
    assert a == b  # 同输入两次构建完全一致
    stroke = a[0]
    assert stroke["kind"] == "path" and stroke["closed"] is True
    assert len(stroke["points"]) >= 24
    assert stroke["width_profile"] and len(stroke["width_profile"]) == len(stroke["points"])
    assert stroke["speed_profile"] and len(stroke["speed_profile"]) == len(stroke["points"])
    # 弧长均匀:相邻点距近似相等(速度由 speed_profile 表达);
    # 末段是起收笔重叠区(方案 4.3 允许短重叠),不参与均匀性检查
    import math
    dists = [
        math.dist(stroke["points"][i], stroke["points"][i - 1])
        for i in range(1, len(stroke["points"]))
    ]
    avg = sum(dists) / len(dists)
    body = dists[:-1]
    assert all(abs(d - avg) < avg * 0.6 for d in body)


def test_seed_changes_local_asymmetry():
    a = _build([_fragment(seed=1)])
    b = _build([_fragment(seed=2)])
    assert a[0]["points"] != b[0]["points"]  # 局部形态随种子变化
    assert _build([_fragment(seed=1)]) == a  # 同种子可重放


def test_template_variety_for_same_seed_space():
    shapes = {_pick_template(seed)[1] for seed in range(6)}
    assert len(shapes) >= 2  # 模板池实际轮换


def test_deform_respects_text_protection_zone():
    # 目标字框 (800,400)-(960,445);轮廓点不得深入字框内部
    template, _ = _pick_template(7)
    bbox = (800.0, 400.0, 960.0, 445.0)
    points = _deform_ellipse(template, bbox, seed=7, pad=8.0)
    # 椭圆中心线允许进入"框+padding"带,但不得比字框内缩更多
    inner_margin = 4.0
    for x, y in points:
        assert x <= 960 + 8 + 60  # 上界宽松:外缘不失控
        # 中心线到字框中心的距离应 >= 半高的一半(避免横穿文字)
        dy = abs(y - 422.5)
        if abs(x - 880) < 60:  # 只检查横跨文字区段的点
            assert dy >= (445 - 400) / 2 - inner_margin or abs(x - 880) > 80


def test_underline_cross_line_split_with_gaps():
    # 跨行 = 两个片段(resolver 拆分),每片段一笔 + 抬笔间隔
    first = _fragment(style="underline", polygons=(((800, 400), (960, 400), (960, 445), (800, 445)),), seed=11)
    second = _fragment(style="underline", polygons=(((800, 500), (940, 500), (940, 545), (800, 545)),), seed=12)
    strokes = _build([first, second])
    assert len(strokes) == 2
    assert strokes[0]["closed"] is False
    # 分笔时序:第二笔 start_offset > 0(抬笔间隔)
    assert strokes[0]["start_offset_sec"] == 0.0
    assert strokes[1]["start_offset_sec"] > 0.0
    # 收笔上扬:末点高于基线起点方向
    assert strokes[0]["points"][-1][1] < strokes[0]["points"][len(strokes[0]["points"]) // 2][1] + 6


def test_highlighter_constant_width_progress():
    strokes = _build([_fragment(style="highlighter")])
    stroke = strokes[0]
    assert stroke["kind"] == "path" and stroke.get("brush_height")
    assert set(stroke["width_profile"]) == {1.0}  # 扁刷恒定宽
    assert stroke["speed_profile"][0] == 0.0 and stroke["speed_profile"][-1] == 1.0


def test_highlighter_caps_stay_within_selected_word_and_neighbor_padding():
    from dataclasses import replace
    fragment = replace(_fragment(style="highlighter", padding=12), pad_left=1, pad_right=2)
    stroke = _build([fragment])[0]
    radius = stroke["brush_height"] / 2
    assert min(point[0] for point in stroke["points"]) - radius >= 799 - .01
    assert max(point[0] for point in stroke["points"]) + radius <= 962 + .01


def test_width_profile_tapers_ends():
    strokes = _build([_fragment(seed=5)])
    profile = strokes[0]["width_profile"]
    assert profile[0] < 0.75  # 起笔细
    assert profile[-1] < 0.75  # 收笔细
    assert max(profile) > 0.8  # 中段饱满


def test_degenerate_polygon_skipped():
    strokes = _build([_fragment(polygons=(((1, 1), (1, 1), (1, 1), (1, 1)),))])
    assert strokes == ()


def test_long_phrase_sampling_cap_keeps_closure():
    # 超长横线:采样量封顶但收笔点仍在
    wide = ((100, 400), (1900, 400), (1900, 445), (100, 445))
    strokes = _build([_fragment(style="underline", polygons=(wide,))])
    assert len(strokes[0]["points"]) <= 720
    assert strokes[0]["points"][-1][0] > 1800  # 收笔完整


def test_strokes_version_tag():
    assert STROKES_VERSION_V2 == "annotation_strokes_v2"


def test_manual_path_stroke_preserves_user_points_and_style():
    points = [(100, 100), (130, 120), (180, 110)]
    stroke = build_manual_path_stroke(points, style_type="highlighter", width=6)
    assert stroke["points"] == points
    assert stroke["closed"] is False
    assert stroke["speed_profile"] == [0.0, 0.5, 1.0]
    assert stroke["brush_height"] == 24.0
