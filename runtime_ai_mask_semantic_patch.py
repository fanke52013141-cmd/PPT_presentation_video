"""Runtime patch: semantic-object AI Mask matching.

The base bridge still owns exact RLE detection and rendering.  This patch only
changes the multimodal matching input from raw connected components to merged
semantic objects, and updates the default prompt accordingly.
"""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from types import ModuleType
from typing import Any

from PIL import Image, ImageDraw

PATCH_MARKER = "__ppt_ai_mask_semantic_object_patch__"
MAX_IMAGE_WIDTH = 1280

DEFAULT_METHODOLOGY = """你是中文 PPT 视频的 AI Mask 语义标注专家。

## 目的
把自动检测到的语义对象绑定到当前 Slide 已有的 visual_groups 与 narration_beats，为后续生成安全、可复核的 Reveal Mask 提供匹配结果；不重写分镜或旁白。

## 输入
- 当前 Slide 的 visual_groups、narration_beats 与 semantic_objects。
- 完整原图、对象切片及其 object_id 和 bbox。
- 所有返回的 ID 必须来自输入，不得创造新 ID。

## 输出
- 只输出符合“输出结构”的一个合法 JSON 对象，不要 Markdown、解释或额外文字。
- 不确定时降低 confidence 或放入 unmatched 列表，不得强行匹配。

任务：把当前 Slide 的画面语义对象绑定到已有 visual_groups 和 narration_beats。你不是重新生成分镜，也不是重写演讲稿；你只做“画面语义对象 → 语块 → 演讲稿 beat”的匹配。

输入包含两张图：
- image_full：未画框的完整原图，用来理解全局版式、阅读顺序和真实语义。
- object_XXX 切片图：每个语义对象的裁切图，图上标注了 object_id。根据切片图的视觉内容判断它对应哪个 visual_group 和 narration_beat。

可修改方法论：
1. group_id 只能使用输入 visual_groups[].id，不要发明新的 group。
2. narration_beat_id 只能使用输入 narration_beats[].id。
3. 优先匹配 semantic_objects[].object_id；输出 element_ids 时必须使用被选 semantic_objects[].element_ids 的完整集合，不要只挑其中一两个碎片。
4. semantic_objects 是由原子连通组件合并后的语义对象；一个标题行、标签行、卡片、配图、图标组合或流程节点通常应作为整体处理，不要因为字形不粘连、颜色不同、边框断开而拆成多个 narration group。
5. 页面上方固定主标题/副标题区域属于静态上下文，不分配给任何 narration group，不参与逐语块 Reveal。
6. 优先匹配 visible_text、visible_anchor、spoken_text，再结合对象二维位置、role 和阅读顺序；横向与纵向距离都必须考虑。
7. 一个语块可以绑定多个空间连续的 semantic_objects，例如主配图 + 配图内部文字 + 紧邻图标/对号/标签。大面积主配图或卡片应吸收其内部、边界上和紧邻的图标、对号、标签与说明，除非它们明确对应独立 narration beat。
8. 不允许因为颜色相似就跨卡片、跨栏或跨配图分配；也不允许因为颜色不同就把同一个标题、同一卡片或同一配图拆开。
9. 对比场景左右两侧如果表达不同叙事状态，必须分别绑定到不同 narration beat；不要把两个独立插图合并为同一个 Mask。
10. 不确定时降低 confidence，不要强行匹配。装饰或无口播对象放入 unmatched_elements 或 unmatched_objects。
11. 输出必须是严格 JSON，不要 Markdown，不要解释段落。
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
      "reason": "obj_010 是完整语义对象，包含主配图与紧邻对号，并共同对应 beat_01"
    }
  ],
  "unmatched_objects": [],
  "unmatched_elements": [],
  "unmatched_groups": [],
  "warnings": []
}

约束：group_id 必须来自 visual_groups[].id；narration_beat_id 必须来自 narration_beats[].id；object_ids 必须来自 semantic_objects[].object_id；element_ids 必须来自 semantic_objects[].element_ids 或 auto_elements[].element_id；confidence 是 0 到 1 的数字。若输出 object_ids，本系统会自动展开为 element_ids；为兼容旧流程，也建议同时输出 element_ids。
"""

