#!/usr/bin/env python3
"""Write per-slide prompts for full-slide reveal-friendly Image Gen masters.

The prompt builder keeps production invariants separate from visual style. Style
profiles may change visual language, but they cannot override fixed generated
image background, subtitle safety zone, title requirement, or maskability.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml


class PromptError(RuntimeError):
    pass


SUBTITLE_POLICY_WITH_SUBTITLE = "all_slides_have_subtitle"
SUBTITLE_POLICY_NO_SUBTITLE = "no_slides_have_subtitle"
ALLOWED_SUBTITLE_POLICIES = {SUBTITLE_POLICY_WITH_SUBTITLE, SUBTITLE_POLICY_NO_SUBTITLE}


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


def read_yaml(path: Path, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        return dict(fallback or {})
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    except yaml.YAMLError as exc:
        raise PromptError(f"Invalid YAML file: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PromptError(f"YAML file must contain an object: {path}")
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


def style_profile_lines(style_tokens: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    brand = style_tokens.get("brand")
    if isinstance(brand, dict):
        keywords = compact_list(brand.get("style_keywords"))
        if keywords:
            lines.append(f"- Style keywords: {keywords}")
    visual_assets = style_tokens.get("visual_assets")
    if isinstance(visual_assets, dict):
        for key in ("image_style", "diagram_style"):
            value = str(visual_assets.get(key) or "").strip()
            if value:
                lines.append(f"- {key}: {value}")
        reveal_rules = visual_assets.get("reveal_friendly_layout")
        if isinstance(reveal_rules, list) and reveal_rules:
            lines.append("- Reveal-friendly style/layout notes:")
            lines.extend(f"  - {str(rule).strip()}" for rule in reveal_rules if str(rule).strip())
        avoid = compact_list(visual_assets.get("avoid"))
        if avoid:
            lines.append(f"- Avoid: {avoid}")
    colors = style_tokens.get("colors")
    if isinstance(colors, dict):
        accent_keys = ("ink", "line", "yellow", "yellow_soft", "green_soft", "blue_soft")
        accents = ", ".join(f"{key}={colors[key]}" for key in accent_keys if key in colors)
        if accents:
            lines.append(f"- Palette: {accents}")
    return lines


def presentation_policy(planning: dict[str, Any]) -> dict[str, Any]:
    policy = planning.get("presentation_policy")
    if not isinstance(policy, dict):
        return {
            "subtitle_policy": SUBTITLE_POLICY_NO_SUBTITLE,
            "subtitle_rationale": "No project-level AI subtitle policy was found; defaulting to no subtitles for visual consistency.",
            "default_visual_group_count": "3-5",
            "layout_diversity": "high",
        }
    result = dict(policy)
    subtitle_policy = str(result.get("subtitle_policy") or "").strip()
    if subtitle_policy not in ALLOWED_SUBTITLE_POLICIES:
        raise PromptError(
            "presentation_policy.subtitle_policy must be "
            f"{SUBTITLE_POLICY_WITH_SUBTITLE} or {SUBTITLE_POLICY_NO_SUBTITLE}"
        )
    return result


def subtitle_prompt_lines(policy: dict[str, Any], slide: dict[str, Any]) -> list[str]:
    subtitle_policy = str(policy.get("subtitle_policy") or SUBTITLE_POLICY_NO_SUBTITLE).strip()
    subtitle = str(slide.get("subtitle") or "").strip()
    if subtitle_policy == SUBTITLE_POLICY_WITH_SUBTITLE:
        if not subtitle:
            raise PromptError(f"Slide {slide.get('slide_id', '')} requires subtitle but subtitle is empty")
        return [
            f"- Project subtitle policy: every slide must render a subtitle.",
            f"- Render subtitle below the main title: \"{subtitle}\".",
            "- Keep subtitle compact; it must not enter the video subtitle safety zone.",
        ]
    if subtitle_policy == SUBTITLE_POLICY_NO_SUBTITLE:
        return [
            "- Project subtitle policy: no slide should render a subtitle.",
            "- Do not draw a subtitle line, subtitle underline, or reserved subtitle placeholder.",
            "- Use the saved title-area space to strengthen the main visual composition.",
        ]
    raise PromptError(f"Unsupported subtitle policy: {subtitle_policy}")


def production_invariant_lines(invariants: dict[str, Any], policy: dict[str, Any], slide: dict[str, Any]) -> list[str]:
    title = str(slide.get("main_title") or "").strip()
    if not title:
        raise PromptError(f"Slide {slide.get('slide_id', '')} missing main_title")
    width = int(invariants.get("canvas", {}).get("width") or 1920)
    height = int(invariants.get("canvas", {}).get("height") or 1080)
    background = str(invariants.get("generated_image", {}).get("background") or "#FFFFFF").strip() or "#FFFFFF"
    y_min = int(invariants.get("subtitle_safe_zone", {}).get("y_min") or 930)
    y_max = int(invariants.get("subtitle_safe_zone", {}).get("y_max") or 1080)
    return [
        f"- Canvas: {width}x{height}, 16:9 landscape.",
        f"- Generated slide image background must be flat pure white {background}.",
        "- All four edges and all four corners must remain continuously pure white; no paper texture, shadow, noise, gradient, vignette, or off-white outer canvas.",
        "- Every slide must contain one clear main title.",
        f"- Main title to render: \"{title}\".",
        *subtitle_prompt_lines(policy, slide),
        f"- Keep y={y_min}..{y_max} completely empty for video subtitles: no text, icons, arrows, labels, decorations, shadows, people, partial objects, or visual fragments.",
        "- Avoid severe overlap. Text, arrows, icons, formulas, card borders, and labels must not collide.",
        "- Semantic groups must be manually maskable; groups may be connected by clean arrows, brackets, timelines, or flow paths, but unrelated groups must not merge.",
    ]


def design_brief_lines(slide: dict[str, Any], policy: dict[str, Any]) -> list[str]:
    composition = slide.get("composition")
    lines = [
        f"- Slide purpose: {str(slide.get('slide_purpose') or '').strip()}",
        f"- Core message: {str(slide.get('core_message') or '').strip()}",
        f"- Layout type: {str(slide.get('layout_type') or 'auto_choose_best_explainer_layout').strip()}",
        f"- Visual metaphor: {str(slide.get('visual_metaphor') or 'choose a clear visual metaphor that fits the content').strip()}",
        f"- Default visual group count guidance: {str(policy.get('default_visual_group_count') or '3-5').strip()}",
        f"- Layout diversity guidance: {str(policy.get('layout_diversity') or 'high').strip()}",
    ]
    if isinstance(composition, dict):
        for key in ("primary_focus", "reading_order", "hierarchy", "group_count"):
            if key in composition:
                value = composition[key]
                if isinstance(value, list):
                    value = ", ".join(str(item) for item in value)
                lines.append(f"- Composition {key}: {value}")
    return [line for line in lines if line.strip() and not line.endswith(": ")]


def build_prompt(
    slide: dict[str, Any],
    template_ref: str,
    example_ref: str,
    *,
    policy: dict[str, Any],
    invariants: dict[str, Any],
    style_tokens: dict[str, Any],
) -> str:
    slide_id = str(slide.get("slide_id", "")).strip()
    core_message = str(slide.get("core_message", "")).strip()
    groups = "\n".join(visual_group_lines(slide)) or "- No visual_groups provided; create 2-6 meaningful, maskable semantic visual groups."
    beats = "\n".join(beat_lines(slide)) or "- No narration_beats provided."
    fallback_items = "\n".join(item_lines(slide))
    production_rules = "\n".join(production_invariant_lines(invariants, policy, slide))
    design_rules = "\n".join(design_brief_lines(slide, policy))
    style_rules = "\n".join(style_profile_lines(style_tokens)) or "- Use the active style reference images as the visual style source."

    return f"""Use case: scientific-educational
