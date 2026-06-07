# 文章转 AI 科普视频生产框架

这个仓库用于把文章生产成 AI 科普类视频。核心流程是：

```text
文章 -> Slide 结构脚本 -> 静态视觉稿 -> 人工审核 -> 元素重建 -> 页面预览 -> 人工审核 -> MiniMax 语音 -> Remotion 动画视频 -> 人工审核 -> 成片
```

## 当前决策

- 平台：B 站、抖音、视频号。
- 主比例：16:9，1920x1080。
- 形式：旁白 + 动效，无真人口播。
- 文章进来后，第一步直接切分成 `slide_plan.json`，不再先生成 `article_brief.json`。
- slide 数量不设固定上下限，以讲清楚整篇文章为准。
- 图片生成：Codex Image Gen。
- TTS：MiniMax T2A HTTP。
- 视频合成：Remotion 作为主渲染引擎，FFmpeg 作为媒体处理工具。
- 默认视觉风格：温暖极简手绘线稿风。
- Git 策略：框架文件进仓库，运行过程和成片不进仓库。

## 目录说明

```text
.agents/skills/       Codex 可复用阶段能力
config/               默认业务配置、风格 token、Git 策略
references/           AI 科普风格、旁白、视觉规则
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

3. 让 Codex 按 `AGENTS.md` 的流程执行，从 `plan-slides` 开始。
4. 第一阶段输出：

```text
runs/<run_id>/planning/slide_plan.json
```

5. 每个审核门只审核图片或视频预览，不直接审核 JSON。

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

## MiniMax TTS

脚本位置：

```text
scripts/minimax_tts.py
```

示例：

```powershell
python scripts/minimax_tts.py `
  --text-file runs/demo/slides/slide_001/narration.txt `
  --out-audio runs/demo/slides/slide_001/voice.mp3 `
  --out-meta runs/demo/slides/slide_001/audio_meta.json
```

需要环境变量：

```text
MINIMAX_API_KEY
MINIMAX_TTS_ENDPOINT
MINIMAX_TTS_MODEL
MINIMAX_TTS_VOICE_ID
```

## 运行产物

`runs/` 和 `outputs/` 默认被 `.gitignore` 忽略。需要长期复用的内容应沉淀到 `templates/`、`references/`、`schemas/`、`.agents/skills/` 或 `bad_cases/`。
