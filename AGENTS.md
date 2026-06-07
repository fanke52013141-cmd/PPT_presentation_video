# AGENTS.md

本仓库是“文章转 AI 科普视频”的 Codex 执行框架。主流程应尽量减少中间环节：文章先直接切分为 PPT 视频结构，再用 Codex Image Gen 生成整页位图视觉，再生成语音字幕、动画时间轴和最终视频。

## 1. 总体原则

- 主版本按 16:9、1920x1080 生产。
- 目标平台是 B 站、抖音、视频号。抖音和视频号先使用横屏主版本，若用户明确要求再做 9:16 适配。
- 表现形式是旁白 + 动效，不做真人口播。
- 图片生成使用 Codex Image Gen。
- TTS 使用 MiniMax。
- 视频合成使用 Remotion，FFmpeg 仅用于编码、转码、抽帧、音视频合并和压缩。
- Remotion 最终只负责 PNG 图层显示、PNG 图层动画、音频播放和字幕叠加；不负责绘制 text、shape、line、group 或复杂图表。
- 正式生产默认每页使用一张 Codex Image Gen 生成的 `full_slide` PNG；模板、示例、标题、内容、图解、线条和标注都必须在位图内完成。
- 人工审核对象必须是图片或视频预览，不把 JSON 作为主要审核对象。
- 可复用框架文件进 Git，生产运行产物不进 Git。
- 不限制 slide 数量。slide 数量由文章内容决定，以“讲清楚整篇文章”为准。
- 视觉风格固定，不接受运行期用户自定义风格。后续需要改风格时，直接修改仓库级 `config/style_tokens.yaml` 和固定参考图。
- 正式生成前必须先跑 Preflight Check。

## 2. 标准运行目录

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
      assets/
        background.png
        title.png
        subtitle.png
        content_body.png
        diagram.png
        annotation.png
        summary.png
      render_preview.png
      render_log.md
      element_review.yaml
      narration.txt
      tts_text.txt
      voice.mp3
      audio_meta.json
      subtitles.srt
      audio_timeline.json
      animation_timeline.json
      preview.mp4
  video/
    rough_cut.mp4
    final.mp4
  logs/
    preflight_report.md
    generation_log.md
    qa_log.md
