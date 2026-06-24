#!/usr/bin/env python3
"""Write per-slide prompts for full-slide reveal-friendly Image Gen masters."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


class PromptError(RuntimeError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise PromptError(f"Missing JSON file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise PromptError(f"Invalid JSON file: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PromptError(f"JSON file must contain an object: {path}")
    return value


def extract_style_refs(style_tokens_path: Path) -> tuple[str, str]:
    text = style_tokens_path.read_text(encoding="utf-8-sig")
    template = ""
    example = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("template_reference_image:"):
            template = line.split(":", 1)[1].strip()
        elif line.startswith("example_reference_image:"):
            example = line.split(":", 1)[1].strip()
    if not template or not example:
        raise PromptError(f"Could not find style reference images in {style_tokens_path}")
    return template, example


def compact_list(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


def visual_group_lines(slide: dict[str, Any]) -> list[str]:
    groups = slide.get("visual_groups")
    if not isinstance(groups, list):
        return []
    lines: list[str] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        group_id = str(group.get("id", "")).strip()
        role = str(group.get("role", "")).strip()
        content_unit_id = str(group.get("content_unit_id", group_id)).strip()
        visible_text = str(group.get("visible_text", "")).strip()
        anchor = str(group.get("visual_anchor", "")).strip()
        function = str(group.get("narration_function", "")).strip()
        source_text = str(group.get("source_text", "")).strip()
        mask_target = str(group.get("mask_target", "")).strip()
        must_include = compact_list(group.get("must_include"))
        must_not_include = compact_list(group.get("must_not_include"))
        order = str(group.get("reveal_order", "")).strip()
        lines.append(
            f"- {group_id} / unit {content_unit_id} / {role} / order {order}: "
            f"visible text=\"{visible_text}\"; source={source_text}; anchor={anchor}; "
            f"narration function={function}; mask target={mask_target}; "
            f"include=[{must_include}]; exclude=[{must_not_include}]"
        )
    return lines


def beat_lines(slide: dict[str, Any]) -> list[str]:
    beats = slide.get("narration_beats")
    if not isinstance(beats, list):
        return []
    lines: list[str] = []
    for beat in beats:
        if not isinstance(beat, dict):
            continue
        beat_id = str(beat.get("id", "")).strip()
        content_unit_id = str(beat.get("content_unit_id", "")).strip()
        group_id = str(beat.get("group_id", beat.get("visual_group", ""))).strip()
        anchor = str(beat.get("visible_anchor", "")).strip()
        intent = str(beat.get("spoken_intent", beat.get("spoken_point", beat.get("text", "")))).strip()
        spoken = str(beat.get("spoken_text", "")).strip()
        lines.append(f"- {beat_id} -> unit {content_unit_id or '-'} -> {group_id}: anchor=\"{anchor}\"; intent={intent}; spoken={spoken}")
    return lines


def item_lines(slide: dict[str, Any]) -> list[str]:
    content = slide.get("content")
    if not isinstance(content, dict):
        return []
    items = content.get("items")
    if not isinstance(items, list):
        return []
    lines: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label", "")).strip()
        text = str(item.get("text", "")).strip()
        item_type = str(item.get("type", "")).strip()
        side = str(item.get("side", "")).strip()
        prefix = " / ".join(part for part in [item_type, label, side] if part)
        if prefix and text:
            lines.append(f"- {prefix}: {text}")
        elif text:
            lines.append(f"- {text}")
    return lines


def build_prompt(slide: dict[str, Any], template_ref: str, example_ref: str) -> str:
    slide_id = str(slide.get("slide_id", "")).strip()
    title = str(slide.get("main_title", "")).strip()
    subtitle = str(slide.get("subtitle", "")).strip()
    core_message = str(slide.get("core_message", "")).strip()
    groups = "\n".join(visual_group_lines(slide)) or "- No visual_groups provided; create 5-8 large reveal groups."
    beats = "\n".join(beat_lines(slide)) or "- No narration_beats provided."
    fallback_items = "\n".join(item_lines(slide))
    slide_purpose = str(slide.get("slide_purpose", "")).strip()

    return f"""Use case: content-first PPT explainer
Asset type: 16:9 Image Gen full-slide master for reveal-layer video production
Slide id: {slide_id}
Input images:
- Reference image 1 ({template_ref}): use for fixed title/subtitle area, spacing, and style mood.
- Reference image 2 ({example_ref}): use for visual style reference only; do not force its body layout.

