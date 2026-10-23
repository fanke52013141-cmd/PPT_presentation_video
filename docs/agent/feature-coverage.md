# Business feature coverage

Generated from config/agent_features.json; pending is an explicit implementation backlog.

This source inventory covers business HTTP entrypoints. Background-only operations and field parity require additional scenario review.

| Feature ID | Coverage | Capabilities | Owner | Reason |
|---|---|---|---|---|
| `account_routes.account_agent_token` | complete | accounts.agent_token.create | account_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `account_routes.account_create` | complete | accounts.create | account_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `account_routes.account_default_config` | complete | accounts.default_config.update | account_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `account_routes.account_delete` | complete | accounts.delete | account_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `account_routes.account_provision_from_current` | complete | accounts.provision | account_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed (mocked-provider full workflow / live transfer client). |
| `account_routes.account_rename` | complete | accounts.rename | account_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `account_routes.account_select` | exempt |  | account_routes.py | Web session-cookie account switching; Agent connections bind their account via token authentication. |
| `account_routes.accounts` | complete | accounts.list | account_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `account_routes.current_account` | complete | accounts.current | account_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `ai_mask_routes.annotate_ai_mask_route` | partial | mask.annotate | ai_mask_routes.py | Deterministic adapter verified; full acceptance requires a live provider run. |
| `ai_mask_routes.get_ai_mask_settings_route` | complete | mask.settings.get | ai_mask_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `ai_mask_routes.put_ai_mask_settings_route` | complete | mask.settings.update | ai_mask_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `annotation_routes.cancel_annotation_job` | complete | annotation.jobs.cancel | annotation_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `annotation_routes.confirm_annotation_slide` | partial | annotation.slide.confirm | annotation_routes.py | Adapter verified structurally; scenario requires generated project assets and is pending. |
| `annotation_routes.download_annotation_preview` | partial | annotation.preview.download | annotation_routes.py | HTTP byte-stream transport declared; transfer client exists; domain acceptance pending. |
| `annotation_routes.export_annotation_preview` | partial | annotation.preview.export | annotation_routes.py | Requires the external engine/service; acceptance pending. |
| `annotation_routes.get_annotation_editor_ink` | partial | annotation.editor_ink.get | annotation_routes.py | HTTP byte-stream transport declared; transfer client exists; domain acceptance pending. |
| `annotation_routes.get_annotation_ink` | partial | annotation.ink.get | annotation_routes.py | HTTP byte-stream transport declared; transfer client exists; domain acceptance pending. |
| `annotation_routes.get_annotation_job` | complete | annotation.jobs.get | annotation_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `annotation_routes.get_annotation_prompts` | complete | annotation.prompts.get | annotation_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `annotation_routes.get_annotation_scene_asset` | partial | annotation.scene_asset.get | annotation_routes.py | HTTP byte-stream transport declared; transfer client exists; domain acceptance pending. |
| `annotation_routes.get_annotation_slide` | complete | annotation.slide.get | annotation_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `annotation_routes.get_annotation_summary` | complete | annotation.summary.get | annotation_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `annotation_routes.get_annotation_text_layout` | complete | annotation.text_layout.get | annotation_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `annotation_routes.patch_annotation_slide` | partial | annotation.slide.patch | annotation_routes.py | Adapter verified structurally; scenario requires generated project assets and is pending. |
| `annotation_routes.patch_annotation_text_layout` | partial | annotation.text_layout.patch | annotation_routes.py | Adapter verified structurally; scenario requires generated project assets and is pending. |
| `annotation_routes.prepare_annotation_slide` | partial | annotation.slide.prepare | annotation_routes.py | Adapter verified structurally; scenario requires generated project assets and is pending. |
| `annotation_routes.put_annotation_prompts` | complete | annotation.prompts.update | annotation_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `annotation_routes.submit_annotation_job` | partial | annotation.jobs.submit | annotation_routes.py | Requires the external engine/service; acceptance pending. |
| `annotation_routes.update_annotation_settings` | complete | annotation.settings.update | annotation_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `article_routes.generate_article_from_topic` | partial | source.set | article_routes.py | source.set verified for direct import; live topic generation acceptance pending. |
| `article_routes.get_article_generation_settings` | complete | article.settings.get | article_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `article_routes.get_step1_result` | complete | article.result.get | article_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `article_routes.import_article` | complete | source.set | article_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `article_routes.update_article_generation_settings` | complete | article.settings.update | article_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `article_routes.update_step1_result` | complete | article.result.update | article_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `course_routes.create_chapter` | complete | chapter.create | course_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `course_routes.create_course` | complete | course.create | course_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `course_routes.delete_chapter` | complete | chapter.delete | course_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `course_routes.delete_course` | complete | course.delete | course_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `course_routes.get_course` | complete | course.get | course_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `course_routes.get_tree` | complete | course.tree.get | course_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `course_routes.list_courses` | complete | course.list | course_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `course_routes.move_chapter` | complete | chapter.move | course_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `course_routes.move_project` | complete | project.move | course_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `course_routes.reorder_chapters` | complete | chapter.reorder | course_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `course_routes.reorder_courses` | complete | course.reorder | course_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `course_routes.reorder_projects` | complete | project.reorder | course_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `course_routes.update_chapter` | complete | chapter.update | course_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `course_routes.update_course` | complete | course.update | course_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `creation_config_routes.archive_creation_config` | complete | config.archive | creation_config_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `creation_config_routes.copy_creation_config` | complete | config.copy | creation_config_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `creation_config_routes.create_creation_config` | complete | config.create | creation_config_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `creation_config_routes.create_creation_config_version` | complete | config.version.create | creation_config_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `creation_config_routes.delete_creation_config` | complete | config.delete | creation_config_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `creation_config_routes.get_creation_config` | complete | config.get | creation_config_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `creation_config_routes.get_creation_config_version` | complete | config.version.get | creation_config_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `creation_config_routes.get_default_creation_config_payload` | complete | config.default_payload.get | creation_config_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `creation_config_routes.import_creation_config` | complete | config.import | creation_config_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed (mocked-provider full workflow / live transfer client). |
| `creation_config_routes.list_creation_configs` | complete | config.list | creation_config_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `creation_config_routes.resolve_creation_config` | complete | config.resolve | creation_config_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `creation_config_routes.update_creation_config` | complete | config.update | creation_config_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `credential_routes.create_credential` | complete | credentials.create | credential_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `credential_routes.list_credentials` | complete | credentials.list | credential_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `credential_routes.update_credential` | complete | credentials.update | credential_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `diagnostics_routes.generation_governor_snapshot` | complete | diagnostics.governor | diagnostics_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `diagnostics_routes.get_error_log` | complete | diagnostics.error_log | diagnostics_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `diagnostics_routes.get_latest_error_log` | complete | diagnostics.error_log.latest | diagnostics_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed (mocked-provider full workflow / live transfer client). |
| `diagnostics_routes.runtime_diagnostics` | complete | diagnostics.runtime | diagnostics_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `digital_human_routes.compose_dh_slide` | partial | digital_human.slide.compose | digital_human_routes.py | Requires the external engine/service; acceptance pending. |
| `digital_human_routes.dh_health` | partial | digital_human.health | digital_human_routes.py | Requires the external engine/service; acceptance pending. |
| `digital_human_routes.export_full_audio` | partial | digital_human.audio.export | digital_human_routes.py | Requires the external engine/service; acceptance pending. |
| `digital_human_routes.generate_dh` | partial | digital_human.slide.generate | digital_human_routes.py | Requires the external engine/service; acceptance pending. |
| `digital_human_routes.generate_dh_full` | partial | digital_human.generate | digital_human_routes.py | Requires the external engine/service; acceptance pending. |
| `digital_human_routes.get_comfyui_workflow` | complete | digital_human.workflow.get | digital_human_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `digital_human_routes.get_dh_composite_video` | partial | digital_human.composite_video.get | digital_human_routes.py | HTTP byte-stream transport declared; transfer client exists; domain acceptance pending. |
| `digital_human_routes.get_dh_config` | complete | digital_human.config.get | digital_human_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `digital_human_routes.get_dh_job` | partial | digital_human.jobs.get | digital_human_routes.py | Requires the external engine/service; acceptance pending. |
| `digital_human_routes.get_dh_slide_video` | partial | digital_human.slide_video.get | digital_human_routes.py | HTTP byte-stream transport declared; transfer client exists; domain acceptance pending. |
| `digital_human_routes.get_dh_upload_video` | partial | digital_human.video.uploaded.get | digital_human_routes.py | HTTP byte-stream transport declared; transfer client exists; domain acceptance pending. |
| `digital_human_routes.get_full_audio` | partial | digital_human.audio.file | digital_human_routes.py | HTTP byte-stream transport declared; transfer client exists; domain acceptance pending. |
| `digital_human_routes.list_dh_avatars` | partial | digital_human.avatars.list | digital_human_routes.py | Requires the external engine/service; acceptance pending. |
| `digital_human_routes.put_dh_config` | complete | digital_human.config.update | digital_human_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `digital_human_routes.upload_comfyui_workflow` | complete | digital_human.workflow.upload | digital_human_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed (mocked-provider full workflow / live transfer client). |
| `digital_human_routes.upload_dh_avatar` | partial | digital_human.avatars.upload | digital_human_routes.py | HTTP multipart transport declared; Agent client upload support pending. |
| `digital_human_routes.upload_dh_video` | partial | digital_human.video.upload | digital_human_routes.py | HTTP multipart transport declared; Agent client upload support pending. |
| `generation_control_routes.get_generation_control` | complete | generation.status | generation_control_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `generation_control_routes.stop_generation` | complete | generation.stop, operation.cancel | generation_control_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `global_image_style_routes.apply_image_style_template_references` | partial | global_style.template_references.apply | global_image_style_routes.py | Adapter verified structurally; scenario requires generated project assets and is pending. |
| `global_image_style_routes.delete_image_style_template` | complete | global_style.templates.delete | global_image_style_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `global_image_style_routes.get_image_style` | complete | global_style.get | global_image_style_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `global_image_style_routes.get_image_style_reference` | partial | global_style.reference.get | global_image_style_routes.py | HTTP byte-stream transport declared; transfer client exists; domain acceptance pending. |
| `global_image_style_routes.get_image_style_template` | complete | global_style.templates.get | global_image_style_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `global_image_style_routes.get_image_style_template_reference` | partial | style.templates.reference.get | global_image_style_routes.py | HTTP byte-stream transport declared; transfer client exists; domain acceptance pending. |
| `global_image_style_routes.get_image_style_templates` | complete | global_style.templates.list | global_image_style_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `global_image_style_routes.save_image_style_template` | complete | global_style.templates.save | global_image_style_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `global_image_style_routes.update_image_style` | complete | global_style.update | global_image_style_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `global_image_style_routes.update_image_style_reference` | partial | global_style.reference.update | global_image_style_routes.py | HTTP multipart transport declared; Agent client upload support pending. |
| `global_image_style_routes.validate_image_style` | complete | global_style.validate | global_image_style_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `image_workflow_routes.apply_slide_candidate` | partial | image.candidate.apply | image_workflow_routes.py | Adapter verified structurally; scenario requires generated project assets and is pending. |
| `image_workflow_routes.confirm_images` | complete | image.confirm | image_workflow_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed (mocked-provider full workflow / live transfer client). |
| `image_workflow_routes.delete_all_slide_images` | partial | image.delete_all | image_workflow_routes.py | Adapter verified structurally; scenario requires generated project assets and is pending. |
| `image_workflow_routes.delete_slide_image` | complete | image.delete | image_workflow_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed (mocked-provider full workflow / live transfer client). |
| `image_workflow_routes.download_all_slide_images` | complete | image.download_all | image_workflow_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed (mocked-provider full workflow / live transfer client). |
| `image_workflow_routes.generate_slide_image` | complete | image.generate | image_workflow_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed (mocked-provider full workflow / live transfer client). |
| `image_workflow_routes.get_all_images` | complete | image.list | image_workflow_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `image_workflow_routes.get_slide_candidate_file` | complete | image.candidate.get | image_workflow_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed (mocked-provider full workflow / live transfer client). |
| `image_workflow_routes.get_slide_image_change_preview` | complete | image.change_preview.get | image_workflow_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `image_workflow_routes.get_slide_image_file` | complete | image.get | image_workflow_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed (mocked-provider full workflow / live transfer client). |
| `image_workflow_routes.get_slide_prompts` | complete | image.prompts.get | image_workflow_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `image_workflow_routes.get_step3_prompt_settings` | complete | image.prompt_settings.get | image_workflow_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `image_workflow_routes.image_recovery_overlay` | partial | image.recovery.overlay | image_workflow_routes.py | HTTP byte-stream transport declared; transfer client exists; domain acceptance pending. |
| `image_workflow_routes.list_slide_image_recovery` | complete | image.recovery.list | image_workflow_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `image_workflow_routes.reuse_slide_image_geometry` | partial | image.geometry.reuse | image_workflow_routes.py | Adapter verified structurally; scenario requires generated project assets and is pending. |
| `image_workflow_routes.update_step3_image_order` | complete | image.order.update | image_workflow_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed (mocked-provider full workflow / live transfer client). |
| `image_workflow_routes.update_step3_prompt_settings` | complete | image.prompt_settings.update | image_workflow_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `image_workflow_routes.upload_slide_image` | complete | image.upload | image_workflow_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed (mocked-provider full workflow / live transfer client). |
| `ip_character_routes.delete_ip_character` | partial | ip.delete | ip_character_routes.py | Adapter verified structurally; scenario requires generated project assets and is pending. |
| `ip_character_routes.get_ip_character_image` | partial | ip.image.get | ip_character_routes.py | HTTP byte-stream transport declared; transfer client exists; domain acceptance pending. |
| `ip_character_routes.get_ip_characters` | complete | ip.list | ip_character_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `ip_character_routes.update_ip_character_config` | complete | ip.config.update | ip_character_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `ip_character_routes.upsert_ip_character` | partial | ip.upsert | ip_character_routes.py | HTTP multipart transport declared; Agent client upload support pending. |
| `mask_editor_routes.build_step5_mask_preview` | partial | mask.preview.build | mask_editor_routes.py | Adapter verified structurally; scenario requires generated project assets and is pending. |
| `mask_editor_routes.get_step5_mask_preview` | partial | mask.preview.get | mask_editor_routes.py | HTTP byte-stream transport declared; transfer client exists; domain acceptance pending. |
| `mask_editor_routes.get_step5_result` | partial | mask.result.get | mask_editor_routes.py | Adapter verified structurally; scenario requires generated project assets and is pending. |
| `mask_editor_routes.repair_step5_result` | partial | mask.result.repair | mask_editor_routes.py | Adapter verified structurally; scenario requires generated project assets and is pending. |
| `mask_editor_routes.semantic_blocks_project` | partial | mask.semantic_blocks | mask_editor_routes.py | Adapter verified structurally; scenario requires generated project assets and is pending. |
| `mask_editor_routes.update_step5_draft` | partial | mask.draft.update | mask_editor_routes.py | Adapter verified structurally; scenario requires generated project assets and is pending. |
| `mask_editor_routes.update_step5_result` | partial | mask.result.update | mask_editor_routes.py | Adapter verified structurally; scenario requires generated project assets and is pending. |
| `model_connection_routes.copy_model_connection` | complete | connections.copy | model_connection_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `model_connection_routes.create_model_connection` | complete | connections.create | model_connection_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `model_connection_routes.delete_model_connection` | complete | connections.delete | model_connection_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `model_connection_routes.get_model_connection` | complete | connections.get | model_connection_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `model_connection_routes.list_model_connections` | complete | connections.list | model_connection_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `model_connection_routes.test_saved_model_connection` | partial | connections.test | model_connection_routes.py | Requires the external engine/service; acceptance pending. |
| `model_connection_routes.update_model_connection` | complete | connections.update | model_connection_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `model_connection_routes.update_model_connection_state` | complete | connections.state.update | model_connection_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `model_connection_routes.upload_model_reference_audio` | partial | connections.reference_audio.upload | model_connection_routes.py | HTTP multipart transport declared; Agent client upload support pending. |
| `narration_routes.annotate_step6_narration` | partial | narration.annotate | narration_routes.py | Deterministic adapter verified; full acceptance requires a live provider run. |
| `narration_routes.get_narration_annotation_settings` | complete | narration.annotation_settings.get | narration_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `narration_routes.get_step6_result` | complete | narration.result.get | narration_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `narration_routes.init_step6_narration` | complete | narration.init | narration_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `narration_routes.repair_step6_result` | complete | narration.repair | narration_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `narration_routes.update_narration_annotation_settings` | complete | narration.annotation_settings.update | narration_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `narration_routes.update_step6_result` | complete | narration.result.update | narration_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `one_click_routes.batch_one_click_status_route` | complete | pipeline.statuses.list | one_click_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `one_click_routes.get_one_click_status_route` | partial | pipeline.status | one_click_routes.py | Shares pipeline.status acceptance; a live automated run is a separately validated item. |
| `one_click_routes.pause_one_click_route` | partial | pipeline.pause | one_click_routes.py | Pause requires an active automated run; acceptance pending. |
| `one_click_routes.start_one_click_route` | partial | pipeline.run | one_click_routes.py | Shares pipeline.run acceptance; a live automated run is a separately validated item. |
| `pptx_routes.create_pptx_export` | complete | pptx.export.create | pptx_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed (mocked-provider full workflow / live transfer client). |
| `pptx_routes.delete_export` | complete | pptx.exports.delete | pptx_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed (mocked-provider full workflow / live transfer client). |
| `pptx_routes.download_export` | complete | pptx.export.download | pptx_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed (mocked-provider full workflow / live transfer client). |
| `pptx_routes.get_job` | complete | pptx.jobs.get | pptx_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `pptx_routes.list_exports` | complete | pptx.exports.list | pptx_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `pptx_routes.list_jobs` | complete | pptx.jobs.list | pptx_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `pptx_routes.pptx_readiness` | complete | pptx.readiness | pptx_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `pptx_routes.retry_job` | partial | pptx.jobs.retry | pptx_routes.py | Adapter verified structurally; scenario requires generated project assets and is pending. |
| `project_routes.confirm_storyboard_image_reuse` | partial | project.impacts.image_reuse_confirm | project_routes.py | Adapter verified structurally; scenario requires generated project assets and is pending. |
| `project_routes.confirm_storyboard_reuse` | partial | project.impacts.reuse_confirm | project_routes.py | Adapter verified structurally; scenario requires generated project assets and is pending. |
| `project_routes.create_project` | partial | project.create | project_routes.py | Agent counterpart exists; field and behavior parity requires domain acceptance. |
| `project_routes.delete_project` | partial | project.delete | project_routes.py | Agent counterpart exists; field and behavior parity requires domain acceptance. |
| `project_routes.get_project` | partial | project.get, project.state | project_routes.py | Project metadata plus read-only workflow state, resource hashes and source-owned checks are exposed. Remaining detail fields and full domain acceptance are pending. |
| `project_routes.get_project_ai_mode` | complete | project.ai_mode.get | project_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `project_routes.get_project_impacts` | complete | project.impacts.get | project_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `project_routes.list_projects` | partial | project.list | project_routes.py | Agent counterpart exists; field and behavior parity requires domain acceptance. |
| `project_routes.preview_storyboard_reuse` | complete | project.impacts.reuse_preview | project_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed (mocked-provider full workflow / live transfer client). |
| `project_routes.update_project` | partial | project.update | project_routes.py | Agent counterpart exists; field and behavior parity requires domain acceptance. |
| `project_routes.update_project_ai_mode` | complete | project.ai_mode.update | project_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `project_routes.update_project_impact_decision` | partial | project.impacts.decision.update | project_routes.py | Adapter verified structurally; scenario requires generated project assets and is pending. |
| `project_style_routes.apply_step3_template` | partial | style.project_template.apply | project_style_routes.py | Adapter verified structurally; scenario requires generated project assets and is pending. |
| `project_style_routes.create_account_style_template` | complete | style.templates.create | project_style_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `project_style_routes.create_account_style_template_with_references` | partial | style.templates.create_with_references | project_style_routes.py | HTTP multipart transport declared; Agent client upload support pending. |
| `project_style_routes.delete_all_legacy_reference_images` | partial | style.references_legacy.delete_all | project_style_routes.py | Adapter verified structurally; scenario requires generated project assets and is pending. |
| `project_style_routes.delete_all_step3_reference_images` | partial | style.references.delete_all | project_style_routes.py | Adapter verified structurally; scenario requires generated project assets and is pending. |
| `project_style_routes.delete_legacy_reference_image` | partial | style.references_legacy.delete | project_style_routes.py | Adapter verified structurally; scenario requires generated project assets and is pending. |
| `project_style_routes.delete_step3_reference_image` | partial | style.references.delete | project_style_routes.py | Adapter verified structurally; scenario requires generated project assets and is pending. |
| `project_style_routes.delete_step3_template` | complete | style.templates.delete | project_style_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `project_style_routes.generate_legacy_reference_images` | partial | style.references_legacy.generate | project_style_routes.py | Deterministic adapter verified; full acceptance requires a live provider run. |
| `project_style_routes.generate_project_image_style` | partial | style.generate | project_style_routes.py | Deterministic adapter verified; full acceptance requires a live provider run. |
| `project_style_routes.generate_step3_reference_images` | partial | style.references.generate | project_style_routes.py | Deterministic adapter verified; full acceptance requires a live provider run. |
| `project_style_routes.get_legacy_reference_image` | partial | style.references_legacy.get | project_style_routes.py | HTTP byte-stream transport declared; transfer client exists; domain acceptance pending. |
| `project_style_routes.get_project_profile` | complete | style.profile.get | project_style_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `project_style_routes.get_project_profile_templates` | complete | style.profile_templates.list | project_style_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `project_style_routes.get_reference_generation_prompt_settings` | complete | style.reference_settings.get | project_style_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `project_style_routes.get_reverse_style_prompt_settings` | complete | style.reverse_settings.get | project_style_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `project_style_routes.get_step3_image_style` | complete | style.get | project_style_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `project_style_routes.get_step3_reference_image` | partial | style.references.get | project_style_routes.py | HTTP byte-stream transport declared; transfer client exists; domain acceptance pending. |
| `project_style_routes.get_step3_template_detail` | complete | style.templates.get | project_style_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `project_style_routes.get_step3_template_reference` | partial | style.templates.reference.get | project_style_routes.py | HTTP byte-stream transport declared; transfer client exists; domain acceptance pending. |
| `project_style_routes.list_legacy_reference_images` | complete | style.references_legacy.list | project_style_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `project_style_routes.list_step3_reference_images` | complete | style.references.list | project_style_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `project_style_routes.list_step3_templates` | complete | style.templates.list | project_style_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `project_style_routes.put_step3_image_style` | complete | style.update | project_style_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `project_style_routes.reverse_legacy_project_image_style` | partial | style.reverse.generate_legacy | project_style_routes.py | HTTP multipart transport declared; Agent client upload support pending. |
| `project_style_routes.reverse_step3_image_style` | partial | style.reverse.generate | project_style_routes.py | HTTP multipart transport declared; Agent client upload support pending. |
| `project_style_routes.save_project_profile` | complete | style.profile.update | project_style_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `project_style_routes.save_step3_template` | partial | style.project_template.save | project_style_routes.py | Adapter verified structurally; scenario requires generated project assets and is pending. |
| `project_style_routes.update_reference_generation_prompt_settings` | complete | style.reference_settings.update | project_style_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `project_style_routes.update_reverse_style_prompt_settings` | complete | style.reverse_settings.update | project_style_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `project_style_routes.upload_step3_reference_images` | partial | style.references.upload | project_style_routes.py | HTTP multipart transport declared; Agent client upload support pending. |
| `settings_routes.export_full_config` | complete | settings.config.export | settings_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `settings_routes.export_full_config_with_secrets` | complete | settings.config.export.secrets | settings_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `settings_routes.export_full_config_with_secrets_zip` | partial | settings.config.export.secrets.zip | settings_routes.py | HTTP byte-stream transport declared; transfer client exists; domain acceptance pending. |
| `settings_routes.export_full_config_zip` | complete | settings.config.export.zip | settings_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed (mocked-provider full workflow / live transfer client). |
| `settings_routes.get_comfyui_tts_workflow` | complete | settings.comfyui_workflow.get | settings_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `settings_routes.get_settings` | complete | settings.get | settings_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `settings_routes.import_full_config` | complete | settings.config.import | settings_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `settings_routes.import_full_config_zip` | complete | settings.config.import.zip | settings_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed (mocked-provider full workflow / live transfer client). |
| `settings_routes.test_image_connection` | partial | settings.image.test | settings_routes.py | Requires the external engine/service; acceptance pending. |
| `settings_routes.test_llm_connection` | partial | settings.llm.test | settings_routes.py | Requires the external engine/service; acceptance pending. |
| `settings_routes.test_tts_connection` | partial | settings.tts.test | settings_routes.py | Requires the external engine/service; acceptance pending. |
| `settings_routes.update_system_settings` | complete | settings.update | settings_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `settings_routes.upload_comfyui_tts_workflow` | partial | settings.comfyui_workflow.upload | settings_routes.py | HTTP multipart transport declared; Agent client upload support pending. |
| `storyboard_background.get_background` | complete | media.background_config.get | storyboard_background.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `storyboard_background.get_background_image` | partial | media.background_image.get | storyboard_background.py | HTTP byte-stream transport declared; transfer client exists; domain acceptance pending. |
| `storyboard_background.put_background` | complete | media.background_config.update | storyboard_background.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `storyboard_background.upload_background` | partial | media.background_image.upload | storyboard_background.py | HTTP multipart transport declared; Agent client upload support pending. |
| `storyboard_routes.compose_step2_visual_contract` | complete | storyboard.compose | storyboard_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `storyboard_routes.delete_step2_prompt_template` | complete | storyboard.prompt_templates.delete | storyboard_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `storyboard_routes.delete_storyboard_template` | complete | storyboard.templates.delete | storyboard_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `storyboard_routes.execute_step2` | partial | storyboard.execute | storyboard_routes.py | Deterministic adapter verified; full acceptance still requires a live LLM generation run. |
| `storyboard_routes.execute_step2_script_plan` | complete | storyboard.script.execute | storyboard_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed (mocked-provider full workflow / live transfer client). |
| `storyboard_routes.execute_step2_visual_plan` | complete | storyboard.visual.execute | storyboard_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed (mocked-provider full workflow / live transfer client). |
| `storyboard_routes.get_step2_prompt_preview` | complete | storyboard.preview | storyboard_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `storyboard_routes.get_step2_prompt_template` | complete | storyboard.prompt_templates.get | storyboard_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `storyboard_routes.get_step2_prompt_templates` | complete | storyboard.prompt_templates.list | storyboard_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `storyboard_routes.get_step2_prompts` | complete | storyboard.prompts.get | storyboard_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `storyboard_routes.get_step2_result` | complete | storyboard.contract.get | storyboard_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `storyboard_routes.get_step2_rules` | complete | storyboard.rules.get | storyboard_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `storyboard_routes.get_step2_script_plan` | complete | storyboard.script.get | storyboard_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `storyboard_routes.get_step2_visual_plan` | complete | storyboard.visual.get | storyboard_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `storyboard_routes.get_storyboard_templates` | complete | storyboard.templates.list | storyboard_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `storyboard_routes.repair_step2_result` | complete | storyboard.contract.repair | storyboard_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed (mocked-provider full workflow / live transfer client). |
| `storyboard_routes.save_step2_prompt_template` | complete | storyboard.prompt_templates.save | storyboard_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `storyboard_routes.save_storyboard_template` | complete | storyboard.templates.save | storyboard_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `storyboard_routes.submit_step2_manual_skeleton` | complete | storyboard.skeleton.submit | storyboard_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `storyboard_routes.update_step2_prompts` | complete | storyboard.prompts.update | storyboard_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `storyboard_routes.update_step2_result` | complete | storyboard.contract.update | storyboard_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `storyboard_routes.update_step2_rules` | complete | storyboard.rules.update | storyboard_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `storyboard_routes.update_step2_script_plan` | complete | storyboard.script.update | storyboard_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `storyboard_routes.update_step2_visual_plan` | complete | storyboard.visual.update | storyboard_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `subtitle_export_routes.download_subtitles_srt` | complete | subtitles.download | subtitle_export_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed (mocked-provider full workflow / live transfer client). |
| `subtitle_export_routes.get_subtitle_export_readiness` | complete | subtitles.readiness | subtitle_export_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `tts_routes.confirm_tts_audio` | complete | tts.audio.confirm | tts_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed (mocked-provider full workflow / live transfer client). |
| `tts_routes.create_tts_synthesis_job` | complete | tts.synthesize | tts_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed (mocked-provider full workflow / live transfer client). |
| `tts_routes.get_slide_audio_file` | complete | audio.get | tts_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed (mocked-provider full workflow / live transfer client). |
| `tts_routes.get_tts_audio_status` | complete | tts.audio_status.get | tts_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `tts_routes.get_tts_synthesis_job` | complete | operation.get | tts_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed (mocked-provider full workflow / live transfer client). |
| `tts_routes.list_tts_synthesis_jobs` | complete | operation.list | tts_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed (mocked-provider full workflow / live transfer client). |
| `tts_routes.synthesize_tts_resumable` | partial | tts.sync_synthesize | tts_routes.py | Deterministic adapter verified; full acceptance requires a live provider run. |
| `video_routes.create_speed_adjusted_video` | partial | video.speed | video_routes.py | Adapter verified structurally; scenario requires generated project assets and is pending. |
| `video_routes.delete_project_video` | complete | video.delete | video_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed (mocked-provider full workflow / live transfer client). |
| `video_routes.get_final_video` | complete | video.latest | video_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed (mocked-provider full workflow / live transfer client). |
| `video_routes.get_final_video_status` | complete | video.status.get | video_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `video_routes.get_project_video` | complete | video.download | video_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed (mocked-provider full workflow / live transfer client). |
| `video_routes.get_render_status` | partial | operation.get, operation.list | video_routes.py | Exact durable operation lifecycle exposed; remaining domain-specific fields require acceptance. |
| `video_routes.list_project_videos` | complete | video.list | video_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `video_routes.render_video` | partial | video.render | video_routes.py | Exact durable operation lifecycle exposed; remaining domain-specific fields require acceptance. |
| `visual_settings_routes.get_project_subtitle_settings` | complete | media.subtitles.get | visual_settings_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `visual_settings_routes.get_step3_visual_settings` | complete | media.background.get | visual_settings_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `visual_settings_routes.update_project_subtitle_settings` | complete | media.subtitles.update | visual_settings_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
| `visual_settings_routes.update_step3_visual_settings` | complete | media.background.update | visual_settings_routes.py | Domain adapter shares the business service entry; isolated scenario acceptance passed. |
