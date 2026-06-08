---
name: bind-animation-timeline
description: Bind decomposed PNG scene layers to narration timing and produce animation_timeline.json.
---

# Purpose

## Production Override: Bind To Actual Narration Cues

The animation timeline must be derived from the current slide's actual
`scene.layers[]`, `text_summary`, `narration_cue`, and `audio_timeline.segments`.
Do not use a generic stagger that reveals every content layer in the first two
seconds.

Required behavior:

- `title` and `subtitle` may appear at the beginning.
- `content_body`, `diagram`, and `annotation` layers appear only when the
  narration reaches the matching cue.
- `summary` layers enter near the closing sentence and may then receive a
  `highlight` event.
- Every non-background production layer should have at least one entry event
  unless it is explicitly marked static.
- A `highlight` event is not an entry event. If a layer is highlighted, it still
  needs a prior `fade_in`, `fade_up`, `slide_in_left`, or `soft_zoom_in`.

把单页 `scene.json` 中的 PNG 图层，与 `audio_timeline.json` 中的旁白分句时间对齐，生成 Remotion 执行的 `animation_timeline.json`。

本阶段不重新设计页面，不修改旁白，只决定哪个 PNG 图层在什么时间出现、轻微移动或被强调。

# Inputs

```json
{
  "scene_path": "runs/<run_id>/slides/slide_xxx/scene.json",
  "audio_timeline_path": "runs/<run_id>/slides/slide_xxx/audio_timeline.json",
  "slide_plan_path": "runs/<run_id>/planning/slide_plan.json",
  "slide_id": "slide_xxx",
  "style_tokens_path": "config/style_tokens.yaml"
}
```

# Outputs

```json
{
  "animation_timeline_path": "runs/<run_id>/slides/slide_xxx/animation_timeline.json"
}
```

# Rules

- `animation_timeline.events[].target` 必须存在于 `scene.layers[].id`。
- 生产默认应绑定多个 PNG layer，不再只绑定 `full_slide_layer`。
- 同一 target 可以有多个事件，例如先 `fade_up`，后 `highlight`。
- 允许动作：`fade_in`、`fade_up`、`soft_zoom_in`、`slide_in_left`、`highlight`。
- 不使用 `line_draw` 或 `count_up`，因为 Remotion 不绘制线条或文本。
- 字幕区不是 layer，不能作为 target。

# Recommended Order

1. `background`: 静态显示，不需要事件。
2. `title`: 0.0s 左右淡入。
3. `subtitle`: 0.1-0.3s 淡入。
4. `content_body`: 跟随旁白分句逐个 `fade_up`。
5. `diagram`: 用 `soft_zoom_in` 或 `fade_up`。
6. `annotation`: 用 `slide_in_left` 或 `fade_in`。
7. `summary`: 页面后段出现，并可追加一次 `highlight`。

# Validation

- `duration_sec` 应与 `audio_timeline.duration_sec` 接近。
- 每个事件的 `at` 和 `duration` 必须为非负数字。
- `at + duration` 不应超过页面 `duration_sec`。
- 重要内容层不要早于对应旁白太久出现。
- 同一时间出现的层不要过多，避免画面拥挤。
- 如果 `scene.decomposition.warnings[]` 存在，优先判断是否需要回到 Stage 3 或重新生成视觉稿。

# Failure Handling

- 缺少图层锚点：回到 `reconstruct-scenes`。
- 只有 `full_slide`：不能视为合格的生产动画，应回到 Stage 3 拆层。
- 时间轴超过音频：重新分配事件时间。
- 视觉元素本身重叠导致动画穿帮：回到 `generate-visual-drafts`。

# Bad Case Tags

- `animation-mismatch`
- `missing-layer-target`
- `single-full-slide-animation`
- `line-draw-on-png-model`
