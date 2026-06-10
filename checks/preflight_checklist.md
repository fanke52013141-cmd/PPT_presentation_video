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

- `scripts/write_visual_contract.py`
- `scripts/write_visual_prompts.py`
- `scripts/validate_visual_contract.py`
- `scripts/build_reveal_scene.py`
- `scripts/validate_reveal_scene.py`
- `scripts/write_narration_from_visual_contract.py`
- `scripts/validate_narration_grounding.py`
- `scripts/bind_reveal_timeline.py`
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
- `narration.txt` and `tts_text.txt` are generated from the visual contract, not written independently.
- `animation_timeline.json` is rebound from `audio_timeline.json` after TTS.
- The master image prompt requires a flat uniform `#FFFDF7` background.
- The master image prompt requires 80-120px spacing between independent visual groups.
- The master image prompt keeps the subtitle safe zone clear above `y=930`.
- The reveal stage will produce `scene.json`, `animation_timeline.json`, and `reveal_report.json`.
- Final QA will inspect `visual_draft.png`, narration grounding, and reveal timing, not only JSON.

## Canonical Command Order

```powershell
python scripts/write_visual_contract.py `
  --run-dir runs/<run_id> `
  --overwrite

python scripts/validate_visual_contract.py `
  --contract runs/<run_id>/planning/visual_contract.json

python scripts/write_visual_prompts.py `
  --run-dir runs/<run_id> `
  --overwrite

# After Image Gen output and manual reveal_manifest.json annotation:
python scripts/build_reveal_scene.py `
  --manifest runs/<run_id>/reveal_manifest.json `
  --repo-root .

python scripts/validate_reveal_scene.py `
  --run-dir runs/<run_id> `
  --repo-root .

python scripts/write_narration_from_visual_contract.py `
  --run-dir runs/<run_id> `
  --overwrite

python scripts/validate_narration_grounding.py `
  --run-dir runs/<run_id>

# After TTS creates audio_timeline.json:
python scripts/bind_reveal_timeline.py `
  --run-dir runs/<run_id>

python scripts/validate_run_assets.py `
  --run-dir runs/<run_id> `
  --require-layered
```

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
- `narration_beats.json` is missing after narration generation.
- Narration is not grounded in the visual contract.
- Master image is crowded, textured, or not reveal-friendly.
- A reveal rectangle enters the subtitle safe zone.
- Missing `reveal_report.json` after building reveal scene.
- Blocking reveal warnings.
- Animation events are not bound to valid audio segments after TTS.
- Missing TTS credentials when real audio is required.

## Safety

- Do not log API keys.
- Do not commit `.env`.
- Runtime folders under `runs/` and `outputs/` are not committed.
