---
name: reconstruct-scenes
description: Reconstruct an approved static visual draft into PNG layers for Remotion animation.
---

# Purpose

把通过审核的整页视觉稿重建为 Remotion 可展示、可动画的 PNG 图层结构 `scene.json`。

本阶段不是让 Remotion 重新绘制文本、shape、line 或 group。最终 Remotion 只负责显示 PNG 图层、做轻量动画、叠加字幕和音频。

本阶段逐页执行。每次只处理一个 `slide_id`，输出该页自己的 `scene.json` 和 `assets/`。

# Inputs

```json
{
  "visual_draft_path": "runs/<run_id>/slides/slide_xxx/visual_draft.png",
  "visual_review_path": "runs/<run_id>/slides/slide_xxx/visual_review.yaml",
  "slide_plan_path": "runs/<run_id>/planning/slide_plan.json",
  "slide_id": "slide_xxx",
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

# Output Meaning

- `scene.json`: 当前页的 PNG 图层结构，是后续预览、动画和视频渲染的核心输入。
- `assets/`: 当前页所有 PNG 图层素材目录。

`scene.json` 必须包含：

- `slide_id`
- `canvas`
- `source_visual_draft`
- `layers[]`

每个 `layers[]` 项必须包含：

- `id`
- `type: png`
- `asset`
- `role`
- `box`
- `z_index`
- 可选 `animation_role`
- 可选 `content_index`

# Procedure

1. 读取 `visual_review.yaml`，确认 `status: approved`。如果不是 approved，停止执行。
2. 读取 `slide_plan.json`，定位当前 `slide_id`。
3. 读取已审核的 `visual_draft.png`。
4. 默认将视觉稿登记为一张整页 `full_slide` PNG 图层。
5. 输出 `scene.json`，只使用 `layers[]` 描述图层，不把 text、shape、line、group 作为 Remotion 主输入。
6. 所有图层资源必须保存到 `runs/<run_id>/slides/slide_xxx/assets/`。
7. 使用 JSON Schema 校验 `scene.json`。校验不通过时，修正结构后再继续。

# Layer Strategy

最小可用方案：

- `full_slide`: 一张整页 PNG，覆盖 1920x1080。适合快速生成视频，但动画空间有限。

可选增强方案：

- `background`: 背景和固定版式 PNG。
- `title`: 主标题 PNG。
- `subtitle`: 副标题 PNG。
- `content_body`: 页面主要内容 PNG。
- `diagram`: 图解或示意图 PNG。
- `annotation`: 重点标注、箭头、下划线 PNG。
- `summary`: 总结条 PNG。

主标题和副标题默认包含在 `full_slide` 中。只有在拆出的素材同样来自图像模型 PNG 或图像裁切时，才允许拆成两个独立 PNG 图层：

- `role: title`
- `role: subtitle`

禁止用 Remotion、React、HTML/CSS 或 SVG 重新绘制主标题和副标题。

# Subtitle Safe Area

- 底部字幕区 `Y=930` 到 `Y=1080` 不应包含 PPT 主体内容。
- 如果使用整页 `full_slide`，也必须确保该区域只有背景或安全留白。
- 视频字幕由 Remotion 单独叠加，不属于 `scene.layers[]`。

# Validation

- `visual_review.yaml` 必须是 `status: approved`。
- `scene.json` 必须通过 `schemas/scene.schema.json` 校验。
- `layers[]` 至少 1 个。
- 每个 layer 的 `asset` 必须指向存在的 PNG 文件。
- 每个 layer 的 `box` 坐标必须在 1920x1080 内。
- 生产默认可以只使用一个 `full_slide` layer。
- 不允许把 Remotion 主路径建立在 text、shape、line、group 渲染上。
- 预览渲染后，页面必须接近已审核的 `visual_draft.png`。

# Failure Handling

- 如果图层拆分困难，先输出 `full_slide` 兜底图层，保证后续视频可渲染。
- 如果需要更细动画，再回到本阶段继续拆出 `title`、`subtitle`、`content_body`、`diagram`、`annotation`、`summary` 等 PNG 图层。
- 如果视觉稿和 slide 内容冲突，回到 `generate-visual-drafts`。
- 如果内容过密，回到 `plan-slides` 拆页。
- 如果 `scene.json` 无法通过 schema 校验，优先修正结构，不进入渲染预览。

# Bad Case Tags

- `data-break`
- `not-animation-friendly`
- `validation-weak`
- `scene-schema-failed`
- `asset-missing`
- `title-subtitle-merged`
