# Agent Capability Matrix

- **Agent API Version**: 1.0.0
- **Contract Hash**: `3a2c36ae12289051`
- **Total Capabilities**: 17

This document is auto-generated from `agent_contract/capabilities.py`.
Do not edit manually — run `python scripts/generate_agent_contracts.py`.

## Capability Table

| Capability ID | Version | Status | Method | Agent API Path | MCP Tool | CLI Command | Service Ref | Long-running | Destructive |
|---|---|---|---|---|---|---|---|---|---|
| `project.create` | 1.0 | stable | POST | `/api/agent/v1/projects` | `ppt_project_create` | `project create` | `project_service.ProjectService.create` | No | No |
| `project.list` | 1.0 | stable | GET | `/api/agent/v1/projects` | `ppt_project_list` | `project list` | `project_service.ProjectService.list` | No | No |
| `project.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}` | `ppt_project_get` | `project show` | `project_service.ProjectService.get` | No | No |
| `project.update` | 1.0 | stable | PATCH | `/api/agent/v1/projects/{project_id}` | `ppt_project_update` | `project update` | `project_service.ProjectService.update` | No | No |
| `source.set` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/source` | `ppt_source_set` | `source set` | `article_service.import_article / generate_article_from_topic` | No | No |
| `pipeline.run` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/runs` | `ppt_pipeline_run` | `run start` | `one_click_orchestrator.start_one_click` | Yes | No |
| `pipeline.status` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/runs/latest` | `ppt_pipeline_status` | `run status` | `one_click_orchestrator.get_one_click_status` | No | No |
| `pipeline.resume` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/runs/latest/resume` | `ppt_pipeline_resume` | `run resume` | `one_click_orchestrator.start_one_click` | Yes | No |
| `checkpoint.approve` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/checkpoints/{checkpoint}/approve` | `ppt_checkpoint_approve` | `approve` | `one_click_orchestrator (stage gating)` | No | No |
| `stage.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/stages/{stage}` | `ppt_stage_get` | `stage get` | `various service read functions` | No | No |
| `image.regenerate` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/images/{slide_id}/regenerate` | `ppt_image_regenerate` | `image regenerate` | `image_workflow_service.generate_slide_image` | Yes | No |
| `narration.update` | 1.0 | stable | PATCH | `/api/agent/v1/projects/{project_id}/narration/{slide_id}` | `ppt_narration_update` | `narration update` | `storyboard_service.update_narration` | No | No |
| `tts.synthesize` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/tts` | `ppt_tts_synthesize` | `tts synthesize` | `tts_service.start_synthesis` | Yes | No |
| `video.render` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/videos/render` | `ppt_video_render` | `video render` | `video_render_service.start_render` | Yes | No |
| `artifacts.list` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/artifacts` | `ppt_artifacts_list` | `artifacts list` | `database.ArtifactRecord` | No | No |
| `artifact.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/artifacts/{artifact_id}` | `ppt_artifact_get` | `artifact get` | `database.ArtifactRecord` | No | No |
| `diagnostics` | 1.0 | stable | GET | `/api/agent/v1/diagnostics` | `ppt_diagnostics` | `diagnostics` | `agent_api.routes.get_diagnostics` | No | No |

## Pipeline Checkpoints

| Checkpoint | Label | Internal Stage | Description |
|---|---|---|---|
| `storyboard_review` | 分镜审查 | `storyboard` | 分镜规划完成，等待确认后再生成图片 |
| `image_review` | 图片审查 | `confirm_images` | 图片生成完成，等待确认后再进行 Mask 标注 |
| `mask_review` | Mask 审查 | `mask_assets` | Mask 标注完成，等待确认后再生成旁白 |
| `narration_review` | 旁白审查 | `narration` | 旁白生成完成，等待确认后再合成音频 |
| `audio_review` | 音频审查 | `tts` | 音频合成完成，等待确认后再渲染视频 |
| `video_review` | 视频审查 | `render` | 视频渲染完成，等待最终确认 |

## MCP Tool Summary

The MCP server exposes **17** stable tools:

- `ppt_project_create` — Create a new PPT video project with canvas and mode settings.
- `ppt_project_list` — List all projects with optional status filter.
- `ppt_project_get` — Get project details including article/contract status and slide IDs.
- `ppt_project_update` — Update project name, description, or AI mode.
- `ppt_source_set` — Set project source content — either direct article text or a topic for AI generation.
- `ppt_pipeline_run` — Start or resume the automated pipeline. Supports stop_at checkpoints.
- `ppt_pipeline_status` — Get current pipeline status including stage progress and blocking errors.
- `ppt_pipeline_resume` — Resume a paused or failed pipeline from the last checkpoint.
- `ppt_checkpoint_approve` — Approve or reject a pipeline checkpoint to continue or halt.
- `ppt_stage_get` — Get detailed data for a specific pipeline stage (storyboard, narration, etc.).
- `ppt_image_regenerate` — Regenerate a single slide image with optional modification instruction.
- `ppt_narration_update` — Update narration text for a specific slide.
- `ppt_tts_synthesize` — Start TTS audio synthesis for specified or all slides.
- `ppt_video_render` — Start video rendering for the project.
- `ppt_artifacts_list` — List all artifacts (images, audio, video, pptx) for a project.
- `ppt_artifact_get` — Get details and download URL for a specific artifact.
- `ppt_diagnostics` — Get system diagnostics including API version, capabilities, and health checks.

## Resource URIs

MCP resources use the following URI scheme:

```
ppt://projects/{project_id}/summary
ppt://projects/{project_id}/slides
ppt://projects/{project_id}/slides/{slide_id}/image
ppt://projects/{project_id}/slides/{slide_id}/audio
ppt://projects/{project_id}/videos/latest
ppt://projects/{project_id}/runs/{run_id}/logs
```