Asset type: 16:9 Image Gen full-slide master for reveal-layer video production
Slide id: {slide_id}
Input images:
- Reference image 1 ({template_ref}): use only as a reusable style/template reference.
- Reference image 2 ({example_ref}): use only as a filled-slide style reference.

Primary request:
Generate one complete full-slide master image. The final video will reveal parts of this full-slide image by using cover/fog/crop reveal layers.
The slide body, title, lines, arrows, icons, labels, and diagram content must all be Image Gen bitmap content.

Production invariants that style must not override:
{production_rules}

Slide design brief:
{design_rules}

Core message:
{core_message}

Visual contract groups:
{groups}

Narration beats that the visual must support:
{beats}

Fallback content items, if any:
{fallback_items}

Semantic mapping and mask rules:
- Treat each visual group as one content unit. Preserve the content_unit_id relationship in the layout.
- For every group, use mask target/include/exclude fields as production hints, not as a requirement to make isolated cards.
- A later mask should be able to cover all included elements without covering excluded elements.
- Keep arrows, labels, icons, formulas, and cards inside the same reveal group when semantically connected.
- Independent groups should have enough clean #FFFFFF around them for manual Mask painting.
- Prefer one dominant hero visual plus 2-4 supporting semantic groups when it improves expression.
- Do not place any content or decoration below y=930.

