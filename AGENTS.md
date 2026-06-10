# AGENTS.md

## Production Override: Visual-Contract Reveal Layers

Effective immediately, the default production path is:

```text
article.md
-> scripts/write_visual_contract.py
-> visual_contract.json with visual_groups and narration_beats
-> scripts/write_visual_prompts.py
-> visual_prompt.md
-> Image Gen full-slide master image: visual_draft.png
-> scripts/write_reveal_manifest_template.py
-> reveal_manifest.json coordinate draft
-> scripts/auto_fit_reveal_boxes.py
-> scripts/draw_reveal_manifest_preview.py
-> manual box review against preview images and visual_draft.png
-> scripts/validate_reveal_manifest.py
-> scripts/build_reveal_scene.py
-> scene.json + full_slide.png + cover/fog/crop reveal layers + reveal_report.json
-> scripts/write_narration_from_visual_contract.py
-> narration.txt + tts_text.txt + narration_beats.json
-> TTS/subtitles/audio_timeline.json
-> scripts/bind_reveal_timeline.py
-> animation_timeline.json bound to audio segments
-> Remotion video
```

The page must be generated as one coherent Image Gen master image first. Do not
alpha-split foreground layers by default. Reveal the approved full-slide image by
using stable rectangular cover, fog, and crop layers.

## Non-Negotiable Rules

- The PPT body must come from Image Gen bitmap output.
- Remotion may display PNG layers, play audio, animate PNG layers, apply reveal
  effects, and overlay subtitles.
- Remotion must not draw PPT body text, shapes, lines, formulas, diagrams,
  arrows, or cards with SVG, HTML, CSS, Canvas, React, or native drawing code.
- `assets/full_slide.png` is the final source image and the visual truth for the
  slide.
- `cover_layer`, `fog_layer`, and `reveal_crop` layers are reveal mechanics only;
  they must not introduce new semantic content.
- `scripts/auto_fit_reveal_boxes.py` is an assistant only; preview review is still required.
- `scripts/split_master_layers.py`, `scripts/decompose_slide_layers.py`, and
  `scripts/compose_manifest_layers.py` are fallback/diagnostic paths only.
- Default production uses `scripts/build_reveal_scene.py`.

## Visual-Contract Planning

The visual contract must exist before visual generation and before final narration.

For each slide:

1. Define 5-8 `visual_groups`.
2. Give each group a `visible_text`, `visual_anchor`, and `narration_function`.
3. Write `narration_beats` that bind each spoken point to a `group_id`.
4. Ensure every spoken point expands a visible group instead of introducing unsupported concepts.
5. Generate the master image from those groups.
6. Generate a draft `reveal_manifest.json` from the visual contract.
7. Auto-fit group boxes against `visual_draft.png` when possible.
8. Inspect `runs/<run_id>/review/*_reveal_manifest_preview.png` and adjust boxes.
9. Generate narration files from the same visual contract.
10. After TTS creates timings, bind reveal events to audio timeline segments.

Narration is an expansion of the visible page. It must not introduce unrelated
ideas that the page does not support.

## Master Image Layout Rules

The master slide must be reveal-friendly:

- Use 1920x1080, 16:9.
- Use a flat uniform `#FFFDF7` background. Do not use paper grain, noise,
  gradients, shadows, or vignette effects.
- Keep the subtitle safe zone clear. At 1080p, no PPT body layer should extend
  below `y=930`.
- Prefer 5-8 visual groups per slide: `title_group`, `subtitle_group`, 2-4
  content/diagram groups, and optional `summary_group`.
- Keep independent groups separated by 80-120px of clean background.
- Each group must contain a short visible Chinese label the narration can cite.
- Avoid object overlaps and near-contact. Text, icons, arrows, card borders,
  labels, formulas, and diagram strokes should not touch unless they belong to
  the same visual group.
- Do not run long connector lines across multiple independent groups.
- Use open middle content space. Do not add a large enclosing content frame.

