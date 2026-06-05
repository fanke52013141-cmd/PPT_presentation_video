---
name: plan-slides
description: Convert an article brief into a 3-6 minute slide-by-slide video plan.
---

# Purpose

把文章解析结果转成可审核的 PPT 分镜脚本。该阶段回答“讲什么、每页怎么讲、每页需要什么画面”。

# Inputs

```json
{
  "article_brief_path": "runs/<run_id>/planning/article_brief.json",
  "task_config_path": "config/task.yaml",
  "narration_rules_path": "references/narration_rules.md"
}
```

# Outputs

```json
{
  "video_outline_path": "runs/<run_id>/planning/video_outline.json",
  "slide_plan_path": "runs/<run_id>/planning/slide_plan.json",
  "slide_specs_dir": "runs/<run_id>/slides/slide_xxx/slide_spec.json",
  "narration_files": "runs/<run_id>/slides/slide_xxx/narration.txt"
}
```

每个 `slide_spec.json` 必须包含：

- `slide_id`
- `role`
- `duration_sec`
- `main_title`
- `subtitle`
- `core_message`
- `screen_content[]`
- `narration`
- `visual_requirement`
- `animation_intent`
- `source_key_points[]`

# Procedure

1. 根据 3 到 6 分钟目标时长，规划 8 到 14 页。
2. 采用 AI 科普叙事结构：开场问题、概念解释、机制拆解、案例、误区、总结。
3. 每页只放一个核心观点。
4. 把旁白拆成短句，避免长句和术语堆叠。
5. 为每页写清楚配图要求和动画意图。
6. 对公考解析、案例拆解等多层级内容，优先把“审题/关键词/身份/步骤/总结”拆成独立页，避免 6 页以内导致最终时长低于 180 秒。
7. 输出总 `slide_plan.json`，并拆出每页 `slide_spec.json` 和 `narration.txt`。

# Validation

- 总时长在 180 到 360 秒之间。
- 每页有明确 `core_message`。
- 每页旁白建议 90 到 180 个中文字符。
- 不允许只有标题没有画面要求。

# Failure Handling

- 如果内容过多，合并相近观点或建议增加分集。
- 如果内容过少或最终 TTS 时长低于 180 秒，增加类比、案例、误区澄清页，或把已有层级拆成独立页。
- 如果旁白和屏幕内容不匹配，优先修改旁白结构。

# Bad Case Tags

- `output-unclear`
- `data-break`
- `scope-creep`

