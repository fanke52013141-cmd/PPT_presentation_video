---
name: render-element-previews
description: Render PNG-layer scene.json into a static per-slide preview for review.
---

# Purpose

把单页 PNG 图层版 `scene.json` 渲染成 `render_preview.png`，作为第二轮审核对象。该阶段用于验证 Stage 3 重建出的 PNG 图层页面是否真实可渲染、可阅读、接近已审核的 `visual_draft.png`。

本阶段逐页执行。每次只处理一个 slide。

# Inputs

```json
{
  "scene_path": "runs/<run_id>/slides/slide_xxx/scene.json",
  "visual_draft_path": "runs/<run_id>/slides/slide_xxx/visual_draft.png",
  "scene_schema_path": "schemas/scene.schema.json"
}
```

# Outputs

```json
{
  "render_preview_path": "runs/<run_id>/slides/slide_xxx/render_preview.png",
  "render_log_path": "runs/<run_id>/slides/slide_xxx/render_log.md"
}
```

# Procedure

1. 读取 `scene.json`。
2. 使用 `schemas/scene.schema.json` 对 `scene.json` 做机器校验。
3. 检查 `scene.layers[]` 中所有 `asset` 路径是否存在，且应为 PNG 图层。
4. 检查 `title` 和 `subtitle` 是否为两个独立 layer；如果使用 `full_slide` 兜底，则在日志中标记动画能力受限。
5. 检查是否有主体 layer 侵入底部字幕区 `Y=930` 到 `Y=1080`。
6. 用 Remotion 或等价渲染器把 PNG 图层渲染为一帧静态页面。
7. 导出 `render_preview.png`。
8. 对比 `visual_draft.png`，记录主要差异到单页 `render_log.md`。
9. 如果渲染失败或资源缺失，阻止进入 Review Gate 2。

# Validation

- `scene.json` 必须通过 JSON Schema 校验。
- `layers[]` 至少 1 个。
- 所有 `layer.asset` 路径必须存在。
- 所有 layer 的 `box` 坐标必须在 1920x1080 内。
- PNG 图层版页面与视觉稿方向一致。
- 页面没有明显重叠、溢出、错位。
- 底部字幕区不得出现 PPT 内容、虚线或装饰元素。
- Remotion 不应依赖 text、shape、line、group 渲染页面主体。

# Failure Handling

- 如果 schema 校验失败，回到 `reconstruct-scenes` 修正 `scene.json`。
- 如果图层资源缺失，记录缺失路径并阻止进入动画阶段。
- 如果图层位置偏差过大，回到 `reconstruct-scenes`。
- 如果只有 `full_slide` 兜底层，允许继续快速预览，但应在日志中提示动画能力有限。

# Bad Case Tags

- `data-break`
- `validation-weak`
- `output-unclear`
- `asset-missing`
- `subtitle-area-occupied`
- `png-layer-missing`