If a draft has crowded central content, overlapping labels, text on arrows, or
groups that touch each other, return to visual generation before building reveal layers.

## Required Artifacts

Each production run should contain:

```text
runs/<run_id>/
  inputs/article.md
  planning/visual_contract.json
  reveal_manifest.json
  reveal_manifest.auto_fit_report.json
  review/*_reveal_manifest_preview.png
  slides/slide_001/
    visual_prompt.md
    visual_draft.png
    visual_provenance.json
    assets/full_slide.png
    assets/covers/<group_id>_cover.png
    assets/fog/<group_id>_fog.png
    assets/crops/<group_id>.png
    scene.json
    animation_timeline.json
    reveal_report.json
    narration_beats.json
    narration.txt
    tts_text.txt
    voice.mp3
    subtitles.srt
    audio_timeline.json
```

`visual_provenance.json` should record that `visual_draft.png` came from Codex
Image Gen, including the prompt path and copied output path.

## Validation Gates

A preflight helper is available:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_reveal_preflight.ps1 `
  -RunId <run_id> `
  -Overwrite
```

Before visual generation:

```powershell
python scripts/write_visual_contract.py `
  --run-dir runs/<run_id> `
  --overwrite

python scripts/validate_visual_contract.py `
  --contract runs/<run_id>/planning/visual_contract.json

python scripts/write_visual_prompts.py `
  --run-dir runs/<run_id> `
  --overwrite

python scripts/write_reveal_manifest_template.py `
  --run-dir runs/<run_id> `
  --overwrite
```

After `visual_draft.png` exists:

```powershell
python scripts/auto_fit_reveal_boxes.py `
  --manifest runs/<run_id>/reveal_manifest.json `
  --repo-root .

python scripts/draw_reveal_manifest_preview.py `
  --manifest runs/<run_id>/reveal_manifest.json `
  --repo-root . `
  --out-dir runs/<run_id>/review
```

After preview review and box adjustment:

```powershell
python scripts/validate_reveal_manifest.py `
  --manifest runs/<run_id>/reveal_manifest.json `
  --contract runs/<run_id>/planning/visual_contract.json

python scripts/build_reveal_scene.py `
  --manifest runs/<run_id>/reveal_manifest.json `
  --repo-root .

python scripts/validate_reveal_scene.py `
  --run-dir runs/<run_id> `
  --repo-root .
```

Before TTS:

```powershell
python scripts/write_narration_from_visual_contract.py `
  --run-dir runs/<run_id> `
  --overwrite

python scripts/validate_narration_grounding.py `
  --run-dir runs/<run_id>
```

After TTS/subtitles:

```powershell
python scripts/bind_reveal_timeline.py `
  --run-dir runs/<run_id>

python scripts/validate_run_assets.py `
  --run-dir runs/<run_id> `
  --require-layered
```

The run is blocked if:

- `visual_contract.json` has narration beats without valid `group_id`.
- A content visual group is not referenced by any narration beat.
- A reveal group references an unknown contract group or beat.
- A group rectangle enters the subtitle safe zone.
- Group boxes overlap beyond the configured tolerance.
- Auto-fit cannot detect meaningful content inside a group search area.
- `reveal_report.json` contains blocking warnings.
- A reveal event targets a missing scene layer.
- Narration introduces concepts not supported by any visual group.

## Animation Rules

- Animation timing follows narration beats and audio timeline segments.
- Title and subtitle may appear early.
- Body and diagram groups appear when the voice reaches their beat.
- Summary enters near the end and may then highlight.
- Do not reveal every body group at frame 0.
- Do not use `line_draw` or code-native chart animation for PPT body content.

Allowed actions:

```text
cover_fade_out
cover_wipe_left_to_right
cover_wipe_top_to_bottom
fog_diagonal_erase
crop_fade_up
crop_slide_in_left
crop_soft_zoom_in
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
