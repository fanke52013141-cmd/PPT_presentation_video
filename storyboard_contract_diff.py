"""Pure classification of downstream effects from Step 2 contract edits."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict

@dataclass(frozen=True)
class StoryboardContractImpact:
    """The smallest reusable downstream scope for one Step 2 edit.

    The contract is the source for both the Step 3 image prompt and the Step 5
    narration source.  Comparing the whole JSON document made a title edit on
    one slide look like an instruction to recreate every asset.  This compact
    diff deliberately separates those independent inputs and preserves slide
    identity so that order-only changes keep their existing assets.
    """

    visual_slide_ids: tuple[str, ...] = ()
    narration_slide_ids: tuple[str, ...] = ()
    added_slide_ids: tuple[str, ...] = ()
    removed_slide_ids: tuple[str, ...] = ()
    reordered: bool = False

    @property
    def has_effect(self) -> bool:
        return bool(
            self.visual_slide_ids
            or self.narration_slide_ids
            or self.added_slide_ids
            or self.removed_slide_ids
            or self.reordered
        )


def _normalized_slide_id(slide: Any) -> str:
    return str(slide.get("slide_id") or "").strip() if isinstance(slide, dict) else ""


def _contract_slides_by_id(contract: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    slides = contract.get("slides") if isinstance(contract, dict) else None
    if not isinstance(slides, list):
        return {}
    return {
        slide_id: slide
        for slide in slides
        if isinstance(slide, dict)
        and (slide_id := _normalized_slide_id(slide))
    }


def _canonical_contract_value(value: Any) -> str:
    """Stable comparison without changing the payload that will be persisted."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def visual_slide_input(slide: Dict[str, Any]) -> Dict[str, Any]:
    """Return only fields which change the image or Mask semantic mapping.

    Public (shared with ``visual_provenance``) so the per-slide image
    provenance hash uses exactly the same projection as the downstream
    invalidation classifier: narration-only edits must not invalidate an
    approved image.
    """
    visual = {
        key: value
        for key, value in slide.items()
        if key not in {"slide_id", "narration_beats"}
    }
    beats = slide.get("narration_beats")
    if isinstance(beats, list):
        # Beat text feeds TTS; its group/anchor mapping feeds visual reveal
        # ownership and must therefore remain in the visual comparison.
        visual["narration_anchors"] = [
            {
                key: value
                for key, value in beat.items()
                if key not in {"spoken_text", "tts_text", "source_text"}
            }
            for beat in beats
            if isinstance(beat, dict)
        ]
    return visual


# 兼容别名:历史代码以私有名引用本投影。
_visual_slide_input = visual_slide_input


def _narration_slide_input(slide: Dict[str, Any]) -> list[str]:
    """Return the ordered words sent to TTS, excluding visual-only metadata."""
    beats = slide.get("narration_beats")
    if not isinstance(beats, list):
        return []
    return [
        str(
            beat.get("spoken_text")
            or beat.get("tts_text")
            or beat.get("source_text")
            or ""
        ).strip()
        for beat in beats
        if isinstance(beat, dict)
    ]


def diff_storyboard_contracts(
    previous_contract: Dict[str, Any],
    current_contract: Dict[str, Any],
) -> StoryboardContractImpact:
    """Classify a normalized Step 2 edit without touching project artifacts."""
    previous_by_id = _contract_slides_by_id(previous_contract)
    current_by_id = _contract_slides_by_id(current_contract)
    previous_ids = tuple(previous_by_id)
    current_ids = tuple(current_by_id)
    added = tuple(slide_id for slide_id in current_ids if slide_id not in previous_by_id)
    removed = tuple(slide_id for slide_id in previous_ids if slide_id not in current_by_id)
    shared = tuple(slide_id for slide_id in current_ids if slide_id in previous_by_id)
    visual = tuple(
        slide_id
        for slide_id in shared
        if _canonical_contract_value(_visual_slide_input(previous_by_id[slide_id]))
        != _canonical_contract_value(_visual_slide_input(current_by_id[slide_id]))
    )
    narration = tuple(
        slide_id
        for slide_id in shared
        if _canonical_contract_value(_narration_slide_input(previous_by_id[slide_id]))
        != _canonical_contract_value(_narration_slide_input(current_by_id[slide_id]))
    )
    previous_shared_order = tuple(slide_id for slide_id in previous_ids if slide_id in current_by_id)
    current_shared_order = tuple(slide_id for slide_id in current_ids if slide_id in previous_by_id)
    return StoryboardContractImpact(
        visual_slide_ids=visual,
        narration_slide_ids=narration,
        added_slide_ids=added,
        removed_slide_ids=removed,
        reordered=previous_shared_order != current_shared_order,
    )
