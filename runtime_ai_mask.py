"""Automatic multimodal AI Mask annotation routes.

The annotator detects exact foreground components, associates every component
with one narrated visual group, and writes mutually-exclusive pixel masks into
``reveal_manifest.json``. Brush strokes remain available as manual corrections
on top of the automatic base mask.
"""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import io
import json
import os
import sys
import threading
import time
from collections import deque
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

PATCH_MARKER = "__ppt_ai_mask_runtime_patch__"
SETTING_PREFIX = "ai_mask_"

DEFAULT_SETTINGS: dict[str, Any] = {
    "white_threshold": 245,
    "color_tolerance": 12,
    "add_border": 2,
    "connectivity": 8,
    "min_element_area": 120,
    "component_padding_px": 12,
    "max_group_elements": 60,
    "llm_confidence_threshold": 0.72,
    "llm_temperature": 0.1,
    "overwrite_existing_manual_mask": True,
    "skip_locked_groups": False,
}

MASK_COLORS = (
    "#E84A5F", "#1B998B", "#F6AE2D", "#3D5A80",
    "#7B2CBF", "#2F80ED", "#D45113", "#4C956C",
)
AI_MASK_VISION_TIMEOUT_SEC = 180.0

DEFAULT_METHODOLOGY = """你是中文 PPT 视频的 AI Mask 语义标注专家。

任务：把纯白背景图片中自动检测到的视觉元素候选，绑定到当前 Slide 已有的 visual_groups 和 narration_beats。你不是重新生成分镜，也不是重写演讲稿；你只做“画面元素 → 语块 → 演讲稿 beat”的匹配。

可修改方法论：
1. group_id 只能使用输入 visual_groups[].id，不要发明新的 group。
2. narration_beat_id 只能使用输入 narration_beats[].id。
3. element_ids 只能使用输入 auto_elements[].element_id。
4. 页面上方固定主标题/副标题区域属于静态上下文，不分配给任何 narration group，不参与逐语块 Reveal。
5. 优先匹配 visible_text、visible_anchor、spoken_text，再结合元素的二维位置、role 和阅读顺序；横向与纵向距离都必须考虑。
6. 一个语块可以绑定多个空间连续的元素，例如主配图 + 配图内部文字 + 紧邻图标/对号/标签。大面积主配图应吸收其内部和边缘邻接元素，除非这些元素明确对应独立 narration beat。
7. 不允许因为颜色相似就跨卡片、跨栏或跨配图分配。落在某一主配图内部、边界上或紧邻区域的元素，不得分给远处语块。
8. 对比场景左右两侧如果表达不同叙事状态，必须分别绑定到不同 narration beat；不要把两个独立插图合并为同一个 Mask。
9. 不确定时降低 confidence，不要强行匹配。装饰或无口播元素放入 unmatched_elements。
10. 输出必须是严格 JSON，不要 Markdown，不要解释段落。
"""

DEFAULT_OUTPUT_STRUCTURE = """必须输出一个 JSON object：
{
  "slide_id": "slide_001",
  "matches": [
    {
      "group_id": "body_group_01",
      "narration_beat_id": "beat_01",
      "element_ids": ["el_auto_010", "el_auto_011"],
      "confidence": 0.95,
      "reason": "主配图与紧邻对号位于同一空间岛，并共同对应 beat_01"
    }
  ],
  "unmatched_elements": [],
  "unmatched_groups": [],
  "warnings": []
}

约束：group_id 必须来自 visual_groups[].id；narration_beat_id 必须来自 narration_beats[].id；element_ids 必须来自 auto_elements[].element_id；confidence 是 0 到 1 的数字。
"""

PROMPT_METHOD_KEY = SETTING_PREFIX + "match_methodology_system_content"
PROMPT_OUTPUT_KEY = SETTING_PREFIX + "match_output_structure_system_content"
LEGACY_TITLE_RULE = "6. 主标题与副标题是否属于同一个 Mask，以 narration_beats 的讲解关系为准，不按字体颜色、断笔或字间距拆分。"
CURRENT_TITLE_AND_ISLAND_RULES = """6. 页面上方固定主标题/副标题区域属于静态上下文，不分配给任何 narration group，不参与逐语块 Reveal；元素匹配必须同时考虑横向与纵向距离；大面积主配图应吸收其内部、边界上和紧邻的图标、对号、标签与说明，除非它们明确对应独立 narration beat；不允许因为颜色相似就跨卡片、跨栏或跨配图分配。"""


def _compose_ai_mask_full_prompt(methodology: str, output_structure: str) -> str:
    return methodology.strip() + "\n\n--- OUTPUT STRUCTURE / 输出结构 ---\n" + output_structure.strip()


def _read_ai_mask_prompts(server_module: ModuleType) -> tuple[str, str]:
    methodology = str(server_module.get_setting(PROMPT_METHOD_KEY, DEFAULT_METHODOLOGY) or DEFAULT_METHODOLOGY)
    output_structure = str(server_module.get_setting(PROMPT_OUTPUT_KEY, DEFAULT_OUTPUT_STRUCTURE) or DEFAULT_OUTPUT_STRUCTURE)
    if LEGACY_TITLE_RULE in methodology:
        methodology = methodology.replace(LEGACY_TITLE_RULE, CURRENT_TITLE_AND_ISLAND_RULES)
    return methodology, output_structure


def _bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "y"}:
        return True
    if text in {"0", "false", "no", "off", "n"}:
        return False
    return default


def _int(value: Any, default: int, lo: int, hi: int) -> int:
    try:
        parsed = int(float(str(value).strip()))
    except Exception:
        parsed = default
    return max(lo, min(hi, parsed))


def _float(value: Any, default: float, lo: float, hi: float) -> float:
    try:
        parsed = float(str(value).strip())
    except Exception:
        parsed = default
    return max(lo, min(hi, parsed))


