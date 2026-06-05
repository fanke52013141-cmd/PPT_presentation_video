---
name: reconstruct-scenes
description: Reconstruct an approved static visual draft into editable scene elements.
---

# Purpose

把通过审核的整页视觉稿重建为可动画、可修改、可程序渲染的 `scene.json`。这一步不是单纯抠图，而是把视觉方向转成可控元素结构。

# Inputs

```json
{
  "visual_draft_path": "runs/<run_id>/slides/slide_xxx/visual_draft.png",
  "visual_review_path": "runs/<run_id>/slides/slide_xxx/visual_review.yaml",
  "slide_spec_path": "runs/<run_id>/slides/slide_xxx/slide_spec.json",
  "style_tokens_path": "config/style_tokens.yaml",
  "scene_schema_path": "schemas/scene.schema.json"
}
```

# Outputs

```json
{
  "scene_path": "runs/<run_id>/slides/slide_xxx/scene.json",
  "assets_dir": "runs/<run_id>/slides/slide_xxx/assets/"
}
```

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
- `animation_role`

# Procedure

1. 识别视觉稿中的背景、主体、图标、图表、装饰和文字区域。
2. 文字一律重建为真实文本元素，不从图片中抠文字。
3. 图片元素可以裁切，也可以用 Codex Image Gen 重新生成单元素素材。
4. 凡承担“配图”功能的视觉主体必须是 `type: image`，素材来源必须是 Codex Image Gen 位图；不得用 `shape` 或文本元素拼装文件、时钟、流程节点等配图。
5. 为每个元素设置 `box`、`z_index`、`animation_role`。
6. 输出符合 schema 的 `scene.json`。

# Validation

- 所有屏幕文字都必须可编辑。
- 所有重要元素都有稳定 `id`。
- 元素不能互相遮挡主要阅读区域。
- `box` 坐标必须在 1920x1080 内。
- 同一视频的页面布局必须有变化；检查 `scene.layout` 或元素坐标，避免所有页复用同一套卡片和配图位置。
- `animation_role: visual` 的配图元素应为 `type: image`，`semantic_role` 使用 `content_visual`。

# Failure Handling

- 如果原图元素难以拆分，保留为背景层，再单独重建标题、正文和重点图标。
- 如果视觉稿和 slide 内容冲突，回到 `generate-visual-drafts`。
- 如果配图被重建成 shape/text 组合，回到 `generate-visual-drafts` 生成 Image Gen 位图资产。

# Bad Case Tags

- `data-break`
- `not-animation-friendly`
- `validation-weak`

