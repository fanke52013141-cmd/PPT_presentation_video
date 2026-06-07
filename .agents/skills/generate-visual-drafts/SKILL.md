---
name: generate-visual-drafts
description: Generate full-slide static visual drafts from slide_plan.json using fixed style tokens and reference images.
---

# Purpose

根据 `slide_plan.json` 中的单页内容，生成整页静态视觉稿。视觉稿是第一轮人工审核对象，用来确认构图、信息密度、图文关系和内容表达方向。

本阶段不定义风格，不接受运行期用户风格输入。风格固定来自仓库资源：

- `config/style_tokens.yaml`
- `references/style_reference/PPT_template.png`
- `references/style_reference/PPT_example.png`

# Inputs

```json
{
  "slide_plan_path": "runs/<run_id>/planning/slide_plan.json",
  "slide_id": "slide_xxx",
  "style_tokens_path": "config/style_tokens.yaml",
  "template_reference_image": "references/style_reference/PPT_template.png",
  "example_reference_image": "references/style_reference/PPT_example.png",
  "prompt_template_path": "templates/prompts/visual_draft.prompt.md"
}
```

# Outputs

```json
{
  "visual_prompt_path": "runs/<run_id>/slides/slide_xxx/visual_prompt.md",
  "visual_draft_path": "runs/<run_id>/slides/slide_xxx/visual_draft.png"
}
```

# Procedure

1. 读取 `slide_plan.json`，定位当前 `slide_id`。
2. 提取该页的 `main_title`、`subtitle`、`core_message`、`content.content_type`、`content.layout_intent`、`content.items[]` 和 `narration`。
3. 读取 `config/style_tokens.yaml`，锁定背景、字号、颜色、标题区、内容框和字幕区规则。
4. 使用 `PPT_template.png` 作为空白母版参考，保持标题区、黄色竖线、副标题横线、大圆角内容框和底部字幕留白。
5. 使用 `PPT_example.png` 作为成品效果参考，控制内容密度、黑色手绘线稿、浅色胶囊、Token 小方块、手绘箭头和总结条风格。
6. 生成适合 Codex Image Gen 的整页视觉 prompt。
7. prompt 中要求：16:9、1920x1080、温暖极简手绘线稿风、可拆分前景/背景/主体。
8. 图片中尽量不生成真实正文，真实标题、正文、标签和图表文字后续由渲染器排版。
9. 保存 `visual_prompt.md` 和 `visual_draft.png`。

# Validation

- 视觉稿必须符合固定模板和示例风格。
- 背景必须是暖白风格，不能漂移到蓝黑科技风或复杂 3D 风。
- 左上标题区、黄色竖线、副标题横线、大圆角内容框和底部字幕留白必须稳定。
- 内容区必须能一眼看出本页核心概念。
- 构图必须为真实文字区域留白。
- 主体、背景、图形关系要适合后续拆成元素。
- 不允许出现乱码文字、假 UI、无法解释的复杂图表。
- 底部字幕区不得出现 PPT 内容、虚线或装饰元素。

# Failure Handling

- 如果文字乱码，重生成并明确 `no readable text in image`。
- 如果太像科技海报，回到固定模板和示例图，降低装饰，增强手绘讲解感。
- 如果无法动画化，要求更清晰的前景、背景、主体分层。
- 如果内容过密，回到 `plan-slides` 拆页或减少该页内容。
- 如果风格漂移，重新生成并强调固定参考图不可偏离。

# Bad Case Tags

- `visual-style-drift`
- `text-in-image`
- `not-animation-friendly`
- `layout-drift`
