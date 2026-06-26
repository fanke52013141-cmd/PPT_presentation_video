"""Additive AI Mask annotation routes and UI injection.

This bridge keeps the existing manual Mask pipeline intact. AI annotation writes
compatible manual_mask.strokes into reveal_manifest.json, so build_reveal_scene.py
continues to use the current manual_mask_boundary_white_v4 path.
"""

from __future__ import annotations

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
from PIL import Image
from starlette.responses import Response

PATCH_MARKER = "__ppt_ai_mask_runtime_patch__"
INJECT_MARKER = "__ppt_ai_mask_inject_patch__"
SETTING_PREFIX = "ai_mask_"

DEFAULT_SETTINGS: dict[str, Any] = {
    "white_threshold": 245,
    "color_tolerance": 12,
    "add_border": 2,
    "connectivity": 8,
    "min_element_area": 120,
    "component_padding_px": 12,
    "merge_gap_px": 40,
    "max_group_elements": 8,
    "subtitle_safe_y": 930,
    "llm_confidence_threshold": 0.72,
    "llm_temperature": 0.1,
    "stroke_brush_size": 96,
    "overwrite_existing_manual_mask": False,
    "skip_locked_groups": True,
}

DEFAULT_METHODOLOGY = """你是中文 PPT 视频的 AI Mask 语义标注专家。

任务：把纯白背景图片中自动检测到的视觉元素候选，绑定到当前 Slide 已有的 visual_groups 和 narration_beats。你不是重新生成分镜，也不是重写演讲稿；你只做“画面元素 → 语块 → 演讲稿 beat”的匹配。

可修改方法论：
1. group_id 只能使用输入 visual_groups[].id，不要发明新的 group。
2. narration_beat_id 只能使用输入 narration_beats[].id。
3. element_ids 只能使用输入 auto_elements[].element_id。
4. 优先匹配 visible_text、visible_anchor、spoken_text，再参考位置、role 和阅读顺序。
5. 一个语块可以绑定多个元素，例如图标 + 标题 + 说明文字、箭头 + 两端节点、流程数字 + 标签。
6. 不确定时降低 confidence，不要强行匹配。装饰或无口播元素放入 unmatched_elements。
7. 输出必须是严格 JSON，不要 Markdown，不要解释段落。
"""

