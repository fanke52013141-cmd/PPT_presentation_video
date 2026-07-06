#!/usr/bin/env python3
"""Write per-slide prompts for full-slide reveal-friendly Image Gen masters.

The prompt builder keeps production invariants separate from visual style. Style
profiles may change visual language, but they cannot override fixed generated
image background, subtitle safety zone, title requirement, or maskability.

Project Profile v1 is applied as an optional run-local style overlay. When a run
contains planning/project_profile.json or planning/project_profile_prompt_companion.json,
its image_style_profile is treated as more authoritative than the global
config/style_tokens.yaml style profile, while production invariants remain fixed.

The storyboard is intentionally narration-first: visual_groups are treated as
post-design anchors for Mask/Reveal review, not as a rigid layout template.
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
SUBTITLE_POLICY_OPTIONAL = "optional_subtitles"
ALLOWED_SUBTITLE_POLICIES = {SUBTITLE_POLICY_WITH_SUBTITLE, SUBTITLE_POLICY_NO_SUBTITLE, SUBTITLE_POLICY_OPTIONAL}


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


def read_optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


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


def extract_style_ref(style_tokens_path: Path) -> str:
    text = style_tokens_path.read_text(encoding="utf-8-sig")
    template = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("template_reference_image:"):
            template = line.split(":", 1)[1].strip()
    if not template:
        raise PromptError(f"Could not find template_reference_image in {style_tokens_path}")
    return template


def compact_list(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


def as_lines(value: Any, *, indent: str = "") -> list[str]:
    if isinstance(value, list):
        return [f"{indent}- {str(item).strip()}" for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    return [f"{indent}{line}" for line in text.splitlines() if line.strip()]


def compact_visual_element_lines(slide: dict[str, Any]) -> list[str]:
    slide_id = str(slide.get("slide_id", "")).strip()
    prefix = f"{slide_id}_" if slide_id else ""
    groups = slide.get("visual_groups")
    if not isinstance(groups, list):
        return []
    lines: list[str] = []
    for idx, group in enumerate(groups, start=1):
        if not isinstance(group, dict):
            continue
        group_id = str(group.get("id", "")).strip()
        element_id = str(group.get("element_id") or "").strip()
        if not element_id:
            element_id = group_id[len(prefix):] if prefix and group_id.startswith(prefix) else (group_id or f"el_{idx:03d}")
        role = str(group.get("role", "content_body")).strip()
        visual_type = str(group.get("visual_type", "")).strip().lower()
        if visual_type == "illustration":
            visual_type = "picture"
        if visual_type not in {"text", "picture"}:
            visual_type = "text" if str(group.get("display_text", "")).strip() else "picture"
        if visual_type == "text":
            description = str(group.get("display_text") or group.get("visual_anchor") or group.get("visible_text") or "").strip()
        else:
            description = str(group.get("visual_anchor") or group.get("mask_target") or group.get("visible_text") or "").strip()
        if description:
            lines.append(
                f"- slide_id={slide_id}; element_id={element_id}; role={role}; "
                f"visual_type={visual_type}; visual_description={description}"
            )
    return lines


def style_profile_lines(style_tokens: dict[str, Any]) -> list[str]:
    prompt_text = str(style_tokens.get("prompt_system_content") or "").strip()
    if prompt_text:
        return prompt_text.splitlines()

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


def load_project_image_style(run_dir: Path) -> dict[str, Any]:
    planning_dir = run_dir / "planning"
    companion = read_optional_json(planning_dir / "project_profile_prompt_companion.json")
    image_style = companion.get("image_style_profile")
    if isinstance(image_style, dict) and image_style:
        return image_style

    profile = read_optional_json(planning_dir / "project_profile.json")
    image_style = profile.get("image_style_profile")
    return image_style if isinstance(image_style, dict) else {}


def project_image_style_lines(image_style: dict[str, Any]) -> list[str]:
    if not isinstance(image_style, dict) or not image_style:
        return []

    lines: list[str] = [
        "Project Profile image style overlay (authoritative over global style tokens when there is any conflict):"
    ]
    style_name = str(image_style.get("style_name") or image_style.get("template_name") or "").strip()
    style_summary = str(image_style.get("style_summary") or image_style.get("description") or "").strip()
    source = str(image_style.get("source") or "").strip()
    custom_requirement = str(image_style.get("custom_requirement") or "").strip()
    if style_name:
        lines.append(f"- Style name: {style_name}")
    if source:
        lines.append(f"- Style source: {source}")
    if style_summary:
        lines.append(f"- Style summary: {style_summary}")
    if custom_requirement:
        lines.append(f"- User style requirement: {custom_requirement}")

    system_content = str(image_style.get("system_content") or "").strip()
    if system_content:
        lines.append("- Image generation system content:")
        lines.extend(f"  {line}" for line in system_content.splitlines() if line.strip())

    visual_language = image_style.get("visual_language")
    if isinstance(visual_language, dict) and visual_language:
        lines.append("- Structured visual language:")
        for key, value in visual_language.items():
            if isinstance(value, list):
                rendered = compact_list(value)
            elif isinstance(value, dict):
                rendered = "; ".join(f"{k}: {v}" for k, v in value.items() if str(v).strip())
            else:
                rendered = str(value or "").strip()
            if rendered:
                lines.append(f"  - {key}: {rendered}")

    maskability_rules = image_style.get("maskability_rules")
    if isinstance(maskability_rules, list) and maskability_rules:
        lines.append("- Project Profile maskability rules:")
        lines.extend(f"  - {str(rule).strip()}" for rule in maskability_rules if str(rule).strip())

    negative_rules = image_style.get("negative_prompt_rules")
    if isinstance(negative_rules, list) and negative_rules:
        lines.append("- Project Profile negative prompt rules:")
        lines.extend(f"  - {str(rule).strip()}" for rule in negative_rules if str(rule).strip())

    sample_prompts = image_style.get("sample_reference_image_prompts")
    if isinstance(sample_prompts, list) and sample_prompts:
        lines.append("- Optional reference prompt examples for this style:")
        lines.extend(f"  - {str(prompt).strip()}" for prompt in sample_prompts if str(prompt).strip())

    lines.extend(
        [
            "- Non-overridable reminder: generated slide image outer background stays pure-white #FFFFFF.",
            "- Non-overridable reminder: final-video background is applied later and must not be drawn into visual_draft.png.",
            "- Non-overridable reminder: leave clear white gaps between semantic visual groups for AI Mask and manual Mask reveal.",
        ]
    )
    return lines


def presentation_policy(planning: dict[str, Any]) -> dict[str, Any]:
    policy = planning.get("presentation_policy")
    if not isinstance(policy, dict):
        return {
            "subtitle_policy": SUBTITLE_POLICY_NO_SUBTITLE,
            "subtitle_rationale": "No project-level AI subtitle policy was found; defaulting to no subtitles for visual consistency.",
            "default_visual_anchor_count": "2-5",
            "layout_freedom": "high",
        }
    result = dict(policy)
    subtitle_policy = str(result.get("subtitle_policy") or "").strip()
    if subtitle_policy not in ALLOWED_SUBTITLE_POLICIES:
        raise PromptError(
            "presentation_policy.subtitle_policy must be "
            f"{SUBTITLE_POLICY_WITH_SUBTITLE}, {SUBTITLE_POLICY_NO_SUBTITLE}, or {SUBTITLE_POLICY_OPTIONAL}"
        )
    return result


def subtitle_prompt_lines(policy: dict[str, Any], slide: dict[str, Any]) -> list[str]:
    subtitle_policy = str(policy.get("subtitle_policy") or SUBTITLE_POLICY_NO_SUBTITLE).strip()
    subtitle = str(slide.get("subtitle") or "").strip()
    if subtitle_policy == SUBTITLE_POLICY_WITH_SUBTITLE:
        if not subtitle:
            raise PromptError(f"Slide {slide.get('slide_id', '')} requires subtitle but subtitle is empty")
        return [
            "- Project subtitle policy: every slide must render a subtitle.",
            f"- Render subtitle below the main title: \"{subtitle}\".",
            "- Keep subtitle compact; it must not enter the video subtitle safety zone.",
        ]
    if subtitle_policy == SUBTITLE_POLICY_NO_SUBTITLE:
        return [
            "- Project subtitle policy: no slide should render a subtitle.",
            "- Do not draw a subtitle line, subtitle underline, or reserved subtitle placeholder.",
            "- Use the saved title-area space to strengthen the main visual composition.",
        ]
    if subtitle_policy == SUBTITLE_POLICY_OPTIONAL:
        if subtitle:
            return [
                "- Project subtitle policy: subtitles are optional per slide.",
                f"- This slide has a subtitle; render it below the main title: \"{subtitle}\".",
                "- Keep subtitle compact; it must not enter the video subtitle safety zone.",
            ]
        return [
            "- Project subtitle policy: subtitles are optional per slide.",
            "- This slide has no subtitle; do not draw a subtitle placeholder or underline.",
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
        f"- Generated slide image background must be flat pure-white {background} background; default invariant wording: pure-white #FFFFFF background.",
        "- All four edges and all four corners must remain continuously pure white; no paper texture, shadow, noise, gradient, vignette, or off-white outer canvas.",
        "- Every slide must contain one clear main title.",
        f"- Main title to render: \"{title}\".",
        "- Typography scale: render the slide-level title at 2x the previous/default title size.",
        "- Typography scale: render main-title content, subtitle content, body content, and narration-related on-slide text at about 2/3 of the previous/default size.",
        *subtitle_prompt_lines(policy, slide),
        f"- Keep y={y_min}..{y_max} completely empty for video subtitles: no text, icons, arrows, labels, decorations, shadows, people, partial objects, or visual fragments.",
        "- Strictly forbid visual overlap. Text, arrows, icons, formulas, card borders, labels, people, and decorations must not cover, intersect, press on, or stick to each other.",
        "- Avoid severe overlap. Text, arrows, icons, formulas, card borders, and labels must not collide.",
        "- The final page should remain manually maskable, but Mask convenience must not force a rigid card grid.",
    ]


def build_prompt(
    slide: dict[str, Any],
    template_ref: str,
    *,
    policy: dict[str, Any],
    invariants: dict[str, Any],
    style_tokens: dict[str, Any],
    project_style: dict[str, Any] | None = None,
) -> str:
    slide_id = str(slide.get("slide_id", "")).strip()
    elements = "\n".join(compact_visual_element_lines(slide)) or "- No visual elements provided."
    production_rules = "\n".join(production_invariant_lines(invariants, policy, slide))
    project_style_rules = project_image_style_lines(project_style or {})
    global_style_rules = style_profile_lines(style_tokens)
    combined_style_rules = []
    if project_style_rules:
        combined_style_rules.extend(project_style_rules)
        if global_style_rules:
            combined_style_rules.append("")
            combined_style_rules.append("Global fallback style tokens; use only where they do not conflict with Project Profile:")
            combined_style_rules.extend(global_style_rules)
    else:
        combined_style_rules = global_style_rules
    style_rules = "\n".join(combined_style_rules) or "- Use the active style reference images as the visual style source."

    return f"""Use case: scientific-educational
