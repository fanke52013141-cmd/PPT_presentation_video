---
name: preflight-check
description: Validate run inputs, repository resources, environment variables, schemas, and local render dependencies before production.
---

# Purpose

在进入 `plan-slides` 前做前置检查，尽早发现缺文件、配置缺失、环境变量未设置、参考图缺失、schema 缺失、Remotion/FFmpeg 依赖不可用等问题。

本阶段不生成内容，不调用图片生成、TTS 或视频渲染。

# Inputs

```json
{
  "run_id": "<run_id>",
  "article_path": "runs/<run_id>/inputs/article.md",
  "task_config_path": "config/task.yaml",
  "style_tokens_path": "config/style_tokens.yaml",
  "template_reference_image": "references/style_reference/PPT模板.png",
  "example_reference_image": "references/style_reference/PPT示例.png",
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
3. 检查 `config/task.yaml` 和 `config/style_tokens.yaml` 是否存在。
4. 检查固定参考图 `PPT模板.png` 和 `PPT示例.png` 是否存在。
5. 检查必需 schema 是否存在并为合法 JSON。
6. 检查 `.agents/skills/**/SKILL.md` 中主流程需要的 skill 是否存在。
7. 检查 prompt 模板：
   - `templates/prompts/visual_draft.prompt.md`
   - `templates/prompts/scene_reconstruction.prompt.md`
8. 检查主流程脚本：
   - `scripts/write_visual_prompts.py`
   - `scripts/decompose_slide_layers.py`
   - `scripts/validate_run_assets.py`
   - `scripts/build_remotion_props.py`
   - `scripts/minimax_tts.py`
9. 检查 `scripts/remotion` 是否存在。
10. 检查环境变量 `MINIMAX_API_KEY` 是否可读，但不得把真实值写入日志。
11. 检查 `ffmpeg` 和 `ffprobe` 是否可用。
12. 输出 `preflight_report.md`。
13. 若存在 blocking issue，停止主流程，不进入 Stage 1。

# Report Structure

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
- template_reference_exists: pass | fail
- example_reference_exists: pass | fail
- schemas_valid: pass | fail
- skills_exist: pass | fail
- prompt_templates_exist: pass | fail
- decomposition_script_exists: pass | fail
- minimax_api_key_present: pass | fail
- ffmpeg_available: pass | fail
- ffprobe_available: pass | fail
- remotion_project_exists: pass | fail
```

# Blocking Issues

- `article.md` 缺失或为空。
- 固定风格资源缺失。
- 必需 schema 缺失或不是合法 JSON。
- 主流程 skill 缺失。
- `scripts/decompose_slide_layers.py` 或渲染脚本缺失。
- 本次流程需要 TTS 时缺少 `MINIMAX_API_KEY`。
- 本次流程需要渲染视频时缺少 `ffmpeg` 或 `ffprobe`。

# Security Rules

- 不得把 API key、token、cookie、Authorization header 写入报告。
- 检查环境变量时只能记录是否存在，不能记录值。
- 不得把 `.env` 内容写入日志。

# Bad Case Tags

- `preflight-failed`
- `missing-input`
- `missing-style-reference`
- `missing-schema`
- `missing-env`
- `missing-render-dependency`
