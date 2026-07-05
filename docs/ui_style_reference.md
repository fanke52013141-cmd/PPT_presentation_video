# UI Style Reference

This project’s current application UI is the soft blue-purple **Soft Pastel Studio** interface. Do not use the older black-outline sketch layer as the visual direction for new UI work.

## Source of truth

Use these files in this order when inspecting or modifying the application UI:

1. `static/style.css`
   - The canonical implementation lives in the lower half of the file.
   - Search for `Soft Pastel Studio refinement layer`.
   - The earlier `Flat Outline UI` section is a legacy compatibility foundation for historical class names.
2. `static/index.html`
   - Defines the static DOM, top navigation, sidebar, step panels, and modal containers.
3. `static/app.js`
   - Defines dynamic UI behavior, generated cards, button states, Mask panel rendering, autosave states, and step transitions.
4. `static/flow.js`
   - Defines the six user-visible workflow steps and their completion/unlock rules.
5. `static/ai_mask_extension.js`
   - Adds AI Mask controls and a small amount of inline UI for the Mask settings modal.

## Current visual direction

The intended product UI is:

- Soft blue-purple palette.
- Light page background with subtle warm gradient.
- Rounded white cards and panels.
- Thin, low-contrast borders.
- Soft shadows, not hard offset sketch shadows.
- Glass-like top navigation.
- Purple gradient AI action buttons.
- Calm, minimal controls with clear spacing.

Representative tokens from `static/style.css`:

```css
--color-primary-deep: #5365d0;
--color-primary-base: #8fa7f8;
--color-primary-soft: #cfddfe;
--color-primary-light: #eef3ff;
--color-primary-text: #263b7a;

--color-ai-deep: #7b5cd6;
--color-ai-light: #f4eeff;

--color-bg-page: #fafbff;
--color-bg-warm: #fffdf8;
--color-bg-surface: #ffffff;
--color-bg-subtle: #f6f8ff;
--color-border-default: #e8ecf6;
--color-border-strong: #d6ddec;

--gradient-ai-soft: linear-gradient(135deg, #cfddfe 0%, #dcc9fb 100%);
--gradient-ai-strong: linear-gradient(135deg, #5365d0 0%, #7b5cd6 100%);
--gradient-progress: linear-gradient(90deg, #5365d0 0%, #8fa7f8 100%);
```

## Legacy layer policy

`static/style.css` still contains early selectors and names such as `.sketch-border`, `.sketch-dashed`, and `.sketch-shadow`. These names are retained because the HTML and JavaScript already use them. They should be treated as compatibility hooks, not as a style brief.

When making new UI changes:

- Keep existing class names if changing them would require broad DOM and JavaScript updates.
- Override their visual appearance using the Soft Pastel Studio tokens.
- Do not add new heavy black borders, dashed sketch cards, or hard `2px 2px 0` shadows.
- Do not describe the application UI as hand-drawn, sketch, wireframe, or flat outline.

## Image generation style is separate

The generated PPT slide images are governed by different files:

- `config/style_tokens.yaml`
- `config/style_tokens_handdrawn.yaml`
- `references/style_reference/`
- `runtime_step3_image_style.py`

Those files affect generated slide imagery and style templates. They do not define the web application’s blue-purple UI shell.

## Quick verification

If the local UI looks like the old black-outline sketch style:

1. Open `http://127.0.0.1:8000/style.css?v=20260704.2`.
2. Search for `Soft Pastel Studio refinement layer`.
3. If it is missing, the browser or server is serving an old CSS file.
4. Hard-refresh the browser or bump the CSS query string in `static/index.html`.
