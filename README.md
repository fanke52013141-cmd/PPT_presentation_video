# PPT Visualization

This repository turns long-form educational articles into AI-generated PPT-style
explainer videos.

## Production Path

The default visual pipeline is now **master-split Image Gen layers**:

```text
article.md
-> slide_plan.json with narration_beats
-> visual_prompt.md
-> Image Gen full-slide master image: visual_draft.png
-> master_split_manifest.json
-> scripts/split_master_layers.py
-> same-source PNG macro layers + render_preview.png + split_report.json
-> narration / TTS / subtitles
-> animation_timeline.json bound to narration beats
-> Remotion video
```

The key rule is:

> Generate one coherent master slide first, then split large same-source macro
> layers from that master. Do not build the page by pasting independently
> generated small elements together.

## Why This Changed

Independent Image Gen elements often look bad when recomposed because each
asset can drift in style, scale, handwriting, lighting, and texture. The
master-split path keeps every animated layer from the same approved page, so
the final composition preserves the original visual coherence.

## Required Planning Order

1. Write the slide narration first.
2. Break the narration into `narration_beats`.
3. Map each beat to a visible macro group.
4. Generate a master slide that supports those beats.
5. Keep macro groups visually separated so the master can be split cleanly.
6. Bind animation events to the same beats after TTS timing is known.

Narration is not a later subtitle patch. It determines the page's key visual
points and the animation timeline.

## Master Slide Layout Rules

- Use 1920x1080, 16:9.
- Keep the bottom subtitle-safe area clear. For 1080p, PPT body content should
  stay above `y=930`.
- Use 5-8 large macro groups per slide:
  `title_group`, `subtitle_group`, 2-4 body or diagram groups, and optional
  `summary_group`.
- Keep independent macro groups separated by at least 48-80px of clean
  background.
- Avoid overlapping or near-touching text, arrows, cards, labels, icons, and
  diagram strokes.
- If an arrow, label, or icon is semantically inseparable from nearby text,
  keep them in the same macro group instead of forcing a tiny split.
- Do not use React, SVG, HTML, CSS, Canvas, or Remotion to draw PPT body
  content. Remotion only displays PNG layers, subtitles, and audio.

## Main Commands

Generate visual prompts:

```powershell
python scripts/write_visual_prompts.py `
  --run-dir runs/<run_id> `
  --overwrite
```

After Image Gen creates each `visual_draft.png`, declare the split boxes in:

```text
runs/<run_id>/slides/<slide_id>/master_split_manifest.json
```

Then split the master images:

```powershell
python scripts/split_master_layers.py `
  --manifest runs/<run_id>/master_split_manifest.json `
  --repo-root .
```

Validate recomposition quality:

```powershell
python scripts/validate_layer_recomposition.py `
  --run-dir runs/<run_id> `
  --require-narration-beats
```

Validate render assets:

```powershell
python scripts/validate_run_assets.py `
  --run-dir runs/<run_id> `
  --require-layered `
  --require-master-split-report
```

Build Remotion props:

```powershell
python scripts/build_remotion_props.py `
  --run-dir runs/<run_id> `
  --repo-root .
```

Render video:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/render_remotion.ps1 `
  -RunId <run_id> `
  -Composition ArticleVideo `
  -OutFile runs/<run_id>/video/final.mp4 `
  -PropsFile runs/<run_id>/remotion_props.json
```

## Run Directory

```text
runs/<run_id>/
  inputs/article.md
  planning/slide_plan.json
  master_split_manifest.json
  slides/slide_001/
    visual_prompt.md
    visual_draft.png
    visual_provenance.json
    assets/
      full_slide.png
      background.png
      title_group.png
      subtitle_group.png
      diagram_group.png
      summary_group.png
    scene.json
    animation_timeline.json
    render_preview.png
    split_report.json
    narration.txt
    tts_text.txt
    voice.mp3
    subtitles.srt
    audio_timeline.json
  video/final.mp4
```

## Alternative Paths

- `scripts/compose_manifest_layers.py` remains available for advanced runs
  where Image Gen can produce consistent full-canvas macro layers.
- `scripts/decompose_slide_layers.py` is diagnostic or fallback only. It is not
  the default production path.

## Git Policy

Commit reusable framework files:

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

Do not commit runtime outputs:

```text
runs/**
outputs/**
*.mp4
*.mp3
*.wav
*.srt
.env
```
