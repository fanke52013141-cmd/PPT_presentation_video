# Preflight Checklist

Run this before a production job starts.

## Required Inputs

- `runs/<run_id>/inputs/article.md` exists and is not empty.
- `runs/<run_id>/planning/visual_contract.json` exists before visual prompt generation.
- `runs/<run_id>/reveal_manifest.json` exists after `visual_draft.png` is approved.
- `config/task.yaml` exists.
- `config/style_tokens.yaml` exists.
- `references/style_reference/PPT模板.png` exists.
- `references/style_reference/PPT示例.png` exists.

## Required Schemas

- `schemas/visual_contract.schema.json`
- `schemas/reveal_manifest.schema.json`
- `schemas/scene.schema.json`
- `schemas/animation_timeline.schema.json`
- `schemas/audio_timeline.schema.json`
- `schemas/video_manifest.schema.json`

## Required Scripts

- `scripts/write_visual_prompts.py`
- `scripts/validate_visual_contract.py`
- `scripts/build_reveal_scene.py`
- `scripts/validate_reveal_scene.py`
- `scripts/validate_run_assets.py`
- `scripts/build_remotion_props.py`
- `scripts/minimax_tts.py`
- `scripts/render_remotion.ps1`
- `scripts/remotion`

Fallback/diagnostic only:

- `scripts/split_master_layers.py`
- `scripts/validate_layer_recomposition.py`
- `scripts/decompose_slide_layers.py`
- `scripts/compose_manifest_layers.py`

## Required Production Decisions

- The visual path is `master_reveal_layers`.
- The slide plan is grounded by `visual_contract.json`.
- Every content visual group has `visible_text`, `visual_anchor`, and `narration_function`.
- Every narration beat references a valid `group_id`.
- The master image prompt requires a flat uniform `#FFFDF7` background.
- The master image prompt requires 80-120px spacing between independent visual groups.
- The master image prompt keeps the subtitle safe zone clear above `y=930`.
- The reveal stage will produce `scene.json`, `animation_timeline.json`, and `reveal_report.json`.
- Final QA will inspect `visual_draft.png` and reveal timing, not only JSON.

## Environment

- MiniMax credentials are available if TTS will run.
- Remotion dependencies are installed under `scripts/remotion`.
- FFmpeg/FFprobe are available if media inspection or final muxing is needed.

## Blocking Conditions

- Missing article input.
- Missing style reference images.
- Missing required schema or production script.
- `visual_draft.png` is not from Image Gen.
- Missing or invalid `visual_contract.json`.
- A narration beat references a missing visual group.
- A content visual group is not referenced by any narration beat.
- Master image is crowded, textured, or not reveal-friendly.
- A reveal rectangle enters the subtitle safe zone.
- Missing `reveal_report.json` after building reveal scene.
- Blocking reveal warnings.
- Missing TTS credentials when real audio is required.

## Safety

- Do not log API keys.
- Do not commit `.env`.
- Runtime folders under `runs/` and `outputs/` are not committed.