def normalize_settings(raw: dict[str, Any] | None) -> dict[str, Any]:
    raw = {**DEFAULT_SETTINGS, **(raw or {})}
    return {
        "white_threshold": _int(raw.get("white_threshold"), 245, 220, 255),
        "color_tolerance": _int(raw.get("color_tolerance"), 12, 0, 40),
        "add_border": _int(raw.get("add_border"), 2, 0, 8),
        "connectivity": 4 if str(raw.get("connectivity")) == "4" else 8,
        "min_element_area": _int(raw.get("min_element_area"), 120, 10, 10000),
        "component_padding_px": _int(raw.get("component_padding_px"), 12, 0, 80),
        "max_group_elements": max(20, _int(raw.get("max_group_elements"), 60, 1, 120)),
        "llm_confidence_threshold": _float(raw.get("llm_confidence_threshold"), 0.72, 0, 1),
        "llm_temperature": _float(raw.get("llm_temperature"), 0.1, 0, 1),
        "overwrite_existing_manual_mask": _bool(raw.get("overwrite_existing_manual_mask"), True),
        "skip_locked_groups": _bool(raw.get("skip_locked_groups"), False),
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise RuntimeError(f"Missing JSON file: {path}")
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON must be object: {path}")
    return value


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _neighbors(connectivity: int) -> tuple[tuple[int, int], ...]:
    base = ((1, 0), (-1, 0), (0, 1), (0, -1))
    return base if connectivity == 4 else base + ((1, 1), (1, -1), (-1, 1), (-1, -1))


def _pad_box(box: dict[str, int], width: int, height: int, padding: int) -> dict[str, int]:
    x1 = max(0, box["x"] - padding)
    y1 = max(0, box["y"] - padding)
    x2 = min(width, box["x"] + box["w"] + padding)
    y2 = min(height, box["y"] + box["h"] + padding)
    return {"x": x1, "y": y1, "w": max(1, x2 - x1), "h": max(1, y2 - y1)}


def _position(cx: float, cy: float, width: int, height: int) -> str:
    xp = "left" if cx < width / 3 else "right" if cx > width * 2 / 3 else "center"
    yp = "top" if cy < height / 3 else "bottom" if cy > height * 2 / 3 else "middle"
    return f"{yp}_{xp}"


def _coords_to_row_runs(
    coords: list[tuple[int, int]],
    border: int,
    width: int,
    height: int,
) -> list[list[int]]:
    """Encode component pixels as compact [y, x_start, x_end) scanline runs."""
    rows: dict[int, list[int]] = {}
    for padded_x, padded_y in coords:
        x = padded_x - border
        y = padded_y - border
        if 0 <= x < width and 0 <= y < height:
            rows.setdefault(y, []).append(x)
    runs: list[list[int]] = []
    for y in sorted(rows):
        xs = sorted(set(rows[y]))
        if not xs:
            continue
        start = previous = xs[0]
        for x in xs[1:]:
            if x != previous + 1:
                runs.append([y, start, previous + 1])
                start = x
            previous = x
        runs.append([y, start, previous + 1])
    return runs


def _merge_row_runs(elements: list[dict[str, Any]], width: int, height: int) -> dict[str, Any]:
    """Union exact component RLE without expanding beyond source pixels."""
    rows: dict[int, list[tuple[int, int]]] = {}
    for element in elements:
        rle = element.get("mask_rle") if isinstance(element.get("mask_rle"), dict) else {}
        for run in rle.get("runs", []) or []:
            if not isinstance(run, list) or len(run) < 3:
                continue
            y, x1, x2 = (int(run[0]), int(run[1]), int(run[2]))
            if 0 <= y < height and x2 > x1:
                rows.setdefault(y, []).append((max(0, x1), min(width, x2)))
    merged: list[list[int]] = []
    for y in sorted(rows):
        intervals = sorted((x1, x2) for x1, x2 in rows[y] if x2 > x1)
        if not intervals:
            continue
        start, end = intervals[0]
        for x1, x2 in intervals[1:]:
            if x1 <= end:
                end = max(end, x2)
            else:
                merged.append([y, start, end])
                start, end = x1, x2
        merged.append([y, start, end])
    return {
        "encoding": "row_runs_v1",
        "width": width,
        "height": height,
        "runs": merged,
    }


def _rle_pixel_count(rle: dict[str, Any]) -> int:
    return sum(
        max(0, int(run[2]) - int(run[1]))
        for run in rle.get("runs", []) or []
        if isinstance(run, list) and len(run) >= 3
    )


def _solidify_planar_component(
    runs: list[list[int]],
    raw_box: dict[str, int],
    source_area: int,
) -> list[list[int]]:
    """Close background leaks inside large card/panel components by scanline.

    Generated slides often use dashed borders and near-white gradients. A
    border flood can enter those panels through a dash gap and punch thousands
    of white pinholes. Large, dense components are therefore filled only
    between their first and last source pixel on each occupied row. Rounded
    outer silhouettes remain intact and small text/illustrations are untouched.
    """
    box_area = max(1, int(raw_box.get("w", 0)) * int(raw_box.get("h", 0)))
    density = source_area / box_area
    if box_area < 40_000 or source_area < 25_000 or density < 0.35:
        return runs
    rows: dict[int, tuple[int, int]] = {}
    for y, x1, x2 in runs:
        if y not in rows:
            rows[y] = (x1, x2)
        else:
            rows[y] = (min(rows[y][0], x1), max(rows[y][1], x2))
    return [[y, x1, x2] for y, (x1, x2) in sorted(rows.items()) if x2 > x1]


def _protect_other_foreground(
    solid_runs: list[list[int]],
    source_runs: list[list[int]],
    source_foreground: np.ndarray,
) -> list[list[int]]:
    """Prevent a filled panel from claiming pixels owned by another component."""
    if solid_runs == source_runs:
        return solid_runs
    own_rows: dict[int, list[tuple[int, int]]] = {}
    for y, x1, x2 in source_runs:
        own_rows.setdefault(y, []).append((x1, x2))
    protected: list[list[int]] = []
    for y, x1, x2 in solid_runs:
        allowed = ~source_foreground[y, x1:x2].copy()
        for own_x1, own_x2 in own_rows.get(y, []):
            left, right = max(x1, own_x1), min(x2, own_x2)
            if right > left:
                allowed[left - x1:right - x1] = True
        indexes = np.flatnonzero(allowed)
        if not len(indexes):
            continue
        start = previous = int(indexes[0])
        for value in indexes[1:]:
            current = int(value)
            if current != previous + 1:
                protected.append([y, x1 + start, x1 + previous + 1])
                start = current
            previous = current
        protected.append([y, x1 + start, x1 + previous + 1])
    return protected


def _rle_bounds(rle: dict[str, Any]) -> dict[str, int] | None:
    runs = rle.get("runs", []) if isinstance(rle, dict) else []
    valid = [run for run in runs if isinstance(run, list) and len(run) >= 3 and int(run[2]) > int(run[1])]
    if not valid:
        return None
    x1 = min(int(run[1]) for run in valid)
    y1 = min(int(run[0]) for run in valid)
    x2 = max(int(run[2]) for run in valid)
    y2 = max(int(run[0]) + 1 for run in valid)
    return {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1}


def detect_elements(image_path: Path, slide_dir: Path, settings: dict[str, Any]) -> dict[str, Any]:
    image = Image.open(image_path).convert("RGB")
    ow, oh = image.size
    border = int(settings["add_border"])
    if border:
        padded = Image.new("RGB", (ow + border * 2, oh + border * 2), (255, 255, 255))
        padded.paste(image, (border, border))
    else:
        padded = image
    arr = np.asarray(padded, dtype=np.uint8)
    h, w = arr.shape[:2]
    hi = arr.max(axis=2).astype(np.int16)
    lo = arr.min(axis=2).astype(np.int16)
    white = (lo >= int(settings["white_threshold"])) & ((hi - lo) <= int(settings["color_tolerance"]))
    bg = np.zeros((h, w), dtype=bool)
    q: deque[tuple[int, int]] = deque()

    def seed(x: int, y: int) -> None:
        if white[y, x] and not bg[y, x]:
            bg[y, x] = True
            q.append((x, y))

    for x in range(w):
        seed(x, 0)
        seed(x, h - 1)
    for y in range(h):
        seed(0, y)
        seed(w - 1, y)
    nbrs = _neighbors(int(settings["connectivity"]))
    while q:
        x, y = q.popleft()
        for dx, dy in nbrs:
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h and white[ny, nx] and not bg[ny, nx]:
                bg[ny, nx] = True
                q.append((nx, ny))

    fg = ~bg
    source_foreground = fg[border:border + oh, border:border + ow] if border else fg
    visited = np.zeros((h, w), dtype=bool)
    ys, xs = np.nonzero(fg)
    candidates: list[dict[str, Any]] = []
    residual: list[dict[str, Any]] = []
    out_dir = slide_dir / "auto_mask"
    crop_dir = out_dir / "elements"
    crop_dir.mkdir(parents=True, exist_ok=True)
    for sx, sy in zip(xs.tolist(), ys.tolist()):
        if visited[sy, sx] or not fg[sy, sx]:
            continue
        q.clear()
        q.append((sx, sy))
        visited[sy, sx] = True
        coords: list[tuple[int, int]] = []
        while q:
            x, y = q.popleft()
            coords.append((x, y))
            for dx, dy in nbrs:
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h and fg[ny, nx] and not visited[ny, nx]:
                    visited[ny, nx] = True
                    q.append((nx, ny))
        px = [c[0] for c in coords]
        py = [c[1] for c in coords]
        x1 = max(0, min(px) - border)
        y1 = max(0, min(py) - border)
        x2 = min(ow, max(px) + 1 - border)
        y2 = min(oh, max(py) + 1 - border)
        if x2 <= x1 or y2 <= y1:
            continue
        raw = {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1}
        box = _pad_box(raw, ow, oh, int(settings["component_padding_px"]))
        cx, cy = box["x"] + box["w"] / 2, box["y"] + box["h"] / 2
        source_runs = _coords_to_row_runs(coords, border, ow, oh)
        component_runs = _solidify_planar_component(source_runs, raw, len(coords))
        component_runs = _protect_other_foreground(component_runs, source_runs, source_foreground)
        component = {
            "element_id": "",
            "bbox": box,
            "raw_bbox": raw,
            "center": {"x": round(cx, 2), "y": round(cy, 2)},
            "area": len(coords),
            "mask_pixel_count": sum(run[2] - run[1] for run in component_runs),
            "position": _position(cx, cy, ow, oh),
            "ocr_text": "",
            "mask_rle": {
                "encoding": "row_runs_v1",
                "width": ow,
                "height": oh,
                "runs": component_runs,
            },
        }
        if len(coords) >= int(settings["min_element_area"]):
            candidates.append(component)
        else:
            residual.append(component)
    candidates.sort(key=lambda e: (e["bbox"]["y"], e["bbox"]["x"]))
    residual.sort(key=lambda e: (e["bbox"]["y"], e["bbox"]["x"]))
    for i, element in enumerate(candidates, 1):
        element["element_id"] = f"el_auto_{i:03d}"
        box = element["bbox"]
        image.crop((box["x"], box["y"], box["x"] + box["w"], box["y"] + box["h"])).save(
            crop_dir / f"{element['element_id']}.png"
        )
    for i, element in enumerate(residual, 1):
        element["element_id"] = f"el_residual_{i:04d}"
    all_components = candidates + residual
    exact_foreground = _merge_row_runs(all_components, ow, oh)
    payload = {
        "version": "auto_elements_v2_exact_rle",
        "slide_id": slide_dir.name,
        "canvas": {"width": ow, "height": oh},
        "elements": candidates,
        "residual_elements": residual,
        "source_foreground_pixel_count": int(np.count_nonzero(fg)),
        "foreground_pixel_count": _rle_pixel_count(exact_foreground),
    }
    _write_json(out_dir / "auto_elements.json", payload)
    return payload


def _box_xyxy(value: Any) -> tuple[float, float, float, float] | None:
    if isinstance(value, dict):
        try:
            x1 = float(value.get("x", 0))
            y1 = float(value.get("y", 0))
            return x1, y1, x1 + float(value.get("w", 0)), y1 + float(value.get("h", 0))
        except (TypeError, ValueError):
            return None
    if isinstance(value, (list, tuple)) and len(value) >= 4:
        try:
            return tuple(float(item) for item in value[:4])  # type: ignore[return-value]
        except (TypeError, ValueError):
            return None
    return None


def _manifest_group_for_visual_id(manifest_slide: dict[str, Any], group_id: str) -> dict[str, Any] | None:
    for field in ("semantic_blocks", "groups"):
        for group in manifest_slide.get(field, []) or []:
            if not isinstance(group, dict):
                continue
            identifiers = {
                str(group.get("id") or ""),
                str(group.get("group_id") or ""),
                str(group.get("visual_group_id") or ""),
            }
            if group_id in identifiers:
                return group
    return None


def _fallback_match(
    slide: dict[str, Any],
    elements: list[dict[str, Any]],
    manifest_slide: dict[str, Any] | None = None,
) -> dict[str, Any]:
    narrated_group_ids = {
        str(beat.get("group_id") or "")
        for beat in slide.get("narration_beats", []) or []
        if isinstance(beat, dict) and str(beat.get("group_id") or "")
    }
    groups = [
        group for group in slide.get("visual_groups", []) or []
        if isinstance(group, dict)
        and str(group.get("role") or "") != "decoration"
        and str(group.get("id") or "") in narrated_group_ids
    ]
    beat_by_group = {
        str(beat.get("group_id") or ""): str(beat.get("id") or "")
        for beat in slide.get("narration_beats", []) or []
        if isinstance(beat, dict)
    }
    matches: list[dict[str, Any]] = []
    used: set[str] = set()
    unmatched_groups: list[str] = []
    for index, group in enumerate(groups):
        gid = str(group.get("id") or "")
        prior = _manifest_group_for_visual_id(manifest_slide or {}, gid)
        prior_box = _box_xyxy((prior or {}).get("box"))
        selected: list[str] = []
        if prior_box:
            px1, py1, px2, py2 = prior_box
            for element in elements:
                eid = str(element.get("element_id") or "")
                if not eid or eid in used:
                    continue
                box = _box_xyxy(element.get("bbox"))
                if not box:
                    continue
                ex1, ey1, ex2, ey2 = box
                cx, cy = (ex1 + ex2) / 2, (ey1 + ey2) / 2
                intersects = min(px2, ex2) > max(px1, ex1) and min(py2, ey2) > max(py1, ey1)
                if (px1 <= cx <= px2 and py1 <= cy <= py2) or intersects:
                    selected.append(eid)
        if not selected and len(elements) == len(groups) and index < len(elements):
            eid = str(elements[index].get("element_id") or "")
            if eid and eid not in used:
                selected = [eid]
        if not selected:
            unmatched_groups.append(gid)
            continue
        used.update(selected)
        matches.append({
            "group_id": gid,
            "narration_beat_id": beat_by_group.get(gid, ""),
            "element_ids": selected,
            "confidence": 0.86 if prior_box else 0.74,
            "reason": "deterministic prior-box match" if prior_box else "deterministic reading-order match",
        })
    all_ids = {str(element.get("element_id") or "") for element in elements if str(element.get("element_id") or "")}
    return {
        "slide_id": slide.get("slide_id"),
        "matches": matches,
        "unmatched_elements": sorted(all_ids - used),
        "unmatched_groups": unmatched_groups,
        "warnings": [],
        "matching_method": "deterministic_prior",
    }


def _candidate_overlay(image_path: Path, elements: list[dict[str, Any]], output_path: Path) -> bytes:
    image = Image.open(image_path).convert("RGB")
    original_width, original_height = image.size
    if image.width > 1280:
        ratio = 1280 / image.width
        image = image.resize((1280, max(1, int(image.height * ratio))), Image.Resampling.LANCZOS)
    scale_x = image.width / original_width
    scale_y = image.height / original_height
    draw = ImageDraw.Draw(image)
    for element in elements:
        box = element.get("bbox") if isinstance(element.get("bbox"), dict) else {}
        x1 = int(float(box.get("x", 0)) * scale_x)
        y1 = int(float(box.get("y", 0)) * scale_y)
        x2 = int(float(box.get("x", 0) + box.get("w", 0)) * scale_x)
        y2 = int(float(box.get("y", 0) + box.get("h", 0)) * scale_y)
        label = str(element.get("element_id") or "")
        draw.rectangle((x1, y1, x2, y2), outline=(220, 30, 50), width=3)
        label_box = draw.textbbox((x1, max(0, y1 - 14)), label)
        draw.rectangle(label_box, fill=(255, 255, 255))
        draw.text((x1, max(0, y1 - 14)), label, fill=(180, 0, 30))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _resolved_vision_model(server_module: ModuleType) -> tuple[str, str]:
    provider = str(server_module.get_setting("llm_provider") or "").strip().lower()
    configured = str(server_module.get_setting("vision_model") or "").strip()
    # A model name from another provider cannot be sent to the active endpoint.
    # Preserve the configured value for diagnostics and use the provider's
    # working LLM model as the multimodal fallback.
    if provider not in {"", "openai", "newapi", "openrouter", "litellm", "custom"} and configured.startswith("gpt-"):
        return str(server_module.get_setting("llm_model") or "").strip(), configured
    return configured or str(server_module.get_setting("llm_model") or "").strip(), configured


def _is_timeout(server_module: ModuleType, exc: BaseException) -> bool:
    helper = getattr(server_module, "is_timeout_exception", None)
    if callable(helper):
        try:
            return bool(helper(exc))
        except Exception:
            pass
    return isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower() or "timed out" in str(exc).lower()


def _vision_match(
    server_module: ModuleType,
    project: Any,
    slide: dict[str, Any],
    elements: list[dict[str, Any]],
    image_path: Path,
    overlay_path: Path,
    methodology: str,
    output_structure: str,
    settings: dict[str, Any],
) -> dict[str, Any] | None:
    api_key = server_module.get_setting("llm_api_key")
    if not api_key:
        return None
    overlay_bytes = _candidate_overlay(image_path, elements, overlay_path)
    model, _ = _resolved_vision_model(server_module)
    base_url = server_module.get_setting("llm_base_url")
    vendor_options: dict[str, Any] = {}
    option_builder = getattr(server_module, "step2_llm_vendor_options", None)
    if callable(option_builder):
        vendor_options = option_builder(model, base_url) or {}
    client = server_module.get_openai_client(
        api_key=api_key,
        base_url=base_url,
        timeout=AI_MASK_VISION_TIMEOUT_SEC,
        max_retries=0,
    )
    payload = {
        "slide": {
            key: slide.get(key)
            for key in ("slide_id", "main_title", "subtitle", "core_message", "body_content", "visual_groups", "narration_beats")
        },
        "auto_elements": [
            {key: element.get(key) for key in ("element_id", "bbox", "raw_bbox", "center", "area", "position", "ocr_text")}
            for element in elements
        ],
        "instruction": "图中红框标签就是 auto_elements.element_id。结合画面语义、可见文字、分镜 visual_groups 与 narration_beats 完成关联。",
    }
    system_prompt = methodology + "\n\n--- OUTPUT STRUCTURE / 输出结构 ---\n" + output_structure
    image_url = "data:image/png;base64," + base64.b64encode(overlay_bytes).decode("ascii")
    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)},
                {"type": "image_url", "image_url": {"url": image_url}},
            ],
        },
    ]
    try:
        try:
            response = client.chat.completions.create(
                model=model,
                temperature=float(settings["llm_temperature"]),
                max_tokens=12000,
                timeout=AI_MASK_VISION_TIMEOUT_SEC,
                response_format={"type": "json_object"},
                messages=messages,
                **vendor_options,
            )
        except Exception as exc:
            # A timeout is not a response-format compatibility problem. Fall
            # back immediately instead of waiting for another full timeout.
            if _is_timeout(server_module, exc):
                raise
            response = client.chat.completions.create(
                model=model,
                temperature=float(settings["llm_temperature"]),
                max_tokens=12000,
                timeout=AI_MASK_VISION_TIMEOUT_SEC,
                messages=messages,
                **vendor_options,
            )
        content = str(response.choices[0].message.content or "").strip()
        cleaner = getattr(server_module, "clean_json_markdown", None)
        cleaned = cleaner(content) if callable(cleaner) else content.strip().removeprefix("```json").removesuffix("```").strip()
        value = json.loads(cleaned)
        return value if isinstance(value, dict) else None
    finally:
        try:
            client.close()
        except Exception:
            pass


