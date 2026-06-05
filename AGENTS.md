# AGENTS.md

本仓库是“文章转 AI 科普视频”的 Codex 执行框架。Codex 的目标不是一次性写文案，而是按固定业务流把文章转成可审核、可修改、可合成的视频工程。

## 1. 总体原则

- 主版本按 16:9、1920x1080、3 到 6 分钟生产。
- 目标平台是 B 站、抖音、视频号。抖音和视频号先使用横屏主版本，若用户明确要求再做 9:16 适配。
- 表现形式是旁白 + 动效，不做真人口播。
- 图片生成使用 Codex Image Gen。
- TTS 使用 MiniMax。
- 视频合成使用 Remotion，FFmpeg 仅用于编码、转码、抽帧、音视频合并和压缩。
- 人工审核对象必须是图片或视频预览，不把 JSON 作为主要审核对象。
- 文字尽量由渲染器排版，不直接写进 AI 生成图里，避免乱码和后续不可编辑。
- 可复用框架文件进 Git，生产运行产物不进 Git。

## 2. 标准运行目录

每次生产创建一个 `runs/<run_id>/`：

```text
runs/<run_id>/
  run_manifest.yaml
  inputs/
    article.md
  planning/
    article_brief.json
    video_outline.json
    slide_plan.json
    style_guide.md
  slides/
    slide_001/
      slide_spec.json
      visual_prompt.md
      visual_draft.png
      visual_review.yaml
      scene.json
      render_preview.png
      element_review.yaml
      narration.txt
      voice.mp3
      subtitles.srt
      audio_timeline.json
      animation_timeline.json
      preview.mp4
  video/
    rough_cut.mp4
    final.mp4
  logs/
    generation_log.md
    qa_log.md
```

## 3. 业务流程与 Skill 调用

### Stage 1: ingest-article

输入：

- `runs/<run_id>/inputs/article.md`
- 可选来源链接、用户补充背景、事实核查资料

输出：

- `runs/<run_id>/planning/article_brief.json`

调用规则：

- 用 `.agents/skills/ingest-article/SKILL.md`。
- 保留原文核心观点、论据、术语和风险点。
- 如果事实不确定，写入 `risk_notes`，不要自行编造。

### Stage 2: plan-slides

输入：

- `article_brief.json`
- `config/task.yaml`
- `references/narration_rules.md`

输出：

- `runs/<run_id>/planning/video_outline.json`
- `runs/<run_id>/planning/slide_plan.json`
- 每页 `runs/<run_id>/slides/slide_xxx/slide_spec.json`
- 每页 `runs/<run_id>/slides/slide_xxx/narration.txt`

调用规则：

- 用 `.agents/skills/plan-slides/SKILL.md`。
- 每页只承载一个核心观点。
- 3 到 6 分钟视频通常建议 8 到 14 页 slide。
- 每页必须包含主标题、副标题、核心信息、屏幕内容、旁白、配图要求和动画意图。
- 同一条视频不能所有页面使用同一版式；至少轮换 3 种以上内容区布局，8 页以上主版本优先使用 6 到 8 种布局。

### Stage 3: define-style

输入：

- `config/task.yaml`
- `config/style_tokens.yaml`
- 可选用户提供的样式参考

输出：

- `runs/<run_id>/planning/style_guide.md`
- 更新后的 `style_tokens.yaml` 草案，若用户确认后再沉淀进 `config/style_tokens.yaml`

调用规则：

- 用 `.agents/skills/define-style/SKILL.md`。
- 默认使用“清晰、现代、可信、教育解释型”的 AI 科普风格。
- 用户给样式图后，先提取风格差异，不直接覆盖仓库默认配置。

### Stage 4: generate-visual-drafts

输入：

- `slide_spec.json`
- `style_guide.md`
- `config/style_tokens.yaml`
- `templates/prompts/visual_draft.prompt.md`

输出：

- `visual_prompt.md`
- `visual_draft.png`

调用规则：

- 用 `.agents/skills/generate-visual-drafts/SKILL.md`。
- 使用 Codex Image Gen 生成整页静态视觉稿。
- 配图资产也必须来自 Codex Image Gen 位图；不得用 SVG、HTML、Canvas 或 shape/text 组合伪造配图。
- 视觉稿用于第一轮人工审美判断。
- 生成图尽量不含文字，或只保留抽象图形和背景。

### Review Gate 1: 静态视觉审核

输入：

- `visual_draft.png`
- `slide_spec.json`
- `narration.txt`

输出：

- `visual_review.yaml`

状态：

- `approved`: 进入 `reconstruct-scenes`
- `revise`: 根据修改意见重新生成视觉稿
- `rejected`: 回退到 `slide_spec` 或风格阶段

### Stage 5: reconstruct-scenes

输入：

- 已通过的 `visual_draft.png`
- `slide_spec.json`
- `style_tokens.yaml`

输出：

- `scene.json`
- 可选独立素材图

调用规则：

- 用 `.agents/skills/reconstruct-scenes/SKILL.md`。
- 目标不是机械抠图，而是把已审核的视觉方向重建为可控元素。
- 标题、正文、标签、图表文字必须是可编辑文本元素。
- 背景、插图、图标、图表主体可以是图片元素；凡承担“配图”功能的视觉主体必须是 Codex Image Gen 生成的位图 `image` 元素。
- `shape` 只用于卡片底、强调点、辅助分隔等 UI 容器，不用于拼装文件、时钟、流程图等配图主体。

