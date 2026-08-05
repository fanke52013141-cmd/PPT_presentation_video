"""Shared visual-contract normalization and slide identity helpers."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from project_storage import UnsafeProjectPath, safe_identifier


logger = logging.getLogger("PPTStudio.VisualContract")


def validate_slide_identifiers(contract: Dict[str, Any]) -> None:
    """Reject slide_id values that could escape the run directory on write.

    slide_id values flow into filesystem paths (narration.txt, tts_text.txt,
    narration_beats.json, visual_draft.png, ...) via ``os.path.join``. Without
    validation, a value like ``..\\..\\outside`` writes outside the project run
    directory (path traversal). This is called before every contract write so a
    single check covers all downstream writers.
    """
    slides = contract.get("slides")
    if not isinstance(slides, list):
        return
    for slide in slides:
        if not isinstance(slide, dict):
            continue
        slide_id = str(slide.get("slide_id") or "").strip()
        if not slide_id:
            continue
        try:
            safe_identifier(slide_id, label="slide_id")
        except UnsafeProjectPath:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"slide_id 含非法字符，可能导致路径穿越，已拒绝：{slide_id!r}"
                ),
            )


def normalize_visual_type(value: Any, has_text: bool = False) -> str:
    visual_type = str(value or "").strip().lower()
    if visual_type in {"text", "文字"}:
        return "text"
    if visual_type in {
        "picture",
        "illustration",
        "image",
        "diagram",
        "chart",
        "visual",
        "graphic",
        "text_and_illustration",
    }:
        return "picture"
    return "text" if has_text else "picture"


def strip_anchor_lead_in(spoken_text: str, anchor: str) -> str:
    text = str(spoken_text or "").strip()
    anchor = str(anchor or "").strip()
    if not text or not anchor:
        return text
    patterns = [
        rf"^围绕“{re.escape(anchor)}”[，,]\s*",
        rf'^围绕"{re.escape(anchor)}"[，,]\s*',
        rf"^围绕「{re.escape(anchor)}」[，,]\s*",
        rf"^围绕『{re.escape(anchor)}』[，,]\s*",
    ]
    for pattern in patterns:
        cleaned = re.sub(pattern, "", text)
        if cleaned != text:
            return cleaned.strip()
    return text


def narration_dedupe_key(value: Any) -> str:
    """Return a punctuation/markup-insensitive spoken-sentence key."""
    text = str(value or "").strip().casefold()
    text = re.sub(
        r"<#\d+(?:\.\d{1,2})?#>|\([A-Za-z-]+\)",
        "",
        text,
    )
    return re.sub(r"[\W_]+", "", text, flags=re.UNICODE)


def dedupe_narration_beats(beats: Any) -> List[Dict[str, Any]]:
    """Keep the first occurrence of each spoken sentence on a slide."""
    if not isinstance(beats, list):
        return []
    seen: set[str] = set()
    result: List[Dict[str, Any]] = []
    for beat in beats:
        if not isinstance(beat, dict):
            continue
        text = (
            beat.get("spoken_text")
            or beat.get("tts_text")
            or beat.get("source_text")
            or ""
        )
        key = narration_dedupe_key(text)
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        result.append(beat)
    return result


def normalize_visual_contract(
    contract: Dict[str, Any],
    profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    del profile
    # 在写契约前拦截非法 slide_id，防止路径穿越（见 validate_slide_identifiers）。
    validate_slide_identifiers(contract)
    presentation_policy = contract.get("presentation_policy")
    if not isinstance(presentation_policy, dict):
        presentation_policy = {}
        contract["presentation_policy"] = presentation_policy
    presentation_policy["subtitle_policy"] = (
        "no_slides_have_subtitle"
    )
    presentation_policy["subtitle_decided_by"] = (
        "system_no_subtitle_contract"
    )
    slides = contract.get("slides")
    if not isinstance(slides, list):
        return contract
    for slide in slides:
        if not isinstance(slide, dict):
            continue
        slide["subtitle"] = ""
        groups = slide.get("visual_groups")
        if not isinstance(groups, list):
            continue
        groups = [
            group
            for group in groups
            if not isinstance(group, dict)
            or str(group.get("role") or "").strip().lower()
            != "subtitle"
        ]
        slide["visual_groups"] = groups

        group_by_id: Dict[str, Dict[str, Any]] = {}
        for index, group in enumerate(groups, start=1):
            if not isinstance(group, dict):
                continue
            group_id = str(
                group.get("id") or f"group_{index:02d}"
            ).strip()
            group["id"] = group_id
            role = str(
                group.get("role") or "content_body"
            ).strip()
            group["role"] = role
            group["visual_type"] = normalize_visual_type(
                group.get("visual_type"),
                has_text=bool(
                    str(group.get("display_text") or "").strip()
                ),
            )
            if not str(group.get("content_unit_id") or "").strip():
                group["content_unit_id"] = f"{group_id}_unit"
            group.pop("speak_policy", None)
            if (
                role != "decoration"
                and not str(group.get("mask_target") or "").strip()
            ):
                group["mask_target"] = str(
                    group.get("visual_anchor")
                    or group.get("visible_text")
                    or group_id
                ).strip()
            if not group.get("reveal_order"):
                group["reveal_order"] = index
            group_by_id[group_id] = group

        beats = slide.get("narration_beats")
        if not isinstance(beats, list):
            continue
        normalized_beats = []
        manual_mode_slide = not groups
        for index, beat in enumerate(beats, start=1):
            if not isinstance(beat, dict):
                continue
            if not str(beat.get("id") or "").strip():
                beat["id"] = f"beat_{index:02d}"
            group_id = str(beat.get("group_id") or "").strip()
            group = group_by_id.get(group_id)
            if not group:
                if manual_mode_slide:
                    if not str(
                        beat.get("content_unit_id") or ""
                    ).strip():
                        beat["content_unit_id"] = (
                            f"{slide.get('slide_id', 'slide')}"
                            f"_unit_{index:03d}"
                        )
                    normalized_beats.append(beat)
                continue
            if not str(beat.get("content_unit_id") or "").strip():
                beat["content_unit_id"] = group.get(
                    "content_unit_id"
                )
            if not str(beat.get("visible_anchor") or "").strip():
                beat["visible_anchor"] = group.get("visible_text")
            anchor = str(
                beat.get("visible_anchor")
                or group.get("visible_text")
                or ""
            ).strip()
            spoken_text = strip_anchor_lead_in(
                str(beat.get("spoken_text") or "").strip(),
                anchor,
            )
            if not spoken_text:
                intent = str(
                    beat.get("spoken_intent") or ""
                ).strip()
                beat["spoken_text"] = (
                    intent or f"请看画面中的{anchor}。"
                )
            else:
                beat["spoken_text"] = spoken_text
            normalized_beats.append(beat)
        slide["narration_beats"] = dedupe_narration_beats(
            normalized_beats
        )

    return contract


def contract_slide_ids_from_payload(
    payload: Dict[str, Any],
) -> List[str]:
    slide_ids: List[str] = []
    for slide in payload.get("slides", []) or []:
        if not isinstance(slide, dict):
            continue
        slide_id = str(slide.get("slide_id") or "").strip()
        if slide_id:
            slide_ids.append(slide_id)
    return slide_ids


def read_contract_slide_ids(run_dir: str) -> List[str]:
    contract_path = os.path.join(
        run_dir,
        "planning",
        "visual_contract.json",
    )
    if not os.path.exists(contract_path):
        return []
    try:
        with open(contract_path, "r", encoding="utf-8") as file:
            contract = json.load(file)
    except Exception as exc:
        logger.warning(
            "Failed to read visual contract for slide sync: %s",
            exc,
        )
        return []
    return contract_slide_ids_from_payload(contract)
