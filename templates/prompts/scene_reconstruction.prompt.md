# Scene Reconstruction Prompt

请把通过审核的 `visual_draft.png` 登记为 Remotion 可渲染的 PNG 图层 `scene.json`。

## 基本要求

- 生产默认使用一张整页 `full_slide` PNG，覆盖 1920x1080。
- Remotion 不重新绘制标题、副标题、正文、标签、线条、箭头、图标或图表。
- 不输出 `text`、`shape`、`line`、`group` 或旧 `elements[]`。
- 输出必须符合 `schemas/scene.schema.json`。

## 固定版式

- 背景固定为 `#FFFDF7`。
- 主标题、副标题、黄色竖线和副标题下划线由 Codex Image Gen 生成在整页位图内。
- 中间内容区为开放区域，不生成大圆角外框。
- 底部 `Y=930` 到 `Y=1080` 是字幕安全区，不放 PPT 主体内容；字幕只在视频合成阶段由 `audio_timeline.json` 叠加。

## 推荐输出

```json
{
  "slide_id": "slide_001",
  "source_visual_draft": "runs/<run_id>/slides/slide_001/visual_draft.png",
  "visual_source": "codex_image_gen_full_slide_bitmap",
  "canvas": {
    "width": 1920,
    "height": 1080,
    "background": "#FFFDF7"
  },
  "layers": [
    {
      "id": "full_slide_layer",
      "type": "png",
      "asset": "assets/full_slide.png",
      "role": "full_slide",
      "box": {"x": 0, "y": 0, "w": 1920, "h": 1080},
      "z_index": 10,
      "animation_role": "full_slide_bitmap"
    }
  ]
}
```

## 可选增强

如果确实需要增强动画，可以拆出多个 PNG layer，但这些 PNG 必须来自图像模型或图像裁切结果；不能用前端代码重新绘制主体内容。
