# AGENTS.md

## Production Override: Image Gen Macro Layers

Effective 2026-06-09, this override supersedes any older text below that says
production should crop semantic layers from `visual_draft.png`.

Default production path:

```text
slide_plan.json -> visual_prompt.md with full-slide reference + macro-layer plan
-> Image Gen/Web Image Gen separate PNG macro layers
-> layer_manifest.json -> scripts/compose_manifest_layers.py
-> scene.json + animation_timeline.json -> preview -> Remotion
```

Rules:

- Do not use code to semantically decompose a full-slide bitmap for production.
- Use `scripts/compose_manifest_layers.py` as the normal Stage 3 path.
- Keep `scripts/decompose_slide_layers.py` only for diagnostics, audits, or an
  explicit fallback run when macro layers are unavailable.
- `scene.visual_source` may be `image_gen_macro_layers_manifest` or
  `codex_image_gen_png_layers`; the former is preferred.
- A valid Image Gen macro package is 3-7 large groups: title, subtitle, 1-4
  body/diagram groups, and optional summary. Do not request many tiny fragments.
- Flat backgrounds should be a manifest color or generated solid PNG. Do not
  split a pure-color background from a full-slide image.
- Macro layer boxes must avoid overlap and keep 40-60px whitespace between
  independent groups.
- Subtitle safe zone must stay empty. For 1920x1080, PPT body layers must end
  at or above `y=930`; scale this proportionally for other canvases.
- Narration, subtitles, and TTS must be regenerated from the actual macro
  layers for the slide. Never reuse another slide's narration/audio/subtitles
  as a production shortcut.
- Each manifest layer should include `text_summary` and `narration_cue` so the
  script and reviewer can verify that the spoken script matches the visible
  content.
- Animation timing must be bound to narration cues. Do not reveal all content
  layers at the start. `summary_group` enters near the end and then highlights.

本仓库是“文章转 AI 科普视频”的 Codex 执行框架。主流程要保证：页面主体由 Codex Image Gen 生成，再从生成图中拆出 PNG 图层，最后由 Remotion 按 PNG 图层做动画。

## 1. 总体原则

- 主版本按 16:9、1920x1080 生产。
- 图片生成使用 Codex Image Gen。
- TTS 使用 MiniMax。
- 视频合成使用 Remotion，FFmpeg 仅用于编码、转码、抽帧、音视频合并和压缩。
- Remotion 只负责 PNG 图层显示、PNG 图层动画、音频播放和字幕叠加。
- Remotion 不负责绘制 text、shape、line、group 或复杂图表。
- 页面主体内容不得由 SVG、HTML/CSS、Canvas、React 或 Remotion 代码补画。
- 生产默认必须拆层：`visual_draft.png` -> `assets/*.png` -> `scene.layers[]` -> `animation_timeline.events[]`。
- `assets/full_slide.png` 只作为拆层来源和审核对照，不是合格生产动画的唯一图层。
- 人工审核对象必须是图片或视频预览，不把 JSON 作为主要审核对象。
- 可复用框架文件进 Git，生产运行产物不进 Git。

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
      decomposition_report.json
      assets/
        full_slide.png
        background.png
        title.png
        subtitle.png
        content_01.png
        content_02.png
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

```text
config/style_tokens.yaml
references/style_reference/PPT模板.png
references/style_reference/PPT示例.png
```

- `PPT模板.png` 锁定标题区、黄色竖线、副标题下划线、开放内容区和底部字幕安全区。
- `PPT示例.png` 锁定内容组织方式、手写感、图标、标注、总结条和视觉密度。
- 中间内容区为开放区域，不生成大圆角内容外框。
- 底部 `Y=930` 到 `Y=1080` 是字幕安全区，不放 PPT 主体内容。

## 4. 阶段流程

### Stage 0: preflight-check

只做检查，不生成内容。必须确认：

- 必需 schemas 存在。
- 固定参考图存在。
- `scripts/decompose_slide_layers.py`、`scripts/validate_run_assets.py`、`scripts/build_remotion_props.py` 存在。
- MiniMax、ffmpeg、Remotion 环境可用。

### Stage 1: plan-slides

把文章直接切分成 `slide_plan.json`。每页只承载一个核心观点、问题或解释单元。

### Stage 2: generate-visual-drafts

输入：

- `slide_plan.json`
- 当前 `slide_id`
- `config/style_tokens.yaml`
- 两张固定参考图

输出：

- `visual_prompt.md`
- `visual_draft.png`

规则：

