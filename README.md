# 文章转 AI 科普视频生产框架

这个仓库用于把文章生产成 AI 科普类 PPT 视频。当前主流程：

```text
文章 -> Preflight -> slide_plan.json -> Codex Image Gen 整页视觉稿 -> 静态视觉审核
-> PNG 图层拆解 scene.json -> 元素预览审核 -> MiniMax 语音/字幕
-> PNG 图层动画时间轴 -> Remotion 渲染 -> 视频审核 -> 成片
```

## 当前决策

- 主比例：16:9，1920x1080。
- 图片生成：Codex Image Gen。
- TTS：MiniMax T2A HTTP。
- 视频合成：Remotion；FFmpeg 只做媒体处理。
- 页面主体必须来自 Codex Image Gen 位图，不允许用 SVG、HTML、CSS、Canvas、React 或 Remotion 代码补画 PPT 主体内容。
- 生产默认不是单张 `full_slide` 淡入，而是从 `visual_draft.png` 裁切多个 PNG layer，再按 layer 做动画。
- `assets/full_slide.png` 只作为原始视觉稿备份和拆层来源；不能作为生产动画的唯一图层。
- 视觉稿生成阶段必须保证可拆解：对象之间留白，避免文字压箭头、图标重叠、总结条进入字幕区。

## 固定视觉资源

固定参考图：

```text
references/style_reference/PPT模板.png
references/style_reference/PPT示例.png
```

当前模板规则：

- 主标题、副标题、黄色竖线和副标题下划线位置固定。
- 中间是无框开放内容区，不生成大圆角黑色内容框。
- 底部 `Y=930` 到 `Y=1080` 是字幕安全区，PPT 主体内容不得进入。
- 图层拆解只能裁切 Image Gen 位图中的内容，不得改用前端绘制。

## 目录说明

```text
.agents/skills/       Codex 可复用阶段能力
config/               默认业务配置、风格 token、Git 策略
references/           固定视觉参考图和规则说明
schemas/              中间产物 JSON Schema
templates/            Prompt、审核清单、manifest 模板
checks/               人工和半自动质检规则
scripts/              拆层、TTS、Remotion、FFmpeg 脚本
runs/                 单次视频生产工作区，默认不进 Git
outputs/              最终导出区，默认不进 Git
bad_cases/            可沉淀进仓库的坏案例记录
```

## 运行主线

1. 新建运行目录：

```text
runs/<run_id>/inputs/article.md
```

2. 按 `AGENTS.md` 从 `preflight-check` 开始执行。

3. 生成视觉提示词：

```powershell
python scripts/write_visual_prompts.py `
  --run-dir runs/<run_id> `
  --overwrite
```

4. 用 Codex Image Gen 生成每页：

```text
runs/<run_id>/slides/slide_xxx/visual_draft.png
```

5. 视觉审核通过后，拆解 PNG 图层：

```powershell
python scripts/decompose_slide_layers.py `
  --run-dir runs/<run_id> `
  --overwrite
```

这一步会生成：

```text
runs/<run_id>/slides/slide_xxx/assets/full_slide.png
runs/<run_id>/slides/slide_xxx/assets/background.png
runs/<run_id>/slides/slide_xxx/assets/title.png
runs/<run_id>/slides/slide_xxx/assets/subtitle.png
runs/<run_id>/slides/slide_xxx/assets/content_*.png
runs/<run_id>/slides/slide_xxx/scene.json
runs/<run_id>/slides/slide_xxx/animation_timeline.json
runs/<run_id>/slides/slide_xxx/decomposition_report.json
```

6. 校验运行资产：

```powershell
python scripts/validate_run_assets.py `
  --run-dir runs/<run_id> `
  --require-layered
```

如果要把拆层 warning 也作为阻塞：

```powershell
python scripts/validate_run_assets.py `
  --run-dir runs/<run_id> `
  --require-layered `
  --fail-on-decomposition-warnings
```

7. 生成 Remotion props：

```powershell
python scripts/build_remotion_props.py `
  --run-dir runs/<run_id> `
  --repo-root .
```

8. 渲染视频：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/render_remotion.ps1 `
  -RunId <run_id> `
  -Composition ArticleVideo `
  -OutFile runs/<run_id>/video/final.mp4 `
  -PropsFile runs/<run_id>/remotion_props.json
```

## Scene 模型

`scene.json` 必须使用 PNG layer：

```json
{
  "slide_id": "slide_001",
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
      "z_index": 0
    },
    {
      "id": "content_01_layer",
      "type": "png",
      "asset": "assets/content_01.png",
      "role": "diagram",
      "box": {"x": 360, "y": 280, "w": 420, "h": 240},
      "z_index": 31
    }
  ]
}
```

禁止：

- `scene.elements[]`
- `type: text`
- `type: shape`
- `type: line`
- SVG / HTML / CSS / Canvas / React 绘制 PPT 主体

## 拆层失败处理

如果 `decomposition_report.json` 出现以下 warning，需要针对性处理：

- `single_content_group`：画面主体粘成一个大组，回到视觉生成阶段增加留白。
- `layer_bbox_overlap`：图层 box 重叠，检查是否需要合并成一个 group 或重新生成视觉稿。
- `no_content_components`：未检测到可拆主体，检查图片是否为空、过浅或生成失败。

对象重叠、文字压线、箭头压字、总结条进入字幕区，都是视觉稿问题，不应靠 Remotion 修补。