DEFAULT_OUTPUT_STRUCTURE = """必须输出一个 JSON object：
{
  "slide_id": "slide_001",
  "matches": [
    {
      "group_id": "title_group",
      "narration_beat_id": "beat_title",
      "element_ids": ["el_auto_001"],
      "confidence": 0.95,
      "reason": "顶部文字区域与标题 visible_text 一致"
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
        "merge_gap_px": _int(raw.get("merge_gap_px"), 40, 0, 160),
        "max_group_elements": _int(raw.get("max_group_elements"), 8, 1, 20),
        "subtitle_safe_y": _int(raw.get("subtitle_safe_y"), 930, 760, 1080),
        "llm_confidence_threshold": _float(raw.get("llm_confidence_threshold"), 0.72, 0, 1),
        "llm_temperature": _float(raw.get("llm_temperature"), 0.1, 0, 1),
        "stroke_brush_size": _int(raw.get("stroke_brush_size"), 96, 24, 240),
        "overwrite_existing_manual_mask": _bool(raw.get("overwrite_existing_manual_mask"), False),
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
    visited = np.zeros((h, w), dtype=bool)
    ys, xs = np.nonzero(fg)
    elements: list[dict[str, Any]] = []
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
        if len(coords) < int(settings["min_element_area"]):
            continue
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
        eid = f"el_auto_{len(elements) + 1:03d}"
        image.crop((box["x"], box["y"], box["x"] + box["w"], box["y"] + box["h"])).save(crop_dir / f"{eid}.png")
        cx, cy = box["x"] + box["w"] / 2, box["y"] + box["h"] / 2
        elements.append({
            "element_id": eid,
            "bbox": box,
            "raw_bbox": raw,
            "center": {"x": round(cx, 2), "y": round(cy, 2)},
            "area": len(coords),
            "position": _position(cx, cy, ow, oh),
            "ocr_text": "",
        })
    elements.sort(key=lambda e: (e["bbox"]["y"], e["bbox"]["x"]))
    for i, element in enumerate(elements, 1):
        element["element_id"] = f"el_auto_{i:03d}"
    payload = {"version": "auto_elements_v1", "slide_id": slide_dir.name, "canvas": {"width": ow, "height": oh}, "elements": elements}
    _write_json(out_dir / "auto_elements.json", payload)
    return payload


def _fallback_match(slide: dict[str, Any], elements: list[dict[str, Any]]) -> dict[str, Any]:
    groups = [g for g in slide.get("visual_groups", []) or [] if isinstance(g, dict) and str(g.get("role") or "") != "decoration"]
    beat_by_group = {str(b.get("group_id") or ""): str(b.get("id") or "") for b in slide.get("narration_beats", []) or [] if isinstance(b, dict)}
    matches = []
    for group, element in zip(groups, elements):
        gid = str(group.get("id") or "")
        matches.append({"group_id": gid, "narration_beat_id": beat_by_group.get(gid, ""), "element_ids": [element["element_id"]], "confidence": 0.51, "reason": "fallback order match"})
    return {"slide_id": slide.get("slide_id"), "matches": matches, "unmatched_elements": [], "unmatched_groups": [], "warnings": ["fallback_order_matching_used"]}


def _clean_match(result: Any, slide: dict[str, Any], elements: list[dict[str, Any]], settings: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(result, dict):
        result = _fallback_match(slide, elements)
    known_groups = {str(g.get("id") or "") for g in slide.get("visual_groups", []) or [] if isinstance(g, dict)}
    known_beats = {str(b.get("id") or "") for b in slide.get("narration_beats", []) or [] if isinstance(b, dict)}
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
        eids = [str(e) for e in item.get("element_ids", []) if str(e) in known_elements][: int(settings["max_group_elements"])]
        if not eids:
            continue
        try:
            conf = float(item.get("confidence", 0))
        except Exception:
            conf = 0
        matches.append({"group_id": gid, "narration_beat_id": bid, "element_ids": eids, "confidence": conf, "reason": str(item.get("reason") or ""), "below_threshold": conf < float(settings["llm_confidence_threshold"])})
        used.update(eids)
    return {"slide_id": slide.get("slide_id"), "matches": matches, "unmatched_elements": sorted(known_elements - used), "unmatched_groups": result.get("unmatched_groups", []), "warnings": result.get("warnings", []) if isinstance(result.get("warnings"), list) else []}


def _union(boxes: list[dict[str, int]], width: int, height: int, padding: int) -> dict[str, int]:
    x1 = min(b["x"] for b in boxes)
    y1 = min(b["y"] for b in boxes)
    x2 = max(b["x"] + b["w"] for b in boxes)
    y2 = max(b["y"] + b["h"] for b in boxes)
    return _pad_box({"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1}, width, height, padding)


def _manual_mask_from_box(box: dict[str, int], brush_size: int, color: str = "#E84A5F") -> dict[str, Any]:
    x1, y1, x2, y2 = box["x"], box["y"], box["x"] + box["w"], box["y"] + box["h"]
    size = max(24, int(brush_size))
    step = max(8, int(size * 0.62))
    strokes = []
    y = y1 + size // 2
    while y <= y2 - size // 3:
        strokes.append({"mode": "paint", "eraser": False, "size": size, "color": color, "points": [{"x": x1, "y": y}, {"x": x2, "y": y}]})
        y += step
    if not strokes:
        strokes.append({"mode": "paint", "eraser": False, "size": size, "color": color, "points": [{"x": x1, "y": (y1 + y2) // 2}, {"x": x2, "y": (y1 + y2) // 2}]})
    return {"source": "ai_auto_mask_v1", "color": color, "bounds": box, "strokes": strokes}


def _has_manual(group: dict[str, Any]) -> bool:
    strokes = group.get("manual_mask", {}).get("strokes") if isinstance(group.get("manual_mask"), dict) else []
    return isinstance(strokes, list) and any(isinstance(s, dict) and s.get("points") for s in strokes)


def _find_group(groups: list[dict[str, Any]], gid: str) -> dict[str, Any] | None:
    for group in groups:
        if isinstance(group, dict) and str(group.get("id") or group.get("group_id") or "") == gid:
            return group
    return None


def _apply(manifest: dict[str, Any], slide: dict[str, Any], elements_payload: dict[str, Any], match_payload: dict[str, Any], settings: dict[str, Any]) -> dict[str, int]:
    slide_id = str(slide.get("slide_id") or "")
    mslide = next((s for s in manifest.get("slides", []) if isinstance(s, dict) and str(s.get("slide_id") or "") == slide_id), None)
    if not mslide:
        raise RuntimeError(f"Missing reveal manifest slide: {slide_id}")
    groups = mslide.setdefault("groups", [])
    semantic = mslide.setdefault("semantic_blocks", [])
    canvas = elements_payload.get("canvas", {})
    width, height = int(canvas.get("width", 1920)), int(canvas.get("height", 1080))
    by_element = {e["element_id"]: e for e in elements_payload.get("elements", []) if isinstance(e, dict)}
    updated = skipped = 0
    for match in match_payload.get("matches", []) or []:
        if match.get("below_threshold"):
            skipped += 1
            continue
        gid = match["group_id"]
        boxes = [by_element[eid]["bbox"] for eid in match.get("element_ids", []) if eid in by_element]
        if not boxes:
            skipped += 1
            continue
        box = _union(boxes, width, height, int(settings["merge_gap_px"]) // 4)
        if box["y"] + box["h"] > int(settings["subtitle_safe_y"]):
            box["h"] = max(1, int(settings["subtitle_safe_y"]) - box["y"])
        for collection in (groups, semantic):
            group = _find_group(collection, gid)
            if group is None:
                group = {"id": gid, "group_id": gid, "role": "body_content", "visible_text": gid, "padding_px": 32, "z_index": 40 + len(collection)}
                collection.append(group)
            if settings["skip_locked_groups"] and str(group.get("review_status") or "") in {"approved", "locked"}:
                continue
            if _has_manual(group) and not settings["overwrite_existing_manual_mask"]:
                continue
            group["box"] = box
            group["manual_mask"] = _manual_mask_from_box(box, int(settings["stroke_brush_size"]), group.get("manual_mask", {}).get("color", "#E84A5F") if isinstance(group.get("manual_mask"), dict) else "#E84A5F")
            group["review_status"] = "ai_matched_needs_review"
            group["source"] = group.get("source") or "ai_auto_mask"
            if match.get("narration_beat_id"):
                group["narration_beat_id"] = match["narration_beat_id"]
            group["auto_mask"] = {"version": "auto_mask_v1", "method": "white_connected_component_v1", "element_ids": match.get("element_ids", []), "bbox": box, "compatible_manual_mask": True}
            group["ai_match"] = {"confidence": match.get("confidence"), "reason": match.get("reason", "")}
        updated += 1
    mslide["ai_mask_status"] = {"version": "ai_mask_annotation_v1", "updated_group_count": updated, "skipped_group_count": skipped, "detected_element_count": len(elements_payload.get("elements", []))}
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
    methodology = server_module.get_setting(PROMPT_METHOD_KEY, DEFAULT_METHODOLOGY) or DEFAULT_METHODOLOGY
    output_structure = server_module.get_setting(PROMPT_OUTPUT_KEY, DEFAULT_OUTPUT_STRUCTURE) or DEFAULT_OUTPUT_STRUCTURE
    slides_out = []
    total_updated = 0
    for slide in contract.get("slides", []) or []:
        if not isinstance(slide, dict):
            continue
        slide_id = str(slide.get("slide_id") or "")
        slide_dir = run_dir / "slides" / slide_id
        elements = detect_elements(slide_dir / "visual_draft.png", slide_dir, settings)
        user_payload = {"slide": {k: slide.get(k) for k in ("slide_id", "main_title", "subtitle", "core_message", "body_content", "visual_groups", "narration_beats")}, "auto_elements": elements.get("elements", [])}
        system_prompt = methodology + "\n\n--- OUTPUT STRUCTURE / 输出结构 ---\n" + output_structure
        user_prompt = "请根据下面 JSON 完成 AI Mask 语块绑定。只返回严格 JSON。\n" + json.dumps(user_payload, ensure_ascii=False, indent=2)
        try:
            raw = server_module.generate_json_with_configured_llm(system_prompt=system_prompt, user_prompt=user_prompt, run_dir=project.run_dir, artifact_prefix=f"ai_mask_match_{slide_id}", schema_hint=output_structure, temperature=float(settings["llm_temperature"]), max_tokens_default=12000)
        except Exception as exc:
            raw = _fallback_match(slide, elements.get("elements", []))
            raw.setdefault("warnings", []).append(f"llm_match_failed: {exc}")
        match = _clean_match(raw, slide, elements.get("elements", []), settings)
        _write_json(slide_dir / "auto_mask" / "auto_match.json", match)
        applied = _apply(manifest, slide, elements, match, settings)
        total_updated += applied["updated"]
        slides_out.append({"slide_id": slide_id, "detected_element_count": len(elements.get("elements", [])), "matched_group_count": len(match.get("matches", [])), "updated_group_count": applied["updated"], "skipped_group_count": applied["skipped"], "unmatched_element_count": len(match.get("unmatched_elements", [])), "unmatched_group_count": len(match.get("unmatched_groups", [])), "warnings": match.get("warnings", [])})
    manifest["ai_mask_annotation"] = {"version": "ai_mask_annotation_v1", "settings": settings, "processed_slide_count": len(slides_out), "updated_group_count": total_updated}
    _write_json(run_dir / "reveal_manifest.json", manifest)
    return {"success": True, "processed_slide_count": len(slides_out), "updated_group_count": total_updated, "slides": slides_out, "manifest_path": str(run_dir / "reveal_manifest.json")}


def _install_injection(app: Any) -> None:
    if getattr(app.state, INJECT_MARKER, False):
        return

    @app.middleware("http")
    async def ai_mask_asset_injection(request: Any, call_next: Any) -> Any:
        response = await call_next(request)
        if "text/html" not in response.headers.get("content-type", "").lower():
            return response
        try:
            body = b"".join([chunk async for chunk in response.body_iterator]).decode("utf-8")
        except Exception:
            return response
        if "ai_mask_extension.js" not in body and "</body>" in body:
            body = body.replace("</body>", '  <script src="ai_mask_extension.js?v=1.0.0"></script>\n</body>')
        headers = dict(response.headers)
        headers.pop("content-length", None)
        return Response(body, status_code=response.status_code, headers=headers, media_type="text/html")

    setattr(app.state, INJECT_MARKER, True)


def _register(server_module: ModuleType) -> bool:
    if getattr(server_module, PATCH_MARKER, False):
        return True
    required = ("app", "Project", "HTTPException", "Depends", "get_db", "generate_json_with_configured_llm", "update_settings", "get_setting", "reveal_lock_for", "write_project_log")
    if not all(hasattr(server_module, item) for item in required):
        return False
    app = server_module.app

    async def get_ai_mask_settings() -> dict[str, Any]:
        return {"success": True, "settings": _get_store_settings(server_module), "prompts": {"methodology": server_module.get_setting(PROMPT_METHOD_KEY, DEFAULT_METHODOLOGY) or DEFAULT_METHODOLOGY, "output_structure": server_module.get_setting(PROMPT_OUTPUT_KEY, DEFAULT_OUTPUT_STRUCTURE) or DEFAULT_OUTPUT_STRUCTURE}}

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
    try:
        _install_injection(app)
    except Exception:
        pass
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
