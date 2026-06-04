---
name: render-element-previews
description: Render scene.json into a static element preview for human review.
---

# Purpose

把 `scene.json` 渲染成 `render_preview.png`，作为第二轮人工审核对象。

# Inputs

```json
{
  "scene_path": "runs/<run_id>/slides/slide_xxx/scene.json",
  "style_tokens_path": "config/style_tokens.yaml",
  "visual_draft_path": "runs/<run_id>/slides/slide_xxx/visual_draft.png"
}
```

# Outputs

```json
{
  "render_preview_path": "runs/<run_id>/slides/slide_xxx/render_preview.png",
  "render_log_path": "runs/<run_id>/logs/render_log.md"
}
```

# Procedure

1. 读取 `scene.json`。
2. 用 Remotion 或等价渲染器渲染一帧静态页面。
3. 导出 `render_preview.png`。
4. 对比 `visual_draft.png`，记录主要差异。

# Validation

- 标题和正文清晰可读。
- 元素版页面与视觉稿方向一致。
- 页面没有明显重叠、溢出、错位。
- 背景和重点元素不会干扰阅读。

# Failure Handling

- 如果文字溢出，调整字号、行高或文本框。
- 如果元素位置偏差过大，回到 `reconstruct-scenes`。
- 如果资源缺失，记录缺失路径并阻止进入动画阶段。

# Bad Case Tags

- `data-break`
- `validation-weak`
- `output-unclear`

