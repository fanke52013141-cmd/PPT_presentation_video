# Slide Plan 检查

检查对象：`runs/<run_id>/planning/slide_plan.json`

- 不应存在 `article_brief.json` 依赖。
- 不应输出 `target_duration_sec`、`duration_sec`、`language`。
- 必须包含 `topic.topic_id`、`topic.topic_name`、`topic.topic_summary`。
- `slides[]` 不能为空。
- 每页必须有 `slide_id`、`slide_purpose`、`main_title`、`subtitle`、`core_message`、`content`、`narration`。
- 每页 `content` 必须有 `content_type`、`layout_intent`、`items[]`。
- 每页 `content.items[]` 至少 1 条。
- 每页只表达一个核心观点、问题或解释单元。
- 文章中的关键内容不能无故遗漏。
- slide 数量不设固定上下限，以讲清楚整篇文章为准。
- 复杂内容应拆页，不要压缩进少数大页。
- `narration` 必须是可直接 TTS 的中文演讲稿，不写舞台说明、镜头说明或括号情绪说明。
- `content_type` 应匹配页面结构，例如概念解释、流程、对比、时间轴、循环、卡片、示例拆解、误区纠正、因果链、框架图、层级结构、矩阵、清单或总结。
