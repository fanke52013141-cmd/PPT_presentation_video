---
name: generate-visual-drafts
description: Generate full-slide Image Gen visual drafts that are animation-friendly and decomposable into PNG layers.
---

# Purpose

根据 `slide_plan.json` 的单页内容，生成整页静态视觉稿 `visual_draft.png`。视觉稿仍然必须是 Codex Image Gen 生成的完整位图，但它必须适合后续裁切为 PNG 图层并逐层动画。

本阶段不定义新风格，不接受运行期用户风格输入。风格固定来自：

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
3. 读取 `config/style_tokens.yaml`，锁定背景、颜色、标题区、开放内容区和字幕区规则。
4. 使用 `PPT模板.png` 锁定标题区、黄色竖线、副标题下划线、开放内容区和底部字幕安全区。
5. 使用 `PPT示例.png` 控制信息组织、手写感、图标、标注、总结条和视觉密度。
6. 运行：

```powershell
python scripts/write_visual_prompts.py `
  --run-dir runs/<run_id> `
  --overwrite
```

7. 用 Codex Image Gen 生成 `visual_draft.png`。

# Required Prompt Constraints

视觉稿必须满足：

- 16:9、1920x1080。
- 主标题、副标题、黄色竖线和副标题下划线位置稳定。
- 中间为无外框开放内容区，不生成大圆角内容框。
- 底部 `Y=930` 到 `Y=1080` 不放 PPT 主体内容。
- 标题、正文、图标、框线、箭头、图表和标注必须进入 Image Gen 位图本身。
- 后续不得用 SVG、HTML/CSS、Canvas、React 或 Remotion 代码补画 PPT 主体内容。

# Decomposition-Friendly Composition

生成时必须为后续拆层服务：

- 主标题、副标题、每个内容块、图解、箭头、标签、总结条都应有清晰分离边界。
- 独立可动画对象之间至少保留 24-40px 干净背景。
- 箭头端点不要贴住或压住文字、图标、边框或标签。
- 不要把文字盖在图标、箭头或装饰上，除非它和背景色块属于同一个标签组。
- 优先 3-7 个大的可裁切内容组，避免大量细碎且粘连的小元素。
- 如果内容需要长连接线，优先改成分组、留白或对齐，不要让线条穿过多个对象。

# Validation

- 视觉稿必须符合固定参考图风格。
- 画面必须一眼看出本页核心概念。
- 内容区不得过密。
- 不得出现乱码、假 UI、无法解释的复杂图表。
- 不得有对象重叠、文字压线、箭头压字、标签互相覆盖。
- 底部字幕区不得出现 PPT 内容、虚线或装饰元素。

# Failure Handling

- 文字乱码：重新生成。
- 风格漂移：回到固定参考图重新生成。
- 对象重叠或不可拆：重新生成，并明确增加留白、分组和禁止压线。
- 内容过密：回到 `plan-slides` 拆页或减少该页内容。

# Bad Case Tags

- `visual-style-drift`
- `text-in-image`
- `not-animation-friendly`
- `visual-overlap`
- `layout-drift`
