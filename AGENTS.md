# AGENTS.md

## Production Pipeline

The application has six user-visible steps:

1. Import article.
2. Plan storyboard.
3. Generate or upload one complete 1920×1080 image per slide.
4. Paint optional manual Masks.
5. Edit narration, generate audio, and confirm audio.
6. Render and manage videos.

The production visual path is:

```text
article.md
-> visual_contract.json
-> visual_prompt.md
-> visual_draft.png
-> optional manual brush Masks in reveal_manifest.json
-> scripts/build_reveal_scene.py
-> scripts/bind_reveal_timeline.py
-> scripts/build_remotion_props.py
-> Remotion MP4
```

## Manual Mask Contract

`scripts/build_reveal_scene.py` is the only production reveal builder.

- Pipeline version: `manual_mask_exact_v2`.
- A slide without a painted Mask is a static full-slide image.
- A slide with painted Masks starts from the fixed canvas background.
- A reveal layer contains only source-image pixels inside that group's saved
  brush Mask.
- The source image must never be reused as the background of a masked slide.
- Do not run box expansion, connected-component growth, nearest-owner
  assignment, foreground segmentation, or cross-group erasing in production.
- Rebuild slide assets and Remotion runtime assets before every render.
- Validate the pipeline version before rendering.

The following scripts are legacy diagnostics only and must not be called by the
web production path:

- `scripts/auto_fit_reveal_boxes.py`
- `scripts/split_master_layers.py`
- `scripts/decompose_slide_layers.py`
- `scripts/compose_manifest_layers.py`
- `scripts/prepare_full_slide_scenes.py`

## Image Rules

- The PPT body comes from an approved bitmap image.
- Use 1920×1080, 16:9.
- Use a flat `#FFFDF7` background.
- Keep independent visual groups separated.
- Keep important body content above the subtitle area.
- Remotion may display PNGs, animate reveal PNGs, play audio, and draw
  subtitles. It must not redraw PPT body content with HTML, SVG, Canvas, or
  React shapes.

## State and File Lifecycle

- Replacing or deleting a slide image clears that slide's Masks, reveal assets,
  Remotion props, audio confirmation, and downstream completion state.
- Editing narration clears audio confirmation.
- Rendering is blocked until all slide audio has been generated and confirmed.
- Rendered videos carry a `.render.json` sidecar with the reveal pipeline
  version.
- Deleting a rendered video deletes both the MP4 and its sidecar.
- Runtime data under `runs/`, `outputs/`, `logs/`, and Remotion `public/runtime`
  is never committed.

## Required Validation

Run before publishing:

```powershell
python -m compileall -q server.py scripts checks
node --check static/app.js
node --check static/flow.js
node checks/test_visible_flow.js
python checks/test_reveal_mask_integrity.py
python checks/test_reveal_pipeline_isolation.py
python checks/test_slide_visual_invalidation.py
python checks/test_audio_confirmation.py
python checks/test_audio_tail_padding.py
Push-Location scripts/remotion
npm install
npx tsc --noEmit -p tsconfig.json
Pop-Location
```

For a populated run:

```powershell
python scripts/validate_reveal_scene.py --run-dir runs/<run_id> --repo-root .
python scripts/validate_run_assets.py --run-dir runs/<run_id> --repo-root . --require-layered
```

Also verify the six visible steps in the local browser, including the exact
Mask preview and a rendered MP4.

## Git Rules

Commit reusable application and framework files:

```text
server.py
database.py
config_store.py
static/**
scripts/**
checks/**
config/**
references/**
schemas/**
templates/**
README.md
AGENTS.md
.gitignore
.env.example
```

Do not commit:

```text
runs/**
outputs/**
logs/**
data/**
scripts/remotion/public/runtime/**
*.mp4
*.mp3
*.wav
*.srt
.env
API keys or other credentials
```
