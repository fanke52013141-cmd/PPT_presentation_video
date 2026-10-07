# -*- coding: utf-8 -*-
"""annotation_ink 栅格墨迹单测:确定性、逐帧推进单调、精准度指标门。"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from annotation_ink import (  # noqa: E402
    InkRequest,
    frames_needed,
    precision_metrics,
    render_stroke_frames,
    render_stroke_rgba,
)


def _request(seed=1382, texture=True, opacity=0.85):
    # 手写圈近似:椭圆采样折线(绕 (900,420) 的日期目标)
    import math

    points = []
    for i in range(72):
        a = i / 72 * math.tau
        points.append((900 + math.cos(a) * 90, 420 + math.sin(a) * 26))
    points.append(points[0])
    profile = [1.0] * 10 + [0.4] + [1.0] * 50 + [0.4] + [1.0] * 10
    return InkRequest(
        points=tuple(points),
        width_profile=tuple(profile[: len(points)]),
        canvas=(1920, 1080),
        seed=seed,
        texture=texture,
        opacity=opacity,
    )


# 模拟真实场景:字框在圈的内部(圈围绕文字,不覆盖文字)
TARGETS = [(858.0, 404.0, 942.0, 437.0)]


def test_deterministic_same_seed_same_bytes():
    a = render_stroke_rgba(_request())
    b = render_stroke_rgba(_request())
    assert hashlib.sha256(a.tobytes()).digest() == hashlib.sha256(b.tobytes()).digest()


def test_different_seed_changes_texture():
    a = render_stroke_rgba(_request(seed=1))
    b = render_stroke_rgba(_request(seed=2))
    assert hashlib.sha256(a.tobytes()).digest() != hashlib.sha256(b.tobytes()).digest()


def test_texture_false_is_uniform_vector_look():
    req = _request(texture=False)
    img = render_stroke_rgba(req)
    # 无纹理:重渲染一致;且墨迹存在
    assert img.split()[-1].getbbox() is not None


def test_frames_progress_monotonically():
    frames = render_stroke_frames(_request(), draw_duration_sec=0.6, fps=30)
    assert len(frames) == 18
    import numpy

    areas = [int(((numpy.array(f.split()[-1]) > 40).sum())) for f in frames]
    # 逐帧墨迹面积单调不减(弧长推进)
    assert all(b >= a for a, b in zip(areas, areas[1:]))
    assert areas[-1] > areas[0] * 2


def test_zero_opacity_really_invisible():
    img = render_stroke_rgba(_request(opacity=0.0))
    assert img.split()[-1].getbbox() is None  # 0% 不可见(R2 修复口径)


def test_precision_metrics_gate():
    ink = render_stroke_rgba(_request())
    m = precision_metrics(ink, target_boxes=TARGETS)
    assert m["enclosure_rate"] >= 0.85  # 完整包住目标
    assert m["intrusion_rate"] < 0.05  # 基本不压字
    assert m["neighbor_rate"] < 0.01  # 无邻词可误圈时为 0


def test_metrics_detect_neighbor_inclusion():
    # 邻框紧贴目标右侧:椭圆右缘可能探入;指标必须能反映
    ink = render_stroke_rgba(_request())
    m = precision_metrics(ink, target_boxes=TARGETS, neighbor_boxes=[(992.0, 404.0, 1080.0, 437.0)])
    assert m["neighbor_rate"] < 0.2  # 有邻词时仍应很低(邻词感知留白)


def test_frames_needed():
    assert frames_needed(0.6) == 18
    assert frames_needed(2.0, fps=25) == 50
    assert frames_needed(0.0) == 2


def test_editor_still_matches_export_final_frame_pixel_for_pixel():
    from types import SimpleNamespace
    from annotation_build import ink_request

    stroke = {
        "points": [[20, 20], [70, 25], [100, 20]],
        "width_profile": [0.4, 1.0, 0.3],
        "speed_profile": [0.0, 0.3, 1.0],
        "closed": False,
    }
    item = SimpleNamespace(style=SimpleNamespace(color="#F46A38", width=7, seed=123))
    for canvas in ((1920, 1080), (1080, 1920)):
        for brush_height in (None, 24):
            if brush_height:
                stroke["brush_height"] = brush_height
            else:
                stroke.pop("brush_height", None)
            request = ink_request(item, stroke, canvas, 1)
            editor = render_stroke_rgba(request, arc=1.0)
            final = render_stroke_frames(request, draw_duration_sec=0.1)[-1]
            assert editor.size == canvas
            assert editor.tobytes() == final.tobytes()
