# Agent Capability Matrix

- **Agent API Version**: 2.1.0
- **Contract Hash**: `5dad5233e6fcad65`
- **Total Capabilities**: 34

This document is auto-generated from `agent_contract/capabilities.py`.
Do not edit manually — run `python scripts/generate_agent_contracts.py`.

## Capability Table

| Capability ID | Version | Status | Method | Agent API Path | MCP Tool | MCP enabled | CLI Command | Service Ref | Long-running | Destructive |
|---|---|---|---|---|---|---|---|---|---|---|
| `operation.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/operations/{operation_id}` | `ppt_operation_get` | Yes | `operation get` | `agent_operation_service.AgentOperationService.get` | No | No |
| `operation.list` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/operations` | `ppt_operation_list` | Yes | `operation list` | `agent_operation_service.AgentOperationService.list` | No | No |
| `operation.cancel` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/operations/{operation_id}/cancel` | `ppt_operation_cancel` | Yes | `operation cancel` | `agent_operation_service.AgentOperationService.cancel` | No | No |
| `generation.status` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/generation/{stage}/status` | `ppt_generation_status` | Yes | `generation status` | `generation_control.status` | No | No |
| `generation.stop` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/generation/{stage}/stop` | `ppt_generation_stop` | Yes | `generation stop` | `generation_control.request_stop` | No | No |
| `identity.get` | 1.0 | stable | GET | `/api/agent/v1/identity` | `ppt_identity_get` | Yes | `identity` | `agent_api.auth / account_service` | No | No |
| `project.create` | 1.5 | stable | POST | `/api/agent/v1/projects` | `ppt_project_create` | Yes | `project create` | `project_service.ProjectService.create` | No | No |
| `project.list` | 1.3 | stable | GET | `/api/agent/v1/projects` | `ppt_project_list` | Yes | `project list` | `project_service.ProjectService.list` | No | No |
| `project.get` | 1.2 | stable | GET | `/api/agent/v1/projects/{project_id}` | `ppt_project_get` | Yes | `project show` | `project_service.ProjectService.get` | No | No |
| `project.update` | 1.2 | stable | PATCH | `/api/agent/v1/projects/{project_id}` | `ppt_project_update` | Yes | `project update` | `project_service.ProjectService.update` | No | No |
| `source.set` | 1.1 | stable | POST | `/api/agent/v1/projects/{project_id}/source` | `ppt_source_set` | Yes | `source set` | `article_service.import_article / generate_article_from_topic` | No | No |
| `pipeline.run` | 1.1 | stable | POST | `/api/agent/v1/projects/{project_id}/runs` | `ppt_pipeline_run` | Yes | `run start` | `one_click_orchestrator.start_one_click` | Yes | No |
| `pipeline.status` | 1.1 | stable | GET | `/api/agent/v1/projects/{project_id}/runs/latest` | `ppt_pipeline_status` | Yes | `run status` | `one_click_orchestrator.get_one_click_status` | No | No |
| `pipeline.resume` | 1.1 | stable | POST | `/api/agent/v1/projects/{project_id}/runs/latest/resume` | `ppt_pipeline_resume` | Yes | `run resume` | `one_click_orchestrator.start_one_click` | Yes | No |
| `pipeline.stream` | 1.1 | stable | GET | `/api/agent/v1/projects/{project_id}/runs/latest/stream` | `ppt_pipeline_stream` | No | `run stream` | `agent_api.routes.agent_pipeline_stream` | Yes | No |
| `checkpoint.approve` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/checkpoints/{checkpoint}/approve` | `ppt_checkpoint_approve` | Yes | `approve` | `one_click_orchestrator (stage gating)` | No | No |
| `stage.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/stages/{stage}` | `ppt_stage_get` | Yes | `stage get` | `various service read functions` | No | No |
| `image.regenerate` | 1.1 | stable | POST | `/api/agent/v1/projects/{project_id}/images/{slide_id}/regenerate` | `ppt_image_regenerate` | Yes | `image regenerate` | `image_workflow_service.generate_slide_image` | Yes | No |
| `narration.update` | 1.1 | stable | PATCH | `/api/agent/v1/projects/{project_id}/narration/{slide_id}` | `ppt_narration_update` | Yes | `narration update` | `storyboard_service.update_narration` | No | No |
| `tts.synthesize` | 2.0 | stable | POST | `/api/agent/v1/projects/{project_id}/tts` | `ppt_tts_synthesize` | Yes | `tts synthesize` | `tts_service.TtsAsyncService.create_job` | Yes | No |
| `video.render` | 2.0 | stable | POST | `/api/agent/v1/projects/{project_id}/videos/render` | `ppt_video_render` | Yes | `video render` | `video_render_service.start_render` | Yes | No |
| `artifacts.list` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/artifacts` | `ppt_artifacts_list` | Yes | `artifacts list` | `database.ArtifactRecord` | No | No |
| `artifact.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/artifacts/{artifact_id}` | `ppt_artifact_get` | Yes | `artifact get` | `database.ArtifactRecord` | No | No |
| `diagnostics` | 1.0 | stable | GET | `/api/agent/v1/diagnostics` | `ppt_diagnostics` | Yes | `diagnostics` | `agent_api.routes.get_diagnostics` | No | No |
| `digital_human.config.get` | 1.1 | stable | GET | `/api/agent/v1/projects/{project_id}/digital-human/config` | `ppt_digital_human_config_get` | Yes | `digital-human config` | `digital_human_routes.router` | No | No |
| `digital_human.config.update` | 1.1 | stable | PATCH | `/api/agent/v1/projects/{project_id}/digital-human/config` | `ppt_digital_human_config_update` | Yes | `digital-human config --set` | `digital_human_routes.router` | No | No |
| `digital_human.health` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/digital-human/health` | `ppt_digital_human_health` | Yes | `digital-human health` | `digital_human_client.get_digital_human_client` | No | No |
| `digital_human.generate` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/digital-human/generate-full` | `ppt_digital_human_generate` | Yes | `digital-human generate` | `digital_human_client.get_digital_human_client` | No | No |
| `project.delete` | 1.0 | stable | DELETE | `/api/agent/v1/projects/{project_id}` | `ppt_project_delete` | Yes | `project delete` | `project_service.ProjectService.delete` | No | Yes |
| `checkpoint.list` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/checkpoints` | `ppt_checkpoint_list` | Yes | `checkpoint list` | `agent_api.routes.agent_list_checkpoints` | No | No |
| `image.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/slides/{slide_id}/image` | `ppt_image_get` | No | `image get` | `image_workflow_service.get_slide_image_file` | No | No |
| `audio.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/slides/{slide_id}/audio` | `ppt_audio_get` | No | `audio get` | `tts_service.get_slide_audio_file` | No | No |
| `video.latest` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/videos/latest` | `ppt_video_latest` | No | `video latest` | `video_render_service final_video_download` | No | No |
| `artifact.download` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/artifacts/{artifact_id}/content` | `ppt_artifact_download` | No | `artifact download` | `agent_api.routes.agent_download_artifact` | No | No |

## Pipeline Checkpoints

| Checkpoint | Label | Internal Stage | Description |
|---|---|---|---|
| `storyboard_review` | 分镜审查 | `storyboard` | 分镜规划完成，等待确认后再生成图片 |
| `image_review` | 图片审查 | `confirm_images` | 图片生成完成，等待确认后再进行 Mask 标注 |
| `mask_review` | Mask 审查 | `ai_mask` | Mask 标注完成，等待确认后再生成旁白 |
| `narration_review` | 旁白审查 | `narration` | 旁白生成完成，等待确认后再合成音频 |
| `audio_review` | 音频审查 | `tts` | 音频合成完成，等待确认后再渲染视频 |
| `video_review` | 视频审查 | `render` | 视频渲染完成，等待最终确认 |

## MCP Tool Summary

The registry contributes **29** stable capability tools, plus the fixed search/describe/invoke discovery tools:

- `ppt_operation_get` — Read an exact durable job or pipeline run by operation_id; never substitute latest.
- `ppt_operation_list` — List project operations across durable jobs and pipeline history, with pagination.
- `ppt_operation_cancel` — Request exact TTS/video cancellation at a safe boundary. accepted does not imply cancelled; poll operation.get. Other producers explicitly report unsupported.
- `ppt_generation_status` — Read the active cooperative generation control for a project stage. Controls are process-local; durable TTS/video results remain in their job APIs.
- `ppt_generation_stop` — Request a safe-boundary stop for the exact active operation ID. In-flight provider requests and render stages finish before stopping.
- `ppt_identity_get` — Return the creative account and scopes associated with this Agent connection.
- `ppt_project_create` — Create a project with canvas, production/presentation mode, versioned creation configuration, and optional course/chapter ownership.
- `ppt_project_list` — List all projects with optional status filter.
- `ppt_project_get` — Get project details including article/contract status, slide IDs, and mask mode.
- `ppt_project_update` — Update project name, description, AI mode, production mode, or presentation mode.
- `ppt_source_set` — Set project source content — either direct article text or a topic for AI generation.
- `ppt_pipeline_run` — Start or resume the automated pipeline. Supports stop_at checkpoints.
- `ppt_pipeline_status` — Get current pipeline status including stage progress and blocking errors.
- `ppt_pipeline_resume` — Resume a paused or failed pipeline from the last checkpoint.
- `ppt_checkpoint_approve` — Approve or reject a pipeline checkpoint to continue or halt.
- `ppt_stage_get` — Get detailed data for a specific pipeline stage (storyboard, narration, etc.).
- `ppt_image_regenerate` — Regenerate a single slide image with optional modification instruction.
- `ppt_narration_update` — Update narration text for a specific slide.
- `ppt_tts_synthesize` — Submit durable background TTS synthesis for the whole project. Returns operation_id for operation.get; slide_ids is not supported yet.
- `ppt_video_render` — Start video rendering for the project.
- `ppt_artifacts_list` — List all artifacts (images, audio, video, pptx) for a project.
- `ppt_artifact_get` — Get details and download URL for a specific artifact.
- `ppt_diagnostics` — Get system diagnostics including API version, capabilities, and health checks.
- `ppt_digital_human_config_get` — Get digital-human configuration for a project.
- `ppt_digital_human_config_update` — Update digital-human configuration for a project.
- `ppt_digital_human_health` — Check digital-human service availability and model readiness.
- `ppt_digital_human_generate` — Trigger full digital-human video generation for all slides.
- `ppt_project_delete` — Delete a project and all of its derived artifacts. Destructive and irreversible.
- `ppt_checkpoint_list` — List the pipeline checkpoints available for a project.

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
