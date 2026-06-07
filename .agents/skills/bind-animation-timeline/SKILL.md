---
name: bind-animation-timeline
description: Bind PNG scene layers to narration timing and produce animation_timeline.json.
---

# Purpose

把单页 `scene.json` 中的 PNG 图层，与 `audio_timeline.json` 中的旁白分句时间对齐，生成可由 Remotion 执行的 `animation_timeline.json`。

本阶段逐页执行。它不重新设计页面，不修改旁白，只负责确定：哪个 PNG 图层在什么时间出现、强调或轻微移动。

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

# Input Meaning

- `scene_path`: Stage 3 输出的 PNG 图层页面结构，包含 `layers[].id`、`role`、`box`、`z_index` 和可选 `animation_role`。
- `audio_timeline_path`: Stage 5 输出的当前页音频和字幕时间轴，包含 `duration_sec` 和 `segments[]`。
- `slide_plan_path`: Stage 1 输出的整套 slide 内容结构，用于读取当前页 `core_message`、`content.content_type`、`content.items[]` 和 `narration`。
- `slide_id`: 当前处理的 slide。
- `style_tokens_path`: 固定动画规则和允许的动画类型。

# Outputs

```json
{
  "animation_timeline_path": "runs/<run_id>/slides/slide_xxx/animation_timeline.json"
}
```

# Output Structure

`animation_timeline.json` 推荐结构：

```json
{
  "slide_id": "slide_001",
  "duration_sec": 18.6,
  "events": [
    {
      "id": "anim_001",
      "target": "title_layer",
      "action": "fade_up",
      "at": 0.1,
      "duration": 0.5
    },
    {
      "id": "anim_002",
      "target": "content_body_layer",
      "action": "fade_up",
      "at": 2.0,
      "duration": 0.5,
      "linked_segment_id": "slide_001_seg_001"
    }
  ]
}
```

每个动画事件字段：

- `id`: 动画事件 ID。
- `target`: 目标 PNG 图层 ID，必须存在于 `scene.layers[].id`。
- `action`: 动画动作，必须属于允许动作集合。
- `at`: 动画开始时间，单位秒。
- `duration`: 动画持续时间，单位秒。
- `linked_segment_id`: 可选，绑定到 `audio_timeline.segments[].id`。

# Allowed Actions

默认只使用轻量解释型动画：

- `fade_in`: 背景、内容主体、辅助元素淡入。
- `fade_up`: 标题、正文图层、卡片图层、总结条图层轻微上浮出现。
- `soft_zoom_in`: 图解或核心视觉图层轻微放大出现。
- `slide_in_left`: 少量用于流程开始图层，默认少用。
- `highlight`: 重点标注图层强调。

不再使用 `line_draw` 作为主动画，因为 Remotion 不绘制线条，只显示 PNG 图层。箭头、下划线、圈注如果要动画，必须先拆成 PNG 图层，再用 `fade_in` 或 `highlight`。

禁止使用旋转、弹跳、快速飞入、大幅缩放等强装饰动画。

# Procedure

1. 读取 `scene.json`。
2. 读取 `audio_timeline.json`，获取 `duration_sec` 和 `segments[]`。
3. 读取 `slide_plan.json`，定位当前 `slide_id`，理解本页 `core_message`、`content_type` 和 `content.items[]`。
4. 读取 `style_tokens.yaml` 中允许的动画动作。
5. 为标题区 PNG 图层分配轻量开场动画：`role: title`、`role: subtitle`。
6. 为 `background` 或 `full_slide` 图层分配静态显示或极轻淡入。
7. 将 `content_body`、`diagram`、`annotation`、`summary` 等主要 PNG 图层绑定到相近的 `audio_timeline.segments[]`。
8. 每个主要 `content.items[]` 尽量有一个对应的 PNG 图层出现或强调动画。
9. 输出 `animation_timeline.json`。
10. 校验所有 `target` 是否存在于 `scene.layers[].id`，所有 `at + duration` 是否不超过 `duration_sec`。

# Timing Rules

- 背景或整页底图可以从 0 秒开始显示。
- 标题和副标题可以较早出现。
- 主体内容、图解、重点标注和总结图层应跟随旁白，不要提前太多。
- 重要图层不要在旁白提到前 1 秒以上出现，除非它是背景或页面结构。
- 同一时间出现的图层不要过多，避免画面拥挤。
- 每个动画 duration 通常控制在 `0.3` 到 `0.8` 秒。
- 页面最后 `0.5` 秒尽量不安排新动画，避免收尾仓促。
- 字幕区不参与动画，不作为 target。

# Fallback Strategy

如果只有 `full_slide` 图层，降级为：

1. `full_slide` 从 0 秒开始显示。
2. 可选做一次极轻 `soft_zoom_in` 或 `fade_in`。
3. 不做内部元素级动画。

如果有多层 PNG，推荐顺序：

1. `background`
2. `title`
3. `subtitle`
4. `content_body`
5. `diagram`
6. `annotation`
7. `summary`

# Validation

- `target` 必须存在于 `scene.layers[].id`。
- `action` 必须属于允许动作集合。
- `at` 和 `duration` 必须为非负数字。
- `at + duration` 不能超出页面真实 `duration_sec`。
- `linked_segment_id` 如果存在，必须存在于 `audio_timeline.segments[].id`。
- 重要图层不能在旁白提到之前太早出现。
- 动画数量适中，不因装饰影响理解。
- 如果存在 `title` 和 `subtitle` 图层，应作为两个独立 target 处理。

# Failure Handling

- 缺少图层锚点时，回到 `reconstruct-scenes` 增加 PNG 图层。
- 时间轴不稳定时，先简化为背景、标题、主体、总结四段动画。
- 如果事件 target 不存在，修正 target 或回到 Stage 3。
- 如果动画时间超出音频时长，重新分配事件时间。

# Bad Case Tags

- `data-break`
- `animation-mismatch`
- `missing-layer-target`
- `line-draw-on-png-model`
