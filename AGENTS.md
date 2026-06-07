# AGENTS.md

本仓库是“文章转 AI 科普视频”的 Codex 执行框架。Codex 的目标不是把文章拆成过多中间文件，而是直接把文章切分成可审核、可修改、可合成的视频化 PPT 结构。

## 1. 总体原则

- 主版本按 16:9、1920x1080 生产。
- 目标平台是 B 站、抖音、视频号。抖音和视频号先使用横屏主版本，若用户明确要求再做 9:16 适配。
- 表现形式是旁白 + 动效，不做真人口播。
- 图片生成使用 Codex Image Gen。
- TTS 使用 MiniMax。
- 视频合成使用 Remotion，FFmpeg 仅用于编码、转码、抽帧、音视频合并和压缩。
- 人工审核对象必须是图片或视频预览，不把 JSON 作为主要审核对象。
- 文字尽量由渲染器排版，不直接写进 AI 生成图里，避免乱码和后续不可编辑。
- 可复用框架文件进 Git，生产运行产物不进 Git。
- 不限制 slide 数量。slide 数量由文章内容决定，以“讲清楚整篇文章”为准，不用为凑时长或控制页数强行合并。
- 视觉风格固定为温暖极简手绘线稿风，不接受运行期用户自定义风格。后续需要改风格时，直接修改仓库级 `config/style_tokens.yaml` 和固定参考图。

## 2. 标准运行目录

每次生产创建一个 `runs/<run_id>/`：

