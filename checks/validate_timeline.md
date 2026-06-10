# Timeline Checks

Targets:

- `audio_timeline.json`
- `animation_timeline.json`
- `scene.json`

## Required

- `audio_timeline.segments[]` times increase.
- `audio_timeline.duration_sec` is positive.
- `animation_timeline.duration_sec` is positive and is not shorter than audio.
- `animation_timeline.events[].target` exists in `scene.layers[].id`.
- `animation_timeline.events[].action` is one of:
  - `fade_in`
  - `fade_up`
  - `soft_zoom_in`
  - `slide_in_left`
  - `highlight`
- `animation_timeline.events[].at` and `duration` are non-negative numbers.
- Events do not exceed the slide duration.

## Narration Binding

- Important body, diagram, annotation, and summary layers should appear near the
  narration beat that introduces them.
- `narration_beat_id` should match between scene layers and animation events.
- `linked_segment_id`, when present, must exist in `audio_timeline.segments[]`.
- All important body layers should not appear in the first two seconds.
- Summary should enter near the closing narration and may then highlight.
- `highlight` alone is not an entry animation; a highlighted layer needs an
  earlier reveal event.

## Forbidden

- Animating only a `full_slide_layer`.
- Making subtitle text a scene layer.
- Using code-native `line_draw` or chart drawing for PPT body content.

## Recommended Command

```powershell
python scripts/validate_run_assets.py `
  --run-dir runs/<run_id> `
  --require-layered `
  --require-master-split-report
```
