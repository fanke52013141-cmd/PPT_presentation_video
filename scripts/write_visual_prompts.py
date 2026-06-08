#!/usr/bin/env python3
"""
Write per-slide prompts for Image Gen macro-layer visual packages.

The image model is intentionally outside this script. This script records the
exact production prompt that should be pasted or issued to Image Gen/Web Image
Gen, and it binds each slide to the configured style reference images.
"""

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
        raise PromptError(
            f"Could not find visual_assets.template_reference_image and "
            f"visual_assets.example_reference_image in {style_tokens_path}"
        )

    return template, example


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
        prefix_parts = [part for part in [item_type, label, side] if part]
        prefix = " / ".join(prefix_parts)
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
    content = slide.get("content") if isinstance(slide.get("content"), dict) else {}
    layout_intent = str(content.get("layout_intent", "")).strip() if isinstance(content, dict) else ""
    content_type = str(content.get("content_type", "")).strip() if isinstance(content, dict) else ""
    bullets = "\n".join(item_lines(slide))

    return f"""Use case: scientific-educational
Asset type: 16:9 bitmap slide reference plus separate macro-layer PNG package
Slide id: {slide_id}
Input images:
- Reference image 1 ({template_ref}): use as the page template and composition reference.
- Reference image 2 ({example_ref}): use as the filled-slide visual style reference.

Primary request:
Generate one complete full-slide reference image in the same warm hand-drawn Chinese explainer style as the references, then generate the separate macro-layer PNG images needed to rebuild that slide. The production pipeline will not use code to semantically crop a full-slide bitmap. It will only compose the macro-layer images declared in layer_manifest.json.
The slide body, title, subtitle, lines, arrows, icons, labels, and diagram content must all be Image Gen bitmap content. Do not create SVG, vector layers, HTML, CSS, Canvas, React, or Remotion-drawn PPT body elements.

Required macro-layer package:
- background: use a plain generated color image or manifest color when the background is flat; only generate a background layer if there is intentional paper texture or a non-flat backdrop.
- title_group: main title plus its yellow left marker if they visually belong together.
- subtitle_group: subtitle plus yellow underline.
- content_group_01..content_group_04: large content blocks only. Keep related text, icons, arrows, and labels together; do not split into tiny pieces.
- summary_group: bottom takeaway strip if used.
- layer_manifest.json plan: for each layer, provide id, role, source filename, x, y, w, h, z_index, text_summary, narration_cue, reveal_at if known, and animation hint.

Canvas and layout:
- 16:9 landscape, suitable for 1920x1080 video.
- Warm off-white paper background.
- Yellow vertical marker at top left.
- Large handwritten Chinese main title at top left.
- Smaller handwritten Chinese subtitle below the title with a short yellow underline.
- The middle of the slide is an open content canvas. Do not draw a large enclosing rounded black content frame.
- Keep the main content inside the open area from roughly x=80,y=235 to x=1840,y=915.
- Leave the bottom 150px visually calm so Remotion subtitles can overlay without covering critical content. For 1920x1080, no PPT body layer may extend below y=930 unless subtitles are disabled.
- Keep at least 40-60px of clean background between independent macro layers. Avoid overlaps between boxes.
- Arrows may connect ideas, but arrow tips must not touch or overlap text strokes, icon strokes, labels, or summary text.

Text to render exactly where possible:
Main title: "{title}"
Subtitle: "{subtitle}"
Core message: "{core_message}"

Content structure:
Type: {content_type}
Layout intent: {layout_intent}
Key content:
{bullets}

Style constraints:
- Match the two reference images: black hand-drawn ink, yellow accent, soft green and blue highlight pills, simple doodle icons, clean spacing.
- Preserve the fixed title/subtitle positions and fixed subtitle-safe area from the reference images.
- Do not add an outer content border around the middle content.
- Avoid overlapping objects. Do not place text on top of icons, arrows, borders, or colored label backgrounds unless that text belongs to the same label group.
- Prefer 3-7 large macro groups over many tiny scattered marks, so Image Gen can produce stable separate layer images and Codex can compose them without semantic cropping.
- Keep arrows short and detached from object borders; avoid vertical ribbons, full-width pale strips, or connector lines that merge multiple cards into one connected bitmap group.
- Keep text large and readable; avoid dense paragraphs and avoid tiny labels.
- Prefer short Chinese labels and diagrammatic blocks over long body text.
- No photorealistic scene, no 3D, no neon technology style, no dark background, no watermark.

Narration and timing binding:
- The narration must explain the visible macro layers in order. Do not reuse unrelated narration from another slide.
- Each layer's text_summary should name what is visibly inside that layer.
- Each layer's narration_cue should state which sentence or paragraph introduces it.
- The animation timeline must reveal a layer only when the narration reaches its cue. Do not reveal every body layer at the beginning.
- Summary_group should appear near the end and may then receive a highlight.
"""


def write_prompts(run_dir: Path, style_tokens_path: Path, overwrite: bool) -> int:
    slide_plan = read_json(run_dir / "planning" / "slide_plan.json")
    slides = slide_plan.get("slides")
    if not isinstance(slides, list) or not slides:
        raise PromptError(f"slide_plan.json must contain non-empty slides[]: {run_dir}")

    template_ref, example_ref = extract_style_refs(style_tokens_path)
    count = 0

    for slide in slides:
        if not isinstance(slide, dict):
            raise PromptError("Each slide in slide_plan.json must be an object")
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
    parser = argparse.ArgumentParser(description="Write Codex Image Gen prompts for a run.")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--style-tokens", default=Path("config/style_tokens.yaml"), type=Path)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        count = write_prompts(
            run_dir=args.run_dir.resolve(),
            style_tokens_path=args.style_tokens.resolve(),
            overwrite=args.overwrite,
        )
    except PromptError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote {count} visual prompt file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
