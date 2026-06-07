---
name: generate-visual-drafts
description: Generate full-slide static visual drafts from slide_plan.json using fixed style tokens and actual reference images.
---

# Purpose

根据 `slide_plan.json` 中的单页内容，生成整页静态视觉稿。视觉稿是第一轮人工审核对象，用来确认构图、信息密度、图文关系和内容表达方向。

本阶段不定义风格，不接受运行期用户风格输入。风格固定来自仓库资源：

- `config/style_tokens.yaml`
- `references/style_reference/PPT模板.png`
- `references/style_reference/PPT示例.png`

# Inputs

```json
{
  "slide_plan_path": "runs/<run_id>/planning/slide_plan.json",
  "slide_id": "slide_xxx",
  "style_tokens_path": "config/style_tokens.yaml",
  "template_reference_image": "references/style_reference/PPT模板.png",
  "example_reference_image": "references/style_reference/PPT示例.png",
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
3. 读取 `config/style_tokens.yaml`，锁定背景、字号、颜色、标题区、开放内容区和字幕区规则。
4. 使用 `PPT模板.png` 作为空白模板参考图，保持标题区、黄色竖线、副标题下划线、开放内容区和底部字幕安全区。
5. 使用 `PPT示例.png` 作为完整页面示例图，控制内容区的信息组织方式、手写感文字、图标、分栏、标注、总结条和视觉密度。
6. 生成适合 Codex Image Gen 的整页视觉 prompt。
7. prompt 中要求：16:9、1920x1080、固定参考图风格、整页位图成稿。
8. 标题、正文、图标、框线、箭头、图表和标注必须进入 Codex Image Gen 生成的位图本身；后续不得用 SVG、HTML/CSS、Canvas、React 或 Remotion 代码补画 PPT 主体内容。
9. 图片中尽量避免不可控乱码文字；如果文字质量不合格，应重新生成整页视觉稿。
10. 保存 `visual_prompt.md` 和 `visual_draft.png`。

# Validation

- 视觉稿必须符合固定参考图风格。
- 背景、标题区、开放内容区和底部字幕留白必须稳定。
- 中间内容区不得出现大圆角外框或 enclosing content frame。
- 内容区必须能一眼看出本页核心概念。
- 构图必须适合作为整页 `full_slide` PNG 直接进入 Remotion。
- 主体、背景、图形关系要适合后续动画化。
- 不允许出现乱码文字、假 UI、无法解释的复杂图表。
- 底部字幕区不得出现 PPT 内容、虚线或装饰元素。

# Failure Handling

- 如果文字乱码，重生成并明确避免不可控文字。
- 如果风格漂移，回到固定参考图重新生成。
- 如果需要增强动画，拆出的素材也必须是图像模型产出的 PNG；不能退回前端代码绘制。
- 如果内容过密，回到 `plan-slides` 拆页或减少该页内容。

# Bad Case Tags

- `visual-style-drift`
- `text-in-image`
- `not-animation-friendly`
- `layout-drift`
