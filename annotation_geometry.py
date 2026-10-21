# -*- coding: utf-8 -*-
"""勾画笔迹生成 v2:手写质感(第二轮优化方案 4.1–4.5)。

模型:目标几何(精确包围文字)与笔迹外观(受限手写形态)两层独立。

- 中心线:人工调形的手写圈模板(非对称:左右弧度不同、顶部略偏、
  起收笔位置变化)+ 横线/荧光的受限轨迹;形变在目标局部坐标完成。
- 笔宽曲线:width_profile 沿弧长定义粗细(起收笔细、中段粗);
  由共享采样器(annotation_playback)生成轮廓,编辑/导出同一实现。
- 行笔节奏:每笔独立 start_offset/draw_frac;跨行按阅读顺序分笔,
  笔间抬笔间隔;起笔稍缓、主体快、收笔减速(speed_profile)。
- 种子只在创建/显式换笔迹时变化;同 (样式, 多边形, seed) 输出逐字节一致。
- 文字保护区:轨迹最内侧不穿字(向内压缩下限),最外侧不圈邻词
  (padding 上限由调用方按邻词距离约束;本层只保证模板收敛于目标框)。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

__all__ = [
    "STROKES_VERSION_V2",
    "STROKE_GAP_SEC",
    "GeometryInputV2",
    "FragmentInput",
    "build_strokes_v2",
    "build_manual_path_stroke",
]

STROKES_VERSION_V2 = "annotation_strokes_v2"
# 跨行分笔的默认抬笔间隔(秒);时间轴层可按语块剩余时间收紧
STROKE_GAP_SEC = 0.09

# 采样:每 6px 一个点,单笔上限 720(保证长句收笔完整)
SAMPLE_STEP_PX = 6.0
MAX_SAMPLES = 720


def _seeded(seed: int):
    state = (int(seed) & 0x7FFFFFFF) or 1

    def rand():
        nonlocal state
        state = (state * 48271) % 0x7FFFFFFF
        return state / 0x7FFFFFFF

    return rand


# ---------------------------------------------------------------- 手写圈模板
# 模板坐标:单位正方形 [0,1]^2 的闭合中心线采样(起笔在右下,逆时针)。
# 非对称已人工调形:左弧半径 > 右弧、顶部压扁、起收笔处小缺口 + 轻微重叠。
# 生成方式:手调三次贝塞尔控制点(非逐点随机噪声),来源标注在注释。

def _sample_bezier_chain(chain: Sequence[Tuple[Tuple[float, float], Tuple[float, float], Tuple[float, float], Tuple[float, float]]], closed: bool, seed: int) -> List[Tuple[float, float]]:
    rand = _seeded(seed)
    points: List[Tuple[float, float]] = []
    approx_len = 0.0
    for p0, p1, p2, p3 in chain:
        approx_len += math.dist(p0, p1) / 2 + math.dist(p1, p2) / 2 + math.dist(p2, p3) / 2
    total_steps = max(48, min(MAX_SAMPLES, int(approx_len / 0.02)))
    steps_per_seg = max(8, total_steps // len(chain))
    for p0, p1, p2, p3 in chain:
        for i in range(steps_per_seg):
            t = i / steps_per_seg
            mt = 1 - t
            x = mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0]
            y = mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1]
            points.append((x, y))
    if closed:
        # 起收笔:小幅缺口(约 8° 弧长)+ 收笔回勾重叠,由固定种子决定方向
        overlap = 2 + int(rand() * 3)
        points.extend(points[1 : 1 + overlap])
        gap_trim = max(1, int(len(points) * 0.02))
        points = points[:-gap_trim]
    # 弧长均匀重采样(速度积分的基础)
    return _resample_uniform(points, closed)


def _resample_uniform(points: List[Tuple[float, float]], closed: bool, step: float = 0.02) -> List[Tuple[float, float]]:
    if len(points) < 2:
        return points
    lengths = [0.0]
    for i in range(1, len(points)):
        lengths.append(lengths[-1] + math.dist(points[i], points[i - 1]))
    total = lengths[-1]
    if total <= 0:
        return points
    target_count = max(32, min(MAX_SAMPLES, int(total / step)))
    # 周长均分:闭合曲线收尾段与其余段等距
    step = total / target_count
    result: List[Tuple[float, float]] = []
    seg = 0
    for k in range(target_count):
        d = k * step
        while seg < len(lengths) - 2 and lengths[seg + 1] < d:
            seg += 1
        span = lengths[seg + 1] - lengths[seg]
        t = (d - lengths[seg]) / span if span > 0 else 0.0
        x = points[seg][0] + (points[seg + 1][0] - points[seg][0]) * t
        y = points[seg][1] + (points[seg + 1][1] - points[seg][1]) * t
        result.append((x, y))
    if closed:
        result.append(result[0])
    else:
        result.append(points[-1])
    return result


# 圈模板 A:均衡手写圈(来源:控制点手调模板,非笔迹采样)
_TEMPLATE_ELLIPSE_A = _sample_bezier_chain(
    [
        ((0.82, 0.90), (1.04, 0.74), (1.03, 0.30), (0.74, 0.10)),
        ((0.74, 0.10), (0.46, -0.08), (0.02, 0.14), (-0.035, 0.52)),
        ((-0.035, 0.52), (-0.09, 0.90), (0.34, 1.10), (0.62, 0.96)),
        ((0.62, 0.96), (0.72, 0.915), (0.78, 0.92), (0.82, 0.90)),
    ],
    closed=True,
    seed=101,
)

# 圈模板 B:顶部压扁、右弧收紧(适合宽词/日期)
_TEMPLATE_ELLIPSE_B = _sample_bezier_chain(
    [
        ((0.86, 0.84), (1.05, 0.62), (0.98, 0.28), (0.66, 0.12)),
        ((0.66, 0.12), (0.34, -0.04), (-0.02, 0.18), (-0.03, 0.55)),
        ((-0.03, 0.55), (-0.04, 0.86), (0.36, 1.04), (0.64, 0.94)),
        ((0.64, 0.94), (0.75, 0.90), (0.82, 0.87), (0.86, 0.84)),
    ],
    closed=True,
    seed=202,
)

# 圈模板 C:落笔更高、左弧外扩(适合短词)
_TEMPLATE_ELLIPSE_C = _sample_bezier_chain(
    [
        ((0.80, 0.96), (1.02, 0.80), (1.00, 0.34), (0.72, 0.14)),
        ((0.72, 0.14), (0.44, -0.06), (0.00, 0.10), (-0.05, 0.50)),
        ((-0.05, 0.50), (-0.10, 0.88), (0.32, 1.08), (0.60, 0.98)),
        ((0.60, 0.98), (0.70, 0.94), (0.76, 0.98), (0.80, 0.96)),
    ],
    closed=True,
    seed=303,
)

_ELLIPSE_TEMPLATES = (_TEMPLATE_ELLIPSE_A, _TEMPLATE_ELLIPSE_B, _TEMPLATE_ELLIPSE_C)


def _pick_template(seed: int) -> Tuple[List[Tuple[float, float]], int]:
    index = seed % len(_ELLIPSE_TEMPLATES)
    return _ELLIPSE_TEMPLATES[index], index


def _push_outside_protection(points: List[Tuple[float, float]], bbox: Tuple[float, float, float, float]) -> List[Tuple[float, float]]:
    """文字保护区:中心线不得进入字框本体(外扩 2px 容差)。

    误入的点沿原方向推到保护区边界外 4%。确定性,不依赖随机。"""
    left, top, right, bottom = bbox
    pl, pt = left - 2.0, top - 2.0
    pr, pb = right + 2.0, bottom + 2.0
    if pr <= pl or pb <= pt:
        return points
    cx = (left + right) / 2
    cy = (top + bottom) / 2
    result: List[Tuple[float, float]] = []
    for x, y in points:
        if pl < x < pr and pt < y < pb:
            dx, dy = x - cx, y - cy
            candidates: List[float] = []
            if dx > 0:
                candidates.append((pr - cx) / dx)
            elif dx < 0:
                candidates.append((pl - cx) / dx)
            if dy > 0:
                candidates.append((pb - cy) / dy)
            elif dy < 0:
                candidates.append((pt - cy) / dy)
            scale = max(1.0, (min(candidates) if candidates else 1.0) * 1.04)
            x, y = round(cx + dx * scale, 2), round(cy + dy * scale, 2)
        result.append((x, y))
    return result


def _deform_ellipse(template: List[Tuple[float, float]], bbox: Tuple[float, float, float, float], seed: int, pad: float, pad_left: Optional[float] = None, pad_right: Optional[float] = None) -> List[Tuple[float, float]]:
    """Circumscribed, pressure-rendered oval with deterministic hand tremor."""
    left, top, right, bottom = bbox
    width, height = right - left, bottom - top
    rand = _seeded(seed)
    phase1, phase2 = rand() * math.tau, rand() * math.tau
    center_x, center_y = (left + right) / 2, (top + bottom) / 2
    rx = (width / 2 + pad) * math.sqrt(2)
    ry = (height / 2 + pad) * math.sqrt(2)
    deformed = []
    for i in range(96):
        angle = math.tau * i / 96
        wobble = 1 + .015 * math.sin(3 * angle + phase1) + .008 * math.sin(5 * angle + phase2)
        deformed.append((center_x + rx * math.cos(angle) * wobble, center_y + ry * math.sin(angle) * wobble))
    if pad_left is not None or pad_right is not None:
        lower = left - max(0.0, pad_left) if pad_left is not None else -math.inf
        upper = right + max(0.0, pad_right) if pad_right is not None else math.inf
        deformed = [(min(upper, max(lower, x)), y) for x, y in deformed]
    return _resample_uniform(deformed, closed=True, step=SAMPLE_STEP_PX)


def _underline_centerline(bbox: Tuple[float, float, float, float], pad: float, seed: int, pad_left: Optional[float] = None, pad_right: Optional[float] = None) -> List[Tuple[float, float]]:
    """横线:沿基线,低频弧度 + 收笔上扬(非周期波浪)。

    pad_left/pad_right 提供时收紧左右延伸(邻词感知)。
    """
    left, top, right, bottom = bbox
    rand = _seeded(seed)
    y = bottom + pad
    width = right - left
    # 低频弯曲:单一拱高(0.5%–1.2% 行宽),收笔上扬 1.5%–3%
    arc = width * (0.005 + rand() * 0.007)
    flick = width * (0.015 + rand() * 0.015)
    tilt = (rand() - 0.5) * width * 0.004
    steps = max(24, min(MAX_SAMPLES, int(width / SAMPLE_STEP_PX)))
    ext_l = pad * 0.5 if pad_left is None else min(pad * 0.5, pad_left)
    ext_r = pad if pad_right is None else min(pad, pad_right)
    points: List[Tuple[float, float]] = []
    for i in range(steps + 1):
        t = i / steps
        x = left - ext_l + (width + ext_l + ext_r) * t
        y_t = y + math.sin(t * math.pi) * arc + (t**2.2) * flick + tilt * t
        points.append((round(x, 2), round(y_t, 2)))
    return points


def _highlighter_centerline(bbox: Tuple[float, float, float, float], pad: float, seed: int) -> List[Tuple[float, float]]:
    """荧光笔:扁刷从左到右扫过,端部轻微不齐(中心线供扫过进度)。"""
    left, top, right, bottom = bbox
    rand = _seeded(seed)
    y = (top + bottom) / 2 + (rand() - 0.5) * (bottom - top) * 0.06
    steps = max(12, int((right - left) / (SAMPLE_STEP_PX * 2)))
    points = []
    for i in range(steps + 1):
        t = i / steps
        x = left - pad * 0.4 + (right - left + pad * 0.8) * t
        points.append((round(x, 2), round(y, 2)))
    return points


def _width_profile(kind: str, count: int, seed: int) -> List[float]:
    """归一化笔宽曲线:起收笔细(占弧长 5%–12%),中段稳定略波动。"""
    rand = _seeded(seed)
    head = 0.05 + rand() * 0.07  # 起笔段占比
    tail = 0.05 + rand() * 0.07  # 收笔段占比
    base = 0.72 + rand() * 0.2   # 中段粗细(基准的 0.72–0.92,峰值到 1.1)
    profile: List[float] = []
    for i in range(count):
        t = i / max(1, count - 1)
        if t < head:
            w = 0.35 + 0.65 * (t / head)
            w *= 0.8 + 0.2 * (t / head)
        elif t > 1 - tail:
            w = 0.30 + 0.70 * ((1 - t) / tail)
        else:
            w = 1.0
        # 中段轻微压感波动(低频,非逐点噪声)
        w *= 1.0 + 0.10 * base * math.sin(t * math.tau * 2 + rand() * 0.4)
        value = max(0.25, min(1.2, w * (0.8 + base * 0.35)))
        profile.append(round(value, 3))
    if kind == "highlighter":
        # 扁刷:两端整齐,恒定宽
        profile = [1.0] * count
    return profile


def _speed_profile(count: int, seed: int) -> List[float]:
    """速度→弧长映射:起笔缓、主体快、转弯略慢、收笔减速。

    返回每个采样点的"时间进度"位置(0–1);采样点本身弧长均匀。
    """
    rand = _seeded(seed)
    head = 0.10 + rand() * 0.05
    tail = 0.12 + rand() * 0.06
    times: List[float] = []
    acc = 0.0
    for i in range(count):
        t = i / max(1, count - 1)
        if t < head:
            speed = 0.45 + 0.55 * (t / head)
        elif t > 1 - tail:
            speed = 0.25 + 0.75 * ((1 - t) / tail)
        else:
            speed = 1.0
        acc += 1.0 / max(0.15, speed)
        times.append(acc)
    total = times[-1]
    return [round(t / total, 4) for t in times]


@dataclass(frozen=True)
class FragmentInput:
    """一个片段(同行连续 token 的合并目标)。

    pad_left/pad_right 为邻词感知留白(方案 4.3:最外侧不得圈入邻词;
    空间不足时降低留白)。None 时退回统一 padding。
    """

    polygons: Tuple[Tuple[Tuple[int, int], ...], ...]
    style_type: str
    width: int
    padding: int
    seed: int
    pad_left: Optional[float] = None
    pad_right: Optional[float] = None


@dataclass(frozen=True)
class GeometryInputV2:
    fragments: Tuple[FragmentInput, ...]


def build_strokes_v2(geometry: GeometryInputV2) -> Tuple[Dict[str, Any], ...]:
    """按片段生成 v2 笔迹;每笔独立 timing 分配(方案 4.5)。"""
    strokes: List[Dict[str, Any]] = []
    for frag_index, fragment in enumerate(geometry.fragments):
        if not fragment.polygons:
            continue
        # 片段框 = 各 token 四边形的并集外接框(保留原始四边形由调用方持有)
        xs: List[float] = []
        ys: List[float] = []
        for polygon in fragment.polygons:
            for p in polygon:
                xs.append(float(p[0]))
                ys.append(float(p[1]))
        bbox = (min(xs), min(ys), max(xs), max(ys))
        if bbox[2] - bbox[0] < 1 or bbox[3] - bbox[1] < 1:
            continue  # 退化片段(与契约层 degenerate 校验一致)
        pad = float(max(0, fragment.padding))
        seed = fragment.seed + frag_index * 733
        if fragment.style_type == "ellipse":
            template, _ = _pick_template(seed)
            points = _deform_ellipse(template, bbox, seed, pad, fragment.pad_left, fragment.pad_right)
            gap = STROKE_GAP_SEC if frag_index else 0.0
            strokes.append(
                {
                    "kind": "path",
                    "points": points,
                    "width_profile": _width_profile("ellipse", len(points), seed),
                    "speed_profile": _speed_profile(len(points), seed),
                    "closed": True,
                    "polygon_index": frag_index,
                    "start_offset_sec": round(gap, 3),
                }
            )
        elif fragment.style_type == "underline":
            pl = pad if fragment.pad_left is None else max(1.0, fragment.pad_left)
            pr = pad if fragment.pad_right is None else max(1.0, fragment.pad_right)
            points = _underline_centerline(bbox, pad + fragment.width / 2, seed, pl, pr)
            strokes.append(
                {
                    "kind": "path",
                    "points": points,
                    "width_profile": _width_profile("underline", len(points), seed),
                    "speed_profile": _speed_profile(len(points), seed),
                    "closed": False,
                    "polygon_index": frag_index,
                    "start_offset_sec": round(STROKE_GAP_SEC if frag_index else 0.0, 3),
                }
            )
        elif fragment.style_type == "highlighter":
            points = _highlighter_centerline(bbox, pad, seed)
            strokes.append(
                {
                    "kind": "path",
                    "points": points,
                    "width_profile": [1.0] * len(points),
                    "speed_profile": [round(i / max(1, len(points) - 1), 4) for i in range(len(points))],
                    "closed": False,
                    "polygon_index": frag_index,
                    "start_offset_sec": round(STROKE_GAP_SEC * 0.5 if frag_index else 0.0, 3),
                    "brush_height": round(max(4.0, (bbox[3] - bbox[1]) + pad * 0.4), 2),
                }
            )
    return tuple(strokes)


def build_manual_path_stroke(
    points: Sequence[Tuple[int, int]], *, style_type: str = "ellipse", width: float = 5.0
) -> Dict[str, Any]:
    """Keep a user-drawn path intact while adapting it to the shared renderer."""
    normalized = [(int(x), int(y)) for x, y in points]
    if len(normalized) < 2:
        raise ValueError("manual path requires at least two points")
    stroke = {
        "kind": "path",
        "points": normalized,
        "width_profile": [1.0] * len(normalized),
        "speed_profile": [round(i / (len(normalized) - 1), 4) for i in range(len(normalized))],
        "closed": False,
        "polygon_index": 0,
        "start_offset_sec": 0.0,
    }
    if style_type == "highlighter":
        stroke["brush_height"] = max(16.0, float(width) * 4.0)
    return stroke