### Stage 6: render-element-previews

输入：

- `scene.json`

输出：

- `render_preview.png`
- 可选渲染日志

调用规则：

- 用 `.agents/skills/render-element-previews/SKILL.md`。
- 预览图必须接近已审核的 `visual_draft.png`。
- 若差异过大，回到 `reconstruct-scenes`。

### Review Gate 2: 元素渲染审核

输入：

- `render_preview.png`
- `visual_draft.png`
- `scene.json`

输出：

- `element_review.yaml`

状态：

- `approved`: 进入语音和动画阶段
- `revise`: 修改 `scene.json`
- `rejected`: 回到视觉稿阶段

### Stage 7: generate-audio-subtitles

输入：

- `narration.txt`
- `config/task.yaml` 中的 MiniMax 配置
- `.env` 中的 MiniMax 凭证

输出：

- `voice.mp3`
- `audio_meta.json`
- `subtitles.srt`
- `audio_timeline.json`

调用规则：

- 用 `.agents/skills/generate-audio-subtitles/SKILL.md`。
- 调用 `scripts/minimax_tts.py`。
- 每页旁白建议 120 到 180 字以内。
- 如果单页旁白过长，先拆分句段，再生成音频。

### Stage 8: bind-animation-timeline

输入：

- `scene.json`
- `audio_timeline.json`
- `slide_spec.json`

输出：

- `animation_timeline.json`

调用规则：

- 用 `.agents/skills/bind-animation-timeline/SKILL.md`。
- 元素出现时间必须服务旁白，不做无意义动画。
- 默认动画包括 `fade_up`、`fade_in`、`soft_zoom_in`、`highlight`、`line_draw`。

### Stage 9: render-video

输入：

- 每页 `scene.json`
- 每页 `animation_timeline.json`
- 每页 `voice.mp3`
- `run_manifest.yaml`

输出：

- 每页 `preview.mp4`
- 整片 `rough_cut.mp4`
- 整片 `final.mp4`

调用规则：

- 用 `.agents/skills/render-video/SKILL.md`。
- 主渲染使用 Remotion。
- FFmpeg 只做媒体合并、转码和压缩。
- Remotion 运行期资源必须复制到 `scripts/remotion/public/runtime/<run_id>/`，组件内用 `staticFile()` 引用，不直接使用 `file:///` 本地路径。
- 先渲染结构版或短预览确认资源路径和画面非黑屏，再执行完整 TTS 视频渲染。
- 若最终主版本低于 180 秒，优先回到 `plan-slides` 拆页或补足讲解层次，不用延长停顿凑时长。
- 字幕叠加必须按底图字幕框垂直居中，抽帧检查单行和双行字幕是否都落在虚线框中心。

### Review Gate 3: 视频预览审核

输入：

- `preview.mp4` 或 `rough_cut.mp4`
- `subtitles.srt`
- `audio_timeline.json`
- `animation_timeline.json`

输出：

- `qa_log.md`

状态：

- `approved`: 导出最终视频
- `revise_audio`: 回到 TTS
- `revise_animation`: 回到动画绑定
- `revise_scene`: 回到元素重建
- `revise_slide`: 回到 slide 规划

## 4. 输入输出守恒规则

- 下游需要的字段必须由上游产生，或明确标记为用户提供。
- 每个 Skill 输出必须写到固定路径，不只在对话中说明。
- 审核文件必须记录 `status`、`reviewer_notes`、`requested_changes`。
- 任何失败都要能定位到具体 stage，并可写入 `bad_cases/bad_case_log.yaml`。

## 5. Git 规则

提交：

- `AGENTS.md`
- `.agents/skills/**/SKILL.md`
- `config/**`
- `references/**`
- `schemas/**`
- `templates/**`
- `checks/**`
- `scripts/**`
- `bad_cases/bad_case_log.yaml`
- `README.md`
- `.gitignore`

不提交：

- `runs/**` 的运行内容
- `outputs/**`
- `*.mp4`、`*.wav`、`*.mp3`、`*.png`、`*.jpg`、`*.webp`
- `.env`

## 6. 样式规则

默认风格见 `config/style_tokens.yaml` 和 `references/visual_rules.md`。如果用户提供参考样式，先生成“样式差异说明”，再更新 `style_guide.md`。只有用户明确确认后，才更新仓库级 `config/style_tokens.yaml`。

## 7. MiniMax TTS 规则

- API Key 只能放在 `.env` 或环境变量，不写入仓库。
- 默认使用 HTTP 非流式 T2A。
- 默认请求输出 `hex`，脚本负责解码为音频文件。
- 若 MiniMax 返回错误，保存 `trace_id`、状态码、错误信息到日志。
- 旁白脚本可以使用 MiniMax 支持的停顿标记 `<#0.5#>`，但不要滥用。

## 8. Bad Case 规则

出现以下情况时记录到 `bad_cases/bad_case_log.yaml`：

- 静态视觉稿好看但无法拆成可动画元素。
- 元素预览与视觉稿差距过大。
- TTS 语速、音色、停顿明显不符合科普表达。
- 动画与旁白不同步。
- 字幕错字、漏字、时间轴错位。
- 同类问题出现两次时，必须更新 Skill、模板、schema 或审核清单。

