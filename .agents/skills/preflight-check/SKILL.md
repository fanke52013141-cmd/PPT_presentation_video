---
name: preflight-check
description: Validate repository resources, run inputs, credentials, schemas, and local render dependencies.
---

# Purpose

在生成和渲染前检查当前 v3 生产链路。此阶段只检查，不调用生图、TTS 或视频渲染。

# Required Files

- `config/pipeline_profiles.yaml`
- `config/style_tokens.yaml`
- `references/style_reference/PPT模板.png`
- `references/style_reference/PPT示例.png`
- `schemas/slide_plan.schema.json`
- `schemas/scene.schema.json`
- `schemas/animation_timeline.schema.json`
- `schemas/video_manifest.schema.json`
- `scripts/write_visual_prompts.py`
- `scripts/build_reveal_scene.py`
- `scripts/validate_reveal_scene.py`
- `scripts/bind_reveal_timeline.py`
- `scripts/build_remotion_props.py`
- `scripts/validate_run_assets.py`
- `scripts/minimax_tts.py`
- `scripts/remotion/`

# Checks

1. `runs/<run_id>` 和输入文章存在且可读。
2. 固定配置、参考图、schema 和生产脚本存在。
3. JSON/YAML 配置可解析。
4. 需要 TTS 时只检查 API Key 是否存在，不记录真实值。
5. `node`、`npm`、`ffmpeg` 和 `ffprobe` 可用。
6. Remotion 依赖可安装，TypeScript 可通过检查。
7. 输出 `runs/<run_id>/logs/preflight_report.md`。

# Blocking Conditions

- 输入文章为空。
- 固定风格资源、schema 或生产脚本缺失。
- 需要 TTS 时没有凭据。
- 需要渲染时 Node、FFmpeg 或 Remotion 不可用。

# Security

不得把 API Key、Token、Cookie、Authorization Header 或 `.env` 内容写入日志。
