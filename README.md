# PPT Visualization

This repository turns long-form educational articles into AI-generated PPT-style
explainer videos.

## Production Path

The default visual pipeline is now **visual-contract-driven full-slide reveal layers**:

```text
article.md
-> visual_contract.json with visual_groups and narration_beats
-> visual_prompt.md
-> Image Gen full-slide master image: visual_draft.png
-> reveal_manifest.json
-> scripts/build_reveal_scene.py
-> full_slide.png + cover/fog/crop reveal layers + reveal_report.json
-> narration / TTS / subtitles
-> animation_timeline.json bound to visual groups and narration beats
-> Remotion video
```

The key rule is:

> Generate one coherent final slide first. Do not split foreground alpha layers by
> default. Reveal the approved full-slide image with stable cover, fog, and
> rectangular crop layers whose group ids are grounded in the visual contract.

## Why This Changed

Image segmentation and alpha splitting are unstable for hand-drawn PPT-style
slides. Text strokes, arrows, icons, and background texture can merge or split in
unexpected ways. The reveal-layer path keeps the final page as one Image Gen
bitmap and uses simple rectangular reveal assets, so the final frame stays
visually identical to the approved master slide.

The second change is planning: narration is now grounded in the visual contract.
The voiceover expands visible groups; it must not introduce unsupported concepts
that the page does not show.

## Required Planning Order

1. Write `visual_contract.json` first.
2. Define 5-8 `visual_groups` for each slide.
3. Give every group a `visible_text`, `visual_anchor`, and `narration_function`.
4. Write `narration_beats` that bind each spoken point to a `group_id`.
5. Generate a full-slide master image that follows those groups.
6. Mark each group's rectangle in `reveal_manifest.json`.
7. Build reveal layers and bind animation events to narration beats after TTS timing is known.

## Master Slide Layout Rules

- Use 1920x1080, 16:9.
- Use a flat uniform `#FFFDF7` background. Avoid paper grain, noise, shadows,
  gradients, and vignette effects.
- Keep the bottom subtitle-safe area clear. For 1080p, PPT body content should
  stay above `y=930`.
- Use 5-8 large visual groups per slide: `title_group`, `subtitle_group`, 2-4
  body or diagram groups, and optional `summary_group`.
- Keep independent visual groups separated by 80-120px of clean background.
- Each group must contain a short visible Chinese label that narration can reference.
- Avoid cross-group connector lines. If an arrow, label, or icon is semantically
  inseparable from nearby text, keep them in the same group.
- Do not use React, SVG, HTML, CSS, Canvas, or Remotion to draw PPT body
  content. Remotion only displays PNG layers, reveal effects, subtitles, and audio.

## Main Commands

Validate the visual contract:

```powershell
python scripts/validate_visual_contract.py `
  --contract runs/<run_id>/planning/visual_contract.json
```

Generate visual prompts:

```powershell
python scripts/write_visual_prompts.py `
  --run-dir runs/<run_id> `
  --overwrite
```

After Image Gen creates each `visual_draft.png`, declare reveal rectangles in:

```text
runs/<run_id>/reveal_manifest.json
```

Then build reveal scene assets:

```powershell
python scripts/build_reveal_scene.py `
  --manifest runs/<run_id>/reveal_manifest.json `
  --repo-root .
```

Validate reveal scene assets:

```powershell
python scripts/validate_reveal_scene.py `
  --run-dir runs/<run_id> `
  --repo-root .
```

Validate complete render assets after TTS/subtitles exist:

```powershell
python scripts/validate_run_assets.py `
  --run-dir runs/<run_id> `
  --require-layered
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
  planning/visual_contract.json
  reveal_manifest.json
  slides/slide_001/
    visual_prompt.md
    visual_draft.png
    visual_provenance.json
    assets/
      full_slide.png
      covers/<group_id>_cover.png
      fog/<group_id>_fog.png
      crops/<group_id>.png
    scene.json
    animation_timeline.json
    reveal_report.json
    narration.txt
    tts_text.txt
    voice.mp3
    subtitles.srt
    audio_timeline.json
  video/final.mp4
```

## Alternative Paths

- `scripts/split_master_layers.py` remains available for fallback or diagnostics,
  but it is not the default production path.
- `scripts/compose_manifest_layers.py` remains available for advanced runs where
  Image Gen can produce consistent full-canvas macro layers.
- `scripts/decompose_slide_layers.py` is diagnostic only.

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
