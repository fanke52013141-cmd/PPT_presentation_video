# Visual Draft Prompt Template

Use this template to generate one complete Image Gen slide. Optional manual Masks may later reveal selected visual anchors, but the source remains one approved full-slide bitmap.

## Production Invariants

These rules are fixed and cannot be changed by a style profile:

- 1920x1080, 16:9.
- The generated slide image background must be pure white `#FFFFFF`.
- All four edges and corners must stay continuously pure white.
- Every slide must contain a clear main title.
- Subtitle usage is decided once by `presentation_policy.subtitle_policy`.
  - If `all_slides_have_subtitle`, every page renders a subtitle.
  - If `no_slides_have_subtitle`, no page renders a subtitle, subtitle underline, or subtitle placeholder.
- Keep y=930..1080 completely empty for video subtitles.
- Do not place text, icons, arrows, labels, decorations, shadows, partial objects, or visual fragments in y=930..1080.
- Strictly forbid visible element overlap: text, icons, arrows, lines, labels, card borders, people, decorations, formulas, and charts must not cover, intersect, press on, pierce through, or stick to each other.
- Avoid text-arrow collision, arrow-through-text, merged unrelated regions, and tiny dense labels.
- The page must remain manually maskable, but Mask convenience must not force a rigid block layout.

## Inputs

- Slide ID: `{{slide_id}}`
- Main title: `{{main_title}}`
- Subtitle policy: `{{subtitle_policy}}`
- Subtitle: `{{subtitle}}`
- Core message: `{{core_message}}`
- Body content: `{{body_content}}`
- Visual intent: `{{visual_intent}}`
- Narration: `{{narration}}`
- Optional narration beats: `{{narration_beats}}`
- Optional visual anchors: `{{visual_groups}}`
- Style profile: `{{style_profile}}`

## Image Gen Request

Generate one 1920x1080, 16:9 Chinese educational PPT-style master image.

Use the fixed style references only for title-area placement, spacing, hierarchy, and density. If they conflict with the active style profile, the active style profile is authoritative:

- `references/style_reference/PPT模板.png`
- `references/style_reference/PPT示例.png`

The image must contain all PPT body visuals as bitmap content: title, optional subtitle when policy allows it, body content, icons, arrows, diagrams, labels, and emphasis marks. Remotion will not draw these later.

## Narration-First Design

Design the whole page from the narration and body content. Do not first split the page into fixed roles such as diagram, data, process, quote, or summary.

- The narration is the source of truth.
- Body content is the only planned content category besides title and optional subtitle.
- Choose the best visual expression freely: scene, diagram, metaphor, cards, timeline, comparison, icon cluster, or a mixed layout.
- Use visual hierarchy to support the speaking order, but do not make every beat an equal isolated card.
- Optional visual anchors are post-design review handles for Mask/Reveal, not a pre-generation layout template.

## Mask-Friendly Layout Rules

Design the image so important regions can be painted cleanly with a manual Mask:

- Prefer one coherent main visual plus supporting details when it improves expression.
- Use 2-5 loose visual anchors after the page is composed; fewer is acceptable if the page reads clearly.
- Connections between ideas are allowed: arrows, brackets, paths, timelines, or flow lines.
- Do not create many isolated cards unless the narration truly calls for a list, comparison, or checklist.
- Keep enough clean white background around important regions for manual Mask painting.
- Absolutely no overlap: text, icons, arrows, lines, labels, card borders, people, decorations, formulas, charts, and illustrations must not cover, press on, pierce through, touch ambiguously, or stick to each other.
- Do not place text on top of arrows, icons, card borders, labels, or formulas.
- Do not let arrows pierce through text or touch label strokes.
- Keep the bottom subtitle-safe area empty. At 1920x1080, no content or decoration should extend below `y=930`.
- Avoid many tiny labels. Prefer fewer, larger, readable elements.

## Style

The built-in default style can be warm hand-drawn explainer, but this section is generalizable by the active style profile. When the active profile asks for another style, do not copy hand-drawn strokes from the reference images.

Default style direction:

- Hand-drawn black ink text.
- Yellow accent marker and underline.
- Soft green and blue label pills when useful.
- Simple doodle icons and diagrams.
- Clean spacing, readable Chinese labels, no fake UI, no watermark.

The active style profile may change typography, line style, icon style, diagram style, accent colors, callouts, card shapes, and visual density. It must not change the production invariants.

## Negative Requirements

- No crowded center layout.
- No overlapping visual elements of any kind.
- No severe overlap, arrow-through-text, text pressed onto borders, or unrelated regions merged together.
- No tiny unreadable text.
- No dark full-page background or 3D render.
- No paper texture, background noise, shadow, gradient, vignette, or off-white outer canvas.
- No content in y=930..1080.
