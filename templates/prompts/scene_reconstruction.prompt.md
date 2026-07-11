# Scene Reconstruction Prompt

## Purpose

Reconstruct a production-ready Reveal scene from an approved slide bitmap and optional manual masks while preserving the approved visual content exactly.

## Input

- One approved full-slide bitmap.
- Optional saved manual brush masks and the current `reveal_manifest.json`.

## Output

- Production scene assets referenced by the updated manifest and a successful validation result.
- Do not redesign, regenerate, reinterpret, crop, or reassign slide content.

Build the production reveal scene from one approved full-slide bitmap and its optional manual brush masks.

## Production Contract

- Pipeline: `manual_mask_boundary_white_v4`.
- No mask: use the complete slide as `full_slide_static`.
- With masks: use `solid_background_mask_boundary_white_cutout`.
- Treat each saved brush Mask as a processing boundary.
- Remove only near-white pixels connected inward from that Mask boundary.
- Preserve white pixels enclosed by visible content.
- Retain all non-white source content inside the saved manual Mask.
- Do not erode, dilate, auto-expand, segment, crop, or reassign foreground.
- Apply only soft antialias alpha and white-edge decontamination.
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

Stop when validation reports missing assets, stale pipeline data, source-image background reuse, or unreferenced legacy assets.
