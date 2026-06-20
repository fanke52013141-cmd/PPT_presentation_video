# Scene Reconstruction Prompt

Build the production reveal scene from one approved full-slide bitmap and its optional manual brush masks.

## Production Contract

- Pipeline: `manual_mask_outer_white_v3`.
- No mask: use the complete slide as `full_slide_static`.
- With masks: use `solid_background_outer_white_manual_mask`.
- Remove only near-white pixels connected to an outer image edge.
- Preserve white pixels enclosed by visible content.
- Use the saved manual mask as the retention boundary.
- Do not erode, dilate, auto-expand, segment, crop, or reassign foreground.
- If no eraser was used, fill only fully enclosed holes in the painted mask.
- If the eraser was used, preserve the explicit erased areas.
- Never reuse the complete source image as the background of a masked slide.

## Commands

```powershell
python scripts/build_reveal_scene.py `
  --manifest runs/<run_id>/reveal_manifest.json `
  --repo-root .

python scripts/validate_reveal_scene.py `
  --run-dir runs/<run_id> `
  --repo-root .
```

Stop when validation reports missing assets, stale pipeline data, source-image background reuse, or insufficient foreground coverage.
