# Scene Reconstruction Prompt

请把已经通过审核的 `visual_draft.png` 拆解为 Remotion 可渲染、可逐层动画的 PNG 图层 `scene.json`。

## 基本要求

- 生产默认使用 `codex_image_gen_png_layers`：先保留整页视觉稿为 `assets/full_slide.png`，再从这张 Image Gen 位图中裁切出多个 PNG 图层。
- Remotion 不重新绘制标题、副标题、正文、标签、线条、箭头、图标或图表，只显示裁切得到的 PNG。
- 不输出 `text`、`shape`、`line`、`group` 或旧 `elements[]`。
- 输出必须符合 `schemas/scene.schema.json`。

## 必须拆出的图层

按画面实际内容尽量拆成：

- `background`: 纯背景或模板底层。
- `title`: 主标题 PNG。
- `subtitle`: 副标题 PNG。
- `content_body`: 主要内容块 PNG。
- `diagram`: 图解、示意图、卡片或流程块 PNG。
- `annotation`: 箭头、重点标注、强调标签 PNG。
- `summary`: 总结条或重点结论 PNG。

如果某些对象相互重叠或粘连，不能硬拆成会穿帮的碎片，应保留为同一个 PNG group，并在 `decomposition.warnings[]` 里说明原因。

## 固定版式

- 画布固定为 `1920x1080`。
- 背景固定为暖白 `#FFFDF7`。
- 主标题、副标题、黄色竖线和副标题下划线来自 Image Gen 位图裁切，不由 Remotion 绘制。
- 中间内容区为开放区域，不生成大圆角外框。
- 底部 `Y=930` 到 `Y=1080` 是字幕安全区，不放 PPT 主体内容；字幕只在视频合成阶段由 `audio_timeline.json` 叠加。

## 推荐输出

```json
{
  "slide_id": "slide_001",
  "source_visual_draft": "runs/<run_id>/slides/slide_001/visual_draft.png",
  "visual_source": "codex_image_gen_png_layers",
  "canvas": {
    "width": 1920,
    "height": 1080,
    "background": "#FFFDF7"
  },
  "layers": [
    {
      "id": "background_layer",
      "type": "png",
      "asset": "assets/background.png",
      "role": "background",
      "box": {"x": 0, "y": 0, "w": 1920, "h": 1080},
      "z_index": 0,
      "animation_role": "static_background"
    },
    {
      "id": "title_layer",
      "type": "png",
      "asset": "assets/title.png",
      "role": "title",
      "box": {"x": 95, "y": 45, "w": 980, "h": 95},
      "z_index": 20,
      "animation_role": "title"
    },
    {
      "id": "content_01_layer",
      "type": "png",
      "asset": "assets/content_01.png",
      "role": "diagram",
      "box": {"x": 360, "y": 285, "w": 420, "h": 240},
      "z_index": 31,
      "animation_role": "diagram",
      "content_index": 1
    }
  ],
  "decomposition": {
    "method": "foreground_mask_connected_components",
    "warnings": []
  }
}
```

## 阻塞条件

- 如果视觉稿中对象互相覆盖、文字压在箭头或图标上、总结条进入字幕区，标记为 `revise_visual_draft`，回到视觉生成阶段。
- 如果只能拆出一个主体 group，允许继续生成视频预览，但必须记录 `single_content_group`，并建议重新生成更可拆的画面。