Narration alignment rules:
- Narration beats are authoritative: a visual group is discussed only when a beat references it.
- Visual groups without a narration beat remain visual-only; do not invent narration merely to cover every group.
- The narration should expand what is visible on the page; it must not introduce unrelated concepts that the page does not show.
- Use the hierarchy implied by reveal_order and narration order.

Style profile; these are generalizable and may vary by active style:
{style_rules}

Creative freedom:
- Choose the exact shapes, icons, arrows, callouts, local decorations, and visual metaphor as long as production invariants are preserved.
- Make the page visually rich inside the content area, but keep it clean and readable.
- Do not create many equal isolated cards unless the slide is truly a list, comparison, or checklist.
"""


def contract_path_for_run(run_dir: Path) -> Path:
    return run_dir / "planning" / "visual_contract.json"


def load_planning(run_dir: Path) -> tuple[dict[str, Any], str]:
    contract_path = contract_path_for_run(run_dir)
    if contract_path.exists():
        return read_json(contract_path), "visual_contract.json"
    slide_plan_path = run_dir / "planning" / "slide_plan.json"
    return read_json(slide_plan_path), "slide_plan.json"


def write_prompts(run_dir: Path, style_tokens_path: Path, production_invariants_path: Path, overwrite: bool) -> int:
    planning, source_name = load_planning(run_dir)
    slides = planning.get("slides")
    if not isinstance(slides, list) or not slides:
        raise PromptError(f"{source_name} must contain non-empty slides[]: {run_dir}")
    style_tokens = read_yaml(style_tokens_path)
    invariants = read_yaml(production_invariants_path, fallback={})
    policy = presentation_policy(planning)
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
        out_path.write_text(
            build_prompt(
                slide,
                template_ref,
                example_ref,
                policy=policy,
                invariants=invariants,
                style_tokens=style_tokens,
            ),
            encoding="utf-8",
        )
        count += 1
    return count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write reveal-friendly Image Gen prompts for a run.")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--style-tokens", default=Path("config/style_tokens.yaml"), type=Path)
    parser.add_argument("--production-invariants", default=Path("config/production_invariants.yaml"), type=Path)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        count = write_prompts(
            run_dir=args.run_dir.resolve(),
            style_tokens_path=args.style_tokens.resolve(),
            production_invariants_path=args.production_invariants.resolve(),
            overwrite=args.overwrite,
        )
    except PromptError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {count} visual prompt file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
