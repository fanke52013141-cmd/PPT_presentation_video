---
name: preflight-check
description: Validate run inputs, repository resources, environment variables, schemas, and local render dependencies before starting production.
---

# Purpose

在正式进入 `plan-slides` 前做一次前置检查，尽早发现缺文件、配置缺失、环境变量未设置、参考图未放入仓库、schema 不存在、Remotion/FFmpeg 依赖不可用等问题。

本阶段不生成内容，不调用图片生成、TTS 或视频渲染。它只做准备状态检查。

# Inputs

```json
{
  "run_id": "<run_id>",
  "article_path": "runs/<run_id>/inputs/article.md",
  "task_config_path": "config/task.yaml",
  "style_tokens_path": "config/style_tokens.yaml",
  "main_reference_image": "references/style_reference/fixed_title_free_content_reference.png",
  "subtitle_reference_image": "references/style_reference/paper_subtitle_background.png",
  "schemas": [
    "schemas/slide_plan.schema.json",
    "schemas/scene.schema.json",
    "schemas/animation_timeline.schema.json",
    "schemas/video_manifest.schema.json"
  ],
  "remotion_project_dir": "scripts/remotion",
  "env_required": ["MINIMAX_API_KEY"],
  "tools_required": ["ffmpeg", "ffprobe"]
}
```

# Outputs

```json
{
  "preflight_report_path": "runs/<run_id>/logs/preflight_report.md",
  "preflight_status": "pass | fail"
}
```

# Procedure

1. 检查 `runs/<run_id>/` 目录是否存在，不存在则创建标准子目录。
2. 检查 `article.md` 是否存在、非空、可读。
3. 检查 `config/task.yaml` 是否存在。
4. 检查 `config/style_tokens.yaml` 是否存在，并包含画布、颜色、字号、字幕区等关键配置。
5. 检查固定参考图是否存在：`fixed_title_free_content_reference.png` 和 `paper_subtitle_background.png`。
6. 检查必要 schema 是否存在并为合法 JSON。
7. 检查 `.agents/skills/**/SKILL.md` 中主流程需要的 Skill 是否存在。
8. 检查 `templates/prompts/visual_draft.prompt.md` 是否存在。
9. 检查 `scripts/minimax_tts.py` 是否存在。
10. 检查 `scripts/remotion` 是否存在。
11. 检查本地环境变量 `MINIMAX_API_KEY` 是否可读取，但不得把真实值写入日志。
12. 检查 `ffmpeg` 和 `ffprobe` 是否可用。
13. 输出 `preflight_report.md`。
14. 若存在 blocking issue，停止主流程，不进入 Stage 1。

# Report Structure

`preflight_report.md` 必须包含：

```md
# Preflight Report

- run_id: <run_id>
- status: pass | fail

## Blocking Issues

- ...

## Warnings

- ...

## Checks

- article_exists: pass | fail
- article_non_empty: pass | fail
- task_config_exists: pass | fail
- style_tokens_exists: pass | fail
- main_reference_exists: pass | fail
- subtitle_reference_exists: pass | fail
- schemas_valid: pass | fail
- skills_exist: pass | fail
- prompt_templates_exist: pass | fail
- minimax_api_key_present: pass | fail
- ffmpeg_available: pass | fail
- ffprobe_available: pass | fail
- remotion_project_exists: pass | fail
```

# Blocking Issues

以下问题必须阻止后续流程：

- `article.md` 缺失或为空。
- `config/style_tokens.yaml` 缺失。
- 固定参考图缺失。
- 必需 schema 缺失或不是合法 JSON。
- 主流程 Skill 缺失。
- `MINIMAX_API_KEY` 缺失，且本次流程需要执行 TTS。
- `ffmpeg` 或 `ffprobe` 不可用，且本次流程需要渲染视频。

# Warnings

以下问题可以写入警告，但不一定阻止 Stage 1：

- `.env` 文件不存在，但环境变量已从系统环境提供。
- `references/visual_rules.md` 不存在。该文件不作为主流程输入，仅供人工参考。
- Remotion 依赖未安装，但当前只进行 Stage 1 到 Stage 3 的文本/结构流程。

# Security Rules

- 不得把 API key、token、cookie、Authorization header 写入报告。
- 检查环境变量时只能记录是否存在，不能记录值。
- 不得把 `.env` 内容写入日志。

# Failure Handling

- 如果 status 为 `fail`，停止主流程，先修复 Blocking Issues。
- 如果只有 warnings，可以进入 Stage 1，但需要在 `generation_log.md` 记录。

# Bad Case Tags

- `preflight-failed`
- `missing-input`
- `missing-style-reference`
- `missing-schema`
- `missing-env`
- `missing-render-dependency`
