# 文章转 AI 科普视频生产框架

这个仓库用于把文章生产成 AI 科普类视频。当前主流程是：

```text
文章 -> Preflight -> slide_plan.json -> Codex Image Gen 整页视觉稿 -> 人工审核 -> full_slide PNG scene.json -> 页面预览 -> 人工审核 -> MiniMax 语音/字幕 -> PNG 动画时间轴 -> Remotion 渲染 -> 视频审核 -> 成片
```

## 当前决策

- 平台：B 站、抖音、视频号。
- 主比例：16:9，1920x1080。
- 形式：旁白 + 动效，无真人口播。
- 正式生成前必须先跑 Preflight Check。
- 文章进来后，第一步直接切分成 `slide_plan.json`，不再先生成 `article_brief.json`。
- slide 数量不设固定上下限，以讲清楚整篇文章为准。
- 图片生成：Codex Image Gen。
- TTS：MiniMax T2A HTTP。
- 视频合成：Remotion 作为主渲染引擎，FFmpeg 作为媒体处理工具。
- Remotion 只负责 PNG 图层显示、PNG 图层动画、音频播放和字幕叠加；不绘制 text、shape、line、group 或复杂图表。
- 生产默认使用 Codex Image Gen 生成整页位图视觉，模板、示例、标题、内容、图解、线条和标注都必须进入这张位图；Remotion 不得用前端代码补画 PPT 主体内容。
- 默认视觉风格固定，不接受运行期用户自定义风格。
- Git 策略：框架文件进仓库，运行过程和成片不进仓库。

## 目录说明

```text
.agents/skills/       Codex 可复用阶段能力
config/               默认业务配置、风格 token、Git 策略
references/           固定视觉参考图、旁白规则、视觉说明
schemas/              中间产物 JSON Schema
templates/            Prompt、审核清单、运行 manifest 模板
checks/               人工和半自动质检规则
scripts/              MiniMax TTS、Remotion、FFmpeg 相关脚本
runs/                 单次视频生产工作区，默认不进 Git
outputs/              最终导出区，默认不进 Git
bad_cases/            可沉淀进仓库的坏案例记录
```

## 快速开始

1. 复制 `.env.example` 为 `.env`，填入 MiniMax 凭证。
2. 新建一次运行目录：

```text
runs/<run_id>/inputs/article.md
```

3. 按 `AGENTS.md` 从 `preflight-check` 开始执行。
4. 第一阶段业务输出：

```text
runs/<run_id>/planning/slide_plan.json
```

5. 每个审核门只审核图片或视频预览，不直接审核 JSON。

## 固定视觉资源

当前固定参考图为：

```text
references/style_reference/PPT模板.png
references/style_reference/PPT示例.png
```

不要在运行期引入新的风格图。后续如需换风格，直接更新这两张固定参考图和 `config/style_tokens.yaml`。

## Slide Plan

`slide_plan.json` 是文章进入视频化流程后的第一个主业务产物。它包含：

```text
topic.topic_id
topic.topic_name
topic.topic_summary
slides[].slide_id
slides[].slide_purpose
slides[].main_title
slides[].subtitle
slides[].core_message
slides[].content
slides[].narration
```

`content.content_type` 支持概念解释、分点说明、流程结构、对比结构、时间轴、循环结构、卡片组、示例拆解、误区纠正、因果链、框架图、层级结构、矩阵、操作清单和总结页。

## Codex Image Gen 全页视觉

正式生产时，每页先写出绑定固定参考图的视觉提示词：

```powershell
python scripts/write_visual_prompts.py `
  --run-dir runs/<run_id> `
  --overwrite
```

每个提示词都会引用：

```text
references/style_reference/PPT模板.png
references/style_reference/PPT示例.png
```

用 Codex Image Gen 生成的每页最终位图必须保存为：

```text
runs/<run_id>/slides/slide_xxx/visual_draft.png
```

然后把整页位图标准化为 Remotion 输入：

```powershell
python scripts/prepare_full_slide_scenes.py `
  --run-dir runs/<run_id> `
  --overwrite
```

这一步只会复制和缩放 PNG，不会绘制页面内容。它会生成 `assets/full_slide.png`、`scene.json` 和 `animation_timeline.json`。

## PNG 图层 scene

Stage 3 输出的 `scene.json` 使用 PNG 图层模型。生产默认是一个整页 `full_slide` PNG：

```json
{
  "slide_id": "slide_001",
  "source_visual_draft": "runs/demo/slides/slide_001/visual_draft.png",
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
      "z_index": 10
    }
  ]
}
```

如果后续确实要拆层，也只能拆成由图像模型产出的 PNG 层：

```json
{
  "slide_id": "slide_001",
  "canvas": {
    "width": 1920,
    "height": 1080,
    "background": "#FFFDF7"
  },
  "layers": [
    {
      "id": "title_layer",
      "type": "png",
      "asset": "assets/title.png",
      "role": "title",
      "box": {"x": 110, "y": 55, "w": 1200, "h": 86},
      "z_index": 20
    }
  ]
}
```

Remotion 主路径只接受 `layers[]` PNG 图层，不接受旧的 `elements[]` 元素渲染模型。

## MiniMax TTS

脚本位置：

```text
scripts/minimax_tts.py
```

示例：

```powershell
python scripts/minimax_tts.py `
  --text-file runs/demo/slides/slide_001/tts_text.txt `
  --subtitle-text-file runs/demo/slides/slide_001/narration.txt `
  --slide-id slide_001 `
  --emotion calm `
  --out-audio runs/demo/slides/slide_001/voice.mp3 `
  --out-meta runs/demo/slides/slide_001/audio_meta.json `
  --out-srt runs/demo/slides/slide_001/subtitles.srt `
  --out-timeline runs/demo/slides/slide_001/audio_timeline.json
```

需要环境变量：

```text
MINIMAX_API_KEY
MINIMAX_TTS_ENDPOINT
MINIMAX_TTS_MODEL
MINIMAX_TTS_VOICE_ID
MINIMAX_TTS_EMOTION
```

`tts_text.txt` 可以包含少量 MiniMax 停顿和自然语气标签，但字幕必须基于清洗后的 `narration.txt`。

## Remotion Props

渲染前必须生成：

```text
runs/<run_id>/remotion_props.json
```

该文件汇总所有 slide 的 `scene.json`、`voice.mp3`、`audio_timeline.json` 和 `animation_timeline.json`，并作为 Remotion 的 `--props` 输入。

渲染前先做运行目录完整性校验：

```powershell
python scripts/validate_run_assets.py `
  --run-dir runs/<run_id> `
  --require-full-slide
```

最低结构：

```json
{
  "fps": 30,
  "width": 1920,
  "height": 1080,
  "total_duration_sec": 120,
  "slides": [
    {
      "slide_id": "slide_001",
      "start_sec": 0,
      "duration_sec": 18.5,
      "scene": {"layers": []},
      "audio_file": "runs/<run_id>/slides/slide_001/voice.mp3",
      "audio_timeline": {"segments": []},
      "animation_timeline": {"events": []}
    }
  ]
}
```

然后执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/render_remotion.ps1 `
  -RunId <run_id> `
  -Composition ArticleVideo `
  -OutFile runs/<run_id>/video/final.mp4 `
  -PropsFile runs/<run_id>/remotion_props.json
```

## 运行产物

`runs/` 和 `outputs/` 默认被 `.gitignore` 忽略。需要长期复用的内容应沉淀到 `templates/`、`references/`、`schemas/`、`.agents/skills/`、`checks/`、`scripts/` 或 `bad_cases/`。
