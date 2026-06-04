---
name: bind-animation-timeline
description: Bind scene elements to narration timing and produce animation_timeline.json.
---

# Purpose

把元素出现、强调、移动、消失的时间点与旁白分句对齐，形成可由 Remotion 执行的动画时间轴。

# Inputs

```json
{
  "scene_path": "runs/<run_id>/slides/slide_xxx/scene.json",
  "audio_timeline_path": "runs/<run_id>/slides/slide_xxx/audio_timeline.json",
  "slide_spec_path": "runs/<run_id>/slides/slide_xxx/slide_spec.json",
  "style_tokens_path": "config/style_tokens.yaml"
}
```

# Outputs

```json
{
  "animation_timeline_path": "runs/<run_id>/slides/slide_xxx/animation_timeline.json"
}
```

# Procedure

1. 读取 `audio_timeline.segments[]`。
2. 为标题、核心图形、步骤、结论等元素分配出现时间。
3. 每个动画事件必须包含 `at`、`target`、`action`、`duration`。
4. 优先使用 `style_tokens.yaml` 中允许的动画。
5. 保证视觉重点和旁白当前内容一致。

# Validation

- `target` 必须存在于 `scene.elements[].id`。
- 动画时间不能超出页面总时长。
- 重要元素不能在旁白提到之前太早出现。
- 动画数量适中，不因装饰影响理解。

# Failure Handling

- 缺少元素锚点时，回到 `reconstruct-scenes` 增加元素。
- 时间轴不稳定时，先简化为标题、主体、结论三段动画。

# Bad Case Tags

- `data-break`
- `animation-mismatch`
- `validation-weak`