```text
runs/<run_id>/
  run_manifest.yaml
  inputs/
    article.md
  planning/
    slide_plan.json
  slides/
    slide_001/
      visual_prompt.md
      visual_draft.png
      visual_review.yaml
      scene.json
      render_preview.png
      element_review.yaml
      narration.txt
      tts_text.txt
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

## 3. 固定风格资源

风格不是运行时输入，而是仓库固定资源：

```text
config/style_tokens.yaml
references/style_reference/PPT_template.png
references/style_reference/PPT_example.png
```

- `config/style_tokens.yaml`：机器可读风格参数，定义背景、字号、颜色、布局、字幕、元素语义角色。
- `references/style_reference/PPT_template.png`：固定空白母版参考图，定义标题区、内容框、背景、字幕留白。
- `references/style_reference/PPT_example.png`：固定成品示例参考图，定义内容密度、图文结构和手绘元素风格。
- `references/visual_rules.md` 可作为人类说明文档保留，但不作为主流程运行输入。

## 4. 业务流程与 Skill 调用

### Stage 1: plan-slides

输入：

- `runs/<run_id>/inputs/article.md`

输出：

- `runs/<run_id>/planning/slide_plan.json`
- 可选：每页 `runs/<run_id>/slides/slide_xxx/narration.txt`，内容来自 `slide_plan.json` 中对应 slide 的 `narration`

调用规则：

- 用 `.agents/skills/plan-slides/SKILL.md`。
- 直接把整篇文章切分成 PPT 视频结构，不再先生成 `article_brief.json`。
- 输出必须符合 `schemas/slide_plan.schema.json`。
- 每页只承载一个核心观点、一个问题或一个解释单元。
- 每页必须包含 `slide_id`、`slide_purpose`、`main_title`、`subtitle`、`core_message`、`content`、`narration`。
- `content.content_type` 必须使用 schema 中定义的内容结构，例如概念解释、流程、对比、时间轴、循环、卡片、示例拆解、误区纠正、因果链、框架图、层级结构、矩阵、清单或总结。
- `narration` 是后续 TTS 的直接输入，必须是可直接朗读的中文演讲稿，不写舞台说明。
- 不输出 `target_duration_sec`、`duration_sec`、`language` 这类估算或固定值。

### Stage 2: generate-visual-drafts

输入：

- `runs/<run_id>/planning/slide_plan.json`
- 当前 `slide_id`
- `config/style_tokens.yaml`
- `references/style_reference/PPT_template.png`
- `references/style_reference/PPT_example.png`
- `templates/prompts/visual_draft.prompt.md`

输出：

- `runs/<run_id>/slides/slide_xxx/visual_prompt.md`
- `runs/<run_id>/slides/slide_xxx/visual_draft.png`

调用规则：

- 用 `.agents/skills/generate-visual-drafts/SKILL.md`。
- 根据 `slide_plan.json` 中对应 slide 的标题、副标题、核心信息、内容结构和旁白生成整页静态视觉稿。
- 必须读取固定风格资源，不允许用户运行时改变风格。
- 视觉稿用于第一轮人工审美判断。
- 生成图尽量不含真实正文；真实标题、正文、标签和图表文字后续由渲染器排版。
- 视觉稿必须遵循温暖极简手绘线稿风，底部字幕区保持为空。

### Review Gate 1: 静态视觉审核

输入：

- `visual_draft.png`
- `slide_plan.json` 中对应 slide
- `narration`

输出：

- `visual_review.yaml`

状态：

- `approved`: 进入 `reconstruct-scenes`
- `revise`: 根据修改意见重新生成视觉稿
- `rejected`: 回退到 `plan-slides`

### Stage 3: reconstruct-scenes

输入：

- 已通过的 `visual_draft.png`
- `visual_review.yaml`
- `slide_plan.json` 中对应 slide
- `config/style_tokens.yaml`
- `schemas/scene.schema.json`

输出：

- `scene.json`
- 可选独立素材图

调用规则：

- 用 `.agents/skills/reconstruct-scenes/SKILL.md`。
- 目标不是机械抠图，而是把已审核的视觉方向重建为可控元素。
- 主标题 `main_title` 和副标题 `subtitle` 必须拆成两个独立 text 元素，不能合并、不能做成图片。
- 标题、正文、标签、图表文字必须是可编辑文本元素。
- 手绘框、手绘箭头、关键词下划线、关键词圈注、Token 小块、总结条优先使用 renderer 可控元素。
- 复杂插图、图标组、概念插画可以使用 Codex Image Gen 位图。
- 所有真实文字必须由渲染器排版。
- 简单线稿元素允许使用 `shape`、`line`、`text` 组合生成，但必须符合手绘线稿风。

### Stage 4: render-element-previews

输入：

- `scene.json`
- `config/style_tokens.yaml`
- `visual_draft.png`
- `schemas/scene.schema.json`

输出：

- `render_preview.png`
- 单页 `render_log.md`

调用规则：

- 用 `.agents/skills/render-element-previews/SKILL.md`。
- 预览图必须接近已审核的 `visual_draft.png`。
- 必须检查 schema、资源路径、主标题副标题拆分、字幕安全区。
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

### Stage 5: generate-audio-subtitles

输入：

- `runs/<run_id>/planning/slide_plan.json`
- 当前 `slide_id`
- `config/task.yaml` 中的 MiniMax 配置
- `.env` 中的 MiniMax 凭证

输出：

- `narration.txt`
- `tts_text.txt`
- `voice.mp3`
- `audio_meta.json`
- `subtitles.srt`
- `audio_timeline.json`

调用规则：

- 用 `.agents/skills/generate-audio-subtitles/SKILL.md`。
- 调用 `scripts/minimax_tts.py`。
- `tts_text.txt` 可包含少量必要停顿和少量自然语气标签，但不能在文本开头或结尾使用。
- 字幕必须清洗掉 TTS 控制标签，切成单行，默认每条不超过 28 个中文字符。
- 如果单页旁白过长，先拆分句段，再生成音频。

### Stage 6: bind-animation-timeline

输入：

- `scene.json`
- `audio_timeline.json`
- `slide_plan.json` 中对应 slide
- 当前 `slide_id`
- `config/style_tokens.yaml`

输出：

- `animation_timeline.json`

调用规则：

- 用 `.agents/skills/bind-animation-timeline/SKILL.md`。
- 使用 `slide_plan_path + slide_id`，不再使用旧的 `slide_spec.json`。
- 元素出现时间必须服务旁白，不做无意义动画。
- 默认动画包括 `fade_up`、`fade_in`、`soft_zoom_in`、`highlight`、`line_draw`。
- `animation_timeline.events[].target` 必须存在于 `scene.elements[].id`。
- `linked_segment_id` 如存在，必须对应 `audio_timeline.segments[].id`。
- 主标题和副标题必须作为两个独立 target 处理。
- 如果精确绑定困难，降级为“标题区和内容框 → 主体内容 → 总结条/重点标注”的三段式动画。

### Stage 7: render-video

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
- 字幕叠加必须单行显示，居中靠下，不遮挡内容框主体信息。

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

## 5. 输入输出守恒规则

- 主流程的第一个业务产物是 `slide_plan.json`，不再使用 `article_brief.json`。
- 主流程不再包含 `define-style` 环节，也不再生成 `style_guide.md`。
- 下游需要的字段必须由 `slide_plan.json` 或仓库固定风格资源产生。
- 每个 Skill 输出必须写到固定路径，不只在对话中说明。
- 审核文件必须记录 `status`、`reviewer_notes`、`requested_changes`。
- 任何失败都要能定位到具体 stage，并可写入 `bad_cases/bad_case_log.yaml`。

## 6. Git 规则

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

## 7. MiniMax TTS 规则

- API Key 只能放在 `.env` 或环境变量，不写入仓库。
- 默认使用 HTTP 非流式 T2A。
- 默认请求输出 `hex`，脚本负责解码为音频文件。
- 若 MiniMax 返回错误，保存 `trace_id`、状态码、错误信息到日志。
- 旁白脚本可以使用 MiniMax 支持的停顿标记，但不要滥用。
- 停顿和语气标签不能出现在字幕中。
- 字幕必须单行显示，默认每条不超过 28 个中文字符。

## 8. Bad Case 规则

出现以下情况时记录到 `bad_cases/bad_case_log.yaml`：

- slide_plan.json 对文章切分不完整，遗漏关键内容。
- 静态视觉稿好看但无法拆成可动画元素。
- 元素预览与视觉稿差距过大。
- TTS 语速、音色、停顿明显不符合科普表达。
- 动画与旁白不同步。
- 字幕错字、漏字、时间轴错位或超过单行限制。
- 同类问题出现两次时，必须更新 Skill、模板、schema 或审核清单。