Primary request:
Generate one complete full-slide master image that serves the content and makes the explanation clear. The final video will reveal parts of this full-slide image by using cover/fog/crop reveal layers. Do not generate separate isolated element images for production.
The slide body, title, subtitle, lines, arrows, icons, labels, and diagram content must all be Image Gen bitmap content.

Canvas and layout:
- 16:9 landscape, 1920x1080.
- Use a flat uniform pure-white #FFFFFF background.
- All four edges and all four corners must remain continuously pure white, without paper texture, shadows, noise, gradients, or vignettes.
- Main title and subtitle stay in the fixed top title area.
- Keep the main content inside x=80,y=235 to x=1840,y=915.
- Keep y=930 to y=1080 visually calm for Remotion subtitles.
- The body area is free: choose whatever visual structure best explains this page, such as reasoning chain, comparison, relationship map, process, timeline, scene breakdown, or action checklist.
- Do not mechanically arrange the body as a few generic cards unless that is truly the clearest explanation.

Text to render exactly where possible:
Main title: "{title}"
Subtitle: "{subtitle}"
Core message: "{core_message}"
Slide purpose: {slide_purpose}

Narration beats / speaker script that the visual must primarily support:
{beats}

Visual contract groups / Mask grouping reference:
{groups}

Fallback content items, if any:
{fallback_items}

Semantic mapping and mask rules:
- Treat each visual group as one content unit. Preserve the content_unit_id relationship in the layout.
- For every group, follow mask target, include, and exclude fields. These determine the later reveal box or mask review.
- A later box must be able to cover all included elements without covering excluded elements.
- Keep arrows, labels, icons, formulas, and cards inside the same reveal group when semantically connected.
- Leave 80-120px of clean #FFFFFF background between independent groups.
- Absolutely no overlap: text, cards, icons, arrows, lines, labels, decorations, and charts must not cover, touch, pierce through, or stick to each other.
- Do not place critical content below y=930.

Narration alignment rules:
- The narration beats are the primary basis for the slide body composition. First understand what the speaker is explaining, then design the visual body to support that explanation.
- Narration beats are authoritative: a visual group is discussed only when a beat references it.
- Visual groups without a narration beat remain visual-only; do not invent narration merely to cover every group.
- The narration should expand what is visible on the page; it must not introduce unrelated concepts that the page does not show.
- Use the hierarchy implied by reveal_order and narration order.

Style constraints:
- Use the reference images for style mood, typography feel, spacing, and title treatment only.
- The body composition must be content-specific and may vary freely from slide to slide.
- Avoid overlapping objects.
- Keep text large and readable; avoid dense paragraphs and tiny labels.
"""


def contract_path_for_run(run_dir: Path) -> Path:
    return run_dir / "planning" / "visual_contract.json"


def load_planning(run_dir: Path) -> tuple[dict[str, Any], str]:
    contract_path = contract_path_for_run(run_dir)
    if contract_path.exists():
        return read_json(contract_path), "visual_contract.json"
    slide_plan_path = run_dir / "planning" / "slide_plan.json"
    return read_json(slide_plan_path), "slide_plan.json"


def write_prompts(run_dir: Path, style_tokens_path: Path, overwrite: bool) -> int:
    planning, source_name = load_planning(run_dir)
    slides = planning.get("slides")
    if not isinstance(slides, list) or not slides:
        raise PromptError(f"{source_name} must contain non-empty slides[]: {run_dir}")
    template_ref, example_ref = extract_style_refs(style_tokens_path)
    count = 0
    for slide in slides:
        if not isinstance(slide, dict):
            raise PromptError(f"Each slide in {source_name} must be an object")
        slide_id = str(slide.get("slide_id", "")).strip()
        if not slide_id:
            raise PromptError("Slide missing slide_id")
        slide_dir = run_dir / "slides" / slide_id
        slide_dir.mkdir(parents=True, exist_ok=True)
        out_path = slide_dir / "visual_prompt.md"
        if out_path.exists() and not overwrite:
            continue
        out_path.write_text(build_prompt(slide, template_ref, example_ref), encoding="utf-8")
        count += 1
    return count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write reveal-friendly Image Gen prompts for a run.")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--style-tokens", default=Path("config/style_tokens.yaml"), type=Path)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        count = write_prompts(run_dir=args.run_dir.resolve(), style_tokens_path=args.style_tokens.resolve(), overwrite=args.overwrite)
    except PromptError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {count} visual prompt file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
