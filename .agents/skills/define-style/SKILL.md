---
name: define-style
description: Define or adapt the visual style guide for an AI science explainer deck.
---

# Purpose

制定每次视频的 PPT 风格、配色、字体、图表、配图和动画基调。用户给参考图时，先生成本次运行的 `style_guide.md`，待确认后再沉淀到仓库配置。

# Inputs

```json
{
  "task_config_path": "config/task.yaml",
  "style_tokens_path": "config/style_tokens.yaml",
  "visual_rules_path": "references/visual_rules.md",
  "user_reference_images": "可选"
}
```

# Outputs

```json
{
  "style_guide_path": "runs/<run_id>/planning/style_guide.md",
  "style_tokens_draft_path": "runs/<run_id>/planning/style_tokens.draft.yaml 可选"
}
```

# Procedure

1. 默认读取 `config/style_tokens.yaml`。
2. 如果用户提供参考样式，提取配色、字体气质、构图、图表风格、配图风格。
3. 生成本次视频 `style_guide.md`。
4. 明确禁止项：图片内大量文字、复杂背景遮挡正文、过度霓虹、单一蓝紫渐变铺满。
5. 如果需要修改仓库默认风格，先输出 draft，等待用户确认。

# Validation

- 必须有主背景色、主文字色、主色、强调色。
- 必须有标题、正文、字幕字号建议。
- 必须定义配图风格和图表风格。
- 必须定义不使用的视觉元素。

# Failure Handling

- 缺少品牌规范时，使用默认 AI 科普风格。
- 用户参考图和当前流程冲突时，说明冲突点并给出折中方案。

# Bad Case Tags

- `visual-style-drift`
- `config-hardcoded`
- `reference-missing`

