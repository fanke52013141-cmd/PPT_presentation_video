# AGENTS.md

## Production Pipeline

The application has six user-visible steps:

1. Import article.
2. Plan storyboard.
3. Generate or upload one complete 1920×1080 image per slide.
4. Paint optional manual Masks.
5. Edit narration, generate audio, and confirm audio.
6. Render and manage videos.

### User-visible steps vs internal step numbers

The UI is intentionally compressed to six user-visible steps, while the backend and historical validation scripts still use internal Step numbers.

| User-visible step | Internal API / artifact stage | Main artifacts |
| --- | --- | --- |
| Step 1 Import article | Step 1 import | `inputs/article.md`, `planning/article_brief.json` |
| Step 2 Plan storyboard | Step 2 storyboard / visual contract | `planning/visual_contract.json` |
| Step 3 Images | Step 3 images + Step 4 confirmation | `slides/<slide_id>/visual_draft.png`, `reveal_manifest.json` |
| Step 4 Mask | Step 5 reveal manifest / mask assets | `reveal_manifest.json`, reveal layer assets |
| Step 5 Narration and audio | Step 6 narration + Step 7 TTS/audio confirmation | `planning/narration_beats.json`, audio, subtitles, timelines |
| Step 6 Render video | Step 8 Remotion render | `remotion_props.json`, rendered video, `.render.json` sidecar |

When writing user-facing documentation, prefer the six visible steps. When changing API routes, validators, or runtime artifacts, use the internal step numbers and keep this mapping accurate.

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

- Pipeline version: `manual_mask_boundary_white_v4`.
- A slide without a painted Mask is a static full-slide image.
- A slide with painted Masks starts from the user-configured video background.
- Generated images must use a pure-white outer background.
- Each painted Mask is a processing boundary; only near-white pixels connected
  inward from that boundary are removed.
- White areas enclosed by content are preserved.
- A reveal layer retains non-white source content inside that group's saved
  brush Mask, with soft antialias alpha and white-edge decontamination.
- The source image must never be reused as the background of a masked slide.
- Do not run box expansion, foreground erosion/dilation, nearest-owner
  assignment, semantic segmentation, or cross-group erasing in production.
- Rebuild slide assets and Remotion runtime assets before every render.
- Validate the pipeline version and reject unreferenced legacy assets before rendering.

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

## Runtime Bridge Policy

The repository still contains runtime bridge modules that patch production behavior during Python startup:

- `sitecustomize.py`
- `usercustomize.py`
- `runtime_security.py`
- `runtime_settings_mask.py`

Treat them as migration debt, not as the normal extension mechanism. New fixes should land in `server.py`, `static/**`, or normal application startup code unless a large-file patch is not safe. Any new runtime bridge behavior must also be added to `docs/runtime_hotfixes_and_security.md` and issue #7.

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

Merged temporary branches with `ahead_by=0` relative to `main` should be deleted after confirming no follow-up work depends on them.