```

## 3. 固定风格资源

风格不是运行时输入，而是仓库固定资源：

```text
config/style_tokens.yaml
references/style_reference/PPT模板.png
references/style_reference/PPT示例.png
```

- `config/style_tokens.yaml`：机器可读风格参数，定义画布、字幕区、PNG 图层模型、参考图和动画动作。
- `PPT模板.png`：空白模板参考图，用于约束标题区、黄色竖线、副标题下划线、主体大圆角手绘边框和整体留白。
- `PPT示例.png`：完整页面示例图，用于约束内容组织、手写感文字、图标、分栏、标注、总结条和视觉密度。
- `references/visual_rules.md` 可作为人类说明文档保留，但不作为主流程运行输入。

## 4. 业务流程与 Skill 调用

### Stage 0: preflight-check

输入：

- `runs/<run_id>/inputs/article.md`
- `config/task.yaml`
- `config/style_tokens.yaml`
- `references/style_reference/PPT模板.png`
- `references/style_reference/PPT示例.png`
- 必需 schemas
- 主流程 skills
- `.env` 或系统环境变量
- 本地 `ffmpeg` / `ffprobe`
- `scripts/remotion`

输出：

- `runs/<run_id>/logs/preflight_report.md`
- `preflight_status: pass | fail`

调用规则：

- 用 `.agents/skills/preflight-check/SKILL.md`。
- 只做检查，不生成内容，不调用图片生成、TTS 或 Remotion。
- 不得把 API key、token、cookie、Authorization header 或 `.env` 内容写入日志。
- 如果存在 blocking issue，停止主流程，不进入 Stage 1。

### Stage 1: plan-slides

输入：

- `runs/<run_id>/inputs/article.md`

输出：

- `runs/<run_id>/planning/slide_plan.json`

调用规则：

- 用 `.agents/skills/plan-slides/SKILL.md`。
- 直接把整篇文章切分成 PPT 视频结构，不再生成 `article_brief.json`。
- 输出必须符合 `schemas/slide_plan.schema.json`。
- 每页只承载一个核心观点、一个问题或一个解释单元。
- 每页必须包含 `slide_id`、`slide_purpose`、`main_title`、`subtitle`、`core_message`、`content`、`narration`。
- `narration` 是后续 TTS 的直接输入，必须是可直接朗读的中文演讲稿。
- 不输出 `target_duration_sec`、`duration_sec`、`language`。

### Stage 2: generate-visual-drafts

输入：

- `runs/<run_id>/planning/slide_plan.json`
- 当前 `slide_id`
- `config/style_tokens.yaml`
- `references/style_reference/PPT模板.png`
- `references/style_reference/PPT示例.png`
- `templates/prompts/visual_draft.prompt.md`

输出：

- `runs/<run_id>/slides/slide_xxx/visual_prompt.md`
- `runs/<run_id>/slides/slide_xxx/visual_draft.png`

调用规则：

- 用 `.agents/skills/generate-visual-drafts/SKILL.md`。
- 根据 `slide_plan.json` 中对应 slide 的标题、副标题、核心信息、内容结构和旁白生成整页静态视觉稿。
- 必须读取固定参考图，不允许用户运行时改变风格。
- 视觉稿用于第一轮人工审美判断。
- 视觉稿必须是完整整页位图，底部字幕区保持为空。
- 不允许把标题、正文、框线、箭头或图表留给 SVG、React、HTML/CSS、Canvas 或 Remotion 代码绘制。

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
- `schemas/scene.schema.json`

输出：

- `runs/<run_id>/slides/slide_xxx/scene.json`
- `runs/<run_id>/slides/slide_xxx/assets/`

调用规则：

- 用 `.agents/skills/reconstruct-scenes/SKILL.md`。
- 默认把已审核视觉稿登记为一个整页 `full_slide` PNG 图层，不再把 text、shape、line、group 作为 Remotion 主输入。
- `scene.json` 必须使用 `layers[]`，每个 layer 必须是 `type: png`。
- 推荐图层角色：`background`、`title`、`subtitle`、`content_body`、`diagram`、`annotation`、`summary`。
- 主标题和副标题只有在拆出的素材同样来自图像模型 PNG 时才允许拆成独立图层。
- `full_slide` 整页 PNG 是生产默认路径；拆层只是可选增强。
- 所有 PNG 图层素材必须保存到当前 slide 的 `assets/` 目录。

### Stage 4: render-element-previews

输入：

- `scene.json`
- `visual_draft.png`
- `schemas/scene.schema.json`

输出：

- `render_preview.png`
- 单页 `render_log.md`

调用规则：

- 用 `.agents/skills/render-element-previews/SKILL.md`。
- 使用 `scene.layers[]` 渲染静态预览图。
- 必须检查 schema、PNG 资源路径、图层坐标、字幕安全区。
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

### Stage 5: generate-audio-subtitles

输入：

- `runs/<run_id>/planning/slide_plan.json`
- 当前 `slide_id`
- `config/task.yaml` 中的 MiniMax 配置
- `.env` 或系统环境变量中的 MiniMax 凭证

输出：

- `narration.txt`
- `tts_text.txt`
- `voice.mp3`
- `audio_meta.json`
- `subtitles.srt`
- `audio_timeline.json`

调用规则：

- 用 `.agents/skills/generate-audio-subtitles/SKILL.md`。
- 从 `slide_plan.json + slide_id` 读取旁白。
- `tts_text.txt` 可包含少量必要停顿和少量自然语气标签，但不能在文本开头或结尾使用。
- 字幕必须清洗掉 TTS 控制标签，切成单行，默认每条不超过 28 个中文字符。

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
- `animation_timeline.events[].target` 必须存在于 `scene.layers[].id`。
- 默认动画仅包括 `fade_in`、`fade_up`、`soft_zoom_in`、`slide_in_left`、`highlight`。
- 不使用 `line_draw` 或 `count_up` 作为主动画动作。
- 如果只有 `full_slide` 图层，降级为整页淡入或轻微缩放。

### Stage 7: render-video

输入：

- 每页 `scene.json`
- 每页 `animation_timeline.json`
- 每页 `voice.mp3`
- 每页 `audio_timeline.json`
- 每页 `subtitles.srt`
- `run_manifest.yaml`

输出：

- 每页 `preview.mp4`
- 整片 `rough_cut.mp4`
- 整片 `final.mp4`

调用规则：

- 用 `.agents/skills/render-video/SKILL.md`。
- Remotion 只显示 PNG 图层、执行 PNG 图层动画、播放音频、叠加单行字幕。
- Remotion 不绘制 text、shape、line、group 或复杂图表。
- 运行期 PNG、音频和字幕必须复制到 `scripts/remotion/public/runtime/<run_id>/`，组件内用 `staticFile()` 引用。
- FFmpeg 只做媒体合并、转码、压缩和抽帧检查。
- 字幕叠加必须单行显示，居中靠下，不遮挡主体信息。

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
- `revise_scene`: 回到 PNG 图层重建
- `revise_slide`: 回到 slide 规划

## 5. 输入输出守恒规则

- 主流程必须从 `preflight-check` 开始。
- 主流程的第一个业务产物是 `slide_plan.json`，不再使用 `article_brief.json`。
- 主流程不包含 `define-style` 环节，也不生成 `style_guide.md`。
- Remotion 主路径只接受 `scene.layers[]` PNG 图层，不接受 `scene.elements[]` 元素渲染模型。
- 下游需要的字段必须由 `slide_plan.json`、`scene.layers[]`、音频字幕文件或仓库固定资源产生。
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
- `*.mp4`、`*.wav`、`*.mp3`
- `.env`