PROMPT_UPGRADE = """

--- 运行时语义对象合并补充规则 ---
当前版本会先把原子连通组件合并为 semantic_objects，再给你完整原图和语义对象 overlay。请优先基于 semantic_objects 做匹配，而不是直接按碎片级 auto_elements 拆分。一个 semantic_object 代表同一个标题行、标签行、卡片、配图或图标组合时，必须作为整体归属；不要因为颜色、断笔、不粘连或候选框碎片化，把同一个语义对象拆给多个 narration group。
"""


def _box(element: dict[str, Any]) -> dict[str, float] | None:
    source = element.get("raw_bbox") if isinstance(element.get("raw_bbox"), dict) else element.get("bbox")
    if not isinstance(source, dict):
        return None
    try:
        x = float(source.get("x", 0)); y = float(source.get("y", 0))
        w = float(source.get("w", 0)); h = float(source.get("h", 0))
    except Exception:
        return None
    if w <= 0 or h <= 0:
        return None
    return {"x": x, "y": y, "w": w, "h": h}


def _cx(box: dict[str, float]) -> float:
    return box["x"] + box["w"] / 2


def _cy(box: dict[str, float]) -> float:
    return box["y"] + box["h"] / 2


def _union(boxes: list[dict[str, float]]) -> dict[str, int]:
    x1 = min(box["x"] for box in boxes); y1 = min(box["y"] for box in boxes)
    x2 = max(box["x"] + box["w"] for box in boxes); y2 = max(box["y"] + box["h"] for box in boxes)
    return {"x": max(0, round(x1)), "y": max(0, round(y1)), "w": max(1, round(x2 - x1)), "h": max(1, round(y2 - y1))}


def _inside(parent: dict[str, float], child: dict[str, float], pad: float) -> bool:
    cx, cy = _cx(child), _cy(child)
    return parent["x"] - pad <= cx <= parent["x"] + parent["w"] + pad and parent["y"] - pad <= cy <= parent["y"] + parent["h"] + pad


def _position(cx: float, cy: float, width: int, height: int) -> str:
    xp = "left" if cx < width / 3 else "right" if cx > width * 2 / 3 else "center"
    yp = "top" if cy < height / 3 else "bottom" if cy > height * 2 / 3 else "middle"
    return f"{yp}_{xp}"


