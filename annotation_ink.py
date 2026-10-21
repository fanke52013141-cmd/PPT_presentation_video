# -*- coding: utf-8 -*-
"""栅格化手写墨迹渲染(R3:勾画必须是手写位图,不是 SVG 路径)。

将 geometry v2 的中心线 + 笔宽曲线渲染为**位图墨迹**:

- 压力轮廓:width_profile 沿弧长决定线宽(起收笔细、中段饱满);
- 墨迹质感:确定性低频浓淡噪声(固定种子 LCG)+ 轻微边缘洇墨(模糊),
  无逐帧噪声、无随机性——同 (笔迹, 种子) 输出逐字节一致;
- 逐帧推进:按 speed_profile 把绘制时长均分为 fps 帧,每帧是一张
  "画到当前弧长"的 PNG;Remotion 按帧号取图,视频里看到的就是位图手写;
- 精准度指标:coverage/enclosure(包住目标)、intrusion(压字)、
  neighbor(圈入邻词)、centroid offset(偏心距),供多轮对比。

纯模块:只依赖 Pillow;不导入 server。
"""
from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFilter

__all__ = [
    "INK_VERSION",
    "cached_ink_metadata",
    "InkRequest",
    "render_stroke_frames",
    "precision_metrics",
    "frames_needed",
]


INK_VERSION = "annotation_ink_v4_neighbor_bounds"
_DEFAULT_FPS = 30


def _seeded_bytes(seed: int, count: int, lo: int, hi: int) -> bytes:
    """确定性伪随机字节流(LCG);不使用语言内置随机。"""
    state = (int(seed) & 0x7FFFFFFF) or 1
    out = bytearray(count)
    span = hi - lo
    for i in range(count):
        state = (state * 48271) % 0x7FFFFFFF
        out[i] = lo + state % span
    return bytes(out)


