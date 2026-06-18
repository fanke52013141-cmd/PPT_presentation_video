# Unified Validation Stages

`python scripts/validate_run.py` is the preferred wrapper for staged run validation. It does not replace the existing validator scripts; it calls them in stable combinations so operators can validate by production stage.

## Stages

```powershell
python scripts/validate_run.py --run-dir runs/<run_id> --stage contract
python scripts/validate_run.py --run-dir runs/<run_id> --stage image
python scripts/validate_run.py --run-dir runs/<run_id> --stage reveal --require-layered
python scripts/validate_run.py --run-dir runs/<run_id> --stage render_ready --require-layered
python scripts/validate_run.py --run-dir runs/<run_id> --stage all --require-layered
```

## What each stage checks

| Stage | Checks |
| --- | --- |
| `contract` | Runs `validate_visual_contract.py` against `planning/visual_contract.json`. |
| `image` | Checks each contract slide has `slides/<slide_id>/visual_draft.png` at 1920x1080 by default. Use `--require-image-provenance` to require `visual_provenance.json`. |
| `reveal` | Runs `validate_reveal_manifest.py`, then `validate_reveal_scene.py`. |
| `render_ready` | Runs `validate_narration_grounding.py`, then `validate_run_assets.py`. |
| `all` | Runs `contract`, `image`, `reveal`, and `render_ready` in order. |

## Strictness flags

- `--require-image-provenance`: require each slide to include `visual_provenance.json`.
- `--require-reviewed`: require reveal groups to have an approved review status.
- `--require-layered`: pass layered-scene enforcement to `validate_run_assets.py`.
- `--strict-literal`: require narration text to literally mention visible text or anchor.
- `--allow-blocking-warnings`: allow reveal-scene blocking warnings during diagnostic runs.

## Backward compatibility

All existing validators remain available for targeted debugging:

```powershell
python scripts/validate_visual_contract.py --contract runs/<run_id>/planning/visual_contract.json
python scripts/validate_reveal_manifest.py --manifest runs/<run_id>/reveal_manifest.json --contract runs/<run_id>/planning/visual_contract.json
python scripts/validate_reveal_scene.py --run-dir runs/<run_id> --repo-root .
python scripts/validate_narration_grounding.py --run-dir runs/<run_id>
python scripts/validate_run_assets.py --run-dir runs/<run_id> --require-layered
```