def _semantic_objects(elements: list[dict[str, Any]], width: int, height: int) -> list[dict[str, Any]]:
    items = []
    for element in elements:
        eid = str(element.get("element_id") or "") if isinstance(element, dict) else ""
        box = _box(element) if isinstance(element, dict) else None
        if eid and box:
            items.append({"id": eid, "element": element, "box": box, "area": float(element.get("area", 0) or 0)})
    canvas_area = max(1, width * height)
    objects: list[dict[str, Any]] = []

    def add(kind: str, ids: list[str], reason: str) -> None:
        unique = [eid for eid in dict.fromkeys(ids) if any(item["id"] == eid for item in items)]
        if not unique:
            return
        boxes = [item["box"] for item in items if item["id"] in unique]
        box = _union(boxes)
        cx = box["x"] + box["w"] / 2; cy = box["y"] + box["h"] / 2
        objects.append({
            "object_id": f"obj_{len(objects) + 1:03d}",
            "type": kind,
            "bbox": box,
            "center": {"x": round(cx, 2), "y": round(cy, 2)},
            "position": _position(cx, cy, width, height),
            "element_ids": unique,
            "element_count": len(unique),
            "reason": reason,
        })

    text_items = [
        item for item in items
        if 5 <= item["box"]["h"] <= max(120, height * 0.14)
        and item["area"] <= canvas_area * 0.06
        and item["box"]["w"] <= width * 0.92
    ]
    text_items.sort(key=lambda item: (_cy(item["box"]), _cx(item["box"])))
    lines: list[list[dict[str, Any]]] = []
    for item in text_items:
        chosen = None
        for line in lines:
            line_box = _union([part["box"] for part in line])
            line_box_f = {key: float(value) for key, value in line_box.items()}
            last = sorted(line, key=lambda part: _cx(part["box"]))[-1]
            x_gap = max(0.0, item["box"]["x"] - (last["box"]["x"] + last["box"]["w"]))
            y_delta = abs(_cy(item["box"]) - _cy(line_box_f))
            allowed_gap = max(18.0, min(96.0, 1.9 * max(item["box"]["h"], line_box_f["h"])))
            if y_delta <= 0.55 * max(item["box"]["h"], line_box_f["h"]) and x_gap <= allowed_gap:
                chosen = line
                break
        if chosen is None:
            lines.append([item])
        else:
            chosen.append(item)
    for line in lines:
        if len(line) >= 2:
            box = _union([part["box"] for part in line])
            if box["w"] >= box["h"] * 1.2:
                add("text_line_or_label", [part["id"] for part in line], "merged disconnected glyph/label components")

    for item in sorted(items, key=lambda part: part["area"], reverse=True):
        box = item["box"]
        box_area = max(1.0, box["w"] * box["h"])
        if not (box_area >= canvas_area * 0.018 or item["area"] >= canvas_area * 0.006):
            continue
        if not (box["w"] >= width * 0.15 or box["h"] >= height * 0.12):
            continue
        pad = max(24.0, min(96.0, 0.09 * max(box["w"], box["h"])))
        child_ids = [part["id"] for part in items if _inside(box, part["box"], pad)]
        add("container_or_illustration", child_ids or [item["id"]], "large visual island with inside/nearby components")

    covered = {eid for obj in objects for eid in obj.get("element_ids", [])}
    for item in items:
        if item["id"] not in covered:
            add("atomic_visual_component", [item["id"]], "single remaining component")

    def priority(obj: dict[str, Any]) -> tuple[int, int, int, int]:
        box = obj.get("bbox", {}) if isinstance(obj.get("bbox"), dict) else {}
        y = int(box.get("y", 0) or 0)
        x = int(box.get("x", 0) or 0)
        kind = str(obj.get("type") or "")
        if y < height * 0.22 and kind == "text_line_or_label":
            rank = 0
        elif kind == "container_or_illustration":
            rank = 1
        elif kind == "text_line_or_label":
            rank = 2
        else:
            rank = 3
        return (rank, y, x, -int(obj.get("element_count", 1) or 1))

    canonical: list[dict[str, Any]] = []
    owned: set[str] = set()
    for obj in sorted(objects, key=priority):
        ids = [str(eid) for eid in obj.get("element_ids", []) or [] if str(eid) and str(eid) not in owned]
        if not ids:
            continue
        next_obj = dict(obj)
        boxes = [item["box"] for item in items if item["id"] in ids]
        if boxes:
            box = _union(boxes)
            cx = box["x"] + box["w"] / 2; cy = box["y"] + box["h"] / 2
            next_obj["bbox"] = box
            next_obj["center"] = {"x": round(cx, 2), "y": round(cy, 2)}
            next_obj["position"] = _position(cx, cy, width, height)
        next_obj["element_ids"] = ids
        next_obj["element_count"] = len(ids)
        next_obj["exclusive"] = True
        canonical.append(next_obj)
        owned.update(ids)

    canonical.sort(key=lambda obj: (obj["bbox"]["y"], obj["bbox"]["x"], -int(obj.get("element_count", 1))))
    for index, obj in enumerate(canonical[:120], start=1):
        obj["object_id"] = f"obj_{index:03d}"
    return canonical[:120]


