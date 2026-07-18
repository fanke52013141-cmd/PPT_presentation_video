"""Automatic multimodal AI Mask annotation routes.

The annotator detects exact foreground components, associates every component
with one narrated visual group, and writes mutually-exclusive pixel masks into
``reveal_manifest.json``. Brush strokes remain available as manual corrections
on top of the automatic base mask.
"""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import io
import json
import time
from collections import deque
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from scripts.visual_group_semantics import visual_group_atomicity_issues

PATCH_MARKER = "__ppt_ai_mask_runtime_patch__"
SETTING_PREFIX = "ai_mask_"

DEFAULT_SETTINGS: dict[str, Any] = {
    "white_threshold": 245,
    "color_tolerance": 12,
    "closing_radius": 6,
    "add_border": 2,
    "connectivity": 8,
    "min_element_area": 120,
    "component_padding_px": 12,
    "max_group_elements": 60,
    "llm_confidence_threshold": 0.72,
    "llm_temperature": 0.1,
    "overwrite_existing_manual_mask": False,
    "overwrite_existing_ai_mask": True,
    "skip_locked_groups": True,
}

MASK_COLORS = (
    "#E84A5F", "#1B998B", "#F6AE2D", "#3D5A80",
    "#7B2CBF", "#2F80ED", "#D45113", "#4C956C",
)
AI_MASK_VISION_TIMEOUT_SEC = 180.0
AI_MASK_MIN_FOREGROUND_COVERAGE = 0.995

DEFAULT_METHODOLOGY = """你是中文 PPT 视频的 AI Mask 语义标注专家。

## 目的
把自动检测到的语义对象绑定到当前 Slide 已有的 visual_groups 与 narration_beats，为后续生成安全、可复核的 Reveal Mask 提供匹配结果；不重写分镜或旁白。

## 系统背景
visual_group 是最小的 Mask/Reveal 原子。AI Mask 只能匹配已有语块，不能创建、拆分或改写 visual_group。若上游把多个独立视觉岛错误地塞进一个语块，你必须明确报告结构冲突，不能把“所有像素都有归属”误判为“语义分组正确”。

## 输入
- 当前 Slide 的 visual_groups、narration_beats 与 semantic_objects。
- image_full：未画框的完整原图，用于理解全局版式、阅读顺序和真实语义。
- object_XXX：语义对象切片，包含 object_id、element_ids 和 bbox。
- 所有返回 ID 必须来自输入，不得创造新 ID。

## 任务
完成“画面语义对象 → 已有语块 → 演讲稿 beat”的匹配。你不是重新生成分镜，也不是重写演讲稿。

## 匹配规则
1. `group_id` 只能使用输入 `visual_groups[].id`，不得发明新 group。
2. `narration_beat_id` 只能使用输入 `narration_beats[].id`。
3. 优先匹配 `semantic_objects[].object_id`；输出 `element_ids` 时使用所选对象的完整集合，不只挑碎片。
4. 一个标题行、标签行、卡片、配图、图标组合或流程节点通常是一个完整对象，不因字形不粘连、颜色不同或边框断开而拆散。
5. 页面上方只保留一个完整主标题，不使用页面副标题。主标题即使包含多种颜色、描边或断开的字形，也必须视为同一个语义对象：有 title narration beat 时整体绑定到唯一 title group；没有时整个标题保持静态，绝不能回退绑定到正文 group。
6. 优先匹配 `visible_text`、`visual_anchor`、`spoken_text`，再结合二维位置、role 和阅读顺序。
7. 同一语块可以绑定多个空间连续、共同服务于同一叙事时刻的对象，例如主配图与其内部标签；不能仅因主题相同就跨越明显留白合并对象。
8. 对比两侧、多个独立卡片、多个独立步骤或相距很远的视觉岛，如果表达不同子结论，必须分别绑定到不同 narration beat，不得合并为一个 Mask。
9. 匹配前执行结构审计：如果画面明显包含多个应分别 Reveal 的语义对象，但输入只提供一个正文 visual_group/narration beat，不得假装结构正确。仍按已有 ID 返回最可靠匹配，同时在 `warnings` 中加入 `type="insufficient_visual_groups_for_independent_objects"`，列出 object_ids 和原因，交由质量门阻止静默合并。
10. 不确定时降低 confidence。装饰或无口播对象放入 unmatched 列表，不得在模型输出中仅为达到覆盖率而强行匹配。
11. 只输出严格 JSON，不要 Markdown、解释或额外文字。

## 输出
严格遵循系统另行提供的“OUTPUT STRUCTURE / 输出结构”，只返回一个 JSON object。
"""

DEFAULT_OUTPUT_STRUCTURE = """必须输出一个 JSON object：
{
  "slide_id": "slide_001",
  "matches": [
    {
      "group_id": "body_group_01",
      "narration_beat_id": "beat_01",
      "object_ids": ["obj_010"],
      "element_ids": ["el_auto_010", "el_auto_011"],
      "confidence": 0.95,
      "reason": "obj_010 是完整语义对象，包含主配图与紧邻标签，并共同对应 beat_01"
    }
  ],
  "unmatched_objects": [],
  "unmatched_elements": [],
  "unmatched_groups": [],
  "warnings": [
    {
      "type": "insufficient_visual_groups_for_independent_objects",
      "object_ids": ["obj_010", "obj_020"],
      "reason": "两个对象空间分离且表达不同子结论，但输入只有一个正文语块"
    }
  ]
}

约束：group_id 必须来自 visual_groups[].id；narration_beat_id 必须来自 narration_beats[].id；object_ids 必须来自 semantic_objects[].object_id；element_ids 必须来自 semantic_objects[].element_ids 或 auto_elements[].element_id；confidence 是 0 到 1 的数字。没有结构冲突时 warnings 输出空数组。
"""

PROMPT_METHOD_KEY = SETTING_PREFIX + "match_methodology_system_content"
PROMPT_OUTPUT_KEY = SETTING_PREFIX + "match_output_structure_system_content"
LEGACY_TITLE_RULE = "6. 主标题与副标题是否属于同一个 Mask，以 narration_beats 的讲解关系为准，不按字体颜色、断笔或字间距拆分。"
STATIC_TITLE_RULE = "6. 页面上方固定主标题/副标题区域属于静态上下文，不分配给任何 narration group，不参与逐语块 Reveal；元素匹配必须同时考虑横向与纵向距离；大面积主配图应吸收其内部、边界上和紧邻的图标、对号、标签与说明，除非它们明确对应独立 narration beat；不允许因为颜色相似就跨卡片、跨栏或跨配图分配。"
PREVIOUS_TITLE_AND_ISLAND_RULES = """6. 页面上方主标题/副标题保持固定布局，但有 narration 绑定时必须参与逐语块 Reveal；副标题优先绑定独立 subtitle group，没有独立组时与主标题共同绑定到首个标题 narration group；元素匹配必须同时考虑横向与纵向距离；大面积主配图应吸收其内部、边界上和紧邻的图标、对号、标签与说明，除非它们明确对应独立 narration beat；不允许因为颜色相似就跨卡片、跨栏或跨配图分配。"""
CURRENT_TITLE_AND_ISLAND_RULES = """6. 页面上方只保留一个完整主标题，不使用页面副标题。无论主标题包含多少颜色、描边、断笔或分离字形，都必须整体绑定到唯一的 title group，不能拆给多个正文 group；如果不存在 title narration beat，则整个标题保持静态。元素匹配必须同时考虑横向与纵向距离；大面积主配图应吸收其内部、边界上和紧邻的图标、对号、标签与说明，除非它们明确对应独立 narration beat；不允许因为颜色相似就跨卡片、跨栏或跨配图分配。"""


