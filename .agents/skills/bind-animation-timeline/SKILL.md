---
name: bind-animation-timeline
description: Bind scene elements to narration timing and produce animation_timeline.json.
---

# Purpose

把单页 `scene.json` 中的页面元素，与 `audio_timeline.json` 中的旁白分句时间对齐，生成可由 Remotion 执行的 `animation_timeline.json`。

本阶段逐页执行。它不重新设计页面，不修改旁白，只负责确定：哪个元素在什么时间出现、强调、绘制或轻微移动。

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

- `scene_path`: Stage 3 输出的结构化页面元素，包含元素 `id`、`semantic_role`、`box`、`z_index` 和可选 `animation_role`。
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
      "target": "main_title",
      "action": "fade_up",
      "at": 0.1,
      "duration": 0.5
    },
    {
      "id": "anim_002",
      "target": "content_text_001",
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
- `target`: 目标元素 ID，必须存在于 `scene.elements[].id`。
- `action`: 动画动作，必须属于允许动作集合。
- `at`: 动画开始时间，单位秒。
- `duration`: 动画持续时间，单位秒。
- `linked_segment_id`: 可选，绑定到 `audio_timeline.segments[].id`。

# Allowed Actions

默认只使用轻量解释型动画：

- `fade_in`: 内容框、图标、辅助元素淡入。
- `fade_up`: 标题、正文、卡片、总结条轻微上浮出现。
- `soft_zoom_in`: 复杂插图或核心图解轻微放大出现。
- `slide_in_left`: 少量用于流程开始元素，默认少用。
- `line_draw`: 箭头、下划线、圈注、连接线绘制。
- `highlight`: 关键词或重点区域强调。
- `count_up`: 仅用于明确数字变化，不默认使用。

禁止使用旋转、弹跳、快速飞入、大幅缩放等强装饰动画。

# Procedure

1. 读取 `scene.json`。
2. 读取 `audio_timeline.json`，获取 `duration_sec` 和 `segments[]`。
3. 读取 `slide_plan.json`，定位当前 `slide_id`，理解本页 `core_message`、`content_type` 和 `content.items[]`。
4. 读取 `style_tokens.yaml` 中允许的动画动作。
5. 为标题区元素分配轻量开场动画：`brand_marker`、`main_title`、`subtitle`、`subtitle_underline`。
6. 为 `content_frame` 分配稳定淡入，不抢占旁白重点。
7. 将正文、卡片、流程步骤、Token 小块、图解、总结条等主要内容元素绑定到相近的 `audio_timeline.segments[]`。
8. 将 `keyword_underline`、`keyword_circle`、`content_arrow` 等强调元素设置为 `line_draw` 或 `highlight`，并贴近旁白提到该重点的时间。
9. 每个主要 `content.items[]` 至少应有一个对应的出现或强调动画。
10. 输出 `animation_timeline.json`。
11. 校验所有 `target` 是否存在于 `scene.elements[].id`，所有 `at + duration` 是否不超过 `duration_sec`。

# Timing Rules

- 标题和内容框可以较早出现。
- 正文、步骤、卡片、图解和重点标注应跟随旁白，不要提前太多。
- 重要元素不要在旁白提到前 1 秒以上出现，除非它是背景框或页面结构。
- 同一时间出现的元素不要过多，避免画面拥挤。
- 每个动画 duration 通常控制在 `0.3` 到 `0.8` 秒。
- 页面最后 `0.5` 秒尽量不安排新动画，避免收尾仓促。
- 字幕区不参与动画，不作为 target。

# Default Ordering

推荐顺序：

1. `brand_marker`
2. `main_title`
3. `subtitle`
4. `subtitle_underline`
5. `content_frame`
6. 当前旁白对应的内容主体
7. 关键词下划线、圈注或箭头
8. 图解补充
9. `summary_bar` 或总结元素

# Fallback Strategy

如果元素与旁白难以精确绑定，降级为三段式动画：

1. 标题区和内容框出现。
2. 主体内容按 `content_index` 顺序出现。
3. 总结条、重点标注和结论出现。

降级后仍必须保证 `target` 合法、时间不越界、动画不拥挤。

# Validation

- `target` 必须存在于 `scene.elements[].id`。
- `action` 必须属于允许动作集合。
- `at` 和 `duration` 必须为非负数字。
- `at + duration` 不能超出页面真实 `duration_sec`。
- `linked_segment_id` 如果存在，必须存在于 `audio_timeline.segments[].id`。
- 重要元素不能在旁白提到之前太早出现。
- 动画数量适中，不因装饰影响理解。
- `main_title` 和 `subtitle` 必须作为两个独立 target 处理。

# Failure Handling

- 缺少元素锚点时，回到 `reconstruct-scenes` 增加元素。
- 时间轴不稳定时，先简化为标题、主体、结论三段动画。
- 如果事件 target 不存在，修正 target 或回到 Stage 3。
- 如果动画时间超出音频时长，重新分配事件时间。

# Bad Case Tags

- `data-break`
- `animation-mismatch`
- `validation-weak`
- `target-missing`
- `animation-overcrowded`
- `animation-out-of-range`
