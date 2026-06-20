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

- Pipeline version: `manual_mask_outer_white_v3`.
- A slide without a painted Mask is a static full-slide image.
- A slide with painted Masks starts from the user-configured video background.
- Generated images must use a pure-white outer background.
- Only near-white pixels connected to the outer image edge are removed.
- White areas enclosed by content are preserved.
- A reveal layer contains source-image content inside that group's saved brush
  Mask. If no eraser was used, fully enclosed holes in the painted Mask are
  filled; explicit eraser results are preserved.
- The source image must never be reused as the background of a masked slide.
- Do not run box expansion, foreground erosion/dilation, nearest-owner
  assignment, semantic segmentation, or cross-group erasing in production.
- Rebuild slide assets and Remotion runtime assets before every render.
- Validate the pipeline version before rendering.

## Image Rules

- The PPT body comes from an approved bitmap image.
- Use 1920×1080, 16:9.
- Generate a pure-white (`#FFFFFF`) outer background.
- The final video canvas color is configurable; the default is `#FEFDF9`.
- Keep independent visual groups separated.
- Keep important body content above the subtitle area.
- Remotion may display PNGs, animate reveal PNGs, play audio, and draw
  transparent-background subtitles. It must not redraw PPT body content with
  HTML, SVG, Canvas, or React shapes.

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
npx tsc --noEmit -p scripts/remotion/tsconfig.json
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
