"""Pure Step 2 plan normalization and Visual Contract composition."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from visual_contract_service import narration_dedupe_key, normalize_visual_type


def stable_plan_id(value: Any, prefix: str, index: int) -> str:
    text = re.sub(r"[^a-zA-Z0-9_\\-]+", "_", str(value or "").strip())
    return text or f"{prefix}_{index:03d}"


def clean_planning_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def clean_planning_block(value: Any) -> str:
    if isinstance(value, list):
        parts = [clean_planning_text(item) for item in value]
        return "\n".join(part for part in parts if part)
    if isinstance(value, dict):
        parts = [clean_planning_text(item) for item in value.values()]
        return "\n".join(part for part in parts if part)
    return "\n".join(
        line
        for line in (clean_planning_text(line) for line in str(value or "").replace("\r", "\n").split("\n"))
        if line
    )


def normalize_slide_body(slide: Dict[str, Any]) -> str:
    body = clean_planning_block(slide.get("body") or slide.get("body_content") or slide.get("core_message"))
    if body:
        return body
    return "\n".join(point["text"] for point in normalize_body_points(slide.get("body_points")) if point.get("text"))


def normalize_body_points(value: Any, fallback_body: str = "") -> List[Dict[str, str]]:
    points = value if isinstance(value, list) else []
    normalized: List[Dict[str, str]] = []
    for index, point in enumerate(points, start=1):
        if isinstance(point, dict):
            text = clean_planning_text(point.get("text") or point.get("content") or "")
            purpose = clean_planning_text(point.get("purpose") or "")
            point_id = stable_plan_id(point.get("point_id"), "point", index)
        else:
            text = clean_planning_text(point)
            purpose = ""
            point_id = f"point_{index:03d}"
        if not text:
            continue
        normalized.append({"point_id": point_id, "text": text, "purpose": purpose})
    if not normalized and fallback_body:
        normalized.append({"point_id": "point_001", "text": clean_planning_text(fallback_body), "purpose": "正文"})
    return normalized


def normalize_narration_segments(value: Any, fallback_narration: str = "") -> List[Dict[str, str]]:
    segments = value if isinstance(value, list) else []
    normalized: List[Dict[str, str]] = []
    seen_narration: set[str] = set()
    previous_narration = ""
    for index, segment in enumerate(segments, start=1):
        if isinstance(segment, dict):
            narration = clean_planning_text(segment.get("narration") or segment.get("spoken_text") or "")
            purpose = clean_planning_text(segment.get("purpose") or segment.get("spoken_intent") or "")
            segment_id = stable_plan_id(segment.get("segment_id"), "seg", index)
        else:
            narration = clean_planning_text(segment)
            purpose = ""
            segment_id = f"seg_{index:03d}"
        if not narration or narration == previous_narration:
            continue
        narration_key = narration_dedupe_key(narration)
        if narration_key and narration_key in seen_narration:
            continue
        if narration_key:
            seen_narration.add(narration_key)
        normalized.append({"segment_id": segment_id, "narration": narration, "purpose": purpose})
        previous_narration = narration
    fallback_narration = clean_planning_text(fallback_narration)
    if not normalized and fallback_narration:
        normalized.append({"segment_id": "seg_001", "narration": fallback_narration, "purpose": "完整演讲稿"})
    return normalized


def normalize_slide_script_plan(plan: Dict[str, Any], project_title: str) -> Dict[str, Any]:
    slides = plan.get("slides") if isinstance(plan, dict) else []
    if not isinstance(slides, list) or not slides:
        raise HTTPException(status_code=500, detail="AI 没有返回可用的 slide_script_plan.slides")
    normalized_slides: List[Dict[str, Any]] = []
    for index, slide in enumerate(slides, start=1):
        if not isinstance(slide, dict):
            continue
        slide_id = stable_plan_id(slide.get("slide_id"), "slide", index)
        if not slide_id.startswith("slide_"):
            slide_id = f"slide_{index:03d}"
        narration = clean_planning_text(
            slide.get("narration")
            or slide.get("speech")
            or slide.get("script")
            or " ".join(
                clean_planning_text(segment.get("narration") if isinstance(segment, dict) else segment)
                for segment in (slide.get("narration_segments") or [])
            )
        )
        if not narration:
            raise HTTPException(status_code=500, detail=f"{slide_id} 缺少 narration")
        slide_title = clean_planning_text(slide.get("slide_title") or slide.get("title") or f"第 {index} 页")
        normalized_slides.append(
            {
                "slide_id": slide_id,
                "slide_title": slide_title,
                "narration": narration,
            }
        )
    if not normalized_slides:
        raise HTTPException(status_code=500, detail="AI 没有返回可用的 slide_script_plan.slides")
    return {"title": str(plan.get("title") or project_title).strip() or project_title, "slides": normalized_slides}


def normalize_visual_elements(value: Any) -> List[Dict[str, str]]:
    elements = value if isinstance(value, list) else []
    normalized: List[Dict[str, str]] = []
    for index, element in enumerate(elements, start=1):
        if not isinstance(element, dict):
            continue
        role = str(element.get("role") or "body").strip().lower()
        if role in {"content_body", "body_content"}:
            role = "body"
        visual_description = clean_planning_text(
            element.get("visual_description")
            or element.get("visible_text")
            or element.get("text")
            or ""
        )
        narration = clean_planning_text(element.get("narration") or "")
        visual_type = normalize_visual_type(element.get("visual_type"), has_text=bool(visual_description))
        if not visual_description:
            continue
        normalized.append(
            {
                "element_id": stable_plan_id(element.get("element_id"), "el", index),
                "role": role,
                "visual_type": visual_type,
                "visual_description": visual_description,
                "narration": narration,
            }
        )
    return normalized


def narration_sequence_key(value: Any) -> str:
    """Compare Step A narration with Step B fragments without hiding punctuation changes."""
    return re.sub(r"\s+", "", clean_planning_text(value))


def validate_slide_visual_mapping(
    slide_id: str,
    elements: List[Dict[str, str]],
    script_slide: Optional[Dict[str, Any]] = None,
) -> None:
    title_elements = [element for element in elements if element.get("role") == "title"]
    body_elements = [element for element in elements if element.get("role") == "body"]
    unsupported_roles = sorted({
        str(element.get("role") or "")
        for element in elements
        if element.get("role") not in {"title", "body"}
    })
    if unsupported_roles:
        raise HTTPException(
            status_code=500,
            detail=(
                f"{slide_id} 包含不参与一对一旁白映射的 role: {', '.join(unsupported_roles)}。"
                "系统不使用页面副标题；装饰由生图阶段处理，visual_elements 只能包含 title 和 body。"
            ),
        )
    if len(title_elements) != 1 or not elements or elements[0].get("role") != "title":
        raise HTTPException(status_code=500, detail=f"{slide_id} 必须以且仅以一个 title 元素开头")
    if not body_elements:
        raise HTTPException(status_code=500, detail=f"{slide_id} 至少需要一个 body 视觉元素")
    title = title_elements[0]
    if title.get("visual_type") != "text":
        raise HTTPException(status_code=500, detail=f"{slide_id} 的 title 必须使用 text 形式")
    for element in elements:
        if not str(element.get("narration") or "").strip():
            raise HTTPException(
                status_code=500,
                detail=f"{slide_id} 的 {element.get('element_id') or 'visual element'} 没有对应演讲片段",
            )
    if not isinstance(script_slide, dict):
        return
    expected_title = clean_planning_text(script_slide.get("slide_title") or "")
    if expected_title and clean_planning_text(title.get("visual_description")) != expected_title:
        raise HTTPException(
            status_code=500,
            detail=f"{slide_id} 的标题画面文字必须逐字等于 slide_title: {expected_title}",
        )
    source_narration = clean_planning_text(script_slide.get("narration") or "")
    combined_narration = "".join(str(element.get("narration") or "") for element in elements)
    if narration_sequence_key(combined_narration) != narration_sequence_key(source_narration):
        raise HTTPException(
            status_code=500,
            detail=(
                f"{slide_id} 的视觉元素演讲片段未能完整还原 Step A 演讲稿。"
                "每个片段必须非空、连续、无遗漏、无重复且保持原顺序。"
            ),
        )


def normalize_slide_visual_plan(
    plan: Dict[str, Any],
    script_plan: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    slides = plan.get("slides") if isinstance(plan, dict) else []
    if not isinstance(slides, list) or not slides:
        raise HTTPException(status_code=500, detail="AI 没有返回可用的 slide_visual_plan.slides")
    script_by_id = {
        str(slide.get("slide_id") or "").strip(): slide
        for slide in ((script_plan or {}).get("slides") or [])
        if isinstance(slide, dict)
    }
    normalized_slides: List[Dict[str, Any]] = []
    for index, slide in enumerate(slides, start=1):
        if not isinstance(slide, dict):
            continue
        slide_id = stable_plan_id(slide.get("slide_id"), "slide", index)
        if not slide_id.startswith("slide_"):
            slide_id = f"slide_{index:03d}"
        elements = normalize_visual_elements(slide.get("visual_elements"))
        if not elements:
            raise HTTPException(status_code=500, detail=f"{slide_id} 缺少 visual_elements")
        validate_slide_visual_mapping(slide_id, elements, script_by_id.get(slide_id))
        normalized_slides.append({"slide_id": slide_id, "visual_elements": elements})
    if not normalized_slides:
        raise HTTPException(status_code=500, detail="AI 没有返回可用的 slide_visual_plan.slides")
    return {"slides": normalized_slides}


def build_step2_script_user_prompt(
    *,
    project_title: str,
    article_content: str,
    generation_requirement: str,
) -> str:
    user_input = {
        "project_title": project_title,
        "article_content": article_content,
    }
    if str(generation_requirement or "").strip():
        user_input["generation_requirement"] = str(generation_requirement).strip()
    return json.dumps(user_input, ensure_ascii=False, indent=2)


def build_step2_visual_user_prompt(script_plan: Dict[str, Any]) -> str:
    minimal_script_plan = {
        "title": str(script_plan.get("title") or "").strip(),
        "slides": [
            {
                "slide_id": str(slide.get("slide_id") or "").strip(),
                "slide_title": str(slide.get("slide_title") or "").strip(),
                "narration": str(slide.get("narration") or "").strip(),
            }
            for slide in (script_plan.get("slides") or [])
            if isinstance(slide, dict)
        ],
    }
    return json.dumps({"slide_script_plan": minimal_script_plan}, ensure_ascii=False, indent=2)


def element_visible_text(element: Dict[str, str], index: int) -> str:
    description = str(element.get("visual_description") or "").strip()
    if description:
        return description[:32]
    return f"视觉元素 {index}"


def compose_visual_contract_from_plans(
    script_plan: Dict[str, Any],
    visual_plan: Dict[str, Any],
    project_id: str,
    project_title: str,
) -> Dict[str, Any]:
    script_slides = script_plan.get("slides") if isinstance(script_plan, dict) else []
    visual_slides = visual_plan.get("slides") if isinstance(visual_plan, dict) else []
    if not isinstance(script_slides, list) or not script_slides:
        raise HTTPException(status_code=400, detail="slide_script_plan.json 缺少 slides")
    if not isinstance(visual_slides, list) or not visual_slides:
        raise HTTPException(status_code=400, detail="slide_visual_plan.json 缺少 slides")

    visual_by_id = {
        str(slide.get("slide_id") or "").strip(): slide
        for slide in visual_slides
        if isinstance(slide, dict)
    }
    subtitle_policy = "no_slides_have_subtitle"
    slides: List[Dict[str, Any]] = []
    for slide_index, script_slide in enumerate(script_slides, start=1):
        if not isinstance(script_slide, dict):
            continue
        slide_id = str(script_slide.get("slide_id") or f"slide_{slide_index:03d}").strip()
        visual_slide = visual_by_id.get(slide_id)
        if not isinstance(visual_slide, dict):
            raise HTTPException(status_code=400, detail=f"{slide_id} 缺少对应的 visual plan")
        body_points = script_slide.get("body_points") if isinstance(script_slide.get("body_points"), list) else []
        visual_groups: List[Dict[str, Any]] = []
        narration_beats: List[Dict[str, Any]] = []
        for element_index, element in enumerate(visual_slide.get("visual_elements") or [], start=1):
            if not isinstance(element, dict):
                continue
            element_id = stable_plan_id(element.get("element_id"), "el", element_index)
            group_id = f"{slide_id}_{element_id}"
            content_unit_id = f"{slide_id}_unit_{element_index:03d}"
            role = str(element.get("role") or "body").strip().lower()
            role = "decoration" if role == "decoration" else ("title" if role == "title" else ("subtitle" if role == "subtitle" else "content_body"))
            visible_text = element_visible_text(element, element_index)
            description = str(element.get("visual_description") or visible_text).strip()
            narration = str(element.get("narration") or "").strip()
            narration_function_value = str(element.get("narration_function") or element.get("visual_description") or visible_text or "").strip()
            visual_type = normalize_visual_type(element.get("visual_type"))
            display_text = description if visual_type == "text" else ""
            group = {
                "id": group_id,
                "element_id": element_id,
                "role": role,
                "visible_text": visible_text,
                "display_text": display_text,
                "visual_anchor": description,
                "narration_function": narration_function_value,
                "reveal_order": element_index,
                "content_unit_id": content_unit_id,
                "mask_target": description,
                "visual_type": visual_type,
            }
            visual_groups.append(group)
            if narration:
                narration_beats.append(
                    {
                        "id": f"{slide_id}_beat_{len(narration_beats) + 1:03d}",
                        "group_id": group_id,
                        "visible_anchor": visible_text,
                        "spoken_intent": narration_function_value,
                        "spoken_text": narration,
                        "content_unit_id": content_unit_id,
                    }
                )
        if not visual_groups:
            raise HTTPException(status_code=400, detail=f"{slide_id} 没有可合成的 visual elements")
        if not narration_beats:
            raise HTTPException(status_code=400, detail=f"{slide_id} 没有可合成的 narration beats")
        body_content = [
            str(point.get("text") or "").strip()
            for point in body_points
            if isinstance(point, dict) and point.get("text")
        ]
        if not body_content and str(script_slide.get("body") or "").strip():
            body_content = [str(script_slide.get("body") or "").strip()]
        if not body_content:
            body_content = [
                str(group.get("visible_text") or "").strip()
                for group in visual_groups
                if group.get("role") == "content_body" and str(group.get("visible_text") or "").strip()
            ]
        slides.append(
            {
                "slide_id": slide_id,
                "main_title": str(script_slide.get("slide_title") or f"第 {slide_index} 页").strip(),
                "subtitle": "",
                "core_message": "；".join(body_content),
                "body_content": body_content,
                "visual_groups": visual_groups,
                "narration_beats": narration_beats,
            }
        )
    return {
        "version": "visual_contract_v1",
        "presentation_policy": {
            "subtitle_policy": subtitle_policy,
            "subtitle_decided_by": "system_no_subtitle_contract",
            "visual_narration_mapping": "one_visual_element_to_one_narration_beat_v1",
        },
        "topic": {
            "topic_id": "topic_" + project_id,
            "topic_name": project_title,
            "topic_summary": "",
        },
        "slides": slides,
    }