def _png_bytes(image_path: Path, out_path: Path | None = None) -> bytes:
    image = Image.open(image_path).convert("RGB")
    if image.width > MAX_IMAGE_WIDTH:
        ratio = MAX_IMAGE_WIDTH / image.width
        image = image.resize((MAX_IMAGE_WIDTH, max(1, int(image.height * ratio))), Image.Resampling.LANCZOS)
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(out_path, format="PNG")
    buffer = io.BytesIO(); image.save(buffer, format="PNG")
    return buffer.getvalue()


def _overlay_bytes(image_path: Path, objects: list[dict[str, Any]], out_path: Path) -> bytes:
    image = Image.open(image_path).convert("RGB")
    ow, oh = image.size
    if image.width > MAX_IMAGE_WIDTH:
        ratio = MAX_IMAGE_WIDTH / image.width
        image = image.resize((MAX_IMAGE_WIDTH, max(1, int(image.height * ratio))), Image.Resampling.LANCZOS)
    sx, sy = image.width / ow, image.height / oh
    draw = ImageDraw.Draw(image)
    colors = [(220, 30, 50), (30, 130, 210), (24, 150, 95), (130, 70, 190), (210, 120, 24)]
    for index, obj in enumerate(objects):
        box = obj.get("bbox") if isinstance(obj.get("bbox"), dict) else {}
        x1 = int(float(box.get("x", 0)) * sx); y1 = int(float(box.get("y", 0)) * sy)
        x2 = int(float(box.get("x", 0) + box.get("w", 0)) * sx); y2 = int(float(box.get("y", 0) + box.get("h", 0)) * sy)
        color = colors[index % len(colors)]
        label = str(obj.get("object_id") or "")
        draw.rectangle((x1, y1, x2, y2), outline=color, width=4)
        label_box = draw.textbbox((x1, max(0, y1 - 16)), label)
        draw.rectangle(label_box, fill=(255, 255, 255))
        draw.text((x1, max(0, y1 - 16)), label, fill=color)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path, format="PNG")
    buffer = io.BytesIO(); image.save(buffer, format="PNG")
    return buffer.getvalue()


def _expand_matches(value: Any, objects: list[dict[str, Any]], elements: list[dict[str, Any]]) -> Any:
    if not isinstance(value, dict):
        return value
    object_map = {str(obj.get("object_id") or ""): [str(eid) for eid in obj.get("element_ids", []) or []] for obj in objects}
    known = {str(element.get("element_id") or "") for element in elements if str(element.get("element_id") or "")}
    # Also include element_ids from objects so absorbed residual fragments
    # (which are not in the candidates list) are not filtered out.
    for obj in objects:
        known.update(str(eid) for eid in obj.get("element_ids", []) or [])
    matches = []
    for match in value.get("matches", []) or []:
        if not isinstance(match, dict):
            continue
        ids: list[str] = []
        valid_object_ids = []
        for object_id in match.get("object_ids", []) or []:
            object_id = str(object_id)
            if object_id in object_map:
                valid_object_ids.append(object_id)
                ids.extend(object_map[object_id])
        for element_id in match.get("element_ids", []) or []:
            if str(element_id) in known:
                ids.append(str(element_id))
        normalized = dict(match)
        normalized["object_ids"] = valid_object_ids
        normalized["expanded_from_object_ids"] = valid_object_ids
        normalized["element_ids"] = [element_id for element_id in dict.fromkeys(ids) if element_id in known]
        matches.append(normalized)
    result = dict(value)
    result["matches"] = matches
    return result


def _patch_read_prompts(original: Any, server_module: ModuleType) -> tuple[str, str]:
    methodology, output_structure = original(server_module)
    if "semantic_objects" not in methodology:
        methodology = methodology.rstrip() + PROMPT_UPGRADE
    if "object_ids" not in output_structure or "semantic_objects" not in output_structure:
        output_structure = DEFAULT_OUTPUT_STRUCTURE
    return methodology, output_structure



