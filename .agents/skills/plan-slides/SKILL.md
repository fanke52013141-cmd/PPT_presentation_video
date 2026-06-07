---
name: plan-slides
description: Convert an input article directly into a structured PPT video slide plan.
---

# Purpose

把输入文章直接拆分成 AI 科普 PPT 视频结构。该阶段回答：整篇文章应该拆成哪些 slide、每页讲什么、内容用什么结构表达、每页演讲稿怎么说。

本阶段不再输出 `article_brief.json`，也不再把文章摘要和分镜拆成两个环节。主输出就是 `slide_plan.json`。

# Inputs

```json
{
  "article_path": "runs/<run_id>/inputs/article.md"
}
```

# Outputs

```json
{
  "slide_plan_path": "runs/<run_id>/planning/slide_plan.json",
  "narration_files_optional": "runs/<run_id>/slides/slide_xxx/narration.txt"
}
```

`narration_files_optional` 只是从 `slide_plan.json` 中拆出的旁白副本，方便 TTS 脚本读取；业务主数据以 `slide_plan.json` 为准。

# Output Structure

`slide_plan.json` 必须符合 `schemas/slide_plan.schema.json`。

顶层字段：

- `topic.topic_id`
- `topic.topic_name`
- `topic.topic_summary`
- `slides[]`

每个 slide 必须包含：

- `slide_id`
- `slide_purpose`
- `main_title`
- `subtitle`
- `core_message`
- `content`
- `narration`

每个 `content` 必须包含：

- `content_type`
- `layout_intent`
- `items[]`

# Supported slide_purpose

- `opening_question`: 开场提问
- `problem_setup`: 提出问题背景
- `concept_intro`: 引出概念
- `concept_explanation`: 概念解释
- `example_demo`: 举例说明
- `process_breakdown`: 流程拆解
- `comparison_explain`: 对比说明
- `misunderstanding_fix`: 纠正常见误解
- `key_takeaway`: 重点提炼
- `practical_advice`: 使用建议
- `closing_summary`: 结尾总结

# Supported content_type

- `concept_explanation`: 概念解释
- `bullet_list`: 分点说明
- `process_flow`: 流程结构
- `comparison`: 对比结构
- `timeline`: 时间轴
- `cycle`: 循环结构
- `cards`: 卡片组
- `example_breakdown`: 示例拆解
- `misconception_correction`: 误区纠正
- `cause_effect`: 因果链
- `framework_map`: 框架图
- `hierarchy`: 层级结构
- `matrix`: 矩阵结构
- `checklist`: 操作清单
- `summary_takeaway`: 总结页
- `custom`: 仅在以上结构都不能表达时使用

# Procedure

1. 读取 `article.md`。
2. 按文章逻辑切分 slide，而不是先做文章摘要。
3. 每页只讲一个核心观点、一个问题或一个解释单元。
4. 不限制 slide 数量，以把整篇文章讲清楚为准。
5. 为每页选择合适的 `slide_purpose` 和 `content.content_type`。
6. 为每页写主标题、副标题和 `core_message`。
7. 把页面主要内容写进 `content.items[]`，不要只写一整段大文本。
8. 为每页写可直接 TTS 的中文 `narration`。
9. 输出 `slide_plan.json`。
10. 如后续脚本需要，可把每页 `narration` 拆出为 `runs/<run_id>/slides/slide_xxx/narration.txt`。

# Rules

- 不输出 `target_duration_sec`。
- 不输出 `duration_sec`。
- 不输出 `language`。
- 不输出 `article_brief.json`。
- 不要求固定 8 到 14 页。
- 不为了凑时长增加空话或无意义页。
- 不为了减少页数把多个复杂概念塞进同一页。
- 旁白必须是演讲稿，不写舞台说明、镜头说明、括号情绪说明。
- 所有内容默认面向普通人和 AI 初学者，避免术语堆叠。

# Validation

- `slides[]` 不能为空。
- 文章中的关键内容不能无故遗漏。
- 每页必须有明确 `core_message`。
- 每页 `content.items[]` 至少 1 条。
- 每页 `narration` 不能为空，且必须可直接朗读。
- 同一页不能同时解释多个复杂概念。
- `content_type` 必须和页面内容结构匹配。

# Failure Handling

- 如果文章过长，按自然章节拆成更多 slide，不压缩成少数大页。
- 如果某一页内容过多，继续拆页。
- 如果文章结构混乱，先按“问题、概念、过程、例子、误区、建议、总结”的教学顺序重组。
- 如果没有合适的结构类型，才使用 `custom`，并在 `layout_intent` 中说明原因。

# Bad Case Tags

- `output-unclear`
- `data-break`
- `scope-creep`
- `slide-overpacked`
- `narration-weak`
