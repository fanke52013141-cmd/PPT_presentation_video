# Visual Draft Prompt Template

Use this template to generate one complete Image Gen slide. Optional manual Masks may later reveal selected visual groups, but the source remains one approved full-slide bitmap.

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
- Avoid severe overlap, text-arrow collision, arrow-through-text, merged unrelated groups, and tiny dense labels.
- Semantic groups must remain manually maskable.

## Inputs

- Slide ID: `{{slide_id}}`
- Page purpose: `{{slide_purpose}}`
- Main title: `{{main_title}}`
- Subtitle policy: `{{subtitle_policy}}`
- Subtitle: `{{subtitle}}`
- Core message: `{{core_message}}`
- Layout type: `{{layout_type}}`
- Visual metaphor: `{{visual_metaphor}}`
- Composition: `{{composition}}`
- Content type: `{{content_type}}`
- Layout intent: `{{layout_intent}}`
- Content items: `{{content_items}}`
- Narration: `{{narration}}`
- Narration beats: `{{narration_beats}}`
- Style profile: `{{style_profile}}`

## Image Gen Request

Generate one 1920x1080, 16:9 Chinese educational PPT-style master image.

Use the fixed style references:

- `references/style_reference/PPT模板.png`
- `references/style_reference/PPT示例.png`

The image must contain all PPT body visuals as bitmap content: title, optional subtitle when policy allows it, cards, icons, arrows, formulas, diagrams, labels, and summary text. Remotion will not draw these later.

## Narration Binding

The image must support the narration beats in order.

- Every important narration beat should map to one visible macro group.
- The narration expands the visible content; it must not be unrelated to the page.
- Later beats can be represented by later visual groups or a summary group.
- Do not show all beats as equally important. Use visual hierarchy to match the speaking order.

## Mask-Friendly Layout Rules

Design the image so visual groups can be painted cleanly with a manual Mask:

- Use 2-6 meaningful semantic visual groups.
- Prefer one dominant hero visual plus several supporting elements when it improves expression.
- Groups may be connected by clean arrows, brackets, timelines, or flow paths.
- Do not create many isolated cards unless the content is truly a list, comparison, or checklist.
- Keep enough clean white background around each semantic group for manual Mask painting.
- Do not place text on top of arrows, icons, card borders, labels, or formulas.
- Do not let arrows pierce through text or touch label strokes.
- If a label, arrow, and icon are inseparable, keep them visually in the same macro group.
- Keep the bottom subtitle-safe area empty. At 1920x1080, no content or decoration should extend below `y=930`.
- Avoid many tiny labels. Prefer fewer, larger, readable groups.
- Do not add a large enclosing rounded content frame around the whole middle area unless the active style explicitly uses it and it does not harm Masking.

## Style

The default style is warm hand-drawn explainer, but this section is generalizable by the active style profile.

Default style direction:

- Hand-drawn black ink text.
- Yellow accent marker and underline.
- Soft green and blue label pills when useful.
- Simple doodle icons and diagrams.
- Clean spacing, readable Chinese labels, no fake UI, no watermark.

The active style profile may change typography, line style, icon style, diagram style, accent colors, callouts, card shapes, and visual density. It must not change the production invariants.

## Negative Requirements

- No crowded center layout.
- No overlapping macro groups.
- No tiny unreadable text.
- No dark full-page background or 3D render.
- No paper texture, background noise, shadow, gradient, vignette, or off-white outer canvas.
- No content in y=930..1080.