def _merge_match_results(primary: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(primary, dict):
        return fallback
    result = dict(primary)
    matches = [item for item in result.get("matches", []) or [] if isinstance(item, dict)]
    primary_groups = {str(item.get("group_id") or "") for item in matches}
    used_elements = {str(eid) for item in matches for eid in (item.get("element_ids") or [])}
    for item in fallback.get("matches", []) or []:
        gid = str(item.get("group_id") or "")
        if gid in primary_groups:
            continue
        candidate_ids = [str(eid) for eid in item.get("element_ids", []) if str(eid) not in used_elements]
        if not candidate_ids:
            continue
        merged = dict(item)
        merged["element_ids"] = candidate_ids
        matches.append(merged)
        used_elements.update(candidate_ids)
    result["matches"] = matches
    result["matching_method"] = "multimodal_with_deterministic_fallback"
    return result


def _clean_match(
    result: Any,
    slide: dict[str, Any],
    elements: list[dict[str, Any]],
    settings: dict[str, Any],
    fallback: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(result, dict):
        result = fallback
    known_beats = {str(b.get("id") or "") for b in slide.get("narration_beats", []) or [] if isinstance(b, dict)}
    narrated_group_ids = {
        str(b.get("group_id") or "")
        for b in slide.get("narration_beats", []) or []
        if isinstance(b, dict) and str(b.get("group_id") or "")
    }
    known_groups = {
        str(g.get("id") or "")
        for g in slide.get("visual_groups", []) or []
        if isinstance(g, dict) and str(g.get("id") or "") in narrated_group_ids
    }
    known_elements = {str(e.get("element_id") or "") for e in elements}
    matches = []
    used = set()
    for item in result.get("matches", []) or []:
        if not isinstance(item, dict):
            continue
        gid = str(item.get("group_id") or "")
        if gid not in known_groups:
            continue
        bid = str(item.get("narration_beat_id") or "")
        if bid and bid not in known_beats:
            bid = ""
        eids = [
            str(e) for e in item.get("element_ids", [])
            if str(e) in known_elements and str(e) not in used
        ][: int(settings["max_group_elements"])]
        if not eids:
            continue
        try:
            conf = float(item.get("confidence", 0))
        except Exception:
            conf = 0
        matches.append({"group_id": gid, "narration_beat_id": bid, "element_ids": eids, "confidence": conf, "reason": str(item.get("reason") or ""), "below_threshold": conf < float(settings["llm_confidence_threshold"])})
        used.update(eids)
    matched_groups = {str(item.get("group_id") or "") for item in matches}
    return {
        "slide_id": slide.get("slide_id"),
        "matches": matches,
        "unmatched_elements": sorted(known_elements - used),
        "unmatched_groups": sorted(known_groups - matched_groups),
        "warnings": result.get("warnings", []) if isinstance(result.get("warnings"), list) else [],
        "matching_method": result.get("matching_method") or fallback.get("matching_method") or "unknown",
    }


def _box_center(box: dict[str, Any]) -> tuple[float, float]:
    return (
        float(box.get("x", 0)) + float(box.get("w", 0)) / 2,
        float(box.get("y", 0)) + float(box.get("h", 0)) / 2,
    )


def _configured_title_regions(server_module: ModuleType, width: int, height: int) -> dict[str, dict[str, int]]:
    """Read the canonical title/subtitle zones and scale them to this slide."""
    defaults = {
        "main_title": {"x": 110, "y": 55, "w": 1600, "h": 86},
        "subtitle": {"x": 110, "y": 150, "w": 1600, "h": 52},
    }
    canvas_width, canvas_height = 1920, 1080
    try:
        tokens = server_module.read_style_tokens_data()
        canvas = tokens.get("canvas") if isinstance(tokens.get("canvas"), dict) else {}
        layout = tokens.get("layout") if isinstance(tokens.get("layout"), dict) else {}
        title_block = layout.get("title_block") if isinstance(layout.get("title_block"), dict) else {}
        canvas_width = max(1, int(canvas.get("width", canvas_width)))
        canvas_height = max(1, int(canvas.get("height", canvas_height)))
        for key in defaults:
            if isinstance(title_block.get(key), dict):
                defaults[key] = {**defaults[key], **title_block[key]}
    except Exception:
        pass

    scale_x, scale_y = width / canvas_width, height / canvas_height
    padding_x = max(4, round(24 * scale_x))
    padding_y = max(4, round(18 * scale_y))

    def scaled(source: dict[str, Any]) -> dict[str, int]:
        x1 = max(0, round(float(source.get("x", 0)) * scale_x) - padding_x)
        y1 = max(0, round(float(source.get("y", 0)) * scale_y) - padding_y)
        x2 = min(width, round((float(source.get("x", 0)) + float(source.get("w", 0))) * scale_x) + padding_x)
        y2 = min(height, round((float(source.get("y", 0)) + float(source.get("h", 0))) * scale_y) + padding_y)
        return {"x": x1, "y": y1, "w": max(1, x2 - x1), "h": max(1, y2 - y1)}

    main = scaled(defaults["main_title"])
    subtitle = scaled(defaults["subtitle"])
    x1 = min(main["x"], subtitle["x"])
    y1 = min(main["y"], subtitle["y"])
    x2 = max(main["x"] + main["w"], subtitle["x"] + subtitle["w"])
    y2 = max(main["y"] + main["h"], subtitle["y"] + subtitle["h"])
    return {
        "main_title": main,
        "subtitle": subtitle,
        "combined": {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1},
    }


def _element_ids_in_region(elements_payload: dict[str, Any], region: dict[str, Any]) -> list[str]:
    result: list[str] = []
    rx1, ry1, rx2, ry2 = _box_xyxy(region) or (0, 0, 0, 0)
    for element in [
        *(elements_payload.get("elements", []) or []),
        *(elements_payload.get("residual_elements", []) or []),
    ]:
        if not isinstance(element, dict):
            continue
        box = element.get("raw_bbox") if isinstance(element.get("raw_bbox"), dict) else element.get("bbox", {})
        bounds = _box_xyxy(box)
        if not bounds:
            continue
        x1, y1, x2, y2 = bounds
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        if rx1 <= cx <= rx2 and ry1 <= cy <= ry2:
            element_id = str(element.get("element_id") or "")
            if element_id:
                result.append(element_id)
    return result


def _speech_signature(value: Any) -> str:
    return "".join(char.casefold() for char in str(value or "") if char.isalnum())


def _consolidate_title_regions(
    match_payload: dict[str, Any],
    elements_payload: dict[str, Any],
    slide: dict[str, Any],
    regions: dict[str, dict[str, int]],
) -> dict[str, Any]:
    """Exclude the fixed title band from narration-driven Mask ownership.

    Main title and subtitle are persistent slide context. Revealing their
    disconnected glyphs with a narration group caused the first frame to look
    partially cut out and also let the first group swallow unrelated content.
    We therefore keep their exact foreground components as a static base layer
    and remove them from every narrated group.
    """
    visual_groups = [group for group in slide.get("visual_groups", []) or [] if isinstance(group, dict)]
    title_group_ids = {
        str(group.get("id") or "")
        for group in visual_groups
        if str(group.get("role") or "").strip().lower() in {"title", "subtitle"}
        and str(group.get("id") or "")
    }
    active_region = regions["combined"] if str(slide.get("subtitle") or "").strip() else regions["main_title"]
    static_ids = set(_element_ids_in_region(elements_payload, active_region))
    static_ids.update(str(value) for value in match_payload.get("static_element_ids", []) or [] if str(value))

    matches: list[dict[str, Any]] = []
    for original in match_payload.get("matches", []) or []:
        if not isinstance(original, dict):
            continue
        group_id = str(original.get("group_id") or "")
        if group_id in title_group_ids:
            continue
        item = dict(original)
        item["element_ids"] = [
            str(element_id)
            for element_id in item.get("element_ids", []) or []
            if str(element_id) and str(element_id) not in static_ids
        ]
        matches.append(item)

    forced_owners = {
        str(element_id): str(group_id)
        for element_id, group_id in (match_payload.get("forced_element_owners") or {}).items()
        if str(element_id) not in static_ids and str(group_id) not in title_group_ids
    }
    result = dict(match_payload)
    result["matches"] = matches
    result["forced_element_owners"] = forced_owners
    result["static_element_ids"] = sorted(static_ids)
    result["static_group_ids"] = sorted(title_group_ids)
    result["title_region_policy"] = "static_header_excluded_from_narration_masks"
    result["unmatched_groups"] = [
        group_id for group_id in result.get("unmatched_groups", []) or []
        if str(group_id) not in title_group_ids
    ]
    return result


def _ensure_narrated_group_anchors(
    match_payload: dict[str, Any],
    elements_payload: dict[str, Any],
    slide: dict[str, Any],
) -> dict[str, Any]:
    """Guarantee one independent visual-island seed per narrated group."""
    beats = [beat for beat in slide.get("narration_beats", []) or [] if isinstance(beat, dict)]
    static_group_ids = {str(value) for value in match_payload.get("static_group_ids", []) or [] if str(value)}
    narrated_group_ids = list(dict.fromkeys(
        str(beat.get("group_id") or "") for beat in beats
        if str(beat.get("group_id") or "") and str(beat.get("group_id") or "") not in static_group_ids
    ))
    if not narrated_group_ids:
        return match_payload
    beat_by_group = {
        str(beat.get("group_id") or ""): str(beat.get("id") or "")
        for beat in beats
        if str(beat.get("group_id") or "")
    }
    matches = [dict(item) for item in match_payload.get("matches", []) or [] if isinstance(item, dict)]
    accepted_by_group = {
        str(item.get("group_id") or ""): item
        for item in matches
        if str(item.get("group_id") or "") in narrated_group_ids
        and not item.get("below_threshold")
        and item.get("element_ids")
    }
    missing_group_ids = [group_id for group_id in narrated_group_ids if group_id not in accepted_by_group]
    if not missing_group_ids:
        return match_payload

    all_elements = [
        element for element in [
            *(elements_payload.get("elements", []) or []),
            *(elements_payload.get("residual_elements", []) or []),
        ] if isinstance(element, dict) and str(element.get("element_id") or "")
    ]
    forced_owners = dict(match_payload.get("forced_element_owners") or {})
    title_locked_ids = set(forced_owners) | {
        str(value) for value in match_payload.get("static_element_ids", []) or [] if str(value)
    }
    canvas = elements_payload.get("canvas", {}) if isinstance(elements_payload.get("canvas"), dict) else {}
    canvas_area = max(1, int(canvas.get("width", 1920))) * max(1, int(canvas.get("height", 1080)))
    prominent_area = max(400, round(canvas_area * 0.003))
    by_id = {str(element.get("element_id") or ""): element for element in all_elements}
    # Keep one strongest existing seed per accepted group. Missing groups may
    # claim other components, but can never empty an already accepted group.
    protected_anchor_ids: set[str] = set()
    for item in accepted_by_group.values():
        owned = [by_id[str(element_id)] for element_id in item.get("element_ids", []) or [] if str(element_id) in by_id]
        if owned:
            protected_anchor_ids.add(str(max(owned, key=lambda element: int(element.get("area", 0))).get("element_id") or ""))
    unavailable_ids = title_locked_ids | protected_anchor_ids
    available = [element for element in all_elements if str(element.get("element_id") or "") not in unavailable_ids]
    available.sort(key=lambda element: int(element.get("area", 0)), reverse=True)
    prominent = [element for element in available if int(element.get("area", 0)) >= prominent_area]
    candidates = [*prominent, *[element for element in available if element not in prominent]]

    claimed_seed_ids: set[str] = set()
    for group_id in missing_group_ids:
        seed = next(
            (
                element for element in candidates
                if str(element.get("element_id") or "") not in claimed_seed_ids
                and str(element.get("element_id") or "") not in forced_owners
            ),
            None,
        )
        if seed is None:
            continue
        seed_id = str(seed.get("element_id") or "")
        claimed_seed_ids.add(seed_id)
        for item in matches:
            item["element_ids"] = [str(element_id) for element_id in item.get("element_ids", []) or [] if str(element_id) != seed_id]
        seeded = {
            "group_id": group_id,
            "narration_beat_id": beat_by_group.get(group_id, ""),
            "element_ids": [seed_id],
            "confidence": 0.82,
            "reason": "deterministic prominent visual-island anchor",
            "below_threshold": False,
        }
        matches.append(seeded)
        forced_owners[seed_id] = group_id

    anchored_groups = {
        str(item.get("group_id") or "") for item in matches
        if not item.get("below_threshold") and item.get("element_ids")
    }
    result = dict(match_payload)
    result["matches"] = matches
    result["forced_element_owners"] = forced_owners
    result["unmatched_groups"] = [group_id for group_id in narrated_group_ids if group_id not in anchored_groups]
    result["anchor_policy"] = "one_visual_island_per_narrated_group"
    return result


def _complete_component_coverage(
    match_payload: dict[str, Any],
    elements_payload: dict[str, Any],
) -> dict[str, Any]:
    """Assign every foreground component to exactly one accepted narration group.

    The multimodal model chooses semantic anchors. Remaining visual-only,
    decorative, and tiny antialiased components are attached to the closest
    anchor by reading-row proximity. Anchor boxes are frozen before completion
    so a large decoration cannot pull later components into the wrong group.
    """
    candidates = [e for e in elements_payload.get("elements", []) or [] if isinstance(e, dict)]
    residual = [e for e in elements_payload.get("residual_elements", []) or [] if isinstance(e, dict)]
    complete_foreground = candidates + residual
    static_element_ids = {
        str(value) for value in match_payload.get("static_element_ids", []) or [] if str(value)
    }
    static_elements = [
        element for element in complete_foreground
        if str(element.get("element_id") or "") in static_element_ids
    ]
    all_elements = [
        element for element in complete_foreground
        if str(element.get("element_id") or "") not in static_element_ids
    ]
    by_id = {str(e.get("element_id") or ""): e for e in all_elements if str(e.get("element_id") or "")}
    accepted = [
        item for item in match_payload.get("matches", []) or []
        if isinstance(item, dict) and not item.get("below_threshold") and item.get("element_ids")
    ]
    original_owner = {
        str(element_id): str(item.get("group_id") or "")
        for item in accepted
        for element_id in item.get("element_ids", []) or []
        if str(element_id) in by_id
    }
    assigned: set[str] = set()
    forced_owners = {
        str(element_id): str(group_id)
        for element_id, group_id in (match_payload.get("forced_element_owners") or {}).items()
        if str(element_id) and str(group_id)
    }
    anchors: dict[str, dict[str, float]] = {}
    canvas = elements_payload.get("canvas", {}) if isinstance(elements_payload.get("canvas"), dict) else {}
    width = max(1, int(canvas.get("width", 1920)))
    height = max(1, int(canvas.get("height", 1080)))
    for item in accepted:
        anchor_elements = [
            by_id[str(element_id)]
            for element_id in item.get("element_ids", []) or []
            if str(element_id) in by_id
        ]
        boxes = [element.get("raw_bbox", element.get("bbox", {})) for element in anchor_elements]
        if not boxes:
            continue
        largest = max(anchor_elements, key=lambda element: int(element.get("area", 0)))
        largest_box = largest.get("raw_bbox", largest.get("bbox", {}))
        largest_bounds = _box_xyxy(largest_box)
        if not largest_bounds:
            continue
        lx1, ly1, lx2, ly2 = largest_bounds
        dominant_w, dominant_h = lx2 - lx1, ly2 - ly1
        dominant_area = max(1, int(largest.get("area", 0)))
        absorb_padding = max(28.0, min(140.0, 0.18 * max(dominant_w, dominant_h)))

        # Build an island envelope from the dominant component plus only the
        # seed components that are genuinely adjacent to it. A stray semantic
        # ID on the other side of the page must not stretch the envelope.
        clustered_bounds: list[tuple[float, float, float, float]] = [largest_bounds]
        for box in boxes:
            bounds = _box_xyxy(box)
            if not bounds or bounds == largest_bounds:
                continue
            cx, cy = _box_center(box)
            dx = max(lx1 - cx, 0.0, cx - lx2)
            dy = max(ly1 - cy, 0.0, cy - ly2)
            if float(np.hypot(dx, dy)) <= absorb_padding:
                clustered_bounds.append(bounds)
        ax1 = min(value[0] for value in clustered_bounds)
        ay1 = min(value[1] for value in clustered_bounds)
        ax2 = max(value[2] for value in clustered_bounds)
        ay2 = max(value[3] for value in clustered_bounds)
        anchors[str(item.get("group_id") or "")] = {
            "x": ax1,
            "y": ay1,
            "w": max(1.0, ax2 - ax1),
            "h": max(1.0, ay2 - ay1),
            "absorb_padding": absorb_padding,
            "dominant_area": float(dominant_area),
        }

    # Repartition every component instead of trusting individual LLM IDs. The
    # model establishes semantic group anchors; deterministic geometry then
    # removes occasional cross-row/cross-card ID mistakes and fills omissions.
    for item in accepted:
        item["element_ids"] = []
    unassigned = list(all_elements)
    if accepted and anchors:
        distance_scale = float(max(1, min(width, height)))

        def box_distance(anchor: dict[str, float], element_box: dict[str, Any]) -> float:
            bounds = _box_xyxy(element_box)
            anchor_bounds = _box_xyxy(anchor)
            if not bounds or not anchor_bounds:
                return float("inf")
            ex1, ey1, ex2, ey2 = bounds
            ax1, ay1, ax2, ay2 = anchor_bounds
            dx = max(ax1 - ex2, 0.0, ex1 - ax2)
            dy = max(ay1 - ey2, 0.0, ey1 - ay2)
            return float(np.hypot(dx, dy))

        def inside_absorption_envelope(anchor: dict[str, float], cx: float, cy: float) -> bool:
            bounds = _box_xyxy(anchor)
            if not bounds:
                return False
            x1, y1, x2, y2 = bounds
            padding = float(anchor.get("absorb_padding", 28.0))
            return x1 - padding <= cx <= x2 + padding and y1 - padding <= cy <= y2 + padding

        def score(item: dict[str, Any], element_box: dict[str, Any], cx: float, cy: float) -> float:
            anchor = anchors[str(item.get("group_id") or "")]
            center_x, center_y = _box_center(anchor)
            edge_distance = box_distance(anchor, element_box) / distance_scale
            center_distance = float(np.hypot(cx - center_x, cy - center_y)) / distance_scale
            absorption_bonus = 0.12 if inside_absorption_envelope(anchor, cx, cy) else 0.0
            return edge_distance + 0.16 * center_distance - absorption_bonus

        for element in sorted(unassigned, key=lambda item: (float((item.get("center") or {}).get("y", 0)), float((item.get("center") or {}).get("x", 0)))):
            box = element.get("raw_bbox") if isinstance(element.get("raw_bbox"), dict) else element.get("bbox", {})
            cx, cy = _box_center(box)
            element_id = str(element.get("element_id") or "")
            original_group_id = original_owner.get(element_id, "")
            forced_group_id = forced_owners.get(element_id, "")
            forced = next((item for item in accepted if str(item.get("group_id") or "") == forced_group_id), None)
            if forced is not None:
                forced.setdefault("element_ids", []).append(element_id)
                assigned.add(element_id)
                continue
            choices = list(accepted)
            absorbing_choices = [
                item for item in choices
                if inside_absorption_envelope(anchors[str(item.get("group_id") or "")], cx, cy)
            ]
            if absorbing_choices:
                choices = absorbing_choices
            best = min(choices, key=lambda item: score(item, box, cx, cy))
            original = next(
                (item for item in choices if str(item.get("group_id") or "") == original_group_id),
                None,
            )
            if original is not None and score(original, box, cx, cy) <= score(best, box, cx, cy) + 0.025:
                best = original
            best.setdefault("element_ids", []).append(str(element.get("element_id") or ""))
            assigned.add(str(element.get("element_id") or ""))

    unassigned_ids = sorted(set(by_id) - assigned)
    target_rle = _merge_row_runs(complete_foreground, width, height)
    foreground_pixels = _rle_pixel_count(target_rle)
    group_rles = [
        _merge_row_runs(
            [by_id[str(element_id)] for element_id in item.get("element_ids", []) or [] if str(element_id) in by_id],
            width,
            height,
        )
        for item in accepted
    ]
    assigned_elements = [by_id[element_id] for element_id in assigned if element_id in by_id]
    dynamic_assigned_rle = _merge_row_runs(assigned_elements, width, height)
    dynamic_assigned_pixels = _rle_pixel_count(dynamic_assigned_rle)
    assigned_rle = _merge_row_runs([*assigned_elements, *static_elements], width, height)
    assigned_pixels = _rle_pixel_count(assigned_rle)
    group_pixel_sum = sum(_rle_pixel_count(rle) for rle in group_rles)
    overlap_pixels = max(0, group_pixel_sum - dynamic_assigned_pixels)
    coverage = assigned_pixels / foreground_pixels if foreground_pixels else 0.0
    quality = {
        "version": "ai_mask_quality_v1",
        "foreground_pixel_count": foreground_pixels,
        "assigned_foreground_pixel_count": assigned_pixels,
        "static_header_pixel_count": _rle_pixel_count(_merge_row_runs(static_elements, width, height)),
        "foreground_coverage_ratio": round(coverage, 6),
        "unassigned_component_count": len(unassigned_ids),
        "overlap_pixel_count": overlap_pixels,
        "exclusive_component_ownership": overlap_pixels == 0,
        "passed": bool(accepted) and not unassigned_ids and coverage >= 0.995 and overlap_pixels == 0,
    }
    match_payload["unmatched_elements"] = unassigned_ids
    match_payload["quality"] = quality
    if quality["passed"]:
        match_payload["warnings"] = []
    match_payload["matching_method"] = str(match_payload.get("matching_method") or "unknown") + "+exact_component_completion"
    match_payload["component_assignment_policy"] = "dominant_island_2d_absorption_v2"
    return match_payload


def _exact_manual_mask(elements: list[dict[str, Any]], width: int, height: int, color: str) -> dict[str, Any]:
    rle = _merge_row_runs(elements, width, height)
    bounds = _rle_bounds(rle)
    if bounds is None:
        raise RuntimeError("Exact AI Mask contains no foreground pixels")
    return {
        "source": "ai_auto_mask_v3_exact_rle",
        "color": color,
        "bounds": bounds,
        "rle": rle,
        "strokes": [],
    }


def _has_manual(group: dict[str, Any]) -> bool:
    manual = group.get("manual_mask") if isinstance(group.get("manual_mask"), dict) else {}
    runs = manual.get("rle", {}).get("runs") if isinstance(manual.get("rle"), dict) else []
    strokes = manual.get("strokes")
    return bool(runs) or (isinstance(strokes, list) and any(isinstance(s, dict) and s.get("points") for s in strokes))


def _find_group(groups: list[dict[str, Any]], gid: str) -> dict[str, Any] | None:
    for group in groups:
        if not isinstance(group, dict):
            continue
        identifiers = {
            str(group.get("id") or ""),
            str(group.get("group_id") or ""),
            str(group.get("visual_group_id") or ""),
        }
        if gid in identifiers:
            return group
    return None


def _migrate_legacy_default_reveal(group: dict[str, Any]) -> None:
    """Replace only the old default wipe, preserving deliberate custom animation."""
    reveal = group.get("reveal") if isinstance(group.get("reveal"), dict) else {}
    if not reveal:
        # Semantic groups created by AI Mask do not necessarily originate from
        # the coordinate template.  Give those groups the current production
        # default explicitly; otherwise the scene builder falls back to its
        # historical 0.75 s duration and the picture is still animating after
        # the narration has begun.
        group["reveal"] = {
            "type": "crop_fade_up",
            "duration": 0.25,
            "auto_default": True,
        }
        return
    reveal_type = str(reveal.get("type") or "")
    try:
        duration = float(reveal.get("duration", 0.0) or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    if reveal_type == "wipe_left_to_right" and abs(duration - 0.75) <= 0.001:
        group["reveal"] = {"type": "crop_fade_up", "duration": 0.25, "auto_migrated": True}


def _apply(manifest: dict[str, Any], slide: dict[str, Any], elements_payload: dict[str, Any], match_payload: dict[str, Any], settings: dict[str, Any]) -> dict[str, int]:
    slide_id = str(slide.get("slide_id") or "")
    mslide = next((s for s in manifest.get("slides", []) if isinstance(s, dict) and str(s.get("slide_id") or "") == slide_id), None)
    if not mslide:
        raise RuntimeError(f"Missing reveal manifest slide: {slide_id}")
    groups = mslide.setdefault("groups", [])
    semantic = mslide.setdefault("semantic_blocks", [])
    canvas = elements_payload.get("canvas", {})
    width, height = int(canvas.get("width", 1920)), int(canvas.get("height", 1080))
    by_element = {
        e["element_id"]: e
        for e in (elements_payload.get("elements", []) or []) + (elements_payload.get("residual_elements", []) or [])
        if isinstance(e, dict) and e.get("element_id")
    }
    updated = skipped = 0
    static_element_ids = [
        str(value) for value in match_payload.get("static_element_ids", []) or []
        if str(value) in by_element
    ]
    static_group_ids = {
        str(value) for value in match_payload.get("static_group_ids", []) or [] if str(value)
    }
    # Remove any former title/subtitle paint so it cannot be rebuilt as a
    # narration-driven crop. The exact title pixels are stored in one hidden
    # static group that the scene builder composites into base_slide.png.
    for collection in (groups, semantic):
        collection[:] = [
            group for group in collection
            if not (
                isinstance(group, dict)
                and (
                    str(group.get("id") or group.get("group_id") or group.get("visual_group_id") or "") in static_group_ids
                    or str(group.get("role") or "").strip().lower() in {"title", "subtitle"}
                    or bool(group.get("is_static_header"))
                )
            )
        ]
    if static_element_ids:
        static_mask = _exact_manual_mask(
            [by_element[element_id] for element_id in static_element_ids],
            width,
            height,
            "#000000",
        )
        groups.append({
            "id": "__static_title_header__",
            "group_id": "__static_title_header__",
            "role": "background",
            "visible_text": "固定标题区",
            "box": dict(static_mask["bounds"]),
            "manual_mask": static_mask,
            "is_static": True,
            "is_static_header": True,
            "link_to_narration": False,
            "review_status": "ai_static",
            "source": "ai_static_header",
            "z_index": 5,
        })
    visual_group_order = {
        str(group.get("id") or ""): index
        for index, group in enumerate(slide.get("visual_groups", []) or [])
        if isinstance(group, dict)
    }
    matches = [match for match in match_payload.get("matches", []) or [] if isinstance(match, dict)]
    valid_match_group_ids = {
        str(match.get("group_id") or "")
        for match in matches
        if not match.get("below_threshold")
        and any(str(element_id) in by_element for element_id in match.get("element_ids", []) or [])
    }
    for match in matches:
        gid = str(match.get("group_id") or "")
        if match.get("below_threshold"):
            # Vision and the deterministic fallback can both report the same
            # group.  A low-confidence/empty vision candidate is not a real
            # omission when a later fallback candidate successfully owns the
            # group, and static title groups are intentionally not dynamic.
            if gid not in valid_match_group_ids and gid not in static_group_ids:
                skipped += 1
            continue
        matched_elements = [by_element[eid] for eid in match.get("element_ids", []) if eid in by_element]
        if not matched_elements:
            if gid not in valid_match_group_ids and gid not in static_group_ids:
                skipped += 1
            continue
        exact_mask = _exact_manual_mask(matched_elements, width, height, MASK_COLORS[visual_group_order.get(gid, 0) % len(MASK_COLORS)])
        box = dict(exact_mask["bounds"])
        semantic_group = _find_group(semantic, gid)
        display_group_id = str((semantic_group or {}).get("group_id") or (semantic_group or {}).get("id") or gid)
        color = MASK_COLORS[visual_group_order.get(gid, 0) % len(MASK_COLORS)]
        for collection in (groups, semantic):
            group = _find_group(collection, gid)
            if group is None:
                group = {
                    "id": display_group_id,
                    "group_id": display_group_id,
                    "visual_group_id": gid,
                    "role": "body_content",
                    "visible_text": gid,
                    "padding_px": 32,
                    "z_index": 40 + len(collection),
                }
                collection.append(group)
            _migrate_legacy_default_reveal(group)
            if settings["skip_locked_groups"] and str(group.get("review_status") or "") in {"approved", "locked"}:
                continue
            if _has_manual(group) and not settings["overwrite_existing_manual_mask"]:
                continue
            group["box"] = box
            group["visual_group_id"] = gid
            group["manual_mask"] = {
                **exact_mask,
                "color": color,
            }
            group["review_status"] = "ai_matched"
            group["source"] = "ai_auto_mask"
            if match.get("narration_beat_id"):
                group["narration_beat_id"] = match["narration_beat_id"]
            group["auto_mask"] = {
                "version": "auto_mask_v3_exact_rle",
                "method": "multimodal_exact_connected_components_v3",
                "element_ids": match.get("element_ids", []),
                "bbox": box,
                "compatible_manual_corrections": True,
                "exclusive_pixel_ownership": True,
            }
            group["ai_match"] = {"confidence": match.get("confidence"), "reason": match.get("reason", "")}
        updated += 1
    mslide["ai_mask_status"] = {
        "version": "ai_mask_annotation_v3_exact_rle",
        "updated_group_count": updated,
        "skipped_group_count": skipped,
        "detected_element_count": len(elements_payload.get("elements", [])),
        "residual_component_count": len(elements_payload.get("residual_elements", [])),
        "quality": match_payload.get("quality", {}),
    }
    return {"updated": updated, "skipped": skipped}


def _get_store_settings(server_module: ModuleType) -> dict[str, Any]:
    raw = {key: server_module.get_setting(SETTING_PREFIX + key, str(default)) for key, default in DEFAULT_SETTINGS.items()}
    return normalize_settings(raw)


def _save_store_settings(server_module: ModuleType, payload: dict[str, Any]) -> dict[str, Any]:
    values = payload.get("settings") if isinstance(payload.get("settings"), dict) else payload
    settings = normalize_settings(values if isinstance(values, dict) else {})
    update = {SETTING_PREFIX + key: value for key, value in settings.items()}
    prompts = payload.get("prompts") if isinstance(payload.get("prompts"), dict) else {}
    if str(prompts.get("methodology") or "").strip():
        update[PROMPT_METHOD_KEY] = prompts["methodology"]
    if str(prompts.get("output_structure") or "").strip():
        update[PROMPT_OUTPUT_KEY] = prompts["output_structure"]
    server_module.update_settings(update)
    return settings


def _annotate_project(server_module: ModuleType, project: Any, settings: dict[str, Any]) -> dict[str, Any]:
    run_dir = Path(project.run_dir)
    contract = _read_json(run_dir / "planning" / "visual_contract.json")
    manifest = _read_json(run_dir / "reveal_manifest.json")
    methodology, output_structure = _read_ai_mask_prompts(server_module)
    prepared: list[dict[str, Any]] = []
    for slide in contract.get("slides", []) or []:
        if not isinstance(slide, dict):
            continue
        slide_id = str(slide.get("slide_id") or "")
        slide_dir = run_dir / "slides" / slide_id
        image_path = slide_dir / "visual_draft.png"
        elements = detect_elements(image_path, slide_dir, settings)
        canvas = elements.get("canvas", {}) if isinstance(elements.get("canvas"), dict) else {}
        title_regions = _configured_title_regions(
            server_module,
            max(1, int(canvas.get("width", 1920))),
            max(1, int(canvas.get("height", 1080))),
        )
        element_list = elements.get("elements", [])
        manifest_slide = next(
            (
                item for item in manifest.get("slides", []) or []
                if isinstance(item, dict) and str(item.get("slide_id") or "") == slide_id
            ),
            {},
        )
        fallback = _fallback_match(slide, element_list, manifest_slide)
        prepared.append({
            "slide": slide,
            "slide_id": slide_id,
            "slide_dir": slide_dir,
            "image_path": image_path,
            "elements": elements,
            "element_list": element_list,
            "fallback": fallback,
            "title_regions": title_regions,
        })

    def match_slide(item: dict[str, Any]) -> dict[str, Any]:
        vision_started = time.monotonic()
        resolved_model, configured_model = _resolved_vision_model(server_module)
        try:
            raw_vision = _vision_match(
                server_module,
                project,
                item["slide"],
                item["element_list"],
                item["image_path"],
                item["slide_dir"] / "auto_mask" / "candidate_overlay.png",
                methodology,
                output_structure,
                settings,
            )
            raw = _merge_match_results(raw_vision, item["fallback"])
        except Exception as exc:
            logger = getattr(server_module, "logger", None)
            if logger is not None:
                logger.warning("AI Mask multimodal match failed for %s; using deterministic prior: %s", item["slide_id"], exc)
            try:
                server_module.write_project_log(
                    project,
                    "ai_mask_vision_failed",
                    slide_id=item["slide_id"],
                    elapsed_sec=round(time.monotonic() - vision_started, 2),
                    timeout=_is_timeout(server_module, exc),
                    error_type=type(exc).__name__,
                    error=str(exc)[:500],
                    configured_vision_model=configured_model,
                    resolved_vision_model=resolved_model,
                    thinking_disabled=bool(getattr(server_module, "step2_llm_vendor_options", lambda *_: {})(resolved_model, server_module.get_setting("llm_base_url"))),
                )
            except Exception:
                pass
            raw = item["fallback"]
        cleaned = _clean_match(raw, item["slide"], item["element_list"], settings, item["fallback"])
        cleaned = _consolidate_title_regions(cleaned, item["elements"], item["slide"], item["title_regions"])
        cleaned = _ensure_narrated_group_anchors(cleaned, item["elements"], item["slide"])
        return _complete_component_coverage(cleaned, item["elements"])

    matches: dict[str, dict[str, Any]] = {}
    if prepared:
        with ThreadPoolExecutor(max_workers=min(3, len(prepared)), thread_name_prefix="ai-mask-match") as executor:
            futures = {executor.submit(match_slide, item): item["slide_id"] for item in prepared}
            for future in as_completed(futures):
                matches[futures[future]] = future.result()

    slides_out = []
    total_updated = 0
    total_unmatched_groups = 0
    total_skipped = 0
    quality_passed = True
    for item in prepared:
        slide_id = item["slide_id"]
        match = matches[slide_id]
        _write_json(item["slide_dir"] / "auto_mask" / "auto_match.json", match)
        applied = _apply(manifest, item["slide"], item["elements"], match, settings)
        total_updated += applied["updated"]
        total_skipped += applied["skipped"]
        unmatched_group_count = len(match.get("unmatched_groups", []))
        total_unmatched_groups += unmatched_group_count
        slide_quality = match.get("quality", {}) if isinstance(match.get("quality"), dict) else {}
        quality_passed = quality_passed and bool(slide_quality.get("passed"))
        slides_out.append({"slide_id": slide_id, "detected_element_count": len(item["element_list"]), "residual_component_count": len(item["elements"].get("residual_elements", [])), "matched_group_count": len(match.get("matches", [])), "updated_group_count": applied["updated"], "skipped_group_count": applied["skipped"], "unmatched_element_count": len(match.get("unmatched_elements", [])), "unmatched_group_count": unmatched_group_count, "matching_method": match.get("matching_method"), "quality": slide_quality, "warnings": match.get("warnings", [])})
    complete = total_unmatched_groups == 0 and total_skipped == 0 and total_updated > 0 and quality_passed
    manifest["ai_mask_annotation"] = {
        "version": "ai_mask_annotation_v3_exact_rle",
        "status": "completed" if complete else "incomplete",
        "settings": settings,
        "processed_slide_count": len(slides_out),
        "updated_group_count": total_updated,
        "unmatched_group_count": total_unmatched_groups,
        "skipped_group_count": total_skipped,
        "quality_passed": quality_passed,
    }
    _write_json(run_dir / "reveal_manifest.json", manifest)
    return {"success": True, "complete": complete, "processed_slide_count": len(slides_out), "updated_group_count": total_updated, "unmatched_group_count": total_unmatched_groups, "slides": slides_out, "manifest_path": str(run_dir / "reveal_manifest.json")}


def _register(server_module: ModuleType) -> bool:
    if getattr(server_module, PATCH_MARKER, False):
        return True
    required = ("app", "Project", "HTTPException", "Depends", "get_db", "get_openai_client", "update_settings", "get_setting", "reveal_lock_for", "write_project_log")
    if not all(hasattr(server_module, item) for item in required):
        return False
    app = server_module.app

    async def get_ai_mask_settings() -> dict[str, Any]:
        methodology, output_structure = _read_ai_mask_prompts(server_module)
        return {
            "success": True,
            "settings": _get_store_settings(server_module),
            "prompts": {
                "methodology": methodology,
                "output_structure": output_structure,
                "full_prompt": _compose_ai_mask_full_prompt(methodology, output_structure),
            },
        }

    async def put_ai_mask_settings(payload: dict[str, Any]) -> dict[str, Any]:
        return {"success": True, "settings": _save_store_settings(server_module, payload if isinstance(payload, dict) else {})}

    def annotate_step5(project_id: str, payload: dict[str, Any] | None = None, db: Any = server_module.Depends(server_module.get_db)) -> dict[str, Any]:
        project = db.query(server_module.Project).filter(server_module.Project.id == project_id).first()
        if not project:
            raise server_module.HTTPException(status_code=404, detail="项目不存在")
        settings = _get_store_settings(server_module)
        if isinstance(payload, dict) and isinstance(payload.get("settings"), dict):
            settings = normalize_settings({**settings, **payload["settings"]})
        with server_module.reveal_lock_for(project):
            result = _annotate_project(server_module, project, settings)
        try:
            server_module.write_project_log(project, "ai_mask_annotation", **result)
        except Exception:
            pass
        return result

    app.add_api_route("/api/settings/ai-mask", get_ai_mask_settings, methods=["GET"])
    app.add_api_route("/api/settings/ai-mask", put_ai_mask_settings, methods=["PUT"])
    app.add_api_route("/api/projects/{project_id}/steps/5/ai-mask/annotate", annotate_step5, methods=["POST"])
    app.add_api_route("/api/projects/{project_id}/steps/4/ai-mask/annotate", annotate_step5, methods=["POST"])
    setattr(server_module, PATCH_MARKER, True)
    return True


def _candidate_modules() -> list[ModuleType]:
    return [m for m in list(sys.modules.values()) if isinstance(m, ModuleType) and hasattr(m, "app") and hasattr(m, "Project")]


def _install_when_ready() -> None:
    def worker() -> None:
        while not os.environ.get("PPT_STUDIO_DISABLE_AI_MASK_RUNTIME"):
            for module in _candidate_modules():
                try:
                    if _register(module):
                        return
                except Exception:
                    return
            time.sleep(0.1)
    threading.Thread(target=worker, name="ppt-ai-mask-runtime", daemon=True).start()


_install_when_ready()
