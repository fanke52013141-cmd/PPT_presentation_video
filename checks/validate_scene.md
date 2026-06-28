# Reveal Scene Checks

Target: `runs/<run_id>/slides/<slide_id>/scene.json`

## Required

- Pipeline version is `exact_rle_mask_with_manual_corrections_v5`.
- Canvas is 1920×1080.
- `layers[]` exists and every asset is a PNG inside the canvas.
- No production PPT body uses HTML, SVG, text, shape, line, or React drawing.
- Animation targets refer to existing layer ids.

## Static Slides

- `composition_method=full_slide_static`.
- The complete source image is displayed.

## Masked Slides

- `composition_method=solid_background_mask_boundary_white_cutout`.
- `source_image_used_for_background=false`.
- White connected inward from each painted Mask boundary is removed.
- Enclosed white content remains visible.
- Reveal assets follow the saved manual Masks.
- No unreferenced legacy PNG remains in `assets/`.

## Commands

```powershell
python scripts/validate_reveal_scene.py `
  --run-dir runs/<run_id> `
  --repo-root .

python scripts/validate_run_assets.py `
  --run-dir runs/<run_id> `
  --repo-root . `
  --require-layered
```
