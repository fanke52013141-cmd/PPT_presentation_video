---
name: reconstruct-scenes
description: Reconstruct an approved static visual draft into editable scene elements.
---

# Purpose

把通过审核的整页视觉稿重建为可动画、可修改、可程序渲染的 `scene.json`。这一步不是单纯抠图，而是把视觉方向转成可控元素结构。

本阶段逐页执行。每次只处理一个 `slide_id`，输出该页自己的 `scene.json` 和可选 `assets/`。

# Inputs

```json
{
  "visual_draft_path": "runs/<run_id>/slides/slide_xxx/visual_draft.png",
  "visual_review_path": "runs/<run_id>/slides/slide_xxx/visual_review.yaml",
  "slide_plan_path": "runs/<run_id>/planning/slide_plan.json",
  "slide_id": "slide_xxx",
  "style_tokens_path": "config/style_tokens.yaml",
  "scene_schema_path": "schemas/scene.schema.json"
}
```

# Input Meaning

- `visual_draft_path`: Stage 2 生成、并已通过审核的静态视觉稿。
- `visual_review_path`: Review Gate 1 的审核结果。只有 `status: approved` 才允许进入本阶段。
- `slide_plan_path`: Stage 1 生成的整套 slide 内容结构。
- `slide_id`: 当前要重建的具体 slide。
- `style_tokens_path`: 固定风格参数，控制颜色、字号、布局、字幕区和元素语义角色。
- `scene_schema_path`: `scene.json` 的结构校验规则。

# Outputs

```json
{
  "scene_path": "runs/<run_id>/slides/slide_xxx/scene.json",
  "assets_dir": "runs/<run_id>/slides/slide_xxx/assets/"
}
```

# Output Meaning

- `scene.json`: 当前页的结构化页面数据，是后续预览、动画和视频渲染的核心输入。
- `assets/`: 当前页需要引用的图片素材目录。只有复杂插图、复杂图标组或无法用简单元素稳定重建的视觉主体才需要进入 assets。

`scene.json` 必须包含：

- `slide_id`
- `canvas`
- `source_visual_draft`
- `elements[]`

每个元素必须包含：

- `id`
- `type`
- `box`
- `z_index`
- `region`
- `semantic_role`
- 可选 `animation_role`

# Procedure

1. 读取 `visual_review.yaml`，确认 `status: approved`。如果不是 approved，停止执行。
2. 读取 `slide_plan.json`，定位当前 `slide_id`。
3. 提取该页的 `main_title`、`subtitle`、`core_message`、`content.content_type`、`content.layout_intent`、`content.items[]` 和 `narration`。
4. 读取 `style_tokens.yaml`，锁定画布、背景、标题区、内容框、字幕安全区、字号、颜色和允许的 semantic_role。
5. 识别视觉稿中的背景、主体、图标、图表、装饰和文字区域。
6. 文字一律重建为真实 `text` 元素，不从图片中抠文字。
7. 固定输出 `brand_marker`、`main_title`、`subtitle`、`subtitle_underline` 和 `content_frame`，并使用 `style_tokens.yaml` 中的固定坐标。
8. 主标题和副标题必须拆成两个独立的 `text` 元素，不能合并为同一个文本框、group 或图片。
9. 手绘框、手绘箭头、关键词下划线、关键词圈注、Token 小块、总结条、胶囊标签，优先重建为 `shape`、`line`、`text` 等 renderer 可控元素。
10. 复杂插图、复杂图标组、人物/机器人插图或无法稳定程序化重建的视觉主体，可以作为 `type: image` 元素引用 `assets/` 下的位图素材。
11. 为每个元素设置稳定 `id`、`box`、`z_index`、`region`、`semantic_role` 和可选 `animation_role`。
12. 输出符合 `schemas/scene.schema.json` 的 `scene.json`。
13. 使用 JSON Schema 校验 `scene.json`。校验不通过时，修正结构后再继续。

# Required Fixed Elements

每页必须包含以下固定元素：

- `brand_marker`: 左侧黄色竖线。
- `main_title`: 主标题真实文本，必须是独立 `text` 元素，`semantic_role: main_title`。
- `subtitle`: 副标题真实文本，必须是独立 `text` 元素，`semantic_role: subtitle`。
- `subtitle_underline`: 副标题下方黄色横线。
- `content_frame`: 中间大圆角内容框。

禁止：

- 把 `main_title` 和 `subtitle` 合并成同一个 `text` 元素。
- 把主标题和副标题做成图片。
- 把标题区做成不可编辑的大背景图。

# Region Rules

- `title_block`: 只放标题区元素，例如 `brand_marker`、`main_title`、`subtitle`、`subtitle_underline`。
- `content`: 只放内容框和内容区元素。
- 底部字幕区 `Y=930` 到 `Y=1080` 不允许输出任何 scene 元素。

# Assets Rules

优先不要把简单元素做成图片。

不进入 `assets/` 的元素：

- 标题、副标题、正文。
- 黄色竖线、副标题横线、内容框。
- 关键词下划线、关键词圈注。
- Token 小块、简单箭头、总结条、胶囊标签。

进入 `assets/` 的元素：

- 复杂手绘插图。
- 复杂图标组。
- 复杂概念图背景。
- 人物、机器人或无法用简单 shape/line/text 稳定重建的视觉主体。

# Validation

- `visual_review.yaml` 必须是 `status: approved`。
- 所有屏幕文字都必须可编辑。
- `main_title` 和 `subtitle` 必须是两个独立 `text` 元素。
- 所有重要元素都有稳定 `id`。
- 元素不能互相遮挡主要阅读区域。
- `box` 坐标必须在 1920x1080 内。
- 不允许在底部字幕区输出元素。
- `region` 必须符合 `scene.schema.json`。
- `semantic_role` 必须符合 `scene.schema.json`。
- `scene.json` 必须通过 JSON Schema 机器校验。
- 预览渲染后，页面必须接近已审核的 `visual_draft.png`。

# Failure Handling

- 如果 `visual_review.yaml` 不是 approved，停止执行并回到 Review Gate 1。
- 如果原图元素难以拆分，保留复杂视觉主体为 image 层，再单独重建标题、正文、重点图标和结构元素。
- 如果视觉稿和 slide 内容冲突，回到 `generate-visual-drafts`。
- 如果内容过密，回到 `plan-slides` 拆页。
- 如果 `scene.json` 无法通过 schema 校验，优先修正结构，不进入渲染预览。

# Bad Case Tags

- `data-break`
- `not-animation-friendly`
- `validation-weak`
- `scene-schema-failed`
- `asset-overuse`
- `title-subtitle-merged`
