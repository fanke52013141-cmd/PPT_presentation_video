---
name: reconstruct-scenes
description: Compose manifest-declared Image Gen macro-layer PNGs into Remotion scene.json and animation timelines.
---

# Purpose

## Production Override: Compose, Do Not Decompose

Default production input is `runs/<run_id>/layer_manifest.json`, whose layers
come from Image Gen/Web Image Gen macro-layer PNGs. This stage composes those
declared layers into `scene.json`; it must not semantically infer layers from a
full-slide bitmap.

Default production command:

```powershell
python scripts/compose_manifest_layers.py `
  --manifest runs/<run_id>/layer_manifest.json `
  --repo-root .
```

Legacy `scripts/decompose_slide_layers.py` is now diagnostic/fallback only. Use
it only when the user explicitly approves a fallback or when auditing why a
full-slide split failed.

Expected `scene.visual_source`: `image_gen_macro_layers_manifest`.

Each production manifest layer should carry `text_summary` and
`narration_cue`. Preserve these fields into `scene.layers[]` so later stages can
verify that narration and animation timing are bound to visible content.

If a layer uses `animation: highlight`, the composer must still create a normal
entry event for that layer. A summary or highlight layer must not be visible
from frame 0 unless it is explicitly `entry_animation: static`.

把通过审核的 `visual_draft.png` 拆解为 Remotion 可显示、可逐层动画的 PNG 图层结构 `scene.json`。

本阶段不让 Remotion 重新绘制文本、shape、line 或 group。Remotion 只能显示由 Image Gen 位图裁切出的 PNG 图层、执行轻量动画、叠加字幕和播放音频。

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
  "animation_timeline_path": "runs/<run_id>/slides/slide_xxx/animation_timeline.json",
  "decomposition_report_path": "runs/<run_id>/slides/slide_xxx/decomposition_report.json",
  "assets_dir": "runs/<run_id>/slides/slide_xxx/assets/"
}
```

# Procedure

1. 读取 `visual_review.yaml`，确认 `status: approved`。如果没有审核通过，停止。
2. 读取 `slide_plan.json`，定位当前 `slide_id`。
3. 读取已审核的 `visual_draft.png`。
4. 默认调用宏观图层组合脚本：

```powershell
python scripts/compose_manifest_layers.py `
  --manifest runs/<run_id>/layer_manifest.json `
  --repo-root .
```

5. 单页调试时可以只保留对应 slide 目录运行脚本，或先复制 run 作为 smoke run。
6. 输出 `scene.json` 必须使用 `layers[]`，每个 layer 必须是 `type: png`。
7. 输出 `visual_source` 优先是 `image_gen_macro_layers_manifest`；旧的 `codex_image_gen_png_layers` 仅用于历史拆图产物。
8. 所有 PNG 图层素材必须保存到当前 slide 的 `assets/` 目录。
9. 运行校验：

```powershell
python scripts/validate_run_assets.py `
  --run-dir runs/<run_id> `
  --require-layered
```

# Layer Strategy

生产默认拆为多层 PNG：

- `background`: 纯背景或模板底层。
- `title`: 主标题 PNG。
- `subtitle`: 副标题 PNG。
- `content_body`: 主要内容块 PNG。
- `diagram`: 图解、示意图、卡片或流程块 PNG。
- `annotation`: 箭头、重点标注、强调标签 PNG。
- `summary`: 总结条或重点结论 PNG。

`assets/full_slide.png` 仍可保留为原始审核稿备份和对照源，但不能作为生产动画的唯一图层。

# Overlap Handling

- 如果对象之间发生实际重叠或粘连，不要硬拆成会穿帮的碎片，应保留为一个 PNG group。
- 如果只能拆出一个主体 group，在 `decomposition_report.json` 记录 `single_content_group`，并建议回到 `generate-visual-drafts` 重新生成更可拆的画面。
- 如果文字压住箭头、图标、边框或总结条进入字幕区，标记为视觉稿问题，回到 `generate-visual-drafts`。
- `projection_split_used` 是投影切分兜底提示，默认 `severity=advisory`，不应单独阻塞渲染；但复盘时要确认拆出来的 layer 没有截断文字或图标。
- `layer_bbox_overlap` 只有明显主体重叠才视为阻塞；轻微标题/副标题 box 相交不应中断流程。

# Timing Rules

- 如果 `audio_timeline.json` 已存在，`animation_timeline.duration_sec` 必须读取真实音频时长。
- 如果先做了视觉拆层诊断，TTS 完成后必须重跑拆层或重新绑定动画时间轴。
- 动画视觉时长可以长于音频时长，用于保证所有 PNG 图层入场和高亮事件完整播放；但不能短于音频时长。

# Validation

- `scene.json` 必须通过 `schemas/scene.schema.json`。
- `layers[]` 至少包含 `background` 加一个主体图层。
- 生产校验使用 `--require-layered`，不再使用 `--require-full-slide`。
- 自动流程优先使用 `--fail-on-blocking-decomposition-warnings`，只让 `severity=blocking` 中断渲染。
- 每个 layer 的 `asset` 必须存在，必须是 PNG，尺寸必须与 `box.w`、`box.h` 一致。
- 每个 layer 的 `box` 必须位于 1920x1080 画布内。
- 不允许 `elements[]`、`type: text`、`type: shape`、`type: line` 或 SVG。
- 底部 `Y=930` 到 `Y=1080` 是字幕安全区，不作为 PPT 主体图层。

# Failure Handling

- 拆层失败：保留 `decomposition_report.json`，回到视觉稿生成阶段调整可拆解构图。
- 内容过密：回到 `plan-slides` 拆页。
- scene 校验失败：修正图层资产、box 或角色后再继续。
- 只有 `full_slide`：只能作为临时诊断预览，不视为生产完成。

# Bad Case Tags

- `data-break`
- `not-animation-friendly`
- `visual-overlap`
- `single-content-group`
- `scene-schema-failed`
- `asset-missing`
- `title-subtitle-merged`