def _compose_ai_mask_full_prompt(methodology: str, output_structure: str) -> str:
    return methodology.strip() + "\n\n--- OUTPUT STRUCTURE / 输出结构 ---\n" + output_structure.strip()


def _read_ai_mask_prompts(server_module: ModuleType) -> tuple[str, str]:
    methodology = str(server_module.get_setting(PROMPT_METHOD_KEY, DEFAULT_METHODOLOGY) or DEFAULT_METHODOLOGY)
    output_structure = str(server_module.get_setting(PROMPT_OUTPUT_KEY, DEFAULT_OUTPUT_STRUCTURE) or DEFAULT_OUTPUT_STRUCTURE)
    if LEGACY_TITLE_RULE in methodology:
        methodology = methodology.replace(LEGACY_TITLE_RULE, CURRENT_TITLE_AND_ISLAND_RULES)
    if STATIC_TITLE_RULE in methodology:
        methodology = methodology.replace(STATIC_TITLE_RULE, CURRENT_TITLE_AND_ISLAND_RULES)
    if PREVIOUS_TITLE_AND_ISLAND_RULES in methodology:
        methodology = methodology.replace(PREVIOUS_TITLE_AND_ISLAND_RULES, CURRENT_TITLE_AND_ISLAND_RULES)
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
        "closing_radius": _int(raw.get("closing_radius"), 6, 0, 20),
        "add_border": _int(raw.get("add_border"), 2, 0, 8),
        "connectivity": 4 if str(raw.get("connectivity")) == "4" else 8,
        "min_element_area": _int(raw.get("min_element_area"), 120, 10, 10000),
        "component_padding_px": _int(raw.get("component_padding_px"), 12, 0, 80),
        "max_group_elements": max(20, _int(raw.get("max_group_elements"), 60, 1, 120)),
        "llm_confidence_threshold": _float(raw.get("llm_confidence_threshold"), 0.72, 0, 1),
        "llm_temperature": _float(raw.get("llm_temperature"), 0.1, 0, 1),
        "overwrite_existing_manual_mask": _bool(raw.get("overwrite_existing_manual_mask"), False),
        "overwrite_existing_ai_mask": _bool(raw.get("overwrite_existing_ai_mask"), True),
        "skip_locked_groups": _bool(raw.get("skip_locked_groups"), True),
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
    # Use open() with mode="w" to reliably overwrite existing files on Windows.
    # pathlib.write_text can raise FileExistsError when the file is read-only
    # or held by another process.
    if path.exists():
        try:
            path.chmod(0o666)
        except (OSError, PermissionError):
            pass
    with path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


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


