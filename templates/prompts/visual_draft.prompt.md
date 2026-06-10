# Visual Draft Prompt Template

Use this template to generate one complete Image Gen master slide.

The master image will later be split into same-source macro PNG layers. Do not
ask Image Gen to create independent isolated elements for the default
production path.

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

## Split-Friendly Layout Rules

Design the master image so it can be cleanly split later:

- Use 5-8 large macro groups.
- Keep independent macro groups separated by at least 48-80px of clean
  background.
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

- Warm off-white paper background.
- Hand-drawn black ink text.
- Yellow accent marker and underline.
- Soft green and blue label pills when useful.
- Simple doodle icons and diagrams.
- Clean spacing, readable Chinese labels, no fake UI, no watermark.

## Negative Requirements

- No independent element package in the default production path.
- No SVG, HTML, CSS, Canvas, React, or Remotion-drawn body content.
- No crowded center layout.
- No overlapping macro groups.
- No tiny unreadable text.
- No photorealistic scene, dark tech background, or 3D render.
