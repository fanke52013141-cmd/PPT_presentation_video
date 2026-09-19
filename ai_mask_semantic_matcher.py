"""Semantic-object multimodal matcher for AI Mask annotation."""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

import ai_mask_engine

MAX_IMAGE_WIDTH = 1280


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
    for index, obj in enumerate(canonical, start=1):
        obj["object_id"] = f"obj_{index:03d}"
    return canonical


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


AI_MASK_PAGE_SIZE = 12
AI_MASK_MAX_PAGES = 6


def _plan_object_pages(
    objects: list[dict[str, Any]],
    page_size: int = AI_MASK_PAGE_SIZE,
    max_pages: int = AI_MASK_MAX_PAGES,
) -> dict[str, Any]:
    """Split every semantic object into VL request pages without dropping any.

    When the object count exceeds page_size * max_pages the page size grows so
    all objects still reach the model within max_pages requests; the overflow
    is reported instead of being silently truncated.
    """
    total = len(objects)
    pages: list[list[dict[str, Any]]] = []
    if total:
        required_pages = -(-total // page_size)
        overflow = required_pages > max_pages
        effective_size = -(-total // max_pages) if overflow else page_size
        for start in range(0, total, effective_size):
            pages.append(objects[start:start + effective_size])
    else:
        overflow = False
        effective_size = page_size
    return {
        "pages": pages,
        "page_size": effective_size,
        "overflow": overflow,
        "total_objects": total,
    }


def _merge_page_values(
    page_values: list[dict[str, Any]],
    budget_exceeded: bool = False,
    object_count: int = 0,
) -> dict[str, Any] | None:
    """Combine per-page model outputs into one match document.

    Matches for the same group/beat across pages are unioned; every object ID
    from every page is preserved. Page-budget overflow is surfaced as a
    warning instead of dropping candidates.
    """
    if not page_values:
        return None
    merged = dict(page_values[0])
    matches_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    order: list[tuple[str, str]] = []
    for value in page_values:
        for match in value.get("matches", []) or []:
            if not isinstance(match, dict):
                continue
            key = (str(match.get("group_id") or ""), str(match.get("narration_beat_id") or ""))
            existing = matches_by_key.get(key)
            if existing is None:
                matches_by_key[key] = dict(match)
                order.append(key)
                continue
            for field in ("object_ids", "element_ids"):
                existing[field] = list(dict.fromkeys(
                    [str(v) for v in existing.get(field, []) or []]
                    + [str(v) for v in match.get(field, []) or []]
                ))
            try:
                existing["confidence"] = max(
                    float(existing.get("confidence", 0) or 0),
                    float(match.get("confidence", 0) or 0),
                )
            except (TypeError, ValueError):
                pass
            reasons = [text for text in (str(existing.get("reason") or ""), str(match.get("reason") or "")) if text]
            existing["reason"] = "；".join(dict.fromkeys(reasons))
    merged["matches"] = [matches_by_key[key] for key in order]
    for field in ("unmatched_objects", "unmatched_elements", "unmatched_groups"):
        merged[field] = list(dict.fromkeys(
            str(item) for value in page_values for item in (value.get(field) or [])
        ))
    warnings = [item for value in page_values for item in (value.get("warnings") or []) if isinstance(item, dict)]
    if budget_exceeded:
        warnings.append({
            "type": "object_page_budget_exceeded",
            "object_ids": [],
            "reason": f"语义对象数量 {object_count} 超过分页预算，已放大每页对象数并全量送模，请复核分组粒度",
        })
    merged["warnings"] = warnings
    merged["pages_merged"] = len(page_values)
    return merged


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


class SemanticVisionMatcher:
    """Match detected slide components to narrated groups by semantic object."""

    def __call__(
        self,
        capabilities: Any,
        project: Any,
        slide: dict[str, Any],
        elements: list[dict[str, Any]],
        image_path: Path,
        overlay_path: Path,
        methodology: str,
        output_structure: str,
        settings: dict[str, Any],
    ) -> dict[str, Any] | None:
        base_module = ai_mask_engine
        api_key = capabilities.get_setting("llm_api_key")
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
        plan = _plan_object_pages(objects)
        pages = plan["pages"]
        try:
            base_module._write_json(overlay_path.parent / "semantic_objects.json", {
                "version": "semantic_objects_v3_paged",
                "slide_id": slide.get("slide_id"),
                "canvas": {"width": width, "height": height},
                "objects": objects,
                "source_auto_element_count": len(elements),
                "residual_absorbed_count": len(residual_elements),
                "object_count": len(objects),
                "page_count": len(pages),
                "page_size": plan["page_size"],
                "page_budget_exceeded": plan["overflow"],
                "page_object_ids": [
                    [str(obj.get("object_id") or "") for obj in page] for page in pages
                ],
            })
        except Exception:
            pass
        if not pages:
            return None
        clean_bytes = _png_bytes(image_path, overlay_path.with_name("clean_original_for_vision.png"))
        model, _ = base_module._resolved_vision_model(capabilities)
        base_url = capabilities.get_setting("llm_base_url")
        vendor_options = capabilities.step2_llm_vendor_options(model, base_url) or {}
        client = capabilities.get_openai_client(api_key=api_key, base_url=base_url, timeout=base_module.AI_MASK_VISION_TIMEOUT_SEC, max_retries=0)
        prompt = methodology.strip() + "\n\n--- OUTPUT STRUCTURE / 输出结构 ---\n" + output_structure.strip()
        clean_url = "data:image/png;base64," + base64.b64encode(clean_bytes).decode("ascii")
        slide_context = {key: slide.get(key) for key in ("slide_id", "main_title", "subtitle", "core_message", "body_content", "visual_groups", "narration_beats")}

        page_values: list[dict[str, Any]] = []
        page_errors: list[tuple[int, BaseException]] = []
        try:
            for page_index, page in enumerate(pages, 1):
                try:
                    value = self._match_page(
                        client=client,
                        capabilities=capabilities,
                        base_module=base_module,
                        model=model,
                        vendor_options=vendor_options,
                        settings=settings,
                        prompt=prompt,
                        clean_url=clean_url,
                        slide_context=slide_context,
                        image_path=image_path,
                        page=page,
                        page_index=page_index,
                        page_count=len(pages),
                        objects=objects,
                        elements=elements,
                    )
                except Exception as exc:
                    page_errors.append((page_index, exc))
                    continue
                if value is not None:
                    page_values.append(value)
        finally:
            try:
                client.close()
            except Exception:
                pass
        if not page_values and page_errors:
            raise page_errors[0][1]
        merged = _merge_page_values(page_values, budget_exceeded=plan["overflow"], object_count=len(objects))
        if merged is not None and page_errors:
            for page_index, exc in page_errors:
                merged.setdefault("warnings", []).append({
                    "type": "semantic_object_page_failed",
                    "object_ids": [],
                    "reason": f"第 {page_index} 页视觉匹配失败，该页对象由确定性回退处理：{type(exc).__name__}: {str(exc)[:200]}",
                })
        return merged

    def _match_page(
        self,
        *,
        client: Any,
        capabilities: Any,
        base_module: Any,
        model: str,
        vendor_options: dict[str, Any],
        settings: dict[str, Any],
        prompt: str,
        clean_url: str,
        slide_context: dict[str, Any],
        image_path: Path,
        page: list[dict[str, Any]],
        page_index: int,
        page_count: int,
        objects: list[dict[str, Any]],
        elements: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        # Simplified payload: slide context + this page's object IDs. VL sees
        # real crops, not raw coordinate guesswork; coordinates stay local
        # evidence because downstream expands objects back to element RLEs.
        payload = {
            "slide": slide_context,
            "semantic_objects": [
                {
                    "object_id": obj.get("object_id"),
                    "type": obj.get("type"),
                    "element_count": obj.get("element_count"),
                    "bbox": obj.get("bbox", {}),
                    "center": obj.get("center", {}),
                }
                for obj in page
            ],
            "page": {"index": page_index, "total": page_count},
            "instruction": "先看完整原图理解全局版式和阅读顺序，再看本页每个 object_XXX 的切片图及其 bbox 坐标。根据切片图视觉内容和空间位置（bbox 的 x/y/w/h），选择 object_id 对应到 visual_groups 和 narration_beats。本次请求是第 {index}/{total} 页：只归属本页列出的 object_ids，其余对象由其他页面负责，不要为它们输出匹配。输出 object_ids 和 element_ids。".format(index=page_index, total=page_count),
        }
        user_content = [
            {"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)},
            {"type": "text", "text": "完整原图（image_full）：理解全局版式和阅读顺序。"},
            {"type": "image_url", "image_url": {"url": clean_url}},
        ]
        for obj in page:
            crop_bytes = _crop_object_bytes(image_path, obj)
            if not crop_bytes:
                continue
            crop_url = "data:image/png;base64," + base64.b64encode(crop_bytes).decode("ascii")
            user_content.append({"type": "text", "text": f"{obj.get('object_id')}（类型:{obj.get('type')}）：此对象的切片图。"})
            user_content.append({"type": "image_url", "image_url": {"url": crop_url}})
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_content},
        ]
        # One match record per object plus Chinese reasons can exceed the
        # legacy flat 12000 budget on dense pages and truncate mid-string.
        max_tokens = min(24000, 12000 + 600 * len(page))
        try:
            response = client.chat.completions.create(model=model, temperature=float(settings["llm_temperature"]), max_tokens=max_tokens, timeout=base_module.AI_MASK_VISION_TIMEOUT_SEC, response_format={"type": "json_object"}, messages=messages, **vendor_options)
        except Exception as exc:
            if base_module._is_timeout(capabilities, exc):
                raise
            response = client.chat.completions.create(model=model, temperature=float(settings["llm_temperature"]), max_tokens=max_tokens, timeout=base_module.AI_MASK_VISION_TIMEOUT_SEC, messages=messages, **vendor_options)
        content = str(response.choices[0].message.content or "").strip()
        cleaned = capabilities.clean_json_markdown(content)
        try:
            value = json.loads(cleaned)
        except json.JSONDecodeError:
            # A truncated or malformed completion is usually transient; one
            # fresh retry recovers the page without degrading to the prior.
            response = client.chat.completions.create(model=model, temperature=float(settings["llm_temperature"]), max_tokens=max_tokens, timeout=base_module.AI_MASK_VISION_TIMEOUT_SEC, messages=messages, **vendor_options)
            content = str(response.choices[0].message.content or "").strip()
            cleaned = capabilities.clean_json_markdown(content)
            value = json.loads(cleaned)
        return _expand_matches(value, objects, elements) if isinstance(value, dict) else None


semantic_vision_matcher = SemanticVisionMatcher()