def _noise_layer(width: int, height: int, seed: int, strength: float) -> Image.Image:
    """低频浓淡噪声:1/6 分辨率生成后放大,值域 [255-strength, 255]。"""
    small_w = max(2, width // 6)
    small_h = max(2, height // 6)
    lo = int(255 - strength)
    small = Image.frombytes("L", (small_w, small_h), _seeded_bytes(seed, small_w * small_h, lo, 255))
    return small.resize((width, height), Image.BILINEAR)


def _polyline_arc_lengths(points: Sequence[Tuple[float, float]]) -> List[float]:
    lengths = [0.0]
    for i in range(1, len(points)):
        lengths.append(lengths[-1] + math.dist(points[i], points[i - 1]))
    return lengths


def _time_to_arc(stroke: Dict[str, Any], t: float) -> float:
    """时间进度(0–1)→ 弧长进度;speed_profile 与前端同一语义。"""
    profile = stroke.get("speed_profile")
    if not isinstance(profile, (list, tuple)) or len(profile) < 2:
        return max(0.0, min(1.0, t))
    clamped = max(0.0, min(1.0, t))
    for i in range(1, len(profile)):
        if profile[i] >= clamped:
            span = profile[i] - profile[i - 1]
            frac = (clamped - profile[i - 1]) / span if span > 0 else 0.0
            return (i - 1 + frac) / (len(profile) - 1)
    return 1.0


def _points_up_to(points: Sequence[Tuple[float, float]], arc: float) -> List[Tuple[float, float]]:
    """截取弧长进度 arc 之前的折线;末端按段内插值(行进中的笔尖)。"""
    if not points:
        return []
    lengths = _polyline_arc_lengths(points)
    total = lengths[-1]
    if total <= 0:
        return list(points[:1])
    target = total * max(0.0, min(1.0, arc))
    out: List[Tuple[float, float]] = [points[0]]
    for i in range(1, len(points)):
        if lengths[i] <= target:
            out.append(points[i])
        else:
            span = lengths[i] - lengths[i - 1]
            t = (target - lengths[i - 1]) / span if span > 0 else 0.0
            out.append((
                points[i - 1][0] + (points[i][0] - points[i - 1][0]) * t,
                points[i - 1][1] + (points[i][1] - points[i - 1][1]) * t,
            ))
            break
    return out


@dataclass(frozen=True)
class InkRequest:
    """一次墨迹渲染的受控输入。

    texture=False 渲染均匀宽度、无噪声的干净中心线(用于复现第二轮
    "矢量手写"观感做多轮对比);True 为第三轮完整墨迹质感。
    """

    points: Tuple[Tuple[float, float], ...]
    width_profile: Tuple[float, ...]
    canvas: Tuple[int, int]
    color: Tuple[int, int, int] = (196, 62, 28)
    base_width: float = 5.0
    opacity: float = 0.85
    seed: int = 1
    closed: bool = False
    texture: bool = True
    speed_profile: Tuple[float, ...] = ()


def _draw_centerline(alpha: Image.Image, points, width_profile, base_width, origin):
    """按逐段宽度把中心线画进 alpha 通道(圆头,压力轮廓)。

    points 为画布坐标;origin 是渲染区域的画布偏移,局部坐标 = 画布 − origin。
    """
    draw = ImageDraw.Draw(alpha)
    ox, oy = origin
    for i in range(1, len(points)):
        width = max(1.0, float(width_profile[min(i, len(width_profile) - 1)]) * base_width)
        x0, y0 = points[i - 1]
        x1, y1 = points[i]
        draw.line(
            [(x0 - ox, y0 - oy), (x1 - ox, y1 - oy)],
            fill=255,
            width=max(1, int(round(width))),
        )
        # 圆头:两端加圆,半径为半宽
        r = width / 2
        for (px, py) in ((x0, y0), (x1, y1)):
            draw.ellipse(
                [px - ox - r, py - oy - r, px - ox + r, py - oy + r],
                fill=255,
            )


def render_stroke_rgba(request: InkRequest, arc: float = 1.0) -> Image.Image:
    """渲染弧长进度 arc(0–1)的 RGBA 墨迹;同输入逐字节一致。"""
    width, height = request.canvas
    points = list(request.points)
    if arc <= 0 or len(points) < 2:
        return Image.new("RGBA", (width, height), (0, 0, 0, 0))
    if arc < 1.0:
        points = _points_up_to(points, arc)
    if len(points) < 2:
        return Image.new("RGBA", (width, height), (0, 0, 0, 0))

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    margin = int(request.base_width * 2 + 12)
    region = (
        max(0, int(min(xs)) - margin),
        max(0, int(min(ys)) - margin),
        min(width, int(max(xs)) + margin + 1),
        min(height, int(max(ys)) + margin + 1),
    )
    rw, rh = max(2, region[2] - region[0]), max(2, region[3] - region[1])
    origin = (region[0], region[1])

    alpha = Image.new("L", (rw, rh), 0)
    _draw_centerline(alpha, points, request.width_profile, request.base_width, origin)

    # 墨迹质感:浓淡噪声只**调制**已有墨迹(乘法,不新增覆盖面),
    # 轻微洇墨;同 (笔迹, 种子) 逐字节一致。
    # texture=False(第二轮矢量观感对比)跳过噪声与洇墨。
    if request.texture:
        noise = _noise_layer(rw, rh, request.seed * 7919 + len(points), 70.0)
        from PIL import ImageChops

        alpha = ImageChops.multiply(alpha, noise)
        alpha = alpha.filter(ImageFilter.GaussianBlur(0.55))

    if request.opacity <= 0:
        return Image.new("RGBA", (width, height), (0, 0, 0, 0))
    solid = Image.new("RGBA", (rw, rh), request.color + (0,))
    solid.putalpha(alpha.point(lambda v: int(v * request.opacity)))
    canvas_img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    canvas_img.alpha_composite(solid, (region[0], region[1]))
    return canvas_img


def frames_needed(draw_duration_sec: float, fps: int = _DEFAULT_FPS) -> int:
    return max(2, min(240, int(math.ceil(draw_duration_sec * fps))))


def render_stroke_frames(
    request: InkRequest,
    *,
    draw_duration_sec: float,
    fps: int = _DEFAULT_FPS,
) -> List[Image.Image]:
    """Include a transparent zero frame and a complete final frame."""
    total = frames_needed(draw_duration_sec, fps)
    return [render_stroke_rgba(request, arc=_time_to_arc(
        {"speed_profile": request.speed_profile}, k / (total - 1))) for k in range(total)]


# ---------------------------------------------------------------- 精准度指标


def _mask_bbox_region(alpha: Image.Image) -> Tuple[int, int, int, int]:
    return alpha.getbbox() or (0, 0, alpha.width, alpha.height)


def precision_metrics(
    ink_alpha: Image.Image,
    *,
    target_boxes: Sequence[Tuple[float, float, float, float]],
    neighbor_boxes: Sequence[Tuple[float, float, float, float]] = (),
    band_px: float = 22.0,
) -> Dict[str, Any]:
    """栅格精准度指标(方案 8.2 的可计算子集)。

    - intrusion_rate: 墨迹像素落入目标**文字框内**的比例(压字;越低越好);
    - neighbor_rate: 墨迹像素落入邻词框内的比例(误圈邻词;应≈0);
    - enclosure_rate: 目标框周界采样点被墨迹(带宽 band_px)包住的比例
      (≥0.9 视为完整包围);
    - centroid_offset_px: 墨迹质心到目标框质心的距离(偏心;越低越好)。
    """
    import numpy  # 仓库已有依赖(Pillow 生态/测试环境均可用)

    alpha = ink_alpha.split()[-1] if ink_alpha.mode == "RGBA" else ink_alpha
    mask = numpy.array(alpha) > 40
    total_ink = int(mask.sum())

    def box_mask(box, pad=0):
        m = numpy.zeros_like(mask)
        x0, y0, x1, y1 = box
        m[max(0, int(y0 - pad)):int(y1 + pad), max(0, int(x0 - pad)):int(x1 + pad)] = True
        return m

    intrusion = 0
    for box in target_boxes:
        intrusion += int((mask & box_mask(box)).sum())
    neighbor = 0
    for box in neighbor_boxes:
        neighbor += int((mask & box_mask(box)).sum())

    # 包围检查:目标框周界采样点在墨迹膨胀带内
    ink_dilated = Image.new("L", alpha.size, 0)
    region = _mask_bbox_region(alpha)
    crop = alpha.crop(region).filter(ImageFilter.MaxFilter(31))
    ink_dilated.paste(crop, region)
    dilated = numpy.array(ink_dilated) > 40

    perimeter_points: List[Tuple[int, int]] = []
    for box in target_boxes:
        x0, y0, x1, y1 = box
        steps = max(8, int((x1 - x0 + y1 - y0) / 8))
        for i in range(steps):
            t = i / steps
            perimeter_points.append((int(x0 + (x1 - x0) * t), int(y0)))
            perimeter_points.append((int(x0 + (x1 - x0) * t), int(y1)))
            perimeter_points.append((int(x0), int(y0 + (y1 - y0) * t)))
            perimeter_points.append((int(x1), int(y0 + (y1 - y0) * t)))
    enclosed = sum(
        1
        for (x, y) in perimeter_points
        if 0 <= y < dilated.shape[0] and 0 <= x < dilated.shape[1] and dilated[y, x]
    )
    enclosure = enclosed / len(perimeter_points) if perimeter_points else 0.0

    if total_ink:
        ys, xs = numpy.nonzero(mask)
        cx, cy = float(xs.mean()), float(ys.mean())
    else:
        cx = cy = 0.0
    offset = 0.0
    if target_boxes and total_ink:
        tx0, ty0, tx1, ty1 = target_boxes[0]
        for box in target_boxes[1:]:
            tx0 = min(tx0, box[0]); ty0 = min(ty0, box[1])
            tx1 = max(tx1, box[2]); ty1 = max(ty1, box[3])
        offset = math.hypot(cx - (tx0 + tx1) / 2, cy - (ty0 + ty1) / 2)

    return {
        "ink_pixels": total_ink,
        "intrusion_rate": round(intrusion / total_ink, 4) if total_ink else 0.0,
        "neighbor_rate": round(neighbor / total_ink, 4) if total_ink else 0.0,
        "enclosure_rate": round(float(enclosure), 4),
        "centroid_offset_px": round(offset, 2),
    }


def render_and_write(
    request: InkRequest,
    out_dir: Path,
    *,
    draw_duration_sec: float,
    fps: int = _DEFAULT_FPS,
    cancel_event=None,
) -> Dict[str, Any]:
    """渲染整笔墨迹并落盘:full.png + frame_%03d.png + meta.json。

    目录结构(相对 slide 目录):annotation_ink/<annotation_id>/stroke_<i>/。
    返回写进 stroke 的 "ink" 元数据字典。内容确定性:同输入重跑得到
    逐字节一致的 PNG。
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if cancel_event and cancel_event.is_set():
        raise RuntimeError("cancelled")
    (out_dir / "meta.json").unlink(missing_ok=True)
    full = render_stroke_rgba(request, arc=1.0)
    full_path = out_dir / "full.png"
    _atomic_bytes(full_path, _png_bytes(full))
    frame_count = frames_needed(draw_duration_sec, fps)
    for index in range(frame_count):
        if cancel_event and cancel_event.is_set():
            raise RuntimeError("cancelled")
        frame = render_stroke_rgba(request, arc=_time_to_arc(
            {"speed_profile": request.speed_profile}, index / (frame_count - 1)))
        _atomic_bytes(out_dir / f"frame_{index:03d}.png", _png_bytes(frame))
    meta = {
        "ink_version": INK_VERSION,
        "fps": fps,
        "frame_count": frame_count,
        "canvas": list(request.canvas),
        "color": list(request.color),
        "full": "full.png",
        "frames_prefix": "frame_",
    }
    if cancel_event and cancel_event.is_set():
        raise RuntimeError("cancelled")
    _atomic_bytes(out_dir / "meta.json", json.dumps(meta, ensure_ascii=False, indent=1).encode("utf-8"))
    return {
        "kind": "raster",
        "dir": out_dir.name,
        "frame_count": frame_count,
        "fps": fps,
        "canvas": list(request.canvas),
    }


def _atomic_bytes(path: Path, content: bytes) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".ink-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def cached_ink_metadata(directory: Path, canvas, duration: float, fps: int):
    """A cache hit requires complete, decodable frames for this build."""
    try:
        metadata = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
        count = frames_needed(duration, fps)
        if (metadata.get("ink_version") != INK_VERSION or metadata.get("fps") != fps
                or metadata.get("frame_count") != count or metadata.get("canvas") != list(canvas)):
            return None
        for name in ["full.png", *(f"frame_{i:03d}.png" for i in range(count))]:
            with Image.open(directory / name) as frame:
                if frame.size != tuple(canvas) or frame.mode != "RGBA" or frame.format != "PNG":
                    return None
                frame.verify()
        return metadata
    except (OSError, ValueError, TypeError, AttributeError, SyntaxError):
        return None


def _png_bytes(image: Image.Image) -> bytes:
    import io

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False)
    return buffer.getvalue()
