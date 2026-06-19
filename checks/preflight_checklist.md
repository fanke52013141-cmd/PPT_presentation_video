# Production Preflight Checklist

## Required Inputs

- Article input exists.
- `planning/visual_contract.json` contains the current slide order.
- Every current slide has `visual_draft.png`.
- `reveal_manifest.json` contains the same current slide ids.
- Narration and audio files exist before final rendering.

## Exact Mask Invariants

- Pipeline version is `manual_mask_exact_v2`.
- A page without painted Masks uses `full_slide_static`.
- A page with Masks uses `solid_background_manual_mask_exact`.
- Masked pages declare `source_image_used_for_background=false`.
- Every reveal PNG is full-canvas and uses only its saved brush alpha.
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

## Legacy Diagnostics

These scripts are not part of production:

- `auto_fit_reveal_boxes.py`
- `split_master_layers.py`
- `decompose_slide_layers.py`
- `compose_manifest_layers.py`

## Blocking Conditions

- Missing current slide image, narration, or audio.
- Unknown or stale reveal pipeline version.
- Source image reused as a masked slide background.
- Animation event targets a missing layer.
- Audio has not been confirmed.
- Blocking reveal warning.
- Runtime assets are missing or stale.

## Safety

- Do not log or commit API keys.
- Do not commit `runs/`, `outputs/`, `logs/`, `data/`, or generated media.
