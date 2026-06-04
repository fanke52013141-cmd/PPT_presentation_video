# Timeline 检查

检查对象：

- `audio_timeline.json`
- `animation_timeline.json`
- `scene.json`

检查项：

- `audio_timeline.segments[]` 时间递增。
- `animation_timeline.events[].target` 必须存在于 `scene.elements[].id`。
- 动画事件不能超出 slide 时长。
- 重要画面元素要在旁白提到附近出现。
- 同一时间出现的元素不能过多。

