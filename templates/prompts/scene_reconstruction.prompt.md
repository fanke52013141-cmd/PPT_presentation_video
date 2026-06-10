# Scene Reconstruction Prompt

Reconstruct the approved `visual_draft.png` into Remotion-ready PNG macro
layers using the master-split path.

## Default Method

Do not ask for code-native text, shapes, arrows, charts, or diagrams.

Create `master_split_manifest.json`, then run:

```powershell
python scripts/split_master_layers.py `
  --manifest runs/<run_id>/master_split_manifest.json `
  --repo-root .
```

The script outputs:

- `assets/full_slide.png`
- `assets/background.png`
- `assets/<macro_layer>.png`
- `scene.json`
- `animation_timeline.json`
- `render_preview.png`
- `split_report.json`

## Manifest Requirements

The manifest must conform to `schemas/master_split_manifest.schema.json`.

Each slide must declare:

- `slide_id`
- `slide_dir`
- `master`
- `narration_beats`
- `layers[]`

Each layer must include:

- `id`
- `role`
- `box`
- `narration_beat_id`
- `text_summary`
- `narration_cue`
- `animation`

## Layering Rules

- Use 5-8 macro layers per slide, not many tiny fragments.
- Keep related text, icons, labels, and arrows together in one macro group.
- Do not split strokes, single icons, or individual words.
- Do not allow independent macro boxes to overlap.
- Keep macro boxes out of the subtitle safe zone. At 1080p, body content should
  stay above `y=930`.
- If two objects touch or overlap in the master image, keep them in the same
  macro group or regenerate the master image with more spacing.

## Animation Binding

Animation timing should follow `narration_beats`.

- Title/subtitle can appear early.
- Main diagram groups appear when their beat starts.
- Summary appears near the end and may highlight.
- Do not reveal all content at frame 0.

Allowed actions:

- `fade_in`
- `fade_up`
- `soft_zoom_in`
- `slide_in_left`
- `highlight`

## Validation

After splitting, run:

```powershell
python scripts/validate_layer_recomposition.py `
  --run-dir runs/<run_id> `
  --require-narration-beats

python scripts/validate_run_assets.py `
  --run-dir runs/<run_id> `
  --require-layered `
  --require-master-split-report
```

If `render_preview.png` looks worse than the master, or
`split_report.json` has blocking warnings, return to the manifest or master
image before rendering video.
