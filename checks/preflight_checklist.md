# Preflight Checklist

Run this before a production job starts.

## Required Inputs

- `runs/<run_id>/inputs/article.md` exists and is not empty.
- `config/task.yaml` exists.
- `config/style_tokens.yaml` exists.
- `references/style_reference/PPT模板.png` exists.
- `references/style_reference/PPT示例.png` exists.

## Required Schemas

- `schemas/slide_plan.schema.json`
- `schemas/master_split_manifest.schema.json`
- `schemas/scene.schema.json`
- `schemas/animation_timeline.schema.json`
- `schemas/audio_timeline.schema.json`
- `schemas/video_manifest.schema.json`

## Required Scripts

- `scripts/write_visual_prompts.py`
- `scripts/split_master_layers.py`
- `scripts/validate_layer_recomposition.py`
- `scripts/validate_run_assets.py`
- `scripts/build_remotion_props.py`
- `scripts/minimax_tts.py`
- `scripts/render_remotion.ps1`
- `scripts/remotion`

`scripts/decompose_slide_layers.py` may exist, but it is diagnostic/fallback
only and is not the default production path.

## Required Production Decisions

- The visual path is `master_split_image_layers`.
- The slide plan contains narration and `narration_beats`.
- The master image prompt requires 48-80px spacing between independent macro
  groups.
- The master image prompt keeps the subtitle safe zone clear.
- The scene reconstruction stage will produce `master_split_manifest.json`.
- Final QA will inspect `render_preview.png`, not only JSON.

## Environment

- MiniMax credentials are available if TTS will run.
- Remotion dependencies are installed under `scripts/remotion`.
- FFmpeg/FFprobe are available if media inspection or final muxing is needed.

## Blocking Conditions

- Missing article input.
- Missing style reference images.
- Missing required schema or production script.
- `visual_draft.png` is not from Image Gen.
- No narration beats.
- Master image is crowded or not splittable.
- Missing `split_report.json` after splitting.
- Blocking split warnings.
- Missing TTS credentials when real audio is required.

## Safety

- Do not log API keys.
- Do not commit `.env`.
- Runtime folders under `runs/` and `outputs/` are not committed.