def _morph_dilate(mask: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    """Binary dilation without scipy/skimage (pure numpy)."""
    kh, kw = kernel.shape
    ph, pw = kh // 2, kw // 2
    padded = np.pad(mask, ((ph, ph), (pw, pw)), mode="constant", constant_values=0)
    result = np.zeros_like(mask)
    for dy in range(kh):
        for dx in range(kw):
            if kernel[dy, dx]:
                result = np.maximum(result, padded[dy:dy + mask.shape[0], dx:dx + mask.shape[1]])
    return result


def _morph_erode(mask: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    """Binary erosion without scipy/skimage (pure numpy)."""
    kh, kw = kernel.shape
    ph, pw = kh // 2, kw // 2
    padded = np.pad(mask, ((ph, ph), (pw, pw)), mode="constant", constant_values=0)
    result = np.full_like(mask, 255)
    for dy in range(kh):
        for dx in range(kw):
            if kernel[dy, dx]:
                result = np.minimum(result, padded[dy:dy + mask.shape[0], dx:dx + mask.shape[1]])
    return result


def detect_elements(image_path: Path, slide_dir: Path, settings: dict[str, Any]) -> dict[str, Any]:
    out_dir = slide_dir / "auto_mask"
    cache_path = out_dir / "auto_elements.json"
    detection_settings = {
        key: settings.get(key)
        for key in (
            "white_threshold",
            "color_tolerance",
            "closing_radius",
            "add_border",
            "connectivity",
            "min_element_area",
            "component_padding_px",
        )
    }
    source_sha256 = hashlib.sha256(image_path.read_bytes()).hexdigest()
    settings_fingerprint = hashlib.sha256(
        json.dumps(detection_settings, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if cache_path.exists():
        try:
            cached = _read_json(cache_path)
            if (
                cached.get("version") == "auto_elements_v3_exact_rle_cached"
                and cached.get("source_sha256") == source_sha256
                and cached.get("detection_settings_fingerprint") == settings_fingerprint
            ):
                return cached
        except Exception:
            pass

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

    # Morphological closing: dilate then erode the foreground mask to bridge
    # small gaps (<= closing_radius pixels) caused by hand-drawn stroke breaks.
    # This merges fragmented strokes of the same element BEFORE connected-
    # component detection, drastically reducing the number of fragments.
    closing_radius = int(settings.get("closing_radius", 6))
    if closing_radius > 0:
        fg_uint8 = fg.astype(np.uint8) * 255
        kernel_size = closing_radius * 2 + 1
        kernel = np.ones((kernel_size, kernel_size), dtype=np.uint8)
        # dilation: bridge gaps; erosion: restore original size
        dilated = _morph_dilate(fg_uint8, kernel)
        closed = _morph_erode(dilated, kernel)
        fg = closed > 0

    source_foreground = fg[border:border + oh, border:border + ow] if border else fg
    visited = np.zeros((h, w), dtype=bool)
    ys, xs = np.nonzero(fg)
    candidates: list[dict[str, Any]] = []
    residual: list[dict[str, Any]] = []
    crop_dir = out_dir / "elements"
    crop_dir.mkdir(parents=True, exist_ok=True)
    for stale_crop in crop_dir.glob("*.png"):
        stale_crop.unlink(missing_ok=True)
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
        # Projection splitting: if this connected component is oversized
        # (bridged by morphological closing), split it at projection valleys.
        canvas_area = ow * oh
        segments = _projection_split(coords, border, ow, oh, canvas_area)
        for seg_coords, raw in segments:
            if not seg_coords:
                continue
            sx = [c[0] for c in seg_coords]
            sy = [c[1] for c in seg_coords]
            x1 = raw["x"]; y1 = raw["y"]
            x2 = x1 + raw["w"]; y2 = y1 + raw["h"]
            if x2 <= x1 or y2 <= y1:
                continue
            box = _pad_box(raw, ow, oh, int(settings["component_padding_px"]))
            cx, cy = box["x"] + box["w"] / 2, box["y"] + box["h"] / 2
            source_runs = _coords_to_row_runs(seg_coords, border, ow, oh)
            component_runs = _solidify_planar_component(source_runs, raw, len(seg_coords))
            component_runs = _protect_other_foreground(component_runs, source_runs, source_foreground)
            component = {
                "element_id": "",
                "bbox": box,
                "raw_bbox": raw,
                "center": {"x": round(cx, 2), "y": round(cy, 2)},
                "area": len(seg_coords),
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
            if len(seg_coords) >= int(settings["min_element_area"]):
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
        "version": "auto_elements_v3_exact_rle_cached",
        "slide_id": slide_dir.name,
        "source_sha256": source_sha256,
        "detection_settings_fingerprint": settings_fingerprint,
        "detection_settings": detection_settings,
        "canvas": {"width": ow, "height": oh},
        "elements": candidates,
        "residual_elements": residual,
        "source_foreground_pixel_count": int(np.count_nonzero(source_foreground)),
        "foreground_pixel_count": _rle_pixel_count(exact_foreground),
    }
    _write_json(out_dir / "auto_elements.json", payload)
    return payload



def _projection_split(
    coords: list[tuple[int, int]],
    border: int,
    ow: int,
    oh: int,
    canvas_area: int,
) -> list[tuple[list[tuple[int, int]], dict[str, int]]]:
    """Split an oversized connected component via projection valleys.

    Returns a list of (coords, raw_bbox) pairs. If no split is needed,
    returns a single-element list with the original component.
    """
    if not coords:
        return []
    px = [c[0] for c in coords]
    py = [c[1] for c in coords]
    x_min, x_max = min(px), max(px)
    y_min, y_max = min(py), max(py)
    w = x_max - x_min + 1
    h = y_max - y_min + 1
    bbox_area = w * h

    # Only split if the component is very large (>15% of canvas) AND
    # has a wide aspect ratio (w > 2*h or h > 2*w), indicating a
    # multi-module row/column that was bridged by morphological closing.
    if bbox_area < canvas_area * 0.15:
        return [(coords, {"x": max(0, x_min - border), "y": max(0, y_min - border),
                          "w": min(ow, x_max + 1 - x_min), "h": min(oh, y_max + 1 - y_min)})]

    # Determine split direction: horizontal if wider than tall, vertical if taller
    split_horizontal = w > h * 1.5
    split_vertical = h > w * 1.5
    if not split_horizontal and not split_vertical:
        # Roughly square — try horizontal first if slightly wider
        split_horizontal = w >= h

    def find_valleys(projection: np.ndarray, length: int) -> list[int]:
        """Find valley points in a 1D projection curve.

        A valley is a local minimum where the projection drops below
        25% of the median peak height, with width >= 3 pixels.
        """
        if length < 20:
            return []
        # Smooth with a simple moving average (window=3)
        smoothed = np.convolve(projection, np.ones(3) / 3, mode="same")
        # Find peak height threshold
        peak_median = float(np.median(smoothed[smoothed > 0])) if np.any(smoothed > 0) else 0.0
        if peak_median < 1:
            return []
        threshold = peak_median * 0.25
        valleys: list[int] = []
        in_valley = False
        valley_start = 0
        for i in range(length):
            if smoothed[i] <= threshold:
                if not in_valley:
                    in_valley = True
                    valley_start = i
            else:
                if in_valley:
                    valley_end = i - 1
                    valley_width = valley_end - valley_start + 1
                    if valley_width >= 3:
                        valleys.append((valley_start + valley_end) // 2)
                    in_valley = False
        return valleys

    if split_horizontal:
        # X-axis projection: count pixels per column
        col_counts = np.zeros(w, dtype=np.int32)
        for cx in px:
            col_counts[cx - x_min] += 1
        valleys = find_valleys(col_counts, w)
        if len(valleys) < 1:
            return [(coords, {"x": max(0, x_min - border), "y": max(0, y_min - border),
                              "w": min(ow, x_max + 1 - x_min), "h": min(oh, y_max + 1 - y_min)})]
        # Split at valley points
        cut_x_positions = [x_min + v for v in valleys]
        cut_x_positions.append(x_max + 1)
        prev = x_min
        segments: list[tuple[list[tuple[int, int]], dict[str, int]]] = []
        for cut_x in cut_x_positions:
            seg_coords = [(cx, cy) for cx, cy in coords if prev <= cx < cut_x]
            if seg_coords:
                sx_min = min(c[0] for c in seg_coords)
                sy_min = min(c[1] for c in seg_coords)
                sx_max = max(c[0] for c in seg_coords)
                sy_max = max(c[1] for c in seg_coords)
                raw = {"x": max(0, sx_min - border), "y": max(0, sy_min - border),
                       "w": min(ow, sx_max + 1 - sx_min), "h": min(oh, sy_max + 1 - sy_min)}
                segments.append((seg_coords, raw))
            prev = cut_x
        if len(segments) >= 2:
            return segments
    elif split_vertical:
        # Y-axis projection: count pixels per row
        row_counts = np.zeros(h, dtype=np.int32)
        for cy in py:
            row_counts[cy - y_min] += 1
        valleys = find_valleys(row_counts, h)
        if len(valleys) < 1:
            return [(coords, {"x": max(0, x_min - border), "y": max(0, y_min - border),
                              "w": min(ow, x_max + 1 - x_min), "h": min(oh, y_max + 1 - y_min)})]
        cut_y_positions = [y_min + v for v in valleys]
        cut_y_positions.append(y_max + 1)
        prev = y_min
        segments: list[tuple[list[tuple[int, int]], dict[str, int]]] = []
        for cut_y in cut_y_positions:
            seg_coords = [(cx, cy) for cx, cy in coords if prev <= cy < cut_y]
            if seg_coords:
                sx_min = min(c[0] for c in seg_coords)
                sy_min = min(c[1] for c in seg_coords)
                sx_max = max(c[0] for c in seg_coords)
                sy_max = max(c[1] for c in seg_coords)
                raw = {"x": max(0, sx_min - border), "y": max(0, sy_min - border),
                       "w": min(ow, sx_max + 1 - sx_min), "h": min(oh, sy_max + 1 - sy_min)}
                segments.append((seg_coords, raw))
            prev = cut_y
        if len(segments) >= 2:
            return segments

    return [(coords, {"x": max(0, x_min - border), "y": max(0, y_min - border),
                      "w": min(ow, x_max + 1 - x_min), "h": min(oh, y_max + 1 - y_min)})]


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
        object_ids = [str(value) for value in item.get("object_ids", []) or [] if str(value)]
        matches.append({"group_id": gid, "narration_beat_id": bid, "object_ids": object_ids, "expanded_from_object_ids": object_ids, "element_ids": eids, "seed_element_ids": list(eids), "confidence": conf, "reason": str(item.get("reason") or ""), "below_threshold": conf < float(settings["llm_confidence_threshold"])})
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


def _union_bounds(bounds_list: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float] | None:
    valid = [bounds for bounds in bounds_list if bounds]
    if not valid:
        return None
    return (
        min(bounds[0] for bounds in valid),
        min(bounds[1] for bounds in valid),
        max(bounds[2] for bounds in valid),
        max(bounds[3] for bounds in valid),
    )


def _bounds_area(bounds: tuple[float, float, float, float] | None) -> float:
    if not bounds:
        return 0.0
    return max(0.0, bounds[2] - bounds[0]) * max(0.0, bounds[3] - bounds[1])


def _layout_region(cx: float, cy: float, width: int, height: int) -> str:
    if cy < 220 * height / 1080:
        return "title"
    if cy >= 930 * height / 1080:
        return "subtitle"
    if cx < width / 3:
        return "content_left"
    if cx > width * 2 / 3:
        return "content_right"
    return "content_center"


def _compatible_regions(a: str, b: str) -> bool:
    if a == b:
        return True
    if "title" in {a, b} or "subtitle" in {a, b}:
        return False
    pairs = {frozenset({"content_left", "content_center"}), frozenset({"content_center", "content_right"})}
    return frozenset({a, b}) in pairs


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
    """Assign title-band components to narrated title groups when available."""
    visual_groups = [group for group in slide.get("visual_groups", []) or [] if isinstance(group, dict)]
    group_roles = {
        str(group.get("id") or ""): str(group.get("role") or "").strip().lower()
        for group in visual_groups
        if str(group.get("id") or "")
    }
    title_group_ids = {group_id for group_id, role in group_roles.items() if role in {"title", "subtitle"}}
    beats = [beat for beat in slide.get("narration_beats", []) or [] if isinstance(beat, dict)]
    beat_by_group = {
        str(beat.get("group_id") or ""): beat
        for beat in beats
        if str(beat.get("group_id") or "")
    }
    narrated_group_ids = list(beat_by_group)
    narrated_title_groups = [
        group_id for group_id in narrated_group_ids if group_roles.get(group_id) == "title"
    ]
    narrated_subtitle_groups = [
        group_id for group_id in narrated_group_ids if group_roles.get(group_id) == "subtitle"
    ]
    # A title band may only belong to a narrated title group. Falling back to
    # the first narrated body group makes one visual title leak into several
    # body Masks during component completion. Legacy contracts without a
    # narrated title therefore keep the whole header static.
    main_target = narrated_title_groups[0] if narrated_title_groups else ""
    subtitle_target = (narrated_subtitle_groups or [main_target])[0] if main_target else ""

    main_ids = set(_element_ids_in_region(elements_payload, regions["main_title"]))
    subtitle_ids = (
        set(_element_ids_in_region(elements_payload, regions["subtitle"])) - main_ids
        if str(slide.get("subtitle") or "").strip()
        else set()
    )
    header_ids = main_ids | subtitle_ids
    dynamic_owners: dict[str, str] = {}
    if main_target:
        dynamic_owners.update({element_id: main_target for element_id in main_ids})
        dynamic_owners.update({element_id: subtitle_target for element_id in subtitle_ids})

    static_ids = {
        str(value)
        for value in match_payload.get("static_element_ids", []) or []
        if str(value) and str(value) not in dynamic_owners
    }
    if not dynamic_owners:
        static_ids.update(header_ids)

    matches: list[dict[str, Any]] = []
    for original in match_payload.get("matches", []) or []:
        if not isinstance(original, dict):
            continue
        item = dict(original)
        item["element_ids"] = [
            str(element_id)
            for element_id in item.get("element_ids", []) or []
            if str(element_id) and str(element_id) not in header_ids
        ]
        matches.append(item)

    matches_by_group = {str(item.get("group_id") or ""): item for item in matches}
    for target_group in dict.fromkeys(dynamic_owners.values()):
        owned_ids = sorted(element_id for element_id, owner in dynamic_owners.items() if owner == target_group)
        item = matches_by_group.get(target_group)
        if item is None:
            beat = beat_by_group.get(target_group, {})
            item = {
                "group_id": target_group,
                "narration_beat_id": str(beat.get("id") or ""),
                "element_ids": [],
                "confidence": 1.0,
                "reason": "title_region_geometry",
            }
            matches.append(item)
            matches_by_group[target_group] = item
        existing_ids = [] if group_roles.get(target_group) in {"title", "subtitle"} else item.get("element_ids", [])
        item["element_ids"] = list(dict.fromkeys([*existing_ids, *owned_ids]))
        item["below_threshold"] = False

    forced_owners = {
        str(element_id): str(group_id)
        for element_id, group_id in (match_payload.get("forced_element_owners") or {}).items()
        if str(element_id) not in header_ids
    }
    forced_owners.update(dynamic_owners)
    result = dict(match_payload)
    result["matches"] = matches
    result["forced_element_owners"] = forced_owners
    result["static_element_ids"] = sorted(static_ids)
    result["static_group_ids"] = sorted(title_group_ids) if not dynamic_owners else []
    result["title_region_policy"] = (
        "narrated_title_and_subtitle_masks"
        if dynamic_owners
        else "static_header_without_narration"
    )
    result["unmatched_groups"] = [
        group_id for group_id in result.get("unmatched_groups", []) or []
        if str(group_id) not in title_group_ids and str(group_id) not in dynamic_owners.values()
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
    # Protect ALL element_ids from already-accepted groups. When the semantic
    # patch is active, VL matches objects as wholes; stealing any element from
    # an accepted group would break the semantic_object boundary and cause the
    # same label/card to be split across multiple narration beats.
    protected_anchor_ids: set[str] = set()
    for item in accepted_by_group.values():
        protected_anchor_ids.update(
            str(element_id) for element_id in item.get("element_ids", []) or []
            if str(element_id)
        )
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
    slide: dict[str, Any] | None = None,
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
    group_roles = {
        str(group.get("id") or ""): str(group.get("role") or "").strip().lower()
        for group in ((slide or {}).get("visual_groups", []) or [])
        if isinstance(group, dict) and str(group.get("id") or "")
    }
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

    # Recheck only small secondary components that the multimodal model placed
    # far from their group's dominant visual island. This is deliberately
    # conservative: dominant components never move, and a new owner must be at
    # least 1.5x closer to avoid geometry overriding a plausible semantic link.
    dominant_ids: dict[str, str] = {}
    for item in accepted:
        group_id = str(item.get("group_id") or "")
        owned = [by_id[str(value)] for value in item.get("element_ids", []) or [] if str(value) in by_id]
        if owned:
            dominant_ids[group_id] = str(max(owned, key=lambda element: int(element.get("area", 0))).get("element_id") or "")

    def anchor_distance(element: dict[str, Any], anchor: dict[str, float]) -> float:
        element_bounds = _box_xyxy(element.get("raw_bbox") if isinstance(element.get("raw_bbox"), dict) else element.get("bbox", {}))
        anchor_bounds = _box_xyxy(anchor)
        if not element_bounds or not anchor_bounds:
            return float("inf")
        ex1, ey1, ex2, ey2 = element_bounds
        ax1, ay1, ax2, ay2 = anchor_bounds
        return float(np.hypot(max(ax1 - ex2, 0.0, ex1 - ax2), max(ay1 - ey2, 0.0, ey1 - ay2)))

    moves: list[tuple[str, str, str]] = []
    for item in accepted:
        current_group = str(item.get("group_id") or "")
        current_anchor = anchors.get(current_group)
        if not current_anchor:
            continue
        for value in list(item.get("element_ids", []) or []):
            element_id = str(value)
            if (
                element_id == dominant_ids.get(current_group)
                or element_id not in by_id
                or element_id in forced_owners
            ):
                continue
            element = by_id[element_id]
            if int(element.get("area", 0)) > float(current_anchor.get("dominant_area", 0)) * 0.35:
                continue
            distances = sorted(
                (anchor_distance(element, anchor), group_id)
                for group_id, anchor in anchors.items()
            )
            if not distances or distances[0][1] == current_group:
                continue
            best_distance, best_group = distances[0]
            current_distance = anchor_distance(element, current_anchor)
            if current_distance >= max(24.0, best_distance * 1.5):
                moves.append((element_id, current_group, best_group))
    for element_id, old_group, new_group in moves:
        old_item = next((item for item in accepted if str(item.get("group_id") or "") == old_group), None)
        new_item = next((item for item in accepted if str(item.get("group_id") or "") == new_group), None)
        if old_item is None or new_item is None:
            continue
        old_item["element_ids"] = [value for value in old_item.get("element_ids", []) or [] if str(value) != element_id]
        new_item["element_ids"] = list(dict.fromkeys([*(new_item.get("element_ids", []) or []), element_id]))

    for item in accepted:
        seed_ids = [str(element_id) for element_id in item.get("element_ids", []) or [] if str(element_id) in by_id]
        existing_seed_ids = item.get("seed_element_ids", []) or []
        item["seed_element_ids"] = list(dict.fromkeys([*existing_seed_ids, *seed_ids]))
        item["element_ids"] = list(dict.fromkeys(seed_ids))
        item["residual_element_ids"] = []
        assigned.update(item["element_ids"])

    residual_assignment_report: list[dict[str, Any]] = []
    # When the semantic_object patch is active, residual fragments are absorbed
    # into semantic_objects BEFORE VL matching and expanded via _expand_matches.
    # In that case most/all residual elements are already in 'assigned' and the
    # distance convergence below is a no-op.  We still run it for any truly
    # unassigned fragments (edge cases where absorption missed something).
    unassigned_residual = [
        element for element in residual
        if str(element.get("element_id") or "") not in assigned
        and str(element.get("element_id") or "") in by_id
    ]
    if accepted and anchors and unassigned_residual:
        CONVERGENCE_RATIO = 1.5

        def box_to_box_distance(anchor: dict[str, float], elem_bounds: tuple[float, float, float, float]) -> float:
            """Shortest gap between two axis-aligned rectangles (0 if overlapping)."""
            anchor_bounds = _box_xyxy(anchor)
            if not anchor_bounds:
                return float("inf")
            ax1, ay1, ax2, ay2 = anchor_bounds
            ex1, ey1, ex2, ey2 = elem_bounds
            dx = max(ax1 - ex2, 0.0, ex1 - ax2)
            dy = max(ay1 - ey2, 0.0, ey1 - ay2)
            return float(np.hypot(dx, dy))

        for element in sorted(unassigned_residual, key=lambda item: (
            float((item.get("center") or {}).get("y", 0)),
            float((item.get("center") or {}).get("x", 0))
        )):
            element_id = str(element.get("element_id") or "")
            if not element_id or element_id in assigned or element_id not in by_id:
                continue
            box = element.get("raw_bbox") if isinstance(element.get("raw_bbox"), dict) else element.get("bbox", {})
            bounds = _box_xyxy(box)
            if not bounds:
                continue
            cx, cy = _box_center(box)
            element_region = _layout_region(cx, cy, width, height)

            # Compute box-to-box distance to every accepted group anchor
            dist_list = []
            for item in accepted:
                group_id = str(item.get("group_id") or "")
                anchor = anchors.get(group_id)
                if not anchor:
                    continue
                anchor_cx, anchor_cy = _box_center(anchor)
                anchor_region = _layout_region(anchor_cx, anchor_cy, width, height)
                if not _compatible_regions(element_region, anchor_region):
                    continue
                dist = box_to_box_distance(anchor, bounds)
                dist_list.append((dist, item, anchor))

            dist_list.sort(key=lambda value: value[0])
            if not dist_list:
                residual_assignment_report.append({
                    "element_id": element_id,
                    "status": "unassigned",
                    "reason": "no_compatible_anchor",
                    "region": element_region
                })
                continue

            d1 = dist_list[0][0]
            d2 = dist_list[1][0] if len(dist_list) > 1 else float("inf")
            best = dist_list[0][1]

            # 1.5x convergence rule: converge if d2 >= 1.5 * d1, or only one anchor
            should_converge = (d2 >= CONVERGENCE_RATIO * d1) or len(dist_list) == 1
            if not should_converge:
                residual_assignment_report.append({
                    "element_id": element_id,
                    "status": "unassigned",
                    "reason": "ambiguous_zone",
                    "d1": round(d1, 2),
                    "d2": round(d2, 2),
                    "ratio": round(d2 / max(d1, 0.01), 3),
                    "region": element_region
                })
                continue

            best.setdefault("element_ids", []).append(element_id)
            best.setdefault("residual_element_ids", []).append(element_id)
            assigned.add(element_id)
            residual_assignment_report.append({
                "element_id": element_id,
                "status": "assigned",
                "group_id": str(best.get("group_id") or ""),
                "distance": round(d1, 2),
                "d2": round(d2, 2) if d2 != float("inf") else None,
                "ratio": round(d2 / max(d1, 0.01), 3) if d2 != float("inf") else None,
                "region": element_region
            })

    # The production contract requires every foreground component to have one
    # owner.  The vision model chooses semantic anchors; this final deterministic
    # pass only closes coverage gaps by attaching any remaining component to the
    # nearest compatible anchor.  It never changes an existing owner.
    forced_completion_assignments: list[dict[str, Any]] = []
    if accepted and anchors:
        residual_ids = {
            str(element.get("element_id") or "")
            for element in residual
            if str(element.get("element_id") or "")
        }
        for element_id in sorted(set(by_id) - assigned):
            element = by_id[element_id]
            box = element.get("raw_bbox") if isinstance(element.get("raw_bbox"), dict) else element.get("bbox", {})
            cx, cy = _box_center(box)
            element_region = _layout_region(cx, cy, width, height)
            ranked: list[tuple[int, float, dict[str, Any]]] = []
            for item in accepted:
                group_id = str(item.get("group_id") or "")
                anchor = anchors.get(group_id)
                if not anchor:
                    continue
                anchor_cx, anchor_cy = _box_center(anchor)
                anchor_region = _layout_region(anchor_cx, anchor_cy, width, height)
                compatible = _compatible_regions(element_region, anchor_region)
                ranked.append((0 if compatible else 1, anchor_distance(element, anchor), item))
            if not ranked:
                continue
            compatibility_rank, distance, owner = min(
                ranked,
                key=lambda value: (value[0], value[1], str(value[2].get("group_id") or "")),
            )
            owner.setdefault("element_ids", []).append(element_id)
            if element_id in residual_ids:
                owner.setdefault("residual_element_ids", []).append(element_id)
            assigned.add(element_id)
            assignment = {
                "element_id": element_id,
                "status": "assigned",
                "group_id": str(owner.get("group_id") or ""),
                "distance": round(distance, 2),
                "region": element_region,
                "forced": True,
                "compatible_region": compatibility_rank == 0,
                "reason": "nearest_compatible_anchor_after_ambiguity" if compatibility_rank == 0 else "nearest_anchor_without_compatible_region",
                "candidate_component": element_id not in residual_ids,
            }
            previous = next(
                (item for item in residual_assignment_report if item.get("element_id") == element_id),
                None,
            )
            if previous is not None:
                previous.clear()
                previous.update(assignment)
            else:
                residual_assignment_report.append(assignment)
            forced_completion_assignments.append(assignment)

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
    semantic_group_checks: list[dict[str, Any]] = []
    semantic_warnings: list[dict[str, Any]] = []
    forced_candidate_groups = sorted({
        str(item.get("group_id") or "")
        for item in forced_completion_assignments
        if item.get("candidate_component") and str(item.get("group_id") or "")
    })
    for group_id in forced_candidate_groups:
        semantic_warnings.append({
            "type": "forced_low_confidence_components",
            "group_id": group_id,
            "component_count": sum(
                1 for item in forced_completion_assignments
                if item.get("candidate_component") and str(item.get("group_id") or "") == group_id
            ),
        })
    existing_warnings = list(match_payload.get("warnings", []) or [])
    structural_model_warnings = [
        dict(warning)
        for warning in existing_warnings
        if isinstance(warning, dict)
        and warning.get("type") == "insufficient_visual_groups_for_independent_objects"
    ]
    blocking_errors: list[dict[str, Any]] = [
        dict(issue)
        for issue in visual_group_atomicity_issues(slide)
    ] + structural_model_warnings
    for item in accepted:
        group_id = str(item.get("group_id") or "")
        element_ids = [str(element_id) for element_id in item.get("element_ids", []) or [] if str(element_id) in by_id]
        residual_ids = [str(element_id) for element_id in item.get("residual_element_ids", []) or [] if str(element_id)]
        bounds_list = [
            _box_xyxy(by_id[element_id].get("raw_bbox") if isinstance(by_id[element_id].get("raw_bbox"), dict) else by_id[element_id].get("bbox", {}))
            for element_id in element_ids
        ]
        regions = sorted({
            _layout_region(*_box_center(by_id[element_id].get("raw_bbox") if isinstance(by_id[element_id].get("raw_bbox"), dict) else by_id[element_id].get("bbox", {})), width, height)
            for element_id in element_ids
        })
        residual_ratio = len(residual_ids) / max(1, len(element_ids))
        check = {
            "group_id": group_id,
            "element_count": len(element_ids),
            "residual_count": len(residual_ids),
            "residual_ratio": round(residual_ratio, 3),
            "regions": regions,
        }
        semantic_group_checks.append(check)
        if "subtitle" in regions:
            blocking_errors.append({"type": "dynamic_group_enters_subtitle_safe_zone", "group_id": group_id})
        title_element_ids = [
            element_id
            for element_id in element_ids
            if _layout_region(
                *_box_center(
                    by_id[element_id].get("raw_bbox")
                    if isinstance(by_id[element_id].get("raw_bbox"), dict)
                    else by_id[element_id].get("bbox", {})
                ),
                width,
                height,
            ) == "title"
        ]
        narrated_title_ownership = (
            match_payload.get("title_region_policy") == "narrated_title_and_subtitle_masks"
            and title_element_ids
            and group_roles.get(group_id) == "title"
            and all(forced_owners.get(element_id) == group_id for element_id in title_element_ids)
        )
        if "title" in regions and not narrated_title_ownership:
            blocking_errors.append({"type": "dynamic_group_owns_title_region_pixels", "group_id": group_id})
        content_regions = [region for region in regions if region.startswith("content_")]
        if "content_left" in content_regions and "content_right" in content_regions:
            # Wide comparisons and process diagrams legitimately span both
            # sides of a slide. Geometry alone is not strong enough evidence
            # to reject the multimodal semantic ownership, so route this to
            # human review instead of failing an otherwise exact Mask.
            semantic_warnings.append({"type": "group_crosses_left_and_right_regions", "group_id": group_id})
        if residual_ratio > 0.85:
            blocking_errors.append({"type": "too_many_residual_components", "group_id": group_id, "residual_ratio": round(residual_ratio, 3)})
        elif residual_ratio > 0.5:
            semantic_warnings.append({"type": "many_residual_components", "group_id": group_id, "residual_ratio": round(residual_ratio, 3)})
        union = _union_bounds(bounds_list)
        if union:
            check["bbox"] = {"x": round(union[0]), "y": round(union[1]), "w": round(union[2] - union[0]), "h": round(union[3] - union[1])}
    semantic_quality = {
        "version": "ai_mask_semantic_quality_v2",
        "passed": bool(accepted) and not blocking_errors,
        "group_checks": semantic_group_checks,
        "warnings": semantic_warnings,
        "blocking_errors": blocking_errors,
        "residual_assignment_summary": {
            "assigned": sum(1 for item in residual_assignment_report if item.get("status") == "assigned"),
            "unassigned": sum(1 for item in residual_assignment_report if item.get("status") == "unassigned"),
        },
    }
    quality = {
        "version": "ai_mask_quality_v2",
        "foreground_pixel_count": foreground_pixels,
        "assigned_foreground_pixel_count": assigned_pixels,
        "static_header_pixel_count": _rle_pixel_count(_merge_row_runs(static_elements, width, height)),
        "foreground_coverage_ratio": round(coverage, 6),
        "unassigned_component_count": len(unassigned_ids),
        "overlap_pixel_count": overlap_pixels,
        "exclusive_component_ownership": overlap_pixels == 0,
        "semantic_quality_passed": semantic_quality["passed"],
        "minimum_foreground_coverage_ratio": AI_MASK_MIN_FOREGROUND_COVERAGE,
        "passed": (
            bool(accepted)
            and coverage >= AI_MASK_MIN_FOREGROUND_COVERAGE
            and len(unassigned_ids) == 0
            and overlap_pixels == 0
            and semantic_quality["passed"]
        ),
    }
    match_payload["unmatched_elements"] = unassigned_ids
    match_payload["quality"] = quality
    match_payload["semantic_quality"] = semantic_quality
    match_payload["residual_assignment_report"] = residual_assignment_report
    if quality["passed"] and not semantic_warnings and not existing_warnings:
        match_payload["warnings"] = []
    else:
        non_structural_model_warnings = [
            warning
            for warning in existing_warnings
            if not (
                isinstance(warning, dict)
                and warning.get("type") == "insufficient_visual_groups_for_independent_objects"
            )
        ]
        match_payload["warnings"] = [*non_structural_model_warnings, *semantic_warnings, *blocking_errors]
    match_payload["matching_method"] = str(match_payload.get("matching_method") or "unknown") + "+constrained_component_completion"
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


def _replaceable_ai_mask(group: dict[str, Any]) -> bool:
    manual = group.get("manual_mask") if isinstance(group.get("manual_mask"), dict) else {}
    source = str(manual.get("source") or group.get("source") or "")
    strokes = manual.get("strokes") if isinstance(manual.get("strokes"), list) else []
    has_corrections = any(isinstance(stroke, dict) and stroke.get("points") for stroke in strokes)
    locked = str(group.get("review_status") or "").lower() in {"approved", "locked"}
    return source.startswith("ai_auto_mask") and not has_corrections and not locked


def _confidence_level(value: Any) -> str:
    confidence = _float(value, 0.0, 0.0, 1.0)
    if confidence >= 0.85:
        return "high"
    if confidence >= 0.65:
        return "medium"
    return "low"


def _review_issues(match_payload: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for match in match_payload.get("matches", []) or []:
        if not isinstance(match, dict):
            continue
        confidence = _float(match.get("confidence"), 0.0, 0.0, 1.0)
        level = _confidence_level(confidence)
        if level == "high" and not match.get("below_threshold"):
            continue
        issues.append({
            "type": "low_confidence_match" if level == "low" else "review_match",
            "severity": "warning",
            "group_id": str(match.get("group_id") or ""),
            "confidence": round(confidence, 4),
            "confidence_level": level,
            "message": "AI 对该语块的元素归属不够确定，请检查。",
        })
    for group_id in match_payload.get("unmatched_groups", []) or []:
        issues.append({
            "type": "unmatched_group",
            "severity": "blocking",
            "group_id": str(group_id),
            "confidence": 0.0,
            "confidence_level": "low",
            "message": "该语块没有找到可靠的画面元素。",
        })
    quality = match_payload.get("quality") if isinstance(match_payload.get("quality"), dict) else {}
    if quality:
        coverage = _float(quality.get("foreground_coverage_ratio"), 0.0, 0.0, 1.0)
        minimum_coverage = _float(
            quality.get("minimum_foreground_coverage_ratio"),
            AI_MASK_MIN_FOREGROUND_COVERAGE,
            0.0,
            1.0,
        )
        if coverage < minimum_coverage:
            issues.append({
                "type": "foreground_coverage_below_threshold",
                "severity": "blocking",
                "group_id": "",
                "message": f"前景覆盖率为 {coverage:.2%}，低于要求的 {minimum_coverage:.2%}。",
                "metrics": {"coverage": round(coverage, 6), "minimum": round(minimum_coverage, 6)},
            })
        unassigned_count = _int(quality.get("unassigned_component_count"), 0, 0, 1_000_000)
        if unassigned_count:
            issues.append({
                "type": "unassigned_foreground_components",
                "severity": "blocking",
                "group_id": "",
                "message": f"仍有 {unassigned_count} 个前景组件未分配。",
                "metrics": {"unassigned_component_count": unassigned_count},
            })
        overlap_count = _int(quality.get("overlap_pixel_count"), 0, 0, 1_000_000_000)
        if overlap_count:
            issues.append({
                "type": "cross_group_pixel_overlap",
                "severity": "blocking",
                "group_id": "",
                "message": f"检测到 {overlap_count} 个跨语块重叠像素。",
                "metrics": {"overlap_pixel_count": overlap_count},
            })
    semantic_quality = match_payload.get("semantic_quality") if isinstance(match_payload.get("semantic_quality"), dict) else {}
    issue_messages = {
        "dynamic_group_enters_subtitle_safe_zone": "动态语块进入字幕安全区，请检查。",
        "dynamic_group_owns_title_region_pixels": "正文语块包含标题区域像素，请检查。",
        "group_crosses_left_and_right_regions": "该语块横跨页面左右区域，请确认它是否属于同一叙事单元。",
        "too_many_residual_components": "该语块包含较多自动吸附的小组件，请检查。",
        "many_residual_components": "该语块包含较多自动吸附的小组件，建议检查。",
        "forced_low_confidence_components": "部分画面组件通过最近锚点规则补全，建议检查归属。",
        "group_contains_multiple_independent_visual_islands": "一个分镜语块描述了多个应分别 Reveal 的独立视觉岛，请返回分镜规划拆分语块。",
        "insufficient_visual_groups_for_independent_objects": "画面存在多个独立语义对象，但分镜提供的可 Reveal 语块不足。",
    }
    for severity, field in (("blocking", "blocking_errors"), ("warning", "warnings")):
        for issue in semantic_quality.get(field, []) or []:
            if not isinstance(issue, dict):
                continue
            issue_type = str(issue.get("type") or "semantic_review")
            issues.append({
                **issue,
                "type": issue_type,
                "severity": severity,
                "group_id": str(issue.get("group_id") or ""),
                "message": issue_messages.get(issue_type, "AI Mask 语义质量需要检查。"),
            })
    return issues


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
    # Remove legacy static title paint. Narrated title/subtitle groups are
    # rebuilt below with the same exact RLE masks as body groups.
    for collection in (groups, semantic):
        collection[:] = [
            group for group in collection
            if not (
                isinstance(group, dict)
                and (
                    str(group.get("id") or group.get("group_id") or group.get("visual_group_id") or "") in static_group_ids
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
            if str(group.get("review_status") or "").lower() in {"approved", "locked"}:
                continue
            # Human corrections are always authoritative. Only a pristine Mask
            # produced by a previous AI run may be replaced automatically.
            if _has_manual(group) and not _replaceable_ai_mask(group):
                continue
            if _has_manual(group) and not settings.get("overwrite_existing_ai_mask", True):
                continue
            group["box"] = box
            group["visual_group_id"] = gid
            group["manual_mask"] = {
                **exact_mask,
                "color": color,
            }
            confidence_level = _confidence_level(match.get("confidence"))
            group["review_status"] = "ai_matched" if confidence_level == "high" else "ai_review_required"
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
            group["ai_match"] = {
                "confidence": match.get("confidence"),
                "confidence_level": confidence_level,
                "needs_review": confidence_level != "high",
                "reason": match.get("reason", ""),
            }
        updated += 1
    mslide["ai_mask_status"] = {
        "version": "ai_mask_annotation_v3_exact_rle",
        "updated_group_count": updated,
        "skipped_group_count": skipped,
        "detected_element_count": len(elements_payload.get("elements", [])),
        "residual_component_count": len(elements_payload.get("residual_elements", [])),
        "quality": match_payload.get("quality", {}),
        "review_issues": _review_issues(match_payload),
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
        element_list = elements.get("elements", []) + elements.get("residual_elements", [])
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
        try:
            _write_json(item["slide_dir"] / "auto_mask" / "auto_match_before_completion.json", cleaned)
        except Exception:
            pass
        completed = _complete_component_coverage(cleaned, item["elements"], item["slide"])
        try:
            _write_json(item["slide_dir"] / "auto_mask" / "auto_match_after_completion.json", completed)
        except Exception:
            pass
        return completed

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
    review_issues: list[dict[str, Any]] = []
    for item in prepared:
        slide_id = item["slide_id"]
        match = matches[slide_id]
        _write_json(item["slide_dir"] / "auto_mask" / "auto_match.json", match)
        _write_json(item["slide_dir"] / "auto_mask" / "semantic_quality_report.json", {
            "slide_id": slide_id,
            "quality": match.get("quality", {}),
            "semantic_quality": match.get("semantic_quality", {}),
            "residual_assignment_report": match.get("residual_assignment_report", []),
        })
        applied = _apply(manifest, item["slide"], item["elements"], match, settings)
        total_updated += applied["updated"]
        total_skipped += applied["skipped"]
        unmatched_group_count = len(match.get("unmatched_groups", []))
        total_unmatched_groups += unmatched_group_count
        slide_quality = match.get("quality", {}) if isinstance(match.get("quality"), dict) else {}
        quality_passed = quality_passed and bool(slide_quality.get("passed"))
        semantic_quality = match.get("semantic_quality", {}) if isinstance(match.get("semantic_quality"), dict) else {}
        slide_review_issues = [{"slide_id": slide_id, **issue} for issue in _review_issues(match)]
        review_issues.extend(slide_review_issues)
        slides_out.append({"slide_id": slide_id, "detected_element_count": len(item["element_list"]), "residual_component_count": len(item["elements"].get("residual_elements", [])), "matched_group_count": len(match.get("matches", [])), "updated_group_count": applied["updated"], "skipped_group_count": applied["skipped"], "unmatched_element_count": len(match.get("unmatched_elements", [])), "unmatched_group_count": unmatched_group_count, "matching_method": match.get("matching_method"), "quality": slide_quality, "semantic_quality": semantic_quality, "warnings": match.get("warnings", []), "review_required": bool(slide_review_issues), "review_issues": slide_review_issues})
    # ``complete`` remains a backward-compatible processing signal.  Consumers
    # must use ``quality_status`` to distinguish a clean result from a usable
    # result that still needs human review.
    complete = total_updated > 0 and len(slides_out) > 0
    if not complete:
        quality_status = "failed"
    elif quality_passed and not review_issues:
        quality_status = "passed"
    else:
        quality_status = "needs_review"
    annotation_status = {
        "passed": "completed",
        "needs_review": "completed_needs_review",
        "failed": "incomplete",
    }[quality_status]
    manifest["ai_mask_annotation"] = {
        "version": "ai_mask_annotation_v3_exact_rle",
        "status": annotation_status,
        "quality_status": quality_status,
        "settings": settings,
        "processed_slide_count": len(slides_out),
        "updated_group_count": total_updated,
        "unmatched_group_count": total_unmatched_groups,
        "skipped_group_count": total_skipped,
        "quality_passed": quality_passed,
        "review_required": bool(review_issues),
        "review_issue_count": len(review_issues),
        "review_issues": review_issues,
    }
    _write_json(run_dir / "reveal_manifest.json", manifest)
    return {
        "success": True,
        "complete": complete,
        "quality_status": quality_status,
        "quality_passed": quality_passed,
        "processed_slide_count": len(slides_out),
        "updated_group_count": total_updated,
        "unmatched_group_count": total_unmatched_groups,
        "review_required": bool(review_issues),
        "review_issue_count": len(review_issues),
        "review_issues": review_issues,
        "slides": slides_out,
        "manifest_path": str(run_dir / "reveal_manifest.json"),
    }


def annotate_project(
    server_module: ModuleType,
    project: Any,
    settings_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Public AI Mask service shared by the API route and one-click pipeline."""
    settings = _get_store_settings(server_module)
    if isinstance(settings_override, dict):
        settings = normalize_settings({**settings, **settings_override})
    with server_module.reveal_lock_for(project):
        result = _annotate_project(server_module, project, settings)
    try:
        server_module.write_project_log(project, "ai_mask_annotation", **result)
    except Exception:
        pass
    return result


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
        settings = payload.get("settings") if isinstance(payload, dict) and isinstance(payload.get("settings"), dict) else {}
        return annotate_project(server_module, project, settings)

    app.add_api_route("/api/settings/ai-mask", get_ai_mask_settings, methods=["GET"])
    app.add_api_route("/api/settings/ai-mask", put_ai_mask_settings, methods=["PUT"])
    app.add_api_route("/api/projects/{project_id}/steps/5/ai-mask/annotate", annotate_step5, methods=["POST"])
    setattr(server_module, PATCH_MARKER, True)
    return True
