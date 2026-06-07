# Preflight Check 清单

检查对象：生产开始前的仓库资源、运行目录和本地环境。

## 必查项

- `runs/<run_id>/inputs/article.md` 存在且非空。
- `config/task.yaml` 存在。
- `config/style_tokens.yaml` 存在。
- `references/style_reference/PPT模板.png` 存在。
- `references/style_reference/PPT示例.png` 存在。
- `schemas/slide_plan.schema.json` 存在且为合法 JSON。
- `schemas/scene.schema.json` 存在且为合法 JSON。
- `schemas/animation_timeline.schema.json` 存在且为合法 JSON。
- `schemas/video_manifest.schema.json` 存在且为合法 JSON。
- 主流程 Skill 均存在：
  - `preflight-check`
  - `plan-slides`
  - `generate-visual-drafts`
  - `reconstruct-scenes`
  - `render-element-previews`
  - `generate-audio-subtitles`
  - `bind-animation-timeline`
  - `render-video`
- `templates/prompts/visual_draft.prompt.md` 存在。
- `templates/prompts/scene_reconstruction.prompt.md` 存在。
- `scripts/write_visual_prompts.py` 存在。
- `scripts/decompose_slide_layers.py` 存在。
- `scripts/validate_run_assets.py` 存在。
- `scripts/build_remotion_props.py` 存在。
- `scripts/minimax_tts.py` 存在。
- `scripts/remotion` 存在。
- `MINIMAX_API_KEY` 可从环境变量或 `.env` 读取，但不得写入日志。
- `ffmpeg` 可用。
- `ffprobe` 可用。

## 输出

```text
runs/<run_id>/logs/preflight_report.md
```

## 阻断条件

- 输入文章缺失或为空。
- 固定风格资源缺失。
- 必需 schema 缺失或非法。
- 主流程 Skill 缺失。
- 拆层脚本或渲染脚本缺失。
- 需要执行 TTS 时缺少 MiniMax API Key。
- 需要渲染视频时缺少 FFmpeg / FFprobe。

## 安全规则

- 不得输出 API key 原文。
- 不得输出 `.env` 内容。
- 只记录环境变量是否存在，不记录具体值。
