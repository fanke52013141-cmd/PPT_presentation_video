# Scene Checks

Target: `runs/<run_id>/slides/<slide_id>/scene.json`

## Required

- `canvas.width = 1920`
- `canvas.height = 1080`
- `layers[]` exists and is non-empty.
- `elements[]` is not present.
- `visual_source` is `master_split_image_layers` for the default production
  path.
- The scene has multiple PNG layers.
- No production animation layer uses `role: full_slide`.
- Each layer has a unique `id`.
- Each layer has `type`, `asset`, `role`, `box`, and `z_index`.
- Each layer `type` is `png`.
- Each PNG file size matches `box.w` and `box.h`.
- Every box is inside the canvas.

## Master-Split Requirements

- `split_report.json` exists.
- `split_report.json` has recomposition metrics.
- There are no `severity=blocking` split warnings.
- Non-background production layers should include `narration_beat_id`,
  `text_summary`, and `narration_cue`.
- Macro layers are large coherent groups, not tiny fragments.

## Forbidden

- SVG assets in production scenes.
- `type: text`, `type: shape`, or `type: line`.
- React/Remotion-drawn PPT body content.
- Subtitle-safe zone content below `y=930` at 1080p.

## Recommended Commands

```powershell
python scripts/validate_layer_recomposition.py `
  --run-dir runs/<run_id> `
  --require-narration-beats

python scripts/validate_run_assets.py `
  --run-dir runs/<run_id> `
  --require-layered `
  --require-master-split-report
```
