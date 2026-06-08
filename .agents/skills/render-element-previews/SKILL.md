---
name: render-element-previews
description: Render PNG-layer scene.json into a static per-slide preview for review.
---

# Purpose

## Production Override: Macro Layer Preview

Preview must accept `scene.visual_source: image_gen_macro_layers_manifest`.
The preview source of truth is `render_preview.png` produced by
`scripts/compose_manifest_layers.py`, not an algorithmically cropped full-slide
decomposition.

Review requirements:

- Compare the composed preview against the full-slide reference for layout
  intent, but do not require pixel-perfect equality.
- Check that macro groups are large and coherent, not many tiny fragments.
- Check that layer boxes do not visually overlap.
- Check subtitle safe zone before video render. For 1920x1080, no PPT body
  layer should extend below `y=930`; for other canvas sizes use
  `safe_y = round(height * 930 / 1080)`.
- If subtitles are enabled, extract or inspect a video frame with active
  subtitles and confirm captions do not cover summary/content layers.
- Read `narration.txt` or `subtitles.srt` and verify that the spoken content
  matches the visible macro layers. A good composition preview is not enough if
  the script describes a different slide.

把单页 PNG 图层版 `scene.json` 渲染成 `render_preview.png`，作为第二轮审核对象。该阶段验证 Stage 3 拆出的 PNG 图层是否真实可渲染、可阅读、接近已审核的 `visual_draft.png`。

# Inputs

```json
{
  "scene_path": "runs/<run_id>/slides/slide_xxx/scene.json",
  "visual_draft_path": "runs/<run_id>/slides/slide_xxx/visual_draft.png",
  "scene_schema_path": "schemas/scene.schema.json",
  "decomposition_report_path": "runs/<run_id>/slides/slide_xxx/decomposition_report.json"
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
2. 使用 `schemas/scene.schema.json` 校验结构。
3. 检查 `scene.layers[]` 中所有 `asset` 是否存在，且均为 PNG。
4. 检查是否至少有 `background` 加一个主体图层；如果只有 `full_slide`，回到 Stage 3。
5. 检查 `title` 和 `subtitle` 是否是独立 PNG layer 或清晰的 `title_group` / `subtitle_group` 宏观图层。
6. 检查主体 layer 是否侵入底部字幕区 `Y=930` 到 `Y=1080`。
7. 使用 Remotion 或等价渲染器把 PNG 图层渲染为一帧静态页面。
8. 导出 `render_preview.png`。
9. 对比 `visual_draft.png`，记录主要差异到 `render_log.md`。
10. 如果渲染失败、资源缺失、图层错位或拆层 warning 阻塞，不能进入 Review Gate 2。

# Validation

- `scene.json` 必须通过 JSON Schema 校验。
- `layers[]` 必须是多 PNG layer。
- 所有 `layer.asset` 路径必须存在。
- 所有 layer 的 `box` 坐标必须在 1920x1080 内。
- PNG 图层版页面与视觉稿方向一致。
- 页面没有明显重复、溢出、错位。
- 底部字幕区不得出现 PPT 内容、虚线或装饰元素。
- Remotion 不依赖 text、shape、line、group 渲染页面主体。

# Failure Handling

- schema 校验失败：回到 `reconstruct-scenes`。
- 图层资源缺失：记录缺失路径并阻止进入动画阶段。
- 图层位置偏差过大：回到 `reconstruct-scenes`。
- 只有 `full_slide`：回到 `reconstruct-scenes` 拆层。
- 拆层报告显示视觉对象重叠或只能拆出一个主体 group：回到 `generate-visual-drafts`。

# Bad Case Tags

- `data-break`
- `validation-weak`
- `output-unclear`
- `asset-missing`
- `subtitle-area-occupied`
- `png-layer-missing`
