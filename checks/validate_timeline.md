# Timeline 检查

检查对象：

- `audio_timeline.json`
- `animation_timeline.json`
- `scene.json`

检查项：

- `audio_timeline.segments[]` 时间必须递增。
- `audio_timeline.duration_sec` 必须大于 0。
- `animation_timeline.duration_sec` 应与 `audio_timeline.duration_sec` 一致或接近。
- `animation_timeline.events[].target` 必须存在于 `scene.layers[].id`。
- `animation_timeline.events[].action` 必须属于允许动作集合：`fade_in`、`fade_up`、`soft_zoom_in`、`slide_in_left`、`highlight`。
- `animation_timeline.events[].at` 和 `duration` 必须为非负数字。
- 动画事件不能超出 slide 真实音频时长。
- 如果存在 `linked_segment_id`，它必须存在于 `audio_timeline.segments[].id`。
- 重要 PNG 图层要在旁白提到附近出现，不能提前太多。
- 同一时间出现的图层不能过多。
- 如果存在 `title` 和 `subtitle` 图层，必须作为两个独立 target 处理。
- 字幕区不属于 `scene.layers[]`，不得成为动画 target。
- 如果精确绑定困难，允许降级为背景、标题、主体、总结四段式动画，但仍需通过 target 和时间校验。
