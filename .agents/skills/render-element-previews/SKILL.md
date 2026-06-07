---
name: render-element-previews
description: Render scene.json into a static per-slide preview for review.
---

# Purpose

把单页 `scene.json` 渲染成 `render_preview.png`，作为第二轮审核对象。该阶段用于验证 Stage 3 重建出的结构化页面是否真实可渲染、可阅读、接近已审核的 `visual_draft.png`。

本阶段逐页执行。每次只处理一个 slide。

# Inputs

```json
{
  "scene_path": "runs/<run_id>/slides/slide_xxx/scene.json",
  "style_tokens_path": "config/style_tokens.yaml",
  "visual_draft_path": "runs/<run_id>/slides/slide_xxx/visual_draft.png",
  "scene_schema_path": "schemas/scene.schema.json"
}
```

# Input Meaning

- `scene_path`: Stage 3 生成的结构化页面数据。
- `style_tokens_path`: 固定风格参数，用于解释字号、颜色、标题区、内容框和字幕区规则。
- `visual_draft_path`: Stage 2 已审核通过的静态视觉稿，用于和渲染预览做方向对比。
- `scene_schema_path`: `scene.json` 的结构校验规则。

# Outputs

```json
{
  "render_preview_path": "runs/<run_id>/slides/slide_xxx/render_preview.png",
  "render_log_path": "runs/<run_id>/slides/slide_xxx/render_log.md"
}
```

# Output Meaning

- `render_preview.png`: 当前页由 `scene.json` 渲染出的静态预览图，是 Review Gate 2 的主要审核对象。
- `render_log.md`: 当前页的渲染日志，记录缺失资源、文本溢出、元素越界、schema 校验失败、与视觉稿的主要差异。

# Procedure

1. 读取 `scene.json`。
2. 使用 `schemas/scene.schema.json` 对 `scene.json` 做机器校验。
3. 检查 `scene.json` 中所有 `image` 元素引用的 `asset` 路径是否存在。
4. 检查 `main_title` 和 `subtitle` 是否为两个独立 `text` 元素。
5. 检查是否有元素落入底部字幕区 `Y=930` 到 `Y=1080`。
6. 用 Remotion 或等价渲染器渲染一帧静态页面。
7. 导出 `render_preview.png`。
8. 对比 `visual_draft.png`，记录主要差异到单页 `render_log.md`。
9. 如果渲染失败或资源缺失，阻止进入 Review Gate 2。

# Validation

- `scene.json` 必须通过 JSON Schema 校验。
- 所有 `image.asset` 路径必须存在。
- `main_title` 和 `subtitle` 必须清晰可读，且是两个独立文本元素。
- 标题和正文清晰可读。
- 元素版页面与视觉稿方向一致。
- 页面没有明显重叠、溢出、错位。
- 背景和重点元素不会干扰阅读。
- 左上黄色竖线、副标题横线和大圆角内容框必须存在。
- 底部字幕区不得出现 PPT 内容、虚线或装饰元素。

# Failure Handling

- 如果 schema 校验失败，回到 `reconstruct-scenes` 修正 `scene.json`。
- 如果文字溢出，调整文本框、字号、行高或拆分文本元素。
- 如果元素位置偏差过大，回到 `reconstruct-scenes`。
- 如果资源缺失，记录缺失路径并阻止进入动画阶段。
- 如果主标题和副标题被合并，回到 `reconstruct-scenes` 拆成两个独立 text 元素。

# Bad Case Tags

- `data-break`
- `validation-weak`
- `output-unclear`
- `asset-missing`
- `subtitle-area-occupied`
- `title-subtitle-merged`
