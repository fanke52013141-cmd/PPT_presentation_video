# Macro Layer Timeline Checks

- Important body, diagram, annotation, and summary layers should not all appear
  in the first two seconds.
- Each non-background production layer should have an entry event unless it is
  explicitly static.
- `highlight` alone is not an entry event. A highlighted layer needs an earlier
  reveal event.
- If `scene.layers[]` contains `narration_cue`, check that the corresponding
  animation event starts near the matching `audio_timeline.segments[]` text.
- `summary` should enter near the closing narration, then optionally highlight.

# Timeline 检查

检查对象：

- `audio_timeline.json`
- `animation_timeline.json`
- `scene.json`

## 检查项

- `audio_timeline.segments[]` 时间必须递增。
- `audio_timeline.duration_sec` 必须大于 0。
- `animation_timeline.duration_sec` 应与 `audio_timeline.duration_sec` 一致或接近。
- `animation_timeline.events[].target` 必须存在于 `scene.layers[].id`。
- `animation_timeline.events[].action` 必须属于允许动作集合：`fade_in`、`fade_up`、`soft_zoom_in`、`slide_in_left`、`highlight`。
- `animation_timeline.events[].at` 和 `duration` 必须为非负数字。
- 动画事件不能超出 slide 真实音频时长。
- 同一个 target 可以有多个事件，例如先出现、后高亮。
- 如果存在 `linked_segment_id`，它必须存在于 `audio_timeline.segments[].id`。
- 重要 PNG 图层要在旁白提到附近出现，不能提前太多。
- 同一时间出现的图层不能过多。
- 如果存在 `title` 和 `subtitle` 图层，必须作为两个独立 target 处理。
- 字幕区不属于 `scene.layers[]`，不得成为动画 target。
- 生产动画不能只绑定 `full_slide_layer`；如果只有整页图层，应回到 Stage 3 拆层。

## 推荐命令

```powershell
python scripts/validate_run_assets.py `
  --run-dir runs/<run_id> `
  --require-layered
```
