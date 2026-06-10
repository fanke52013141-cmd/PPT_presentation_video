# Master-Split Workflow

## Core Principle

Production visuals should be generated as one coherent Image Gen master slide,
then split into same-source macro PNG layers.

This avoids the common failure mode where independently generated layer images
look inconsistent after recomposition.

## Priority Order

1. **Default:** `master_split_image_layers`
   - Generate `visual_draft.png` as a complete master slide.
   - Declare macro boxes in `master_split_manifest.json`.
   - Run `scripts/split_master_layers.py`.
   - Validate `render_preview.png` and `split_report.json`.

2. **Advanced:** `image_gen_macro_layers_manifest`
   - Use only when Image Gen can reliably produce consistent full-canvas macro
     layers in the same style and coordinate system.
   - Compose with `scripts/compose_manifest_layers.py`.

3. **Diagnostic/Fallback:** algorithmic decomposition
   - Use `scripts/decompose_slide_layers.py` only for audits or explicit
     fallback experiments.
   - Do not treat it as the default production path.

## Narration-Driven Design

The narration defines:

- what the page must show;
- which macro groups exist;
- the visual hierarchy;
- the reveal order;
- animation timing after TTS.

Each production layer should have:

- `narration_beat_id`
- `text_summary`
- `narration_cue`

If a layer cannot be tied to the narration, it is probably decoration or a
planning mistake.

## Split-Friendly Master Images

A good master image is both beautiful and splittable:

- 5-8 macro groups.
- 48-80px clean spacing between independent groups.
- No overlapping labels, arrows, icons, card borders, or formulas.
- No dense center cluster.
- No critical content below `y=930` at 1080p.
- Related small details stay inside one macro group.

## Review Gates

Do not render the final video until:

```powershell
python scripts/validate_layer_recomposition.py `
  --run-dir runs/<run_id> `
  --require-narration-beats

python scripts/validate_run_assets.py `
  --run-dir runs/<run_id> `
  --require-layered `
  --require-master-split-report
```

If recomposition looks worse than the master, fix the manifest or regenerate a
more splittable master image.
