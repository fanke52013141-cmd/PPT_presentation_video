# UI Style Reference

This project's application UI is a 1:1 implementation of the supplied Stitch
design code. The Stitch export is the visual authority. The former global
blue-purple "Soft Pastel Studio" mandate and the older black-outline sketch
layer are retired; do not use either as the visual direction for new UI work.

## Source of truth

Inspect and modify the application UI using these files in this order:

1. `references/ui_extract/stitch_extract/stitch_web_ui_style_extractor/*/code.html`
   - The approved Stitch design screens. When CSS layers disagree, these
     files win.
2. `static/stitch.css`
   - Deliberately loaded after `static/style.css` by `static/index.html` so
     legacy compatibility rules cannot change the exported geometry. It only
     changes presentation; event handlers, IDs, and routes remain owned by
     the existing feature modules.
3. `static/style.css`
   - The early `Flat Outline UI` and `Soft Pastel Studio` blocks are legacy
     compatibility foundations only. Visible surfaces are styled by the
     appended strict-parity layers at the end of the file (search for
     `Exported homepage parity contract`, `Final strict-parity layer
     (ui_extract stitch screens)`, and `strict parity polish`).
4. `static/index.html`
   - Defines the static DOM, top navigation, sidebar, step panels, and modal
     containers.
5. `static/workflow_state.js` and feature-owned frontend modules
   - Define dynamic UI behavior, generated cards, button states, Mask panel
     rendering, autosave states, and step transitions. See the module
     ownership list in `AGENTS.md` before adding behavior; never recreate
     `static/app.js`.
6. `static/workspace_navigation.js` and `static/event_bindings.js`
   - Own workspace entry/exit, visible-step routing, and the single shared
     DOMContentLoaded boot entry.

## Current visual direction

The intended product UI is:

- Orange `#f46a38` brand accents on active steps, highlights, and AI actions.
- Light warm page background with white rounded cards.
- Dark primary buttons with orange hover/focus accents.
- The 7-step workspace rail and the course-library home exactly as exported.
- "Plus Jakarta Sans" / "Noto Sans SC" typography, shared through the
  `--font-family` token defined identically in `stitch.css` and
  `style.css`.
- A single line-icon system with equal optical size and shared stroke and
  baseline.

Representative tokens from `static/stitch.css`:

```css
--stitch-page: #faf9fb;
--stitch-card: #ffffff;
--stitch-line: #eae8ed;
--stitch-dark: #1e1d22;
--stitch-brand: #f46a38;
--stitch-brand-hover: #dc5121;
--stitch-brand-soft: #fff7f4;
--stitch-radius-lg: 18px;
--stitch-shadow-card: 0 1px 2px rgba(30, 29, 34, .035);
--stitch-shadow-float: 0 14px 36px rgba(30, 29, 34, .12);
```

## Legacy layer policy

`static/style.css` still contains early selectors and names such as
`.sketch-border`, `.sketch-dashed`, `.sketch-shadow`, and the blue-purple
`--color-primary-*` tokens. These names are retained because the HTML and
JavaScript already use them. They are compatibility hooks, not a style brief.

When making new UI changes:

- Keep existing class names if changing them would require broad DOM and
  JavaScript updates.
- Override their visual appearance using the Stitch tokens and the appended
  strict-parity layers, matching the exported screens.
- Do not add new heavy black borders, dashed sketch cards, or hard
  `2px 2px 0` shadows.
- Do not reintroduce the blue-purple Soft Pastel Studio palette on visible
  surfaces.
- Do not describe the application UI as hand-drawn, sketch, wireframe, or
  flat outline.

## Image generation style is separate

The generated PPT slide images are governed by different files:

- `config/style_tokens.yaml`
- `config/style_tokens_handdrawn.yaml`
- `references/style_reference/`
- `project_style_routes.py`
- `project_style_template_service.py`

Those files affect generated slide imagery and style templates. They do not
define the web application shell.

## Quick verification

If the local UI looks like the retired sketch or Soft Pastel Studio styles:

1. Open `http://127.0.0.1:8000/stitch.css` and confirm it starts with the
   `Stitch screen contract` comment and defines `--stitch-brand: #f46a38`.
2. Open `http://127.0.0.1:8000/style.css` and confirm the appended
   strict-parity layers exist near the end of the file.
3. If either file is missing or stale, the browser or server is serving an
   old copy; hard-refresh the browser or bump the `?v=` query strings in
   `static/index.html` for `style.css` and `stitch.css`.