def _obj_bounds_xyxy(obj: dict[str, Any]) -> tuple[float, float, float, float] | None:
    box = obj.get("bbox") if isinstance(obj.get("bbox"), dict) else None
    if not box:
        return None
    try:
        x1 = float(box.get("x", 0)); y1 = float(box.get("y", 0))
        return x1, y1, x1 + float(box.get("w", 0)), y1 + float(box.get("h", 0))
    except (TypeError, ValueError):
        return None


def _elem_bounds_xyxy(elem: dict[str, Any]) -> tuple[float, float, float, float] | None:
    source = elem.get("raw_bbox") if isinstance(elem.get("raw_bbox"), dict) else elem.get("bbox")
    if not isinstance(source, dict):
        return None
    try:
        x1 = float(source.get("x", 0)); y1 = float(source.get("y", 0))
        return x1, y1, x1 + float(source.get("w", 0)), y1 + float(source.get("h", 0))
    except (TypeError, ValueError):
        return None


def _box_gap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    """Shortest gap between two axis-aligned rectangles (0 if overlapping)."""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    dx = max(ax1 - bx2, 0.0, bx1 - ax2)
    dy = max(ay1 - by2, 0.0, by1 - ay2)
    return float((dx * dx + dy * dy) ** 0.5)


def _union_bounds_list(bounds_list: list[tuple[float, float, float, float]]) -> dict[str, int]:
    x1 = min(b[0] for b in bounds_list); y1 = min(b[1] for b in bounds_list)
    x2 = max(b[2] for b in bounds_list); y2 = max(b[3] for b in bounds_list)
    return {"x": max(0, round(x1)), "y": max(0, round(y1)), "w": max(1, round(x2 - x1)), "h": max(1, round(y2 - y1))}


