# AGENTS.md

## Production Override: Master-Split Image Gen Layers

Effective immediately, the default production path is:

```text
article.md
-> slide_plan.json with narration_beats
-> visual_prompt.md
-> Image Gen full-slide master image: visual_draft.png
-> master_split_manifest.json
-> scripts/split_master_layers.py
-> scene.json + same-source PNG macro layers + render_preview.png + split_report.json
-> narration/TTS/subtitles
-> animation_timeline.json bound to narration beats
-> Remotion video
```

The page must be generated as one coherent Image Gen master image first. Then
Codex splits large macro layers from that same master image. Do not make the
production page by recomposing many independently generated small assets.

## Non-Negotiable Rules

- The PPT body must come from Image Gen bitmap output.
- Remotion may only display PNG layers, play audio, animate PNG layers, and
  overlay subtitles.
- Do not draw PPT body text, shapes, lines, formulas, diagrams, arrows, or
  cards with SVG, HTML, CSS, Canvas, React, or Remotion code.
- `assets/full_slide.png` is a source/audit image, not a production animation
  layer.
- `scripts/decompose_slide_layers.py` is diagnostic/fallback only.
- `scripts/compose_manifest_layers.py` is an advanced external-layer path only.
- Default production uses `scripts/split_master_layers.py`.

## Narration-First Planning

Narration must be planned before visual generation.

For each slide:

1. Convert the article point into a short voiceover paragraph.
2. Split that paragraph into `narration_beats`.
3. Map each beat to one visible macro group.
4. Use those beats to decide page hierarchy and animation order.
5. After TTS creates exact timings, bind animation events to the same beats.

Narration expands the visible page content. It must not introduce unrelated
ideas that the page does not support.

## Master Image Layout Rules

The master slide must be easy to split later:

- Use 1920x1080, 16:9.
- Keep the subtitle safe zone clear. At 1080p, no PPT body layer should extend
  below `y=930`.
- Prefer 5-8 macro groups per slide:
  `title_group`, `subtitle_group`, 2-4 content/diagram groups, and optional
  `summary_group`.
- Keep independent macro groups separated by at least 48-80px of clean
  background.
- Avoid object overlaps and near-contact. Text, icons, arrows, card borders,
  labels, formulas, and diagram strokes should not touch unless they belong to
  the same macro group.
- Keep short arrows inside their related group when possible. Do not run thin
  connector lines across many independent groups.
- Use open middle content space. Do not add a large enclosing content frame.

If a draft has crowded central content, overlapping labels, text on arrows, or
groups that touch each other, return to visual generation before splitting.

## Required Artifacts

Each production run should contain:

```text
runs/<run_id>/
  inputs/article.md
  planning/slide_plan.json
  master_split_manifest.json
  slides/slide_001/
    visual_prompt.md
    visual_draft.png
    visual_provenance.json
    assets/full_slide.png
    assets/background.png
    assets/<macro_layer>.png
    scene.json
    animation_timeline.json
    render_preview.png
    split_report.json
    narration.txt
    tts_text.txt
    voice.mp3
    subtitles.srt
    audio_timeline.json
```

`visual_provenance.json` should record that `visual_draft.png` came from Codex
Image Gen, including the prompt path and copied output path.

## Validation Gates

Before rendering:

```powershell
python scripts/validate_layer_recomposition.py `
  --run-dir runs/<run_id> `
  --require-narration-beats

python scripts/validate_run_assets.py `
  --run-dir runs/<run_id> `
  --require-layered `
  --require-master-split-report
```

The run is blocked if:

- `scene.visual_source` is not a layered source.
- the only visible layer is a full-slide image.
- `split_report.json` is missing.
- split warnings contain `severity=blocking`.
- recomposition metrics are missing or too poor.
- layer boxes overlap or enter the subtitle safe zone.
- macro layers are not linked to narration beats in production review.

## Animation Rules

- Animation timing follows narration beats.
- Title and subtitle may appear early.
- Body and diagram groups appear when the voice reaches their beat.
- Summary enters near the end and may then highlight.
- Do not reveal every body layer at frame 0.
- Do not use `line_draw` or code-native chart animation for PPT body content.

Allowed actions:

```text
fade_in
fade_up
soft_zoom_in
slide_in_left
highlight
```

## Git Rules

Commit reusable framework files only:

```text
AGENTS.md
config/**
references/**
schemas/**
templates/**
checks/**
scripts/**
README.md
bad_cases/**
```

Do not commit runtime products:

```text
runs/**
outputs/**
*.mp4
*.mp3
*.wav
*.srt
.env
```
