# Visual Draft Prompt Template

Use this template to generate one complete Image Gen slide. Optional manual
Masks may later reveal selected visual groups, but the source remains one
approved full-slide bitmap.

## Inputs

- Slide ID: `{{slide_id}}`
- Page purpose: `{{slide_purpose}}`
- Main title: `{{main_title}}`
- Subtitle: `{{subtitle}}`
- Core message: `{{core_message}}`
- Content type: `{{content_type}}`
- Layout intent: `{{layout_intent}}`
- Content items: `{{content_items}}`
- Narration: `{{narration}}`
- Narration beats: `{{narration_beats}}`

## Image Gen Request

Generate one 1920x1080, 16:9 Chinese educational PPT-style master image.

The image must be content-first: choose the body composition that best explains
the slide, instead of mechanically applying a fixed card/list template.

Use the fixed style references:

- `references/style_reference/PPT模板.png`
- `references/style_reference/PPT示例.png`

The image must contain all PPT body visuals as bitmap content: title, subtitle,
cards, icons, arrows, formulas, diagrams, labels, and summary text. Remotion
will not draw these later.

## Narration Binding

The image must support the narration beats in order.

- Every important narration beat should map to one visible macro group.
- The narration expands the visible content; it must not be unrelated to the
  page.
- Later beats can be represented by later visual groups or a summary group.
- Do not show all beats as equally important. Use visual hierarchy to match the
  speaking order.
- If the narration explains reasoning, draw a reasoning path. If it compares,
  draw a comparison. If it coordinates objects, draw an object map. If it gives
  actions, draw an action flow.

## Mask-Friendly Layout Rules

Design the image so visual groups can be painted cleanly with a manual Mask:

- Use 5-8 large macro groups.
- Keep independent macro groups separated by at least 48-80px of clean
  background.
- Absolutely no overlap: text, cards, icons, arrows, lines, labels, decorative
  marks, charts, and illustrations must not cover, press on, pierce through, or
  stick to each other.
- In the middle content area, avoid dense clusters, overlaps, touching edges,
  and near-contact.
- Do not place text on top of arrows, icons, card borders, labels, or formulas.
- Do not let arrows pierce through text or touch label strokes.
- If a label, arrow, and icon are inseparable, keep them visually in the same
  macro group.
- Keep the bottom subtitle-safe area empty. At 1920x1080, no PPT body content
  should extend below `y=930`.
- Avoid many tiny labels. Prefer fewer, larger, readable groups.
- Do not add a large enclosing rounded content frame around the whole middle
  area.

## Style

- Flat, uniform pure-white `#FFFFFF` outer background.
- Main title and subtitle stay in the fixed top title area.
- Bottom subtitle-safe area stays empty.
- All four edges and corners must stay continuously pure white.
- No paper texture, background noise, shadow, gradient, vignette, or warm
  off-white outer canvas.
- Hand-drawn black ink text.
- Yellow accent marker and underline.
- Soft green and blue label pills when useful.
- Simple doodle icons and diagrams.
- Clean spacing, readable Chinese labels, no fake UI, no watermark.

## Negative Requirements

- No SVG, HTML, CSS, Canvas, React, or Remotion-drawn body content.
- No crowded center layout.
- No overlapping macro groups.
- No overlapping visual elements of any kind.
- No tiny unreadable text.
- No photorealistic scene, dark tech background, or 3D render.