def _absorb_residuals_into_objects(
    objects: list[dict[str, Any]],
    residual: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Absorb residual fragments into the nearest semantic_object by box-to-box distance.

    Each residual element is assigned to its single nearest object (no 1.5x
    ambiguity gate - we want every fragment absorbed before VL sees the crops).
    Object bbox and element_ids are updated to include absorbed fragments.
    """
    if not objects or not residual:
        return objects
    obj_bounds = []
    for obj in objects:
        bounds = _obj_bounds_xyxy(obj)
        obj_bounds.append(bounds if bounds else (0.0, 0.0, 0.0, 0.0))
    elem_map: dict[str, dict[str, Any]] = {}
    for elem in residual:
        eid = str(elem.get("element_id") or "")
        if eid:
            elem_map[eid] = elem
        eb = _elem_bounds_xyxy(elem)
        if not eb:
            continue
        best_idx = -1
        best_dist = float("inf")
        for idx, ob in enumerate(obj_bounds):
            d = _box_gap(ob, eb)
            if d < best_dist:
                best_dist = d
                best_idx = idx
        if best_idx < 0:
            continue
        obj = objects[best_idx]
        existing = list(obj.get("element_ids", []) or [])
        if eid not in existing:
            existing.append(eid)
            obj["element_ids"] = existing
            obj["element_count"] = len(existing)
            obj.setdefault("absorbed_residual_ids", []).append(eid)
    # Recompute bbox for objects that absorbed fragments
    for obj in objects:
        absorbed = obj.get("absorbed_residual_ids", [])
        if not absorbed:
            continue
        all_bounds = []
        ob = _obj_bounds_xyxy(obj)
        if ob:
            all_bounds.append(ob)
        for eid in absorbed:
            elem = elem_map.get(eid)
            if elem:
                eb = _elem_bounds_xyxy(elem)
                if eb:
                    all_bounds.append(eb)
        if len(all_bounds) > 1:
            obj["bbox"] = _union_bounds_list(all_bounds)
    return objects


def _spatial_cluster_objects(
    objects: list[dict[str, Any]],
    target_count: int,
) -> list[dict[str, Any]]:
    """Cluster spatially-adjacent semantic_objects into ~target_count groups.

    Uses agglomerative merging by nearest box-to-box distance. Each cluster
    becomes one composite object whose bbox is the union of its members.
    """
    if len(objects) <= target_count or target_count < 1:
        return objects
    clusters: list[list[dict[str, Any]]] = [[obj] for obj in objects]
    cluster_bounds: list[tuple[float, float, float, float]] = []
    for cluster in clusters:
        bounds_list = [_obj_bounds_xyxy(obj) for obj in cluster]
        bounds_list = [b for b in bounds_list if b]
        if bounds_list:
            x1 = min(b[0] for b in bounds_list); y1 = min(b[1] for b in bounds_list)
            x2 = max(b[2] for b in bounds_list); y2 = max(b[3] for b in bounds_list)
            cluster_bounds.append((x1, y1, x2, y2))
        else:
            cluster_bounds.append((0.0, 0.0, 0.0, 0.0))

    while len(clusters) > target_count:
        best_i = -1
        best_j = -1
        best_dist = float("inf")
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                d = _box_gap(cluster_bounds[i], cluster_bounds[j])
                if d < best_dist:
                    best_dist = d
                    best_i = i
                    best_j = j
        if best_i < 0:
            break
        merged_bounds_list = [cluster_bounds[best_i], cluster_bounds[best_j]]
        x1 = min(b[0] for b in merged_bounds_list); y1 = min(b[1] for b in merged_bounds_list)
        x2 = max(b[2] for b in merged_bounds_list); y2 = max(b[3] for b in merged_bounds_list)
        clusters[best_i] = clusters[best_i] + clusters[best_j]
        cluster_bounds[best_i] = (x1, y1, x2, y2)
        clusters.pop(best_j)
        cluster_bounds.pop(best_j)

    result: list[dict[str, Any]] = []
    for idx, cluster in enumerate(clusters):
        if len(cluster) == 1:
            obj = dict(cluster[0])
            obj["object_id"] = f"obj_{idx + 1:03d}"
            obj["cluster_member_count"] = 1
            result.append(obj)
            continue
        all_eids: list[str] = []
        for member in cluster:
            all_eids.extend(str(eid) for eid in member.get("element_ids", []) or [])
        unique_eids = list(dict.fromkeys(all_eids))
        bounds_list = [_obj_bounds_xyxy(obj) for obj in cluster]
        bounds_list = [b for b in bounds_list if b]
        bbox = _union_bounds_list(bounds_list) if bounds_list else {"x": 0, "y": 0, "w": 1, "h": 1}
        cx = bbox["x"] + bbox["w"] / 2
        cy = bbox["y"] + bbox["h"] / 2
        result.append({
            "object_id": f"obj_{idx + 1:03d}",
            "type": "spatial_cluster",
            "bbox": bbox,
            "center": {"x": round(cx, 2), "y": round(cy, 2)},
            "element_ids": unique_eids,
            "element_count": len(unique_eids),
            "cluster_member_count": len(cluster),
            "member_object_ids": [str(m.get("object_id") or "") for m in cluster],
            "reason": f"spatial cluster of {len(cluster)} adjacent objects",
            "exclusive": True,
        })
    return result


def _crop_object_bytes(image_path: Path, obj: dict[str, Any], max_width: int = 400) -> bytes | None:

    """Crop a single semantic_object region from the slide image and return PNG bytes.

    Adds a small padding around the bbox and draws the object_id label on top
    so VL can identify which crop is which object.
    """
    box = obj.get("bbox") if isinstance(obj.get("bbox"), dict) else None
    if not box:
        return None
    try:
        image = Image.open(image_path).convert("RGB")
        ow, oh = image.size
        sx = MAX_IMAGE_WIDTH / ow if ow > MAX_IMAGE_WIDTH else 1.0
        if ow > MAX_IMAGE_WIDTH:
            ratio = MAX_IMAGE_WIDTH / ow
            image = image.resize((MAX_IMAGE_WIDTH, max(1, int(oh * ratio))), Image.Resampling.LANCZOS)
        x = int(float(box.get("x", 0)) * sx)
        y = int(float(box.get("y", 0)) * sx)
        w = int(float(box.get("w", 0)) * sx)
        h = int(float(box.get("h", 0)) * sx)
        # Add padding so VL sees context around the element
        pad = max(8, min(20, w // 10))
        x1 = max(0, x - pad)
        y1 = max(0, y - pad)
        x2 = min(image.width, x + w + pad)
        y2 = min(image.height, y + h + pad)
        if x2 <= x1 or y2 <= y1:
            return None
        crop = image.crop((x1, y1, x2, y2))
        # Resize if too wide, but keep aspect ratio
        if crop.width > max_width:
            ratio = max_width / crop.width
            crop = crop.resize((max_width, max(1, int(crop.height * ratio))), Image.Resampling.LANCZOS)
        # Draw object_id label at top-left
        draw = ImageDraw.Draw(crop)
        label = str(obj.get("object_id") or "")
        label_bg = (255, 255, 200)
        label_fg = (180, 30, 50)
        try:
            bbox = draw.textbbox((4, 2), label)
            draw.rectangle(bbox, fill=label_bg)
            draw.text((4, 2), label, fill=label_fg)
        except Exception:
            pass
        buffer = io.BytesIO()
        crop.save(buffer, format="PNG")
        return buffer.getvalue()
    except Exception:
        return None


def _patched_vision_match(base_module: ModuleType):
    def vision_match(server_module: ModuleType, project: Any, slide: dict[str, Any], elements: list[dict[str, Any]], image_path: Path, overlay_path: Path, methodology: str, output_structure: str, settings: dict[str, Any]) -> dict[str, Any] | None:
        api_key = server_module.get_setting("llm_api_key")
        if not api_key:
            return None
        with Image.open(image_path) as image:
            width, height = image.size
        objects = _semantic_objects(elements, width, height)
        # Read residual fragments from auto_elements.json so we can absorb them
        # into semantic_objects BEFORE VL sees the crops.  This ensures VL
        # gets complete object crops that include nearby stray fragments.
        residual_elements: list[dict[str, Any]] = []
        try:
            ae_path = overlay_path.parent / "auto_elements.json"
            if ae_path.exists():
                ae_data = json.loads(ae_path.read_text(encoding="utf-8"))
                residual_elements = list(ae_data.get("residual_elements", []) or [])
        except Exception:
            pass
        objects = _absorb_residuals_into_objects(objects, residual_elements)
        # Spatially cluster objects so VL sees at most (beats + 3) crops.
        beat_count = len(slide.get("narration_beats", []) or [])
        target_count = max(1, min(12, beat_count + 3))
        pre_cluster_count = len(objects)
        objects = _spatial_cluster_objects(objects, target_count)
        try:
            base_module._write_json(overlay_path.parent / "semantic_objects.json", {
                "version": "semantic_objects_v2_clustered",
                "slide_id": slide.get("slide_id"),
                "canvas": {"width": width, "height": height},
                "objects": objects,
                "source_auto_element_count": len(elements),
                "residual_absorbed_count": len(residual_elements),
                "pre_cluster_object_count": pre_cluster_count,
                "target_cluster_count": target_count,
            })
        except Exception:
            pass
        clean_bytes = _png_bytes(image_path, overlay_path.with_name("clean_original_for_vision.png"))
        model, _ = base_module._resolved_vision_model(server_module)
        base_url = server_module.get_setting("llm_base_url")
        vendor_options: dict[str, Any] = {}
        option_builder = getattr(server_module, "step2_llm_vendor_options", None)
        if callable(option_builder):
            vendor_options = option_builder(model, base_url) or {}
        client = server_module.get_openai_client(api_key=api_key, base_url=base_url, timeout=base_module.AI_MASK_VISION_TIMEOUT_SEC, max_retries=0)

        # Build crop images for each semantic_object — VL sees actual visual
        # content, not coordinate numbers. Each crop is labeled with object_id.
        crop_entries = []
        for obj in objects:
            crop_bytes = _crop_object_bytes(image_path, obj)
            if crop_bytes:
                crop_entries.append({
                    "object_id": obj.get("object_id"),
                    "type": obj.get("type"),
                    "element_count": obj.get("element_count"),
                    "image_data": crop_bytes,
                })

        # Simplified payload: slide context + object IDs (no coordinates)
        payload = {
            "slide": {key: slide.get(key) for key in ("slide_id", "main_title", "subtitle", "core_message", "body_content", "visual_groups", "narration_beats")},
            "semantic_objects": [
                {
                    "object_id": obj.get("object_id"),
                    "type": obj.get("type"),
                    "element_count": obj.get("element_count"),
                    "bbox": obj.get("bbox", {}),
                    "center": obj.get("center", {}),
                    "cluster_member_count": obj.get("cluster_member_count", 1),
                }
                for obj in objects
            ],
            "instruction": "先看完整原图理解全局版式和阅读顺序，再看每个 object_XXX 的切片图及其 bbox 坐标。根据切片图视觉内容和空间位置（bbox 的 x/y/w/h），选择 object_id 对应到 visual_groups 和 narration_beats。一个 object 可能包含多个空间相邻的语义元素（cluster_member_count>1），应作为整体归属。输出 object_ids 和 element_ids。",
        }
        prompt = methodology.strip() + "\n\n--- OUTPUT STRUCTURE / 输出结构 ---\n" + output_structure.strip()
        clean_url = "data:image/png;base64," + base64.b64encode(clean_bytes).decode("ascii")

        # Build user message: text payload + full image + each crop image
        user_content = [
            {"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)},
            {"type": "text", "text": "完整原图（image_full）：理解全局版式和阅读顺序。"},
            {"type": "image_url", "image_url": {"url": clean_url}},
        ]
        for entry in crop_entries:
            oid = entry["object_id"]
            otype = entry["type"]
            crop_url = "data:image/png;base64," + base64.b64encode(entry["image_data"]).decode("ascii")
            user_content.append({"type": "text", "text": f"{oid}（类型:{otype}）：此对象的切片图。"})
            user_content.append({"type": "image_url", "image_url": {"url": crop_url}})

        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_content},
        ]
        try:
            try:
                response = client.chat.completions.create(model=model, temperature=float(settings["llm_temperature"]), max_tokens=12000, timeout=base_module.AI_MASK_VISION_TIMEOUT_SEC, response_format={"type": "json_object"}, messages=messages, **vendor_options)
            except Exception as exc:
                if base_module._is_timeout(server_module, exc):
                    raise
                response = client.chat.completions.create(model=model, temperature=float(settings["llm_temperature"]), max_tokens=12000, timeout=base_module.AI_MASK_VISION_TIMEOUT_SEC, messages=messages, **vendor_options)
            content = str(response.choices[0].message.content or "").strip()
            cleaner = getattr(server_module, "clean_json_markdown", None)
            cleaned = cleaner(content) if callable(cleaner) else content.strip().removeprefix("```json").removesuffix("```").strip()
            value = json.loads(cleaned)
            return _expand_matches(value, objects, elements) if isinstance(value, dict) else None
        finally:
            try:
                client.close()
            except Exception:
                pass
    return vision_match


def install() -> bool:
    try:
        import runtime_ai_mask as base_module
    except Exception:
        return False
    if getattr(base_module, PATCH_MARKER, False):
        return True
    original_read = getattr(base_module, "_read_ai_mask_prompts", None)
    if not callable(original_read) or not callable(getattr(base_module, "_vision_match", None)):
        return False
    base_module.DEFAULT_METHODOLOGY = DEFAULT_METHODOLOGY
    base_module.DEFAULT_OUTPUT_STRUCTURE = DEFAULT_OUTPUT_STRUCTURE
    base_module._read_ai_mask_prompts = lambda server_module: _patch_read_prompts(original_read, server_module)
    base_module._vision_match = _patched_vision_match(base_module)
    setattr(base_module, PATCH_MARKER, True)
    return True


install()