- 使用 `.agents/skills/generate-visual-drafts/SKILL.md`。
- 视觉稿必须是整页 Image Gen 位图。
- 同时必须适合拆层：对象之间保留 24-40px 干净背景，避免文字压箭头、图标重叠、标签互相覆盖。
- 不得把标题、正文、框线、箭头或图表留给 SVG、React、HTML/CSS、Canvas 或 Remotion 绘制。
- 底部字幕区不得放 PPT 主体内容。

### Review Gate 1: 静态视觉审核

审核 `visual_draft.png`。如果出现对象重叠、文字压线、不可拆、内容过密、字幕区被占用，返回 Stage 2 或 Stage 1。

### Stage 3: reconstruct-scenes

输入：

- 已通过审核的 `visual_draft.png`
- `visual_review.yaml`
- `slide_plan.json`
- `schemas/scene.schema.json`

输出：

- `scene.json`
- `animation_timeline.json`
- `decomposition_report.json`
- `assets/*.png`

规则：

- 使用 `.agents/skills/reconstruct-scenes/SKILL.md`。
- 默认生产运行：

```powershell
python scripts/compose_manifest_layers.py `
  --manifest runs/<run_id>/layer_manifest.json `
  --repo-root .
```

- 旧算法拆图脚本只用于诊断、审计或显式 fallback，不作为默认生产路径：

```powershell
python scripts/decompose_slide_layers.py `
  --run-dir runs/<run_id> `
  --overwrite
```

- `scene.json` 必须使用 `layers[]`，每个 layer 必须是 `type: png`。
- `visual_source` 必须是 `codex_image_gen_png_layers`。
- 生产校验使用：

```powershell
python scripts/validate_run_assets.py `
  --run-dir runs/<run_id> `
  --require-layered
```

- 如果只有 `full_slide`，不能视为生产完成。
- 如果拆层 warning 指向画面重叠或只能拆出单一主体，应回到 Stage 2 重新生成更可拆的视觉稿。
- 拆层 warning 必须看 `severity`：`blocking` 才中断自动流程，`projection_split_used` 默认是 `advisory`，用于复盘而不是直接失败。

### Stage 4: render-element-previews

渲染 `scene.layers[]` 静态预览，确认 PNG 图层组合后接近 `visual_draft.png`，且没有明显重复、溢出、错位或字幕区占用。

### Review Gate 2: 元素渲染审核

审核 `render_preview.png`。如果图层缺失、错位、遮挡或拆层报告有阻塞 warning，回到 Stage 3 或 Stage 2。

### Stage 5: generate-audio-subtitles

根据 `slide_plan.json` 和当前 `slide_id` 生成：

- `narration.txt`
- `tts_text.txt`
- `voice.mp3`
- `subtitles.srt`
- `audio_timeline.json`

规则：

- 中文文案必须以 UTF-8 文件形式写入。Windows/PowerShell 下不要用 here-string 管道把中文传给 Python 再写文件。
- TTS 前抽查 `narration.txt`、`tts_text.txt`、`audio_timeline.json`，不得出现只有 `?` 的字幕段或连续 `??`。

### Stage 6: bind-animation-timeline

输入：

- `scene.json`
- `audio_timeline.json`
- `slide_plan.json`
- `config/style_tokens.yaml`

输出：

- `animation_timeline.json`

规则：

- 使用 `.agents/skills/bind-animation-timeline/SKILL.md`。
- `events[].target` 必须存在于 `scene.layers[].id`。
- 允许同一 target 有多个事件，例如先 `fade_up` 后 `highlight`。
- 只使用 PNG 图层动画：`fade_in`、`fade_up`、`soft_zoom_in`、`slide_in_left`、`highlight`。
- 不使用 `line_draw` 或 `count_up`。
- 如果只有 `full_slide`，回到 Stage 3，不做生产级内部动画。
- `animation_timeline.duration_sec` 可以长于音频，用来保证所有图层入场和高亮事件完整播放；但不能短于 `audio_timeline.duration_sec`。
- 如果 Stage 3 在 TTS 前已经运行过，Stage 5 后必须重跑拆层或重新绑定动画时间轴。

### Stage 7: render-video

Remotion 只显示 PNG 图层、执行 PNG 图层动画、播放音频、叠加单行字幕。运行期 PNG、音频和字幕必须复制到 `scripts/remotion/public/runtime/<run_id>/`，组件内用 `staticFile()` 引用。

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

- `runs/**` 运行内容
- `outputs/**`
- `*.mp4`、`*.wav`、`*.mp3`
- `.env`
