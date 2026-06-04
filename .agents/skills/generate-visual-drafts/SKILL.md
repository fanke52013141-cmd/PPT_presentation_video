---
name: generate-visual-drafts
description: Generate full-slide static visual drafts with Codex Image Gen for human review.
---

# Purpose

生成整页静态视觉稿。它是第一轮人工审核对象，用来确认整体风格、构图、信息密度和配图方向。

# Inputs

```json
{
  "slide_spec_path": "runs/<run_id>/slides/slide_xxx/slide_spec.json",
  "style_guide_path": "runs/<run_id>/planning/style_guide.md",
  "style_tokens_path": "config/style_tokens.yaml",
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

1. 读取 slide 的核心信息、配图要求和动画意图。
2. 生成适合 Codex Image Gen 的整页视觉 prompt。
3. prompt 中要求：16:9、1920x1080、教育解释型、可拆分前景/背景/主体。
4. 图片中尽量不生成文字，真实标题和正文后续由渲染器排版。
5. 保存 prompt 和生成图。

# Validation

- 视觉稿必须能一眼看出本页核心概念。
- 构图必须预留真实文字区域。
- 主体、背景、图形关系要适合后续拆成元素。
- 不允许出现乱码文字、假 UI、无法解释的复杂图表。

# Failure Handling

- 如果文字乱码，重生成并明确 `no readable text in image`。
- 如果太像科技海报，降低装饰，增强教育图解。
- 如果无法动画化，要求更清晰的前景、背景、主体分层。

# Bad Case Tags

- `visual-style-drift`
- `text-in-image`
- `not-animation-friendly`

