# Config Effectiveness Patch

This branch adds `static/config_effectiveness.js`, a small frontend patch that fixes the configuration-effectiveness issues without rewriting the large `static/app.js` file.

## What the patch script does

- Reloads `/api/settings` after saving system settings so `state.settings` matches backend state.
- Shows the actual configured image model and image size when generating a slide image.
- Refreshes Step 3 prompts after saving image style settings.
- Updates the currently open Step 3 prompt editor when style settings change.
- Clarifies that storyboard rules affect the next storyboard regeneration.
- Adds a runtime `保存并重新规划` button to the storyboard rules modal.

## Required HTML hook

The script must be loaded after `app.js`:

```html
<script src="app.js?v=2.0.14"></script>
<script src="config_effectiveness.js?v=1.0.0"></script>
```

Do not load it before `app.js`; it patches functions that are defined by `app.js`.

## Why this is separate

The current GitHub contents update path replaces whole files. Keeping the patch as a separate script makes the behavior change small and easy to review. The only remaining integration change is the one-line script tag above.
