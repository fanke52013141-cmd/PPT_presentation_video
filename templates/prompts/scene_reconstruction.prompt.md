# Scene Reconstruction Prompt

<PromptVersion>scene_reconstruction_v5_exact_rle</PromptVersion>

## Purpose

Build deterministic Reveal assets from the approved slide bitmap and the semantic ownership already saved by AI Mask. Do not perform semantic rematching or visual redesign.

## Input

- The current `reveal_manifest.json`, including exact automatic `manual_mask.rle` ownership when AI Mask has run.
- One approved full-slide bitmap per Slide.
- Optional manual paint/erase correction strokes already stored in the manifest.

## Output

- Scene PNG assets and reports referenced by the current manifest.
- A successful reveal-scene validation result.
- No redesigned, regenerated, cropped, rematched, or reassigned slide content.

## Production Contract

- Pipeline: `exact_rle_mask_with_manual_corrections_v5`.
- A Slide without a Mask remains `full_slide_static`.
- A masked Slide starts from the configured video background; never reuse the source bitmap as its background.
- Treat each saved automatic Mask as a processing boundary and apply optional manual paint/erase strokes only as corrections.
- Remove only near-white pixels connected inward from that boundary; preserve white areas enclosed by visible content.
- Retain non-white source content within the saved ownership Mask, with soft antialias alpha and white-edge decontamination.
- Do not rematch semantic ownership, redesign, regenerate, crop, or silently reuse legacy layer assets.
- The resulting automatic Masks must preserve at least 99.5% of foreground content, leave zero unassigned components, and have zero cross-group pixel overlap.

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
