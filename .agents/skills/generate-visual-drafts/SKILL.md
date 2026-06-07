---
name: generate-visual-drafts
description: Generate full-slide static visual drafts from slide_plan.json using fixed style tokens and actual reference images.
---

# Purpose

根据 `slide_plan.json` 中的单页内容，生成整页静态视觉稿。视觉稿是第一轮人工审核对象，用来确认构图、信息密度、图文关系和内容表达方向。

本阶段不定义风格，不接受运行期用户风格输入。风格固定来自仓库资源：

- `config/style_tokens.yaml`
- `references/style_reference/fixed_title_free_content_reference.png`
- `references/style_reference/paper_subtitle_background.png`

# Inputs

```json
{
  "slide_plan_path": "runs/<run_id>/planning/slide_plan.json",
  "slide_id": "slide_xxx",
  "style_tokens_path": "config/style_tokens.yaml",
  "main_reference_image": "references/style_reference/fixed_title_free_content_reference.png",
  "subtitle_reference_image": "references/style_reference/paper_subtitle_background.png",
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
4. 使用 `fixed_title_free_content_reference.png` 作为主参考图，保持固定标题区、内容区自由编排、整体页面密度和知识类页面气质。
5. 使用 `paper_subtitle_background.png` 作为底部参考图，控制字幕区域、字幕背景视觉和页面底部留白。
6. 生成适合 Codex Image Gen 的整页视觉 prompt。
7. prompt 中要求：16:9、1920x1080、固定参考图风格、适合拆成 PNG 图层。
8. 图片中尽量避免不可控乱码文字；如果必须有文字，后续应拆成独立 PNG 图层或由上游重新生成。
9. 保存 `visual_prompt.md` 和 `visual_draft.png`。

# Validation

- 视觉稿必须符合固定参考图风格。
- 背景、标题区、内容区和底部字幕留白必须稳定。
- 内容区必须能一眼看出本页核心概念。
- 构图必须适合后续拆成独立 PNG 图层。
- 主体、背景、图形关系要适合后续动画化。
- 不允许出现乱码文字、假 UI、无法解释的复杂图表。
- 底部字幕区不得出现 PPT 内容、虚线或装饰元素。

# Failure Handling

- 如果文字乱码，重生成并明确避免不可控文字。
- 如果风格漂移，回到固定参考图重新生成。
- 如果无法动画化，要求更清晰的 PNG 图层分离：背景、标题、副标题、内容主体、图解、标注、总结条。
- 如果内容过密，回到 `plan-slides` 拆页或减少该页内容。

# Bad Case Tags

- `visual-style-drift`
- `text-in-image`
- `not-animation-friendly`
- `layout-drift`