Asset type: 16:9 Image Gen full-slide master for reveal-layer video production
Slide id: {slide_id}
Input images:
- Reference image ({template_ref}): use only as an overall style, title-area, spacing, hierarchy, color, and density reference.
- If the reference image conflicts with the active style profile below, the active style profile is authoritative.

Primary request:
Generate one complete full-slide master image from the compact Step 2B visual element list.
The slide body, title, lines, arrows, icons, labels, and diagrams must all be Image Gen bitmap content.

Production invariants that style must not override:
{production_rules}

Compact visual element list:
{elements}

Mapping and mask guidance:
- First design a coherent page from the element list.
- Every listed element must be visible and easy to associate with its element_id during later Mask/Reveal work.
- A later mask should be able to reveal meaningful regions without covering unrelated content.
- Arrows, icons, labels, and callouts may connect ideas, but they must not collide with text or create severe overlap.
- Do not place any content or decoration below y=930.
- Do not overlap elements. Leave visible white space between text, icons, arrows, cards, labels, and decorative marks.

Style profile; Project Profile rules are authoritative when present:
{style_rules}

Creative freedom:
- Choose the exact composition, shapes, icons, arrows, callouts, local decorations, and visual metaphor as long as production invariants are preserved.
- Make the page visually rich inside the content area, but keep it clean and readable.
- Do not create many equal isolated cards unless the narration truly calls for a list, comparison, or checklist.
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
    template_ref = extract_style_ref(style_tokens_path)
    project_style = load_project_image_style(run_dir)
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
                policy=policy,
                invariants=invariants,
                style_tokens=style_tokens,
                project_style=project_style,
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
