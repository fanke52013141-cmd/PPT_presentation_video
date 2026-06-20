# Production Preflight Checklist

## Required Inputs

- Article input exists.
- `planning/visual_contract.json` contains the current slide order.
- Every current slide has `visual_draft.png`.
- `reveal_manifest.json` contains the same current slide ids.
- Narration and audio files exist before final rendering.

## Exact Mask Invariants

- Pipeline version is `manual_mask_boundary_white_v4`.
- A page without painted Masks uses `full_slide_static`.
- A page with Masks uses `solid_background_mask_boundary_white_cutout`.
- Masked pages declare `source_image_used_for_background=false`.
- Generated images use a pure-white outer background.
- Only near-white pixels connected inward from each painted Mask boundary are removed.
- Enclosed white content is preserved.
- Every reveal PNG is full-canvas and uses the saved brush Mask as its
  retention boundary.
- `assets/` is rebuilt before render.
- Remotion `public/runtime/<run_id>` is rebuilt before render.
- Blocking reveal warnings stop the build.

## Commands

```powershell
python scripts/build_reveal_scene.py `
  --manifest runs/<run_id>/reveal_manifest.json `
  --repo-root .

python scripts/validate_reveal_scene.py `
  --run-dir runs/<run_id> `
  --repo-root .

python scripts/bind_reveal_timeline.py `
  --run-dir runs/<run_id> `
  --lead-sec 0

python scripts/build_remotion_props.py `
  --run-dir runs/<run_id> `
  --repo-root .

python scripts/validate_run_assets.py `
  --run-dir runs/<run_id> `
  --repo-root . `
  --require-layered
```

## Blocking Conditions

- Missing current slide image, narration, or audio.
- Unknown or stale reveal pipeline version.
- Source image reused as a masked slide background.
- Animation event targets a missing layer.
- Audio has not been confirmed.
- Blocking reveal warning.
- Runtime assets are missing or stale.
- Reveal assets contain unreferenced legacy files.

## Safety

- Do not log or commit API keys.
- Do not commit `runs/`, `outputs/`, `logs/`, `data/`, or generated media.
