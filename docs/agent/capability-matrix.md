# Agent Capability Matrix

- **Agent API Version**: 2.8.0
- **Contract Hash**: `943a745ec66c7c4b`
- **Total Capabilities**: 273

This document is auto-generated from `agent_contract/capabilities.py`.
Do not edit manually — run `python scripts/generate_agent_contracts.py`.

## Capability Table

| Capability ID | Version | Status | Method | Agent API Path | MCP Tool | MCP enabled | CLI Command | Service Ref | Long-running | Destructive |
|---|---|---|---|---|---|---|---|---|---|---|
| `project.state` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/state` | `ppt_project_state` | Yes | `project state` | `agent_workflow_service.inspect_project_state` | No | No |
| `operation.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/operations/{operation_id}` | `ppt_operation_get` | Yes | `operation get` | `agent_operation_service.AgentOperationService.get` | No | No |
| `operation.list` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/operations` | `ppt_operation_list` | Yes | `operation list` | `agent_operation_service.AgentOperationService.list` | No | No |
| `operation.cancel` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/operations/{operation_id}/cancel` | `ppt_operation_cancel` | Yes | `operation cancel` | `agent_operation_service.AgentOperationService.cancel` | No | No |
| `generation.status` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/generation/{stage}/status` | `ppt_generation_status` | Yes | `generation status` | `generation_control.status` | No | No |
| `generation.stop` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/generation/{stage}/stop` | `ppt_generation_stop` | Yes | `generation stop` | `generation_control.request_stop` | No | No |
| `identity.get` | 1.0 | stable | GET | `/api/agent/v1/identity` | `ppt_identity_get` | Yes | `identity` | `agent_api.auth / account_service` | No | No |
| `project.create` | 1.5 | stable | POST | `/api/agent/v1/projects` | `ppt_project_create` | Yes | `project create` | `project_service.ProjectService.create` | No | No |
| `project.list` | 1.4 | stable | GET | `/api/agent/v1/projects` | `ppt_project_list` | Yes | `project list` | `project_service.ProjectService.list` | No | No |
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
| `artifacts.list` | 1.1 | stable | GET | `/api/agent/v1/projects/{project_id}/artifacts` | `ppt_artifacts_list` | Yes | `artifacts list` | `database.ArtifactRecord` | No | No |
| `artifact.get` | 1.1 | stable | GET | `/api/agent/v1/projects/{project_id}/artifacts/{artifact_id}` | `ppt_artifact_get` | Yes | `artifact get` | `database.ArtifactRecord` | No | No |
| `diagnostics` | 1.0 | stable | GET | `/api/agent/v1/diagnostics` | `ppt_diagnostics` | Yes | `diagnostics` | `agent_api.routes.get_diagnostics` | No | No |
| `digital_human.config.get` | 1.1 | stable | GET | `/api/agent/v1/projects/{project_id}/digital-human/config` | `ppt_digital_human_config_get` | Yes | `digital-human config` | `digital_human_routes.router` | No | No |
| `digital_human.config.update` | 1.1 | stable | PATCH | `/api/agent/v1/projects/{project_id}/digital-human/config` | `ppt_digital_human_config_update` | Yes | `digital-human config --set` | `digital_human_routes.router` | No | No |
| `digital_human.health` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/digital-human/health` | `ppt_digital_human_health` | Yes | `digital-human health` | `digital_human_client.get_digital_human_client` | No | No |
| `digital_human.generate` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/digital-human/generate-full` | `ppt_digital_human_generate` | Yes | `digital-human generate` | `digital_human_client.get_digital_human_client` | No | No |
| `project.delete` | 1.1 | stable | DELETE | `/api/agent/v1/projects/{project_id}` | `ppt_project_delete` | Yes | `project delete` | `project_service.ProjectService.delete` | No | Yes |
| `checkpoint.list` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/checkpoints` | `ppt_checkpoint_list` | Yes | `checkpoint list` | `agent_api.routes.agent_list_checkpoints` | No | No |
| `image.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/slides/{slide_id}/image` | `ppt_image_get` | No | `image get` | `image_workflow_service.get_slide_image_file` | No | No |
| `audio.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/slides/{slide_id}/audio` | `ppt_audio_get` | No | `audio get` | `tts_service.get_slide_audio_file` | No | No |
| `video.latest` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/videos/latest` | `ppt_video_latest` | No | `video latest` | `video_render_service final_video_download` | No | No |
| `artifact.download` | 1.1 | stable | GET | `/api/agent/v1/projects/{project_id}/artifacts/{artifact_id}/content` | `ppt_artifact_download` | No | `artifact download` | `agent_api.routes.agent_download_artifact` | No | No |
| `article.settings.get` | 1.0 | stable | GET | `/api/agent/v1/article/settings` | `ppt_article_settings_get` | Yes | `article settings` | `article_service.get_article_generation_settings` | No | No |
| `article.settings.update` | 1.0 | stable | PUT | `/api/agent/v1/article/settings` | `ppt_article_settings_update` | Yes | `article settings --set` | `article_service.update_article_generation_settings` | No | No |
| `article.result.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/article` | `ppt_article_get` | Yes | `article show` | `article_service.get_step1_result` | No | No |
| `article.result.update` | 1.0 | stable | PUT | `/api/agent/v1/projects/{project_id}/article` | `ppt_article_update` | Yes | `article update` | `article_service.update_step1_result` | No | No |
| `storyboard.templates.list` | 1.0 | stable | GET | `/api/agent/v1/storyboard/templates` | `ppt_storyboard_templates_list` | Yes | `storyboard templates` | `storyboard_service.get_storyboard_templates` | No | No |
| `storyboard.templates.save` | 1.0 | stable | POST | `/api/agent/v1/storyboard/templates` | `ppt_storyboard_templates_save` | Yes | `storyboard template-save` | `storyboard_service.save_storyboard_template` | No | No |
| `storyboard.templates.delete` | 1.0 | stable | DELETE | `/api/agent/v1/storyboard/templates/{template_id}` | `ppt_storyboard_templates_delete` | Yes | `storyboard template-delete` | `storyboard_service.delete_storyboard_template` | No | No |
| `storyboard.prompt_templates.list` | 1.0 | stable | GET | `/api/agent/v1/storyboard/prompt-templates` | `ppt_step2_prompt_templates_list` | Yes | `storyboard prompt-templates` | `storyboard_service.get_step2_prompt_templates` | No | No |
| `storyboard.prompt_templates.get` | 1.0 | stable | GET | `/api/agent/v1/storyboard/prompt-templates/{template_id}` | `ppt_step2_prompt_templates_get` | Yes | `storyboard prompt-template` | `storyboard_service.get_step2_prompt_template` | No | No |
| `storyboard.prompt_templates.save` | 1.0 | stable | POST | `/api/agent/v1/storyboard/prompt-templates` | `ppt_step2_prompt_templates_save` | Yes | `storyboard prompt-template-save` | `storyboard_service.save_step2_prompt_template` | No | No |
| `storyboard.prompt_templates.delete` | 1.0 | stable | DELETE | `/api/agent/v1/storyboard/prompt-templates/{template_id}` | `ppt_step2_prompt_templates_delete` | Yes | `storyboard prompt-template-delete` | `storyboard_service.delete_step2_prompt_template` | No | No |
| `storyboard.rules.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/storyboard/rules` | `ppt_storyboard_rules_get` | Yes | `storyboard rules` | `storyboard_service.get_step2_rules` | No | No |
| `storyboard.rules.update` | 1.0 | stable | PUT | `/api/agent/v1/projects/{project_id}/storyboard/rules` | `ppt_storyboard_rules_update` | Yes | `storyboard rules --set` | `storyboard_service.update_step2_rules` | No | No |
| `storyboard.prompts.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/storyboard/prompts` | `ppt_storyboard_prompts_get` | Yes | `storyboard prompts` | `storyboard_service.get_step2_prompts` | No | No |
| `storyboard.prompts.update` | 1.0 | stable | PUT | `/api/agent/v1/projects/{project_id}/storyboard/prompts` | `ppt_storyboard_prompts_update` | Yes | `storyboard prompts --set` | `storyboard_service.update_step2_prompts` | No | No |
| `storyboard.script.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/storyboard/script` | `ppt_storyboard_script_get` | Yes | `storyboard script` | `storyboard_service.get_step2_script_plan` | No | No |
| `storyboard.script.update` | 1.0 | stable | PUT | `/api/agent/v1/projects/{project_id}/storyboard/script` | `ppt_storyboard_script_update` | Yes | `storyboard script --set` | `storyboard_service.update_step2_script_plan` | No | No |
| `storyboard.script.execute` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/storyboard/script/execute` | `ppt_storyboard_script_execute` | Yes | `storyboard script-execute` | `storyboard_service.execute_step2_script_plan` | Yes | No |
| `storyboard.visual.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/storyboard/visual` | `ppt_storyboard_visual_get` | Yes | `storyboard visual` | `storyboard_service.get_step2_visual_plan` | No | No |
| `storyboard.visual.update` | 1.0 | stable | PUT | `/api/agent/v1/projects/{project_id}/storyboard/visual` | `ppt_storyboard_visual_update` | Yes | `storyboard visual --set` | `storyboard_service.update_step2_visual_plan` | No | No |
| `storyboard.visual.execute` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/storyboard/visual/execute` | `ppt_storyboard_visual_execute` | Yes | `storyboard visual-execute` | `storyboard_service.execute_step2_visual_plan` | Yes | No |
| `storyboard.compose` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/storyboard/compose` | `ppt_storyboard_compose` | Yes | `storyboard compose` | `storyboard_service.compose_step2_visual_contract` | Yes | No |
| `storyboard.preview` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/storyboard/preview` | `ppt_storyboard_preview` | Yes | `storyboard preview` | `storyboard_service.get_step2_prompt_preview` | No | No |
| `storyboard.contract.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/storyboard/contract` | `ppt_storyboard_contract_get` | Yes | `storyboard contract` | `storyboard_service.get_step2_result` | No | No |
| `storyboard.contract.update` | 1.0 | stable | PUT | `/api/agent/v1/projects/{project_id}/storyboard/contract` | `ppt_storyboard_contract_update` | Yes | `storyboard contract --set` | `storyboard_service.update_step2_result` | No | No |
| `storyboard.contract.repair` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/storyboard/contract/repair` | `ppt_storyboard_contract_repair` | Yes | `storyboard contract-repair` | `storyboard_service.repair_step2_result` | No | No |
| `storyboard.skeleton.submit` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/storyboard/manual-skeleton` | `ppt_storyboard_skeleton_submit` | Yes | `storyboard skeleton` | `storyboard_service.submit_step2_manual_skeleton` | No | No |
| `storyboard.execute` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/storyboard/execute` | `ppt_storyboard_execute` | Yes | `storyboard execute-legacy` | `storyboard_service.execute_step2` | Yes | No |
| `narration.init` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/narration/init` | `ppt_narration_init` | Yes | `narration init` | `narration_service.init_step6_narration` | No | No |
| `narration.result.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/narration` | `ppt_narration_result_get` | Yes | `narration show` | `narration_service.get_step6_result` | No | No |
| `narration.result.update` | 1.0 | stable | PUT | `/api/agent/v1/projects/{project_id}/narration` | `ppt_narration_result_update` | Yes | `narration update-result` | `narration_service.update_step6_result` | No | No |
| `narration.repair` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/narration/repair` | `ppt_narration_repair` | Yes | `narration repair` | `narration_service.repair_step6_result` | No | No |
| `narration.annotation_settings.get` | 1.0 | stable | GET | `/api/agent/v1/narration-annotation/settings` | `ppt_narration_annotation_settings_get` | Yes | `narration annotation-settings` | `narration_service.get_narration_annotation_settings` | No | No |
| `narration.annotation_settings.update` | 1.0 | stable | PUT | `/api/agent/v1/narration-annotation/settings` | `ppt_narration_annotation_settings_update` | Yes | `narration annotation-settings --set` | `narration_service.update_narration_annotation_settings` | No | No |
| `narration.annotate` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/narration/annotate` | `ppt_narration_annotate` | Yes | `narration annotate` | `narration_service.annotate_step6_narration` | Yes | No |
| `tts.sync_synthesize` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/tts/sync` | `ppt_tts_sync_synthesize` | Yes | `tts synthesize-sync` | `tts_service.synthesize_tts_resumable` | Yes | No |
| `tts.audio_status.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/tts/audio-status` | `ppt_tts_audio_status_get` | Yes | `tts audio-status` | `tts_service.get_tts_audio_status` | No | No |
| `tts.audio.confirm` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/tts/confirm` | `ppt_tts_audio_confirm` | Yes | `tts confirm` | `tts_service.confirm_tts_audio` | No | No |
| `media.background.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/media/background` | `ppt_media_background_get` | Yes | `media background` | `visual_settings_service.VisualSettingsService.get` | No | No |
| `media.background.update` | 1.0 | stable | PUT | `/api/agent/v1/projects/{project_id}/media/background` | `ppt_media_background_update` | Yes | `media background --set` | `visual_settings_service.VisualSettingsService.update_background` | No | No |
| `media.subtitles.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/media/subtitles` | `ppt_media_subtitles_get` | Yes | `media subtitles` | `visual_settings_service.VisualSettingsService.get_subtitles` | No | No |
| `media.subtitles.update` | 1.0 | stable | PUT | `/api/agent/v1/projects/{project_id}/media/subtitles` | `ppt_media_subtitles_update` | Yes | `media subtitles --set` | `visual_settings_service.VisualSettingsService.update_subtitles` | No | No |
| `video.list` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/videos` | `ppt_video_list` | Yes | `video list` | `video_render_service.VideoRenderService.list_videos` | No | No |
| `video.download` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/videos/{filename}/content` | `ppt_video_download` | No | `video download` | `video_render_service.VideoRenderService.video_download` | No | No |
| `video.status.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/video/status` | `ppt_video_status_get` | Yes | `video status` | `video_render_service.VideoRenderService.final_video_status` | No | No |
| `video.speed` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/videos/{filename}/speed` | `ppt_video_speed` | Yes | `video speed` | `video_render_service.VideoRenderService.create_speed_adjusted_video` | Yes | No |
| `video.delete` | 1.0 | stable | DELETE | `/api/agent/v1/projects/{project_id}/videos/{filename}` | `ppt_video_delete` | Yes | `video delete` | `video_render_service.VideoRenderService.delete_video` | No | Yes |
| `pptx.readiness` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/pptx/readiness` | `ppt_pptx_readiness` | Yes | `pptx readiness` | `pptx_service.PptxExportService.readiness` | No | No |
| `pptx.export.create` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/pptx/exports` | `ppt_pptx_export_create` | Yes | `pptx export` | `pptx_service.PptxExportService.create_export` | Yes | No |
| `pptx.exports.list` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/pptx/exports` | `ppt_pptx_exports_list` | Yes | `pptx exports` | `pptx_service.PptxExportService.list_exports` | No | No |
| `pptx.export.download` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/pptx/exports/{artifact_id}/content` | `ppt_pptx_export_download` | No | `pptx download` | `pptx_service.PptxExportService.download_export` | No | No |
| `pptx.exports.delete` | 1.0 | stable | DELETE | `/api/agent/v1/projects/{project_id}/pptx/exports/{artifact_id}` | `ppt_pptx_exports_delete` | Yes | `pptx delete` | `pptx_service.PptxExportService.delete_export` | No | Yes |
| `pptx.jobs.list` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/pptx/jobs` | `ppt_pptx_jobs_list` | Yes | `pptx jobs` | `pptx_service.PptxExportService.list_jobs` | No | No |
| `pptx.jobs.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/pptx/jobs/{job_id}` | `ppt_pptx_jobs_get` | Yes | `pptx job` | `pptx_service.PptxExportService.get_job` | No | No |
| `pptx.jobs.retry` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/pptx/jobs/{job_id}/retry` | `ppt_pptx_jobs_retry` | Yes | `pptx retry` | `pptx_service.PptxExportService.retry_job` | Yes | No |
| `subtitles.readiness` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/subtitles/readiness` | `ppt_subtitles_readiness` | Yes | `subtitles readiness` | `subtitle_export_service.subtitle_export_readiness` | No | No |
| `subtitles.download` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/subtitles/content` | `ppt_subtitles_download` | No | `subtitles download` | `subtitle_export_service.build_subtitle_export` | No | No |
| `image.prompt_settings.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/image-prompt-settings` | `ppt_image_prompt_settings_get` | Yes | `image prompt-settings` | `image_workflow_service.get_step3_prompt_settings` | No | No |
| `image.prompt_settings.update` | 1.0 | stable | PUT | `/api/agent/v1/projects/{project_id}/image-prompt-settings` | `ppt_image_prompt_settings_update` | Yes | `image prompt-settings --set` | `image_workflow_service.update_step3_prompt_settings` | No | No |
| `image.prompts.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/image-prompts` | `ppt_image_prompts_get` | Yes | `image prompts` | `image_workflow_service.get_slide_prompts` | No | No |
| `image.generate` | 1.1 | stable | POST | `/api/agent/v1/projects/{project_id}/images/generate` | `ppt_image_generate` | Yes | `image generate` | `image_workflow_service.generate_slide_image` | Yes | No |
| `image.upload` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/images/upload` | `ppt_image_upload` | No | `image upload` | `image_workflow_service.upload_slide_image` | No | No |
| `image.change_preview.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/images/{slide_id}/change-preview` | `ppt_image_change_preview_get` | Yes | `image change-preview` | `image_workflow_service.get_slide_image_change_preview` | No | No |
| `image.recovery.list` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/images/{slide_id}/recovery` | `ppt_image_recovery_list` | Yes | `image recovery` | `image_workflow_service.list_slide_image_recovery` | No | No |
| `image.recovery.overlay` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/images/{slide_id}/recovery/{archive_id}/overlay` | `ppt_image_recovery_overlay` | No | `image recovery-overlay` | `image_workflow_service.image_recovery_overlay` | No | No |
| `image.geometry.reuse` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/images/{slide_id}/reuse-geometry` | `ppt_image_geometry_reuse` | Yes | `image reuse-geometry` | `image_workflow_service.reuse_slide_image_geometry` | No | No |
| `image.candidate.apply` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/images/apply-candidate` | `ppt_image_candidate_apply` | Yes | `image apply-candidate` | `image_workflow_service.apply_slide_candidate` | No | No |
| `image.candidate.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/images/{slide_id}/candidate` | `ppt_image_candidate_get` | No | `image candidate` | `image_workflow_service.get_slide_candidate_file` | No | No |
| `image.download_all` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/images/download` | `ppt_image_download_all` | No | `image download-all` | `image_workflow_service.download_all_slide_images` | No | No |
| `image.delete_all` | 1.0 | stable | DELETE | `/api/agent/v1/projects/{project_id}/images` | `ppt_image_delete_all` | Yes | `image delete-all` | `image_workflow_service.delete_all_slide_images` | No | Yes |
| `image.delete` | 1.0 | stable | DELETE | `/api/agent/v1/projects/{project_id}/images/{slide_id}` | `ppt_image_delete` | Yes | `image delete` | `image_workflow_service.delete_slide_image` | No | Yes |
| `image.list` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/images` | `ppt_image_list` | Yes | `image list` | `image_workflow_service.get_all_images` | No | No |
| `image.order.update` | 1.0 | stable | PUT | `/api/agent/v1/projects/{project_id}/image-order` | `ppt_image_order_update` | Yes | `image order --set` | `image_workflow_service.update_step3_image_order` | No | No |
| `image.confirm` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/images/confirm` | `ppt_image_confirm` | Yes | `image confirm` | `image_workflow_service.confirm_images` | No | No |
| `style.profile_templates.list` | 1.0 | stable | GET | `/api/agent/v1/style/profile-templates` | `ppt_style_profile_templates_list` | Yes | `style profile-templates` | `project_style_routes.get_project_profile_templates` | No | No |
| `style.profile.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/style/profile` | `ppt_style_profile_get` | Yes | `style profile` | `project_style_routes.get_project_profile` | No | No |
| `style.profile.update` | 1.0 | stable | PUT | `/api/agent/v1/projects/{project_id}/style/profile` | `ppt_style_profile_update` | Yes | `style profile --set` | `project_style_routes.save_project_profile` | No | No |
| `style.generate` | 1.0 | stable | POST | `/api/agent/v1/style/generate` | `ppt_style_generate` | Yes | `style generate` | `project_style_routes.generate_project_image_style` | Yes | No |
| `style.reverse_settings.get` | 1.0 | stable | GET | `/api/agent/v1/style/reverse-settings` | `ppt_style_reverse_settings_get` | Yes | `style reverse-settings` | `project_style_routes.get_reverse_style_prompt_settings` | No | No |
| `style.reverse_settings.update` | 1.0 | stable | PUT | `/api/agent/v1/style/reverse-settings` | `ppt_style_reverse_settings_update` | Yes | `style reverse-settings --set` | `project_style_routes.update_reverse_style_prompt_settings` | No | No |
| `style.reverse.generate` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/style/reverse` | `ppt_style_reverse_generate` | No | `style reverse` | `project_style_routes.reverse_step3_image_style` | No | No |
| `style.reverse.generate_legacy` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/style/reverse-legacy` | `ppt_style_reverse_generate_legacy` | No | `style reverse-legacy` | `project_style_routes.reverse_legacy_project_image_style` | No | No |
| `style.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/style` | `ppt_style_get` | Yes | `style show` | `project_style_routes.get_step3_image_style` | No | No |
| `style.update` | 1.0 | stable | PUT | `/api/agent/v1/projects/{project_id}/style` | `ppt_style_update` | Yes | `style --set` | `project_style_routes.put_step3_image_style` | No | No |
| `style.reference_settings.get` | 1.0 | stable | GET | `/api/agent/v1/style/reference-settings` | `ppt_style_reference_settings_get` | Yes | `style reference-settings` | `project_style_routes.get_reference_generation_prompt_settings` | No | No |
| `style.reference_settings.update` | 1.0 | stable | PUT | `/api/agent/v1/style/reference-settings` | `ppt_style_reference_settings_update` | Yes | `style reference-settings --set` | `project_style_routes.update_reference_generation_prompt_settings` | No | No |
| `style.references.list` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/style/references` | `ppt_style_references_list` | Yes | `style references` | `project_style_routes.list_step3_reference_images` | No | No |
| `style.references.generate` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/style/references/generate` | `ppt_style_references_generate` | Yes | `style references-generate` | `project_style_routes.generate_step3_reference_images` | Yes | No |
| `style.references.upload` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/style/references/upload` | `ppt_style_references_upload` | No | `style references-upload` | `project_style_routes.upload_step3_reference_images` | No | No |
| `style.references.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/style/references/{index}/content` | `ppt_style_references_get` | No | `style reference` | `project_style_routes.get_step3_reference_image` | No | No |
| `style.references.delete` | 1.0 | stable | DELETE | `/api/agent/v1/projects/{project_id}/style/references/{index}` | `ppt_style_references_delete` | Yes | `style reference-delete` | `project_style_routes.delete_step3_reference_image` | No | Yes |
| `style.references.delete_all` | 1.0 | stable | DELETE | `/api/agent/v1/projects/{project_id}/style/references` | `ppt_style_references_delete_all` | Yes | `style references-clear` | `project_style_routes.delete_all_step3_reference_images` | No | Yes |
| `style.references_legacy.list` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/style/references-legacy` | `ppt_style_references_legacy_list` | Yes | `style references-legacy` | `project_style_routes.list_legacy_reference_images` | No | No |
| `style.references_legacy.generate` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/style/references-legacy/generate` | `ppt_style_references_legacy_generate` | Yes | `style references-legacy-generate` | `project_style_routes.generate_legacy_reference_images` | Yes | No |
| `style.references_legacy.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/style/references-legacy/{index}/content` | `ppt_style_references_legacy_get` | No | `style reference-legacy` | `project_style_routes.get_legacy_reference_image` | No | No |
| `style.references_legacy.delete` | 1.0 | stable | DELETE | `/api/agent/v1/projects/{project_id}/style/references-legacy/{index}` | `ppt_style_references_legacy_delete` | Yes | `style reference-legacy-delete` | `project_style_routes.delete_legacy_reference_image` | No | Yes |
| `style.references_legacy.delete_all` | 1.0 | stable | DELETE | `/api/agent/v1/projects/{project_id}/style/references-legacy` | `ppt_style_references_legacy_delete_all` | Yes | `style references-legacy-clear` | `project_style_routes.delete_all_legacy_reference_images` | No | Yes |
| `style.templates.list` | 1.0 | stable | GET | `/api/agent/v1/style/templates` | `ppt_style_templates_list` | Yes | `style templates` | `project_style_routes.list_step3_templates` | No | No |
| `style.templates.get` | 1.0 | stable | GET | `/api/agent/v1/style/templates/{template_id}` | `ppt_style_templates_get` | Yes | `style template` | `project_style_routes.get_step3_template_detail` | No | No |
| `style.templates.create` | 1.0 | stable | POST | `/api/agent/v1/style/templates` | `ppt_style_templates_create` | Yes | `style template-create` | `project_style_routes.create_account_style_template` | No | No |
| `style.templates.create_with_references` | 1.0 | stable | POST | `/api/agent/v1/style/templates/with-references` | `ppt_style_templates_create_with_references` | No | `style template-create-with-references` | `project_style_routes.create_account_style_template_with_references` | No | No |
| `style.templates.reference.get` | 1.0 | stable | GET | `/api/agent/v1/style/templates/{template_id}/references/{index}/content` | `ppt_style_templates_reference_get` | No | `style template-reference` | `project_style_routes.get_step3_template_reference` | No | No |
| `style.project_template.save` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/style/templates` | `ppt_style_project_template_save` | Yes | `style project-template-save` | `project_style_routes.save_step3_template` | No | No |
| `style.project_template.apply` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/style/templates/{template_id}/apply` | `ppt_style_project_template_apply` | Yes | `style template-apply` | `project_style_routes.apply_step3_template` | No | No |
| `style.templates.delete` | 1.0 | stable | DELETE | `/api/agent/v1/style/templates/{template_id}` | `ppt_style_templates_delete` | Yes | `style template-delete` | `project_style_routes.delete_step3_template` | No | Yes |
| `global_style.get` | 1.0 | stable | GET | `/api/agent/v1/global-image-style` | `ppt_global_style_get` | Yes | `global-style show` | `global_image_style_routes.get_image_style` | No | No |
| `global_style.update` | 1.0 | stable | PUT | `/api/agent/v1/global-image-style` | `ppt_global_style_update` | Yes | `global-style --set` | `global_image_style_routes.update_image_style` | No | No |
| `global_style.validate` | 1.0 | stable | POST | `/api/agent/v1/global-image-style/validate` | `ppt_global_style_validate` | Yes | `global-style validate` | `global_image_style_routes.validate_image_style` | No | No |
| `global_style.templates.list` | 1.0 | stable | GET | `/api/agent/v1/global-image-style/templates` | `ppt_global_style_templates_list` | Yes | `global-style templates` | `global_image_style_routes.get_image_style_templates` | No | No |
| `global_style.templates.get` | 1.0 | stable | GET | `/api/agent/v1/global-image-style/templates/{template_id}` | `ppt_global_style_templates_get` | Yes | `global-style template` | `global_image_style_routes.get_image_style_template` | No | No |
| `global_style.templates.save` | 1.0 | stable | POST | `/api/agent/v1/global-image-style/templates` | `ppt_global_style_templates_save` | Yes | `global-style template-save` | `global_image_style_routes.save_image_style_template` | No | No |
| `global_style.templates.delete` | 1.0 | stable | DELETE | `/api/agent/v1/global-image-style/templates/{template_id}` | `ppt_global_style_templates_delete` | Yes | `global-style template-delete` | `global_image_style_routes.delete_image_style_template` | No | Yes |
| `global_style.reference.get` | 1.0 | stable | GET | `/api/agent/v1/global-image-style/reference/{kind}/content` | `ppt_global_style_reference_get` | No | `global-style reference` | `global_image_style_routes.get_image_style_reference` | No | No |
| `global_style.reference.update` | 1.0 | stable | PUT | `/api/agent/v1/global-image-style/reference/{kind}` | `ppt_global_style_reference_update` | No | `global-style reference --set` | `global_image_style_routes.update_image_style_reference` | No | No |
| `global_style.template_references.apply` | 1.0 | stable | POST | `/api/agent/v1/global-image-style/template-references/apply` | `ppt_global_style_template_references_apply` | Yes | `global-style template-references-apply` | `global_image_style_routes.apply_image_style_template_references` | No | No |
| `ip.list` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/ip-characters` | `ppt_ip_list` | Yes | `ip list` | `ip_character_routes.get_ip_characters` | No | No |
| `ip.upsert` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/ip-characters` | `ppt_ip_upsert` | No | `ip upsert` | `ip_character_routes.upsert_ip_character` | No | No |
| `ip.config.update` | 1.0 | stable | PUT | `/api/agent/v1/projects/{project_id}/ip-characters/config` | `ppt_ip_config_update` | Yes | `ip config --set` | `ip_character_routes.update_ip_character_config` | No | No |
| `ip.delete` | 1.0 | stable | DELETE | `/api/agent/v1/projects/{project_id}/ip-characters/{character_id}` | `ppt_ip_delete` | Yes | `ip delete` | `ip_character_routes.delete_ip_character` | No | Yes |
| `ip.image.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/ip-characters/{character_id}/image` | `ppt_ip_image_get` | No | `ip image` | `ip_character_routes.get_ip_character_image` | No | No |
| `mask.settings.get` | 1.0 | stable | GET | `/api/agent/v1/ai-mask/settings` | `ppt_mask_settings_get` | Yes | `mask settings` | `ai_mask_config.ai_mask_config_payload` | No | No |
| `mask.settings.update` | 1.0 | stable | PUT | `/api/agent/v1/ai-mask/settings` | `ppt_mask_settings_update` | Yes | `mask settings --set` | `ai_mask_config.save_ai_mask_settings` | No | No |
| `mask.annotate` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/mask/annotate` | `ppt_mask_annotate` | Yes | `mask annotate` | `ai_mask_service.AiMaskTaskService.annotate_project` | Yes | No |
| `mask.semantic_blocks` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/mask/semantic-blocks` | `ppt_mask_semantic_blocks` | Yes | `mask semantic-blocks` | `mask_manifest_service.semantic_blocks_project` | No | No |
| `mask.result.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/mask` | `ppt_mask_result_get` | Yes | `mask show` | `mask_manifest_service.get_step5_result` | No | No |
| `mask.result.repair` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/mask/repair` | `ppt_mask_result_repair` | Yes | `mask repair` | `mask_manifest_service.repair_step5_result` | No | No |
| `mask.draft.update` | 1.0 | stable | PUT | `/api/agent/v1/projects/{project_id}/mask/draft` | `ppt_mask_draft_update` | Yes | `mask draft --set` | `mask_manifest_service.update_step5_draft` | No | No |
| `mask.result.update` | 1.0 | stable | PUT | `/api/agent/v1/projects/{project_id}/mask` | `ppt_mask_result_update` | Yes | `mask save` | `mask_manifest_service.update_step5_result` | No | No |
| `mask.preview.build` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/mask/previews/{slide_id}` | `ppt_mask_preview_build` | Yes | `mask preview-build` | `mask_preview_service.build_step5_mask_preview` | No | No |
| `mask.preview.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/mask/previews/{slide_id}/content` | `ppt_mask_preview_get` | No | `mask preview` | `mask_preview_service.get_step5_mask_preview_path` | No | No |
| `annotation.summary.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/annotations` | `ppt_annotation_summary_get` | Yes | `annotation summary` | `annotation_service.AnnotationService.get_summary` | No | No |
| `annotation.settings.update` | 1.0 | stable | PUT | `/api/agent/v1/projects/{project_id}/annotations/settings` | `ppt_annotation_settings_update` | Yes | `annotation settings --set` | `annotation_service.AnnotationService.update_settings` | No | No |
| `annotation.slide.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/annotations/slides/{slide_id}` | `ppt_annotation_slide_get` | Yes | `annotation slide` | `annotation_service.AnnotationService.get_slide` | No | No |
| `annotation.slide.patch` | 1.0 | stable | PATCH | `/api/agent/v1/projects/{project_id}/annotations/slides/{slide_id}` | `ppt_annotation_slide_patch` | Yes | `annotation slide --patch` | `annotation_service.AnnotationService.patch_slide` | No | No |
| `annotation.text_layout.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/annotations/slides/{slide_id}/text-layout` | `ppt_annotation_text_layout_get` | Yes | `annotation text-layout` | `annotation_service.AnnotationService.get_text_layout` | No | No |
| `annotation.text_layout.patch` | 1.0 | stable | PATCH | `/api/agent/v1/projects/{project_id}/annotations/slides/{slide_id}/text-layout` | `ppt_annotation_text_layout_patch` | Yes | `annotation text-layout --patch` | `annotation_service.AnnotationService.patch_text_layout` | No | No |
| `annotation.prompts.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/annotations/prompts` | `ppt_annotation_prompts_get` | Yes | `annotation prompts` | `annotation_service.AnnotationService.get_prompts` | No | No |
| `annotation.prompts.update` | 1.0 | stable | PUT | `/api/agent/v1/projects/{project_id}/annotations/prompts` | `ppt_annotation_prompts_update` | Yes | `annotation prompts --set` | `annotation_service.AnnotationService.put_prompts` | No | No |
| `annotation.slide.prepare` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/annotations/slides/{slide_id}/prepare` | `ppt_annotation_slide_prepare` | Yes | `annotation prepare` | `annotation_service.AnnotationService.prepare_slide` | No | No |
| `annotation.slide.confirm` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/annotations/slides/{slide_id}/confirm` | `ppt_annotation_slide_confirm` | Yes | `annotation confirm` | `annotation_service.AnnotationService.confirm_slide` | No | No |
| `annotation.jobs.submit` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/annotations/jobs` | `ppt_annotation_jobs_submit` | Yes | `annotation submit` | `annotation_service.AnnotationService.submit_job` | Yes | No |
| `annotation.jobs.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/annotations/jobs/{job_id}` | `ppt_annotation_jobs_get` | Yes | `annotation job` | `annotation_service.AnnotationService.get_job` | No | No |
| `annotation.jobs.cancel` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/annotations/jobs/{job_id}/cancel` | `ppt_annotation_jobs_cancel` | Yes | `annotation cancel` | `annotation_service.AnnotationService.cancel_job` | No | No |
| `annotation.preview.export` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/annotations/slides/{slide_id}/export-preview` | `ppt_annotation_preview_export` | Yes | `annotation export-preview` | `annotation_service.AnnotationService.export_preview` | Yes | No |
| `annotation.scene_asset.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/annotations/slides/{slide_id}/scene-assets/{asset}` | `ppt_annotation_scene_asset_get` | No | `annotation scene-asset` | `annotation_service.AnnotationService.preview_scene_asset` | No | No |
| `annotation.editor_ink.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/annotations/slides/{slide_id}/editor-inks/{annotation_id}/{stroke_index}` | `ppt_annotation_editor_ink_get` | No | `annotation editor-ink` | `annotation_service.AnnotationService.annotation_editor_ink` | No | No |
| `annotation.ink.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/annotations/slides/{slide_id}/inks/{build_id}/{annotation_id}/{stroke_index}/{frame_index}` | `ppt_annotation_ink_get` | No | `annotation ink` | `annotation_service.AnnotationService.annotation_asset` | No | No |
| `annotation.preview.download` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/annotations/slides/{slide_id}/export-previews/{token}` | `ppt_annotation_preview_download` | No | `annotation preview` | `annotation_service preview_exports` | No | No |
| `digital_human.slide.generate` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/digital-human/slides/{slide_id}/generate` | `ppt_digital_human_slide_generate` | Yes | `digital-human generate-slide` | `digital_human_routes.generate_dh` | Yes | No |
| `digital_human.jobs.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/digital-human/jobs/{job_id}` | `ppt_digital_human_jobs_get` | Yes | `digital-human job` | `digital_human_routes.get_dh_job` | No | No |
| `digital_human.slide_video.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/digital-human/slides/{slide_id}/video` | `ppt_digital_human_slide_video_get` | No | `digital-human slide-video` | `digital_human_routes.get_dh_slide_video` | No | No |
| `digital_human.slide.compose` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/digital-human/slides/{slide_id}/compose` | `ppt_digital_human_slide_compose` | Yes | `digital-human compose` | `digital_human_routes.compose_dh_slide` | Yes | No |
| `digital_human.composite_video.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/digital-human/slides/{slide_id}/composite-video` | `ppt_digital_human_composite_video_get` | No | `digital-human composite-video` | `digital_human_routes.get_dh_composite_video` | No | No |
| `digital_human.audio.export` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/digital-human/export-audio` | `ppt_digital_human_audio_export` | Yes | `digital-human export-audio` | `digital_human_routes.export_full_audio` | Yes | No |
| `digital_human.audio.file` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/digital-human/export-audio/content` | `ppt_digital_human_audio_file` | No | `digital-human audio` | `digital_human_routes.get_full_audio` | No | No |
| `digital_human.video.upload` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/digital-human/upload` | `ppt_digital_human_video_upload` | No | `digital-human upload-video` | `digital_human_routes.upload_dh_video` | No | No |
| `digital_human.video.uploaded.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/digital-human/upload/content` | `ppt_digital_human_video_uploaded_get` | No | `digital-human uploaded-video` | `digital_human_routes.get_dh_upload_video` | No | No |
| `digital_human.avatars.upload` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/digital-human/avatars/upload` | `ppt_digital_human_avatars_upload` | No | `digital-human upload-avatar` | `digital_human_routes.upload_dh_avatar` | No | No |
| `digital_human.avatars.list` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/digital-human/avatars` | `ppt_digital_human_avatars_list` | Yes | `digital-human avatars` | `digital_human_routes.list_dh_avatars` | No | No |
| `digital_human.workflow.upload` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/digital-human/workflow/upload` | `ppt_digital_human_workflow_upload` | No | `digital-human upload-workflow` | `digital_human_routes.upload_comfyui_workflow` | No | No |
| `digital_human.workflow.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/digital-human/workflow` | `ppt_digital_human_workflow_get` | Yes | `digital-human workflow` | `digital_human_routes.get_comfyui_workflow` | No | No |
| `course.tree.get` | 1.0 | stable | GET | `/api/agent/v1/courses/tree` | `ppt_course_tree_get` | Yes | `course tree` | `course_routes.get_tree` | No | No |
| `course.reorder` | 1.0 | stable | PATCH | `/api/agent/v1/courses/reorder` | `ppt_course_reorder` | Yes | `course reorder` | `course_routes.reorder_courses` | No | No |
| `chapter.reorder` | 1.0 | stable | PATCH | `/api/agent/v1/chapters/reorder` | `ppt_chapter_reorder` | Yes | `chapter reorder` | `course_routes.reorder_chapters` | No | No |
| `course.create` | 1.0 | stable | POST | `/api/agent/v1/courses` | `ppt_course_create` | Yes | `course create` | `course_routes.create_course` | No | No |
| `course.list` | 1.0 | stable | GET | `/api/agent/v1/courses` | `ppt_course_list` | Yes | `course list` | `course_routes.list_courses` | No | No |
| `course.get` | 1.0 | stable | GET | `/api/agent/v1/courses/{course_id}` | `ppt_course_get` | Yes | `course show` | `course_routes.get_course` | No | No |
| `course.update` | 1.0 | stable | PATCH | `/api/agent/v1/courses/{course_id}` | `ppt_course_update` | Yes | `course --set` | `course_routes.update_course` | No | No |
| `course.delete` | 1.0 | stable | DELETE | `/api/agent/v1/courses/{course_id}` | `ppt_course_delete` | Yes | `course delete` | `course_routes.delete_course` | No | Yes |
| `chapter.create` | 1.0 | stable | POST | `/api/agent/v1/courses/{course_id}/chapters` | `ppt_chapter_create` | Yes | `chapter create` | `course_routes.create_chapter` | No | No |
| `chapter.update` | 1.0 | stable | PATCH | `/api/agent/v1/chapters/{chapter_id}` | `ppt_chapter_update` | Yes | `chapter --set` | `course_routes.update_chapter` | No | No |
| `chapter.delete` | 1.0 | stable | DELETE | `/api/agent/v1/chapters/{chapter_id}` | `ppt_chapter_delete` | Yes | `chapter delete` | `course_routes.delete_chapter` | No | Yes |
| `chapter.move` | 1.0 | stable | POST | `/api/agent/v1/chapters/{chapter_id}/move` | `ppt_chapter_move` | Yes | `chapter move` | `course_routes.move_chapter` | No | No |
| `project.move` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/move` | `ppt_project_move` | Yes | `project move` | `course_routes.move_project` | No | No |
| `project.reorder` | 1.0 | stable | PATCH | `/api/agent/v1/projects/reorder` | `ppt_project_reorder` | Yes | `project reorder` | `course_routes.reorder_projects` | No | No |
| `config.list` | 1.0 | stable | GET | `/api/agent/v1/creation-configs` | `ppt_config_list` | Yes | `config list` | `creation_config_routes.list_creation_configs` | No | No |
| `config.default_payload.get` | 1.0 | stable | GET | `/api/agent/v1/creation-configs/default-payload` | `ppt_config_default_payload_get` | Yes | `config default-payload` | `creation_config_routes.get_default_creation_config_payload` | No | No |
| `config.create` | 1.0 | stable | POST | `/api/agent/v1/creation-configs` | `ppt_config_create` | Yes | `config create` | `creation_config_routes.create_creation_config` | No | No |
| `config.import` | 1.0 | stable | POST | `/api/agent/v1/creation-configs/import` | `ppt_config_import` | Yes | `config import` | `creation_config_routes.import_creation_config` | No | No |
| `config.get` | 1.0 | stable | GET | `/api/agent/v1/creation-configs/{package_id}` | `ppt_config_get` | Yes | `config show` | `creation_config_routes.get_creation_config` | No | No |
| `config.update` | 1.0 | stable | PUT | `/api/agent/v1/creation-configs/{package_id}` | `ppt_config_update` | Yes | `config --set` | `creation_config_routes.update_creation_config` | No | No |
| `config.version.get` | 1.0 | stable | GET | `/api/agent/v1/creation-configs/{package_id}/versions/{version}` | `ppt_config_version_get` | Yes | `config version` | `creation_config_routes.get_creation_config_version` | No | No |
| `config.copy` | 1.0 | stable | POST | `/api/agent/v1/creation-configs/{package_id}/copy` | `ppt_config_copy` | Yes | `config copy` | `creation_config_routes.copy_creation_config` | No | No |
| `config.version.create` | 1.0 | stable | POST | `/api/agent/v1/creation-configs/{package_id}/versions` | `ppt_config_version_create` | Yes | `config version-create` | `creation_config_routes.create_creation_config_version` | No | No |
| `config.archive` | 1.0 | stable | PUT | `/api/agent/v1/creation-configs/{package_id}/archive` | `ppt_config_archive` | Yes | `config archive` | `creation_config_routes.archive_creation_config` | No | No |
| `config.delete` | 1.0 | stable | DELETE | `/api/agent/v1/creation-configs/{package_id}` | `ppt_config_delete` | Yes | `config delete` | `creation_config_routes.delete_creation_config` | No | Yes |
| `config.resolve` | 1.0 | stable | POST | `/api/agent/v1/creation-configs/{package_id}/resolve` | `ppt_config_resolve` | Yes | `config resolve` | `creation_config_routes.resolve_creation_config` | No | No |
| `pipeline.pause` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/runs/latest/pause` | `ppt_pipeline_pause` | Yes | `run pause` | `one_click_routes.pause_one_click_route` | No | No |
| `pipeline.statuses.list` | 1.0 | stable | GET | `/api/agent/v1/one-click-statuses` | `ppt_pipeline_statuses_list` | Yes | `run statuses` | `one_click_routes.batch_one_click_status_route` | No | No |
| `media.background_config.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/storyboard-background` | `ppt_media_background_config_get` | Yes | `media background-config` | `storyboard_background.get_background` | No | No |
| `media.background_config.update` | 1.0 | stable | PUT | `/api/agent/v1/projects/{project_id}/storyboard-background` | `ppt_media_background_config_update` | Yes | `media background-config --set` | `storyboard_background.put_background` | No | No |
| `media.background_image.upload` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/storyboard-background/image` | `ppt_media_background_image_upload` | No | `media background-image-upload` | `storyboard_background.upload_background` | No | No |
| `media.background_image.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/storyboard-background/image` | `ppt_media_background_image_get` | No | `media background-image` | `storyboard_background.get_background_image` | No | No |
| `settings.get` | 1.0 | stable | GET | `/api/agent/v1/settings` | `ppt_settings_get` | Yes | `settings show` | `settings_service.get_settings` | No | No |
| `settings.update` | 1.0 | stable | PUT | `/api/agent/v1/settings` | `ppt_settings_update` | Yes | `settings --set` | `settings_service.update_system_settings` | No | No |
| `settings.config.export` | 1.0 | stable | GET | `/api/agent/v1/config/export` | `ppt_settings_config_export` | Yes | `settings config-export` | `settings_routes.export_full_config` | No | No |
| `settings.config.export.zip` | 1.0 | stable | GET | `/api/agent/v1/config/export-zip` | `ppt_settings_config_export_zip` | No | `settings config-export-zip` | `settings_routes.export_full_config_zip` | No | No |
| `settings.config.export.secrets` | 1.0 | stable | POST | `/api/agent/v1/config/export-with-secrets` | `ppt_settings_config_export_secrets` | Yes | `settings config-export-secrets` | `settings_routes.export_full_config_with_secrets` | No | No |
| `settings.config.export.secrets.zip` | 1.0 | stable | POST | `/api/agent/v1/config/export-with-secrets-zip` | `ppt_settings_config_export_secrets_zip` | No | `settings config-export-secrets-zip` | `settings_routes.export_full_config_with_secrets_zip` | No | No |
| `settings.config.import` | 1.0 | stable | POST | `/api/agent/v1/config/import` | `ppt_settings_config_import` | Yes | `settings config-import` | `settings_routes.import_full_config` | No | No |
| `settings.config.import.zip` | 1.0 | stable | POST | `/api/agent/v1/config/import-zip` | `ppt_settings_config_import_zip` | No | `settings config-import-zip` | `settings_routes.import_full_config_zip` | No | No |
| `settings.llm.test` | 1.0 | stable | POST | `/api/agent/v1/settings/test-llm` | `ppt_settings_llm_test` | Yes | `settings test-llm` | `settings_service.test_llm_connection` | No | No |
| `settings.image.test` | 1.0 | stable | POST | `/api/agent/v1/settings/test-image` | `ppt_settings_image_test` | Yes | `settings test-image` | `settings_service.test_image_connection` | No | No |
| `settings.tts.test` | 1.0 | stable | POST | `/api/agent/v1/settings/test-tts` | `ppt_settings_tts_test` | Yes | `settings test-tts` | `settings_service.test_tts_connection` | No | No |
| `settings.comfyui_workflow.get` | 1.0 | stable | GET | `/api/agent/v1/settings/comfyui-tts-workflow` | `ppt_settings_comfyui_workflow_get` | Yes | `settings comfyui-workflow` | `settings_routes.get_comfyui_tts_workflow` | No | No |
| `settings.comfyui_workflow.upload` | 1.0 | stable | POST | `/api/agent/v1/settings/comfyui-tts-workflow` | `ppt_settings_comfyui_workflow_upload` | No | `settings comfyui-workflow-upload` | `settings_routes.upload_comfyui_tts_workflow` | No | No |
| `credentials.list` | 1.0 | stable | GET | `/api/agent/v1/credentials` | `ppt_credentials_list` | Yes | `credentials list` | `credential_routes.list_credentials` | No | No |
| `credentials.create` | 1.0 | stable | POST | `/api/agent/v1/credentials` | `ppt_credentials_create` | Yes | `credentials create` | `credential_routes.create_credential` | No | No |
| `credentials.update` | 1.0 | stable | PUT | `/api/agent/v1/credentials` | `ppt_credentials_update` | Yes | `credentials --set` | `credential_routes.update_credential` | No | No |
| `connections.list` | 1.0 | stable | GET | `/api/agent/v1/model-connections` | `ppt_connections_list` | Yes | `connections list` | `model_connection_routes.list_model_connections` | No | No |
| `connections.create` | 1.0 | stable | POST | `/api/agent/v1/model-connections` | `ppt_connections_create` | Yes | `connections create` | `model_connection_routes.create_model_connection` | No | No |
| `connections.get` | 1.0 | stable | GET | `/api/agent/v1/model-connections/{connection_id}` | `ppt_connections_get` | Yes | `connections show` | `model_connection_routes.get_model_connection` | No | No |
| `connections.update` | 1.0 | stable | PUT | `/api/agent/v1/model-connections/{connection_id}` | `ppt_connections_update` | Yes | `connections --set` | `model_connection_routes.update_model_connection` | No | No |
| `connections.reference_audio.upload` | 1.0 | stable | POST | `/api/agent/v1/model-connections/{connection_id}/reference-audio` | `ppt_connections_reference_audio_upload` | No | `connections reference-audio-upload` | `model_connection_routes.upload_model_reference_audio` | No | No |
| `connections.copy` | 1.0 | stable | POST | `/api/agent/v1/model-connections/{connection_id}/copy` | `ppt_connections_copy` | Yes | `connections copy` | `model_connection_routes.copy_model_connection` | No | No |
| `connections.test` | 1.0 | stable | POST | `/api/agent/v1/model-connections/{connection_id}/test` | `ppt_connections_test` | Yes | `connections test` | `model_connection_routes.test_saved_model_connection` | No | No |
| `connections.state.update` | 1.0 | stable | PUT | `/api/agent/v1/model-connections/{connection_id}/state` | `ppt_connections_state_update` | Yes | `connections state --set` | `model_connection_routes.update_model_connection_state` | No | No |
| `connections.delete` | 1.0 | stable | DELETE | `/api/agent/v1/model-connections/{connection_id}` | `ppt_connections_delete` | Yes | `connections delete` | `model_connection_routes.delete_model_connection` | No | Yes |
| `diagnostics.runtime` | 1.0 | stable | GET | `/api/agent/v1/runtime/diagnostics` | `ppt_diagnostics_runtime` | Yes | `diagnostics runtime` | `diagnostics_routes.runtime_diagnostics` | No | No |
| `diagnostics.governor` | 1.0 | stable | GET | `/api/agent/v1/diagnostics/generation-governor` | `ppt_diagnostics_governor` | Yes | `diagnostics governor` | `diagnostics_routes.generation_governor_snapshot` | No | No |
| `diagnostics.error_log` | 1.0 | stable | GET | `/api/agent/v1/error-log` | `ppt_diagnostics_error_log` | Yes | `diagnostics error-log` | `diagnostics_routes.get_error_log` | No | No |
| `diagnostics.error_log.latest` | 1.0 | stable | GET | `/api/agent/v1/error-log/latest` | `ppt_diagnostics_error_log_latest` | No | `diagnostics latest-error` | `diagnostics_routes.get_latest_error_log` | No | No |
| `project.impacts.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/impacts` | `ppt_project_impacts_get` | Yes | `project impacts` | `project_routes.get_project_impacts` | No | No |
| `project.impacts.reuse_preview` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/impacts/storyboard-reuse-preview` | `ppt_project_impacts_reuse_preview` | Yes | `project reuse-preview` | `project_routes.preview_storyboard_reuse` | No | No |
| `project.impacts.reuse_confirm` | 1.0 | stable | PUT | `/api/agent/v1/projects/{project_id}/impacts/reuse-storyboard` | `ppt_project_impacts_reuse_confirm` | Yes | `project reuse-confirm` | `project_routes.confirm_storyboard_reuse` | No | No |
| `project.impacts.decision.update` | 1.0 | stable | PUT | `/api/agent/v1/projects/{project_id}/impacts/decision` | `ppt_project_impacts_decision_update` | Yes | `project impact-decision` | `project_routes.update_project_impact_decision` | No | No |
| `project.impacts.image_reuse_confirm` | 1.0 | stable | PUT | `/api/agent/v1/projects/{project_id}/impacts/reuse-image` | `ppt_project_impacts_image_reuse_confirm` | Yes | `project image-reuse-confirm` | `project_routes.confirm_storyboard_image_reuse` | No | No |
| `project.ai_mode.get` | 1.0 | stable | GET | `/api/agent/v1/projects/{project_id}/ai-mode` | `ppt_project_ai_mode_get` | Yes | `project ai-mode` | `project_routes.get_project_ai_mode` | No | No |
| `project.change_preview` | 1.0 | stable | POST | `/api/agent/v1/projects/{project_id}/change-preview` | `ppt_project_change_preview` | Yes | `project change-preview` | `agent_workflow_service.preview_storyboard_change` | No | No |
| `project.ai_mode.update` | 1.0 | stable | PUT | `/api/agent/v1/projects/{project_id}/ai-mode` | `ppt_project_ai_mode_update` | Yes | `project ai-mode --set` | `project_routes.update_project_ai_mode` | No | No |
| `accounts.list` | 1.0 | stable | GET | `/api/agent/v1/accounts` | `ppt_accounts_list` | Yes | `accounts list` | `account_routes.accounts` | No | No |
| `accounts.current` | 1.0 | stable | GET | `/api/agent/v1/accounts/current` | `ppt_accounts_current` | Yes | `accounts current` | `account_routes.current_account` | No | No |
| `accounts.create` | 1.0 | stable | POST | `/api/agent/v1/accounts` | `ppt_accounts_create` | Yes | `accounts create` | `account_routes.account_create` | No | No |
| `accounts.provision` | 1.0 | stable | POST | `/api/agent/v1/accounts/provision` | `ppt_accounts_provision` | Yes | `accounts provision` | `account_routes.account_provision_from_current` | No | No |
| `accounts.rename` | 1.0 | stable | PUT | `/api/agent/v1/accounts/{account_id}` | `ppt_accounts_rename` | Yes | `accounts rename` | `account_routes.account_rename` | No | No |
| `accounts.delete` | 1.0 | stable | DELETE | `/api/agent/v1/accounts/{account_id}` | `ppt_accounts_delete` | Yes | `accounts delete` | `account_routes.account_delete` | No | Yes |
| `accounts.default_config.update` | 1.0 | stable | PUT | `/api/agent/v1/accounts/{account_id}/default-config` | `ppt_accounts_default_config_update` | Yes | `accounts default-config` | `account_routes.account_default_config` | No | No |
| `accounts.agent_token.create` | 1.0 | stable | POST | `/api/agent/v1/accounts/{account_id}/agent-tokens` | `ppt_accounts_agent_token_create` | Yes | `accounts agent-token` | `account_routes.account_agent_token` | No | No |

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

The registry contributes **230** stable capability tools, plus the fixed search/describe/invoke discovery tools:

- `ppt_project_state` — Observe eight visible steps, saved internal statuses, source-owned artifact checks, resource hashes, annotation decision, optional presenter state, pending impacts and authorized candidate actions. Read-only; not a render-success guarantee or a global concurrency lock. Actions marked requires_input need additional schema-valid input.
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
- `ppt_artifacts_list` — List registered project artifacts with exact per-artifact resource URIs, never substituting the latest output. Hashes are computed by artifact.get.
- `ppt_artifact_get` — Get exact artifact metadata, controlled download path and current SHA-256. Hash is null when its file is unavailable; no arbitrary file paths are accepted.
- `ppt_diagnostics` — Get system diagnostics including API version, capabilities, and health checks.
- `ppt_digital_human_config_get` — Get digital-human configuration for a project.
- `ppt_digital_human_config_update` — Update digital-human configuration for a project.
- `ppt_digital_human_health` — Check digital-human service availability and model readiness.
- `ppt_digital_human_generate` — Trigger full digital-human video generation for all slides.
- `ppt_project_delete` — Delete a project and all derived artifacts with optional revision checking and account-scoped idempotent replay, including after deletion. Destructive and irreversible.
- `ppt_checkpoint_list` — List the pipeline checkpoints available for a project.
- `ppt_article_settings_get` — Read the global article-generation System Content prompt.
- `ppt_article_settings_update` — Replace the global article-generation System Content prompt; blank content is rejected.
- `ppt_article_get` — Read the project article source (title, summary, content). success=false with message when no article is imported yet.
- `ppt_article_update` — Replace the project article content; an identical save is a no-op without downstream invalidation, a changed save invalidates Step 2+ artifacts.
- `ppt_storyboard_templates_list` — List reusable storyboard structure templates (rules + profile YAML).
- `ppt_storyboard_templates_save` — Create or update a storyboard template by name; built-in template names cannot be overwritten.
- `ppt_storyboard_templates_delete` — Delete a custom storyboard template by id; built-in templates are rejected.
- `ppt_step2_prompt_templates_list` — List reusable Step 2 prompt templates (script/visual system content and output example).
- `ppt_step2_prompt_templates_get` — Read one Step 2 prompt template by id.
- `ppt_step2_prompt_templates_save` — Create or update a Step 2 prompt template; both prompt fields of the declared type are required and built-in names cannot be overwritten.
- `ppt_step2_prompt_templates_delete` — Delete a custom Step 2 prompt template by id; built-in templates are rejected.
- `ppt_storyboard_rules_get` — Read the project's custom storyboard rules, pipeline profile YAML, contract schema text and profile editor data.
- `ppt_storyboard_rules_update` — Replace the project's storyboard rules and/or pipeline profile YAML; omitted text falls back to the built-in defaults; profile_patch is applied after profile_yaml.
- `ppt_storyboard_prompts_get` — Read the project's effective Step 2 prompts, built-in defaults, legacy-contract compatibility flags and composed system contents.
- `ppt_storyboard_prompts_update` — Replace Step 2 prompt fields; omitted fields reset to the built-in defaults.
- `ppt_storyboard_script_get` — Read the stored Step 2A speech script plan and target-duration response.
- `ppt_storyboard_script_update` — Save a normalized speech script plan (manual edit); an empty slides list clears the storyboard chain; replanning effects are reported via workflow_changed/workflow_pending.
- `ppt_storyboard_script_execute` — Run the Step 2A article-to-script LLM planning call synchronously; uses the configured LLM provider and the storyboard cooperative stop signal.
- `ppt_storyboard_visual_get` — Read the stored Step 2B visual plan and whether it is stale relative to the current script plan.
- `ppt_storyboard_visual_update` — Save a normalized visual plan (manual edit); narration fragments are re-bound deterministically from the stored script plan.
- `ppt_storyboard_visual_execute` — Run the Step 2B script-to-visual LLM planning call synchronously; requires a stored script plan.
- `ppt_storyboard_compose` — Compose and persist the Visual Contract from the stored script and visual plans, run contract validation, and apply downstream invalidation; stale visual plans are rejected before any write.
- `ppt_storyboard_preview` — Compose the Step 2 LLM request preview (system/user content) from the article plus optional rule/profile overrides, without calling any model.
- `ppt_storyboard_contract_get` — Read the normalized Visual Contract with its canonical SHA-256 CAS baseline and schema-repair hints; success=false before the first compose.
- `ppt_storyboard_contract_update` — Save the Visual Contract under CAS: pass the previously read contract_sha256 as expected_contract_sha256; a stale baseline returns 409 with zero side effects, an identical save is a no-op. Manual edits trigger validation, reveal/narration sync and registered downstream impacts.
- `ppt_storyboard_contract_repair` — Explicitly persist schema normalization of the stored contract instead of mutating on read; reports whether anything changed.
- `ppt_storyboard_skeleton_submit` — Manual mode: build a Visual Contract from title + narration slides only (empty visual groups, static pages), set ai_mode=manual and finish Step 2.
- `ppt_storyboard_execute` — Legacy one-shot composite (script execute + visual execute + compose) kept in parity with the business route; Agents should prefer the two-phase storyboard.script/visual/compose flow which reports intermediate results.
- `ppt_narration_init` — Initialize Step 6 narration beats from the current Visual Contract.
- `ppt_narration_result_get` — Read the stored Step 6 narration result (per-slide narration beats and sources).
- `ppt_narration_result_update` — Save the Step 6 narration result; semantic changes retain the audio confirmation record for hash revalidation, identical saves are no-ops.
- `ppt_narration_repair` — Explicitly repair/normalize the stored narration result without mutating on read.
- `ppt_narration_annotation_settings_get` — Read the global AI narration-annotation prompt settings.
- `ppt_narration_annotation_settings_update` — Update the global AI narration-annotation prompt settings.
- `ppt_narration_annotate` — Run the AI narration annotation LLM call synchronously; uses the configured provider and the cooperative stop signal.
- `ppt_tts_sync_synthesize` — Legacy synchronous TTS synthesis kept in parity with the business route; Agents should prefer tts.synthesize which returns a durable operation_id.
- `ppt_tts_audio_status_get` — Read per-slide TTS audio status including freshness and confirmation state.
- `ppt_tts_audio_confirm` — Confirm generated slide audio; confirmation validates artifact hashes and is required before rendering.
- `ppt_media_background_get` — Read the project video-background settings and their manifest synchronization state.
- `ppt_media_background_update` — Update project video-background settings; downstream invalidation follows the registered impact rules.
- `ppt_media_subtitles_get` — Read project subtitle settings (font, color, position) with preview selection.
- `ppt_media_subtitles_update` — Update project subtitle settings; identical saves are no-ops.
- `ppt_video_list` — List rendered videos with freshness metadata; exact artifacts are addressed via artifacts.list.
- `ppt_video_status_get` — Read the final-video status including the current rendered artifact reference.
- `ppt_video_speed` — Create a speed-adjusted MP4 variant of one rendered video; the new file is registered in the artifact registry.
- `ppt_video_delete` — Delete one rendered MP4 together with its .render.json sidecar and artifact record. Destructive and irreversible.
- `ppt_pptx_readiness` — Read image-only PPTX export readiness and its blockers.
- `ppt_pptx_export_create` — Submit a persistent image-only PPTX export job; returns a job id addressable via operation.get and pptx.jobs.get.
- `ppt_pptx_exports_list` — List completed PPTX export artifacts.
- `ppt_pptx_exports_delete` — Delete one PPTX export artifact and its registry record. Destructive and irreversible.
- `ppt_pptx_jobs_list` — List persistent PPTX/video export jobs with an optional job-type filter.
- `ppt_pptx_jobs_get` — Read one persistent export job by id; never substitutes the latest job.
- `ppt_pptx_jobs_retry` — Retry one failed export job as a new persistent job.
- `ppt_subtitles_readiness` — Read merged SRT subtitle export readiness for the current slides.
- `ppt_image_prompt_settings_get` — Read project Step 3 image-generation prompt settings.
- `ppt_image_prompt_settings_update` — Update project Step 3 image-generation prompt settings.
- `ppt_image_prompts_get` — Read the composed per-slide image-generation prompts.
- `ppt_image_generate` — Generate one slide image synchronously through the generation governor; keeps the raw source pair and registers downstream invalidation.
- `ppt_image_change_preview_get` — Read the registered downstream impact preview for replacing one slide image.
- `ppt_image_recovery_list` — List archived image versions available for geometry reuse on one slide.
- `ppt_image_geometry_reuse` — Reuse saved element geometry from an archived image for one slide.
- `ppt_image_candidate_apply` — Apply a generated candidate image to its slide; candidate identity and provenance are validated.
- `ppt_image_delete_all` — Delete all slide images with registered downstream invalidation. Destructive and irreversible.
- `ppt_image_delete` — Delete one slide image (query: disposition, expected_version CAS) with downstream invalidation. Destructive and irreversible.
- `ppt_image_list` — List all slide image states including versions, candidates and confirmation state.
- `ppt_image_order_update` — Update the slide image ordering payload.
- `ppt_image_confirm` — Confirm Step 3 images; unblocks the mask and audio stages and validates completeness.
- `ppt_style_profile_templates_list` — List built-in and saved project profile templates.
- `ppt_style_profile_get` — Read the project profile (pipeline profile selection and overrides).
- `ppt_style_profile_update` — Save the project profile; downstream invalidation follows profile rules.
- `ppt_style_generate` — Generate a project image style from the topic/article via LLM synchronously.
- `ppt_style_reverse_settings_get` — Read the image-style reverse-analysis prompt settings.
- `ppt_style_reverse_settings_update` — Update the image-style reverse-analysis prompt settings.
- `ppt_style_get` — Read the project Step 3 image style settings.
- `ppt_style_update` — Update the project Step 3 image style settings; refreshes prompts and downstream state.
- `ppt_style_reference_settings_get` — Read the style reference-generation prompt settings.
- `ppt_style_reference_settings_update` — Update the style reference-generation prompt settings.
- `ppt_style_references_list` — List the project Step 3 style reference images.
- `ppt_style_references_generate` — Generate style reference images via LLM synchronously.
- `ppt_style_references_delete` — Delete one style reference image by index. Destructive.
- `ppt_style_references_delete_all` — Delete all Step 3 style reference images. Destructive.
- `ppt_style_references_legacy_list` — Legacy project-profile reference image listing kept in parity with the business route.
- `ppt_style_references_legacy_generate` — Legacy project-profile reference image generation path.
- `ppt_style_references_legacy_delete` — Delete one legacy project-profile reference image. Destructive.
- `ppt_style_references_legacy_delete_all` — Delete all legacy project-profile reference images. Destructive.
- `ppt_style_templates_list` — List account-level image style templates.
- `ppt_style_templates_get` — Read one image style template detail.
- `ppt_style_templates_create` — Create an account image style template.
- `ppt_style_project_template_save` — Save the project-scoped Step 3 image style template.
- `ppt_style_project_template_apply` — Apply one image style template to the project.
- `ppt_style_templates_delete` — Delete one account image style template. Destructive.
- `ppt_global_style_get` — Read the legacy-compatible global image style settings.
- `ppt_global_style_update` — Update the global image style settings.
- `ppt_global_style_validate` — Validate a global image style payload without writing.
- `ppt_global_style_templates_list` — List global image style templates.
- `ppt_global_style_templates_get` — Read one global image style template.
- `ppt_global_style_templates_save` — Create or update a global image style template.
- `ppt_global_style_templates_delete` — Delete a global image style template. Destructive.
- `ppt_global_style_template_references_apply` — Apply template reference images into the active global style.
- `ppt_ip_list` — List project IP characters and their reference state.
- `ppt_ip_config_update` — Update project IP character configuration (without file upload).
- `ppt_ip_delete` — Delete one project IP character. Destructive.
- `ppt_mask_settings_get` — Read the global AI Mask settings and migrated prompts.
- `ppt_mask_settings_update` — Update the global AI Mask settings; recognized legacy defaults migrate, genuine custom prompts are preserved.
- `ppt_mask_annotate` — Run automatic AI Mask annotation for the project (detection, semantic matching, exact RLE masks); honors the generation governor and cooperative stop signals.
- `ppt_mask_semantic_blocks` — Read or normalize the Step 5 semantic blocks derived from the Reveal Manifest.
- `ppt_mask_result_get` — Read the stored Step 5 reveal manifest workspace result.
- `ppt_mask_result_repair` — Explicitly repair the stored Step 5 manifest (stale groups, missing groups) instead of mutating on read.
- `ppt_mask_draft_update` — Save the Step 5 draft workspace state; a content change registers the mask impact and commits.
- `ppt_mask_result_update` — Save the final Step 5 manifest; with build_assets=true exact reveal assets are rebuilt before any render.
- `ppt_mask_preview_build` — Build the exact single-slide mask preview and its report.
- `ppt_annotation_summary_get` — Read the project annotation summary: enable decision, per-slide revision and confirm state.
- `ppt_annotation_settings_update` — Update annotation settings including the enable/skip decision; commits with one database write.
- `ppt_annotation_slide_get` — Read one slide's structured annotation state and revision.
- `ppt_annotation_slide_patch` — Apply a structured annotation patch (operations, undo) with revision-conflict handling; commits once.
- `ppt_annotation_text_layout_get` — Read one slide's OCR text layout used for annotation anchoring.
- `ppt_annotation_text_layout_patch` — Patch one slide's text layout; index units follow annotations_core conventions.
- `ppt_annotation_prompts_get` — Read annotation prompts with an optional slide filter.
- `ppt_annotation_prompts_update` — Update annotation prompts.
- `ppt_annotation_slide_prepare` — Prepare one slide for annotation review (scene context binding).
- `ppt_annotation_slide_confirm` — Confirm one slide's annotations; the confirmation binds the reviewed revision and commits once.
- `ppt_annotation_jobs_submit` — Submit an OCR/annotation planning job; poll via annotation.jobs.get or operation.get when durable.
- `ppt_annotation_jobs_get` — Read one annotation job by id; ownership is validated against the account.
- `ppt_annotation_jobs_cancel` — Request cancellation of one annotation job at a safe boundary.
- `ppt_annotation_preview_export` — Export an annotation preview video for one slide; returns a token addressable by the download transport.
- `ppt_digital_human_slide_generate` — Generate the digital-human presenter video for one slide (ComfyUI/Minimax backend per configuration).
- `ppt_digital_human_jobs_get` — Read one digital-human generation job by id.
- `ppt_digital_human_slide_compose` — Compose the slide video with the digital-human presenter overlay.
- `ppt_digital_human_audio_export` — Export the full digital-human narration audio for the project.
- `ppt_digital_human_avatars_list` — List uploaded digital-human avatars.
- `ppt_digital_human_workflow_get` — Read the project ComfyUI workflow template state.
- `ppt_course_tree_get` — Read the full course/chapter/project tree.
- `ppt_course_reorder` — Reorder courses with an ordered id list.
- `ppt_chapter_reorder` — Reorder chapters within one course.
- `ppt_course_create` — Create a course.
- `ppt_course_list` — List courses.
- `ppt_course_get` — Read one course with its chapters.
- `ppt_course_update` — Update course name/description.
- `ppt_course_delete` — Delete one course. Destructive.
- `ppt_chapter_create` — Create a chapter inside one course.
- `ppt_chapter_update` — Update one chapter.
- `ppt_chapter_delete` — Delete one chapter. Destructive.
- `ppt_chapter_move` — Move one chapter to another course/position.
- `ppt_project_move` — Move one project into a course chapter.
- `ppt_project_reorder` — Reorder projects within one chapter.
- `ppt_config_list` — List creation configuration packages (query: include_archived).
- `ppt_config_default_payload_get` — Read the default creation-config payload template.
- `ppt_config_create` — Create a creation configuration package.
- `ppt_config_import` — Import a creation configuration package; every image reference is validated before any write.
- `ppt_config_get` — Read one creation configuration package.
- `ppt_config_update` — Update one creation configuration package.
- `ppt_config_version_get` — Read one stored version of a creation configuration package.
- `ppt_config_copy` — Copy one creation configuration package.
- `ppt_config_version_create` — Snapshot the current package as a new version.
- `ppt_config_archive` — Archive or restore one creation configuration package.
- `ppt_config_delete` — Delete one creation configuration package. Destructive.
- `ppt_config_resolve` — Resolve the effective creation configuration for a project with package overrides.
- `ppt_pipeline_pause` — Pause the active one-click pipeline run at the next safe boundary.
- `ppt_pipeline_statuses_list` — List all active one-click run statuses across projects.
- `ppt_media_background_config_get` — Read the storyboard video-background configuration (mode, color, image reference).
- `ppt_media_background_config_update` — Update the storyboard video-background configuration; prompts, manifest and Reveal assets are synchronized.
- `ppt_settings_get` — Read masked global settings; credentials are never returned in clear text.
- `ppt_settings_update` — Update global settings; masked placeholders preserve stored secrets.
- `ppt_settings_config_export` — Export the portable configuration package (secrets stripped).
- `ppt_settings_config_export_secrets` — Export the configuration package including secrets (JSON).
- `ppt_settings_config_import` — Import a configuration package; every image reference is validated before any write.
- `ppt_settings_llm_test` — Test the LLM connection with the supplied credentials; never stores them.
- `ppt_settings_image_test` — Test the image provider connection with the supplied credentials.
- `ppt_settings_tts_test` — Test the TTS provider connection with the supplied credentials.
- `ppt_settings_comfyui_workflow_get` — Read the global ComfyUI TTS workflow template.
- `ppt_credentials_list` — List credential references (query: include_disabled); secret values stay masked.
- `ppt_credentials_create` — Create a credential reference; the secret travels once and is stored hashed.
- `ppt_credentials_update` — Update one credential by reference; omitted secret fields are preserved.
- `ppt_connections_list` — List saved model connections (query: kind, include_archived).
- `ppt_connections_create` — Create a saved model connection.
- `ppt_connections_get` — Read one saved model connection with masked credentials.
- `ppt_connections_update` — Update one saved model connection.
- `ppt_connections_copy` — Copy one saved model connection.
- `ppt_connections_test` — Test one saved model connection end to end.
- `ppt_connections_state_update` — Archive/restore or toggle one saved model connection.
- `ppt_connections_delete` — Delete one saved model connection. Destructive.
- `ppt_diagnostics_runtime` — Read runtime diagnostics for the current process.
- `ppt_diagnostics_governor` — Read the generation governor snapshot (gateway quotas and queues).
- `ppt_diagnostics_error_log` — Read recent pipeline error log entries (query: limit).
- `ppt_project_impacts_get` — Read registered downstream impacts for the project with their acknowledge state.
- `ppt_project_impacts_reuse_preview` — Preview which artifacts a storyboard reuse confirmation would keep or clear.
- `ppt_project_impacts_reuse_confirm` — Confirm storyboard reuse after a profile switch, with explicit impact acknowledgement.
- `ppt_project_impacts_decision_update` — Update one impact item's acknowledgement decision; does not override artifact freshness gates.
- `ppt_project_impacts_image_reuse_confirm` — Confirm image reuse after storyboard structure changes, with explicit impact acknowledgement.
- `ppt_project_ai_mode_get` — Read the project AI mode (auto/manual).
- `ppt_project_change_preview` — Read-only what-if impact preview for a proposed Visual Contract edit; reuses the same pure diff as the commit path and reports the affected slides and expected downstream invalidation without writing anything.
- `ppt_project_ai_mode_update` — Update the project AI mode (auto/manual).
- `ppt_accounts_list` — List creative accounts visible to this connection.
- `ppt_accounts_current` — Read the account bound to this Agent connection.
- `ppt_accounts_create` — Create a creative account; default creation configuration is set after switching.
- `ppt_accounts_provision` — Provision a ready-to-run account from the current one without exposing reused secrets.
- `ppt_accounts_rename` — Rename one account.
- `ppt_accounts_delete` — Delete one account and its scoped data. Destructive.
- `ppt_accounts_default_config_update` — Set or clear one account's default creation configuration; the package must resolve inside that account.
- `ppt_accounts_agent_token_create` — Create one Agent token for the account; the token value is returned only at creation time.

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
