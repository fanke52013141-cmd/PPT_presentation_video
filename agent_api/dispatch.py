"""Explicit adapters to source-owned Agent endpoints; no dynamic imports from input."""

from __future__ import annotations

import inspect
import json
from typing import Any

from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ValidationError
from starlette.responses import JSONResponse

from agent_api.errors import AgentAPIError
from agent_contract.capabilities import get_capability
from agent_contract.discovery import describe_capability, input_model, path_names, required_scope


# These are Python adapter names, never supplied or resolved by the caller.
# Both named HTTP routes and invoke execute these same functions.
HANDLERS = {
    "operation.get": "agent_get_operation",
    "operation.list": "agent_list_operations",
    "operation.cancel": "agent_cancel_operation",
    "identity.get": "get_agent_identity",
    "diagnostics": "get_diagnostics",
    "project.create": "agent_create_project",
    "project.list": "agent_list_projects",
    "project.get": "agent_get_project",
    "project.state": "agent_project_state",
    "project.update": "agent_update_project",
    "project.delete": "agent_delete_project",
    "source.set": "agent_set_source",
    "pipeline.run": "agent_start_pipeline",
    "pipeline.status": "agent_pipeline_status",
    "pipeline.resume": "agent_resume_pipeline",
    "checkpoint.list": "agent_list_checkpoints",
    "checkpoint.approve": "agent_approve_checkpoint",
    "stage.get": "agent_get_stage",
    "image.regenerate": "agent_regenerate_image",
    "narration.update": "agent_update_narration",
    "tts.synthesize": "agent_tts_synthesize",
    "video.render": "agent_video_render",
    "artifacts.list": "agent_list_artifacts",
    "artifact.get": "agent_get_artifact",
    "digital_human.config.get": "agent_get_digital_human_config",
    "digital_human.config.update": "agent_update_digital_human_config",
    "digital_human.health": "agent_digital_human_health",
    "digital_human.generate": "agent_digital_human_generate_full",
    "generation.status": "agent_generation_status",
    "generation.stop": "agent_generation_stop",
    "article.settings.get": "agent_get_article_settings",
    "article.settings.update": "agent_update_article_settings",
    "article.result.get": "agent_get_article_result",
    "article.result.update": "agent_update_article_result",
    "storyboard.templates.list": "agent_list_storyboard_templates",
    "storyboard.templates.save": "agent_save_storyboard_template",
    "storyboard.templates.delete": "agent_delete_storyboard_template",
    "storyboard.prompt_templates.list": "agent_list_step2_prompt_templates",
    "storyboard.prompt_templates.get": "agent_get_step2_prompt_template",
    "storyboard.prompt_templates.save": "agent_save_step2_prompt_template",
    "storyboard.prompt_templates.delete": "agent_delete_step2_prompt_template",
    "storyboard.rules.get": "agent_get_step2_rules",
    "storyboard.rules.update": "agent_update_step2_rules",
    "storyboard.prompts.get": "agent_get_step2_prompts",
    "storyboard.prompts.update": "agent_update_step2_prompts",
    "storyboard.script.execute": "agent_execute_step2_script_plan",
    "storyboard.script.get": "agent_get_step2_script_plan",
    "storyboard.script.update": "agent_update_step2_script_plan",
    "storyboard.visual.execute": "agent_execute_step2_visual_plan",
    "storyboard.visual.get": "agent_get_step2_visual_plan",
    "storyboard.visual.update": "agent_update_step2_visual_plan",
    "storyboard.compose": "agent_compose_step2_visual_contract",
    "storyboard.preview": "agent_get_step2_prompt_preview",
    "storyboard.contract.get": "agent_get_step2_result",
    "storyboard.contract.update": "agent_update_step2_result",
    "storyboard.contract.repair": "agent_repair_step2_result",
    "storyboard.skeleton.submit": "agent_submit_step2_manual_skeleton",
    "storyboard.execute": "agent_execute_step2",
    # ---- 分域扩展（dotted path：module:function） ----
    "narration.init": "agent_api.domain_routes.audio:agent_narration_init",
    "narration.result.get": "agent_api.domain_routes.audio:agent_get_narration_result",
    "narration.result.update": "agent_api.domain_routes.audio:agent_update_narration_result",
    "narration.repair": "agent_api.domain_routes.audio:agent_repair_narration_result",
    "narration.annotation_settings.get": "agent_api.domain_routes.audio:agent_get_narration_annotation_settings",
    "narration.annotation_settings.update": "agent_api.domain_routes.audio:agent_update_narration_annotation_settings",
    "narration.annotate": "agent_api.domain_routes.audio:agent_annotate_narration",
    "tts.sync_synthesize": "agent_api.domain_routes.audio:agent_tts_sync_synthesize",
    "tts.audio_status.get": "agent_api.domain_routes.audio:agent_get_tts_audio_status",
    "tts.audio.confirm": "agent_api.domain_routes.audio:agent_confirm_tts_audio",
    "media.background.get": "agent_api.domain_routes.audio:agent_get_media_background",
    "media.background.update": "agent_api.domain_routes.audio:agent_update_media_background",
    "media.subtitles.get": "agent_api.domain_routes.audio:agent_get_media_subtitles",
    "media.subtitles.update": "agent_api.domain_routes.audio:agent_update_media_subtitles",
    "video.list": "agent_api.domain_routes.outputs:agent_list_project_videos",
    "video.status.get": "agent_api.domain_routes.outputs:agent_get_final_video_status",
    "video.speed": "agent_api.domain_routes.outputs:agent_create_speed_adjusted_video",
    "video.delete": "agent_api.domain_routes.outputs:agent_delete_project_video",
    "pptx.readiness": "agent_api.domain_routes.outputs:agent_pptx_readiness",
    "pptx.export.create": "agent_api.domain_routes.outputs:agent_create_pptx_export",
    "pptx.exports.list": "agent_api.domain_routes.outputs:agent_list_pptx_exports",
    "pptx.exports.delete": "agent_api.domain_routes.outputs:agent_delete_pptx_export",
    "pptx.jobs.list": "agent_api.domain_routes.outputs:agent_list_pptx_jobs",
    "pptx.jobs.get": "agent_api.domain_routes.outputs:agent_get_pptx_job",
    "pptx.jobs.retry": "agent_api.domain_routes.outputs:agent_retry_pptx_job",
    "subtitles.readiness": "agent_api.domain_routes.outputs:agent_subtitle_export_readiness",
    "image.prompt_settings.get": "agent_api.domain_routes.images_ext:agent_get_image_prompt_settings",
    "image.prompt_settings.update": "agent_api.domain_routes.images_ext:agent_update_image_prompt_settings",
    "image.prompts.get": "agent_api.domain_routes.images_ext:agent_get_image_prompts",
    "image.generate": "agent_api.domain_routes.images_ext:agent_generate_image",
    "image.change_preview.get": "agent_api.domain_routes.images_ext:agent_get_image_change_preview",
    "image.recovery.list": "agent_api.domain_routes.images_ext:agent_list_image_recovery",
    "image.geometry.reuse": "agent_api.domain_routes.images_ext:agent_reuse_image_geometry",
    "image.candidate.apply": "agent_api.domain_routes.images_ext:agent_apply_image_candidate",
    "image.delete_all": "agent_api.domain_routes.images_ext:agent_delete_all_images",
    "image.delete": "agent_api.domain_routes.images_ext:agent_delete_image",
    "image.list": "agent_api.domain_routes.images_ext:agent_list_images",
    "image.order.update": "agent_api.domain_routes.images_ext:agent_update_image_order",
    "image.confirm": "agent_api.domain_routes.images_ext:agent_confirm_images",
    "style.profile_templates.list": "agent_api.domain_routes.style:agent_get_profile_templates",
    "style.profile.get": "agent_api.domain_routes.style:agent_get_project_profile",
    "style.profile.update": "agent_api.domain_routes.style:agent_save_project_profile",
    "style.generate": "agent_api.domain_routes.style:agent_generate_project_style",
    "style.reverse_settings.get": "agent_api.domain_routes.style:agent_get_reverse_settings",
    "style.reverse_settings.update": "agent_api.domain_routes.style:agent_update_reverse_settings",
    "style.get": "agent_api.domain_routes.style:agent_get_style",
    "style.update": "agent_api.domain_routes.style:agent_update_style",
    "style.reference_settings.get": "agent_api.domain_routes.style:agent_get_reference_settings",
    "style.reference_settings.update": "agent_api.domain_routes.style:agent_update_reference_settings",
    "style.references.list": "agent_api.domain_routes.style:agent_list_references",
    "style.references.generate": "agent_api.domain_routes.style:agent_generate_references",
    "style.references.delete": "agent_api.domain_routes.style:agent_delete_reference",
    "style.references.delete_all": "agent_api.domain_routes.style:agent_delete_all_references",
    "style.references_legacy.list": "agent_api.domain_routes.style:agent_list_references_legacy",
    "style.references_legacy.generate": "agent_api.domain_routes.style:agent_generate_references_legacy",
    "style.references_legacy.delete": "agent_api.domain_routes.style:agent_delete_reference_legacy",
    "style.references_legacy.delete_all": "agent_api.domain_routes.style:agent_delete_all_references_legacy",
    "style.templates.list": "agent_api.domain_routes.style:agent_list_style_templates",
    "style.templates.get": "agent_api.domain_routes.style:agent_get_style_template",
    "style.templates.create": "agent_api.domain_routes.style:agent_create_style_template",
    "style.templates.delete": "agent_api.domain_routes.style:agent_delete_style_template",
    "style.project_template.save": "agent_api.domain_routes.style:agent_save_project_style_template",
    "style.project_template.apply": "agent_api.domain_routes.style:agent_apply_project_style_template",
    "global_style.get": "agent_api.domain_routes.style:agent_get_global_style",
    "global_style.update": "agent_api.domain_routes.style:agent_update_global_style",
    "global_style.validate": "agent_api.domain_routes.style:agent_validate_global_style",
    "global_style.templates.list": "agent_api.domain_routes.style:agent_list_global_templates",
    "global_style.templates.get": "agent_api.domain_routes.style:agent_get_global_template",
    "global_style.templates.save": "agent_api.domain_routes.style:agent_save_global_template",
    "global_style.templates.delete": "agent_api.domain_routes.style:agent_delete_global_template",
    "global_style.template_references.apply": "agent_api.domain_routes.style:agent_apply_global_template_references",
    "ip.list": "agent_api.domain_routes.style:agent_list_ip_characters",
    "ip.config.update": "agent_api.domain_routes.style:agent_update_ip_config",
    "ip.delete": "agent_api.domain_routes.style:agent_delete_ip_character",
    "mask.settings.get": "agent_api.domain_routes.mask:agent_get_ai_mask_settings",
    "mask.settings.update": "agent_api.domain_routes.mask:agent_update_ai_mask_settings",
    "mask.annotate": "agent_api.domain_routes.mask:agent_annotate_ai_mask",
    "mask.semantic_blocks": "agent_api.domain_routes.mask:agent_mask_semantic_blocks",
    "mask.result.get": "agent_api.domain_routes.mask:agent_get_mask_result",
    "mask.result.repair": "agent_api.domain_routes.mask:agent_repair_mask_result",
    "mask.draft.update": "agent_api.domain_routes.mask:agent_update_mask_draft",
    "mask.result.update": "agent_api.domain_routes.mask:agent_update_mask_result",
    "mask.preview.build": "agent_api.domain_routes.mask:agent_build_mask_preview",
    "annotation.summary.get": "agent_api.domain_routes.annotations:agent_get_annotation_summary",
    "annotation.settings.update": "agent_api.domain_routes.annotations:agent_update_annotation_settings",
    "annotation.slide.get": "agent_api.domain_routes.annotations:agent_get_annotation_slide",
    "annotation.slide.patch": "agent_api.domain_routes.annotations:agent_patch_annotation_slide",
    "annotation.text_layout.get": "agent_api.domain_routes.annotations:agent_get_annotation_text_layout",
    "annotation.text_layout.patch": "agent_api.domain_routes.annotations:agent_patch_annotation_text_layout",
    "annotation.prompts.get": "agent_api.domain_routes.annotations:agent_get_annotation_prompts",
    "annotation.prompts.update": "agent_api.domain_routes.annotations:agent_put_annotation_prompts",
    "annotation.slide.prepare": "agent_api.domain_routes.annotations:agent_prepare_annotation_slide",
    "annotation.slide.confirm": "agent_api.domain_routes.annotations:agent_confirm_annotation_slide",
    "annotation.jobs.submit": "agent_api.domain_routes.annotations:agent_submit_annotation_job",
    "annotation.jobs.get": "agent_api.domain_routes.annotations:agent_get_annotation_job",
    "annotation.jobs.cancel": "agent_api.domain_routes.annotations:agent_cancel_annotation_job",
    "annotation.preview.export": "agent_api.domain_routes.annotations:agent_export_annotation_preview",
    "digital_human.slide.generate": "agent_api.domain_routes.digital_human_ext:agent_dh_generate_slide",
    "digital_human.jobs.get": "agent_api.domain_routes.digital_human_ext:agent_dh_get_job",
    "digital_human.slide.compose": "agent_api.domain_routes.digital_human_ext:agent_dh_compose_slide",
    "digital_human.audio.export": "agent_api.domain_routes.digital_human_ext:agent_dh_export_audio",
    "digital_human.avatars.list": "agent_api.domain_routes.digital_human_ext:agent_dh_list_avatars",
    "digital_human.workflow.get": "agent_api.domain_routes.digital_human_ext:agent_dh_get_workflow",
    "course.tree.get": "agent_api.domain_routes.workspace:agent_get_course_tree",
    "course.reorder": "agent_api.domain_routes.workspace:agent_reorder_courses",
    "chapter.reorder": "agent_api.domain_routes.workspace:agent_reorder_chapters",
    "course.create": "agent_api.domain_routes.workspace:agent_create_course",
    "course.list": "agent_api.domain_routes.workspace:agent_list_courses",
    "course.get": "agent_api.domain_routes.workspace:agent_get_course",
    "course.update": "agent_api.domain_routes.workspace:agent_update_course",
    "course.delete": "agent_api.domain_routes.workspace:agent_delete_course",
    "chapter.create": "agent_api.domain_routes.workspace:agent_create_chapter",
    "chapter.update": "agent_api.domain_routes.workspace:agent_update_chapter",
    "chapter.delete": "agent_api.domain_routes.workspace:agent_delete_chapter",
    "chapter.move": "agent_api.domain_routes.workspace:agent_move_chapter",
    "project.move": "agent_api.domain_routes.workspace:agent_move_project",
    "project.reorder": "agent_api.domain_routes.workspace:agent_reorder_projects",
    "config.list": "agent_api.domain_routes.workspace:agent_list_configs",
    "config.default_payload.get": "agent_api.domain_routes.workspace:agent_default_config_payload",
    "config.create": "agent_api.domain_routes.workspace:agent_create_config",
    "config.get": "agent_api.domain_routes.workspace:agent_get_config",
    "config.update": "agent_api.domain_routes.workspace:agent_update_config",
    "config.version.get": "agent_api.domain_routes.workspace:agent_get_config_version",
    "config.copy": "agent_api.domain_routes.workspace:agent_copy_config",
    "config.version.create": "agent_api.domain_routes.workspace:agent_create_config_version",
    "config.archive": "agent_api.domain_routes.workspace:agent_archive_config",
    "config.delete": "agent_api.domain_routes.workspace:agent_delete_config",
    "config.resolve": "agent_api.domain_routes.workspace:agent_resolve_config",
    "pipeline.pause": "agent_api.domain_routes.workspace:agent_pause_pipeline",
    "pipeline.statuses.list": "agent_api.domain_routes.workspace:agent_pipeline_statuses",
    "media.background_config.get": "agent_api.domain_routes.workspace:agent_get_background",
    "media.background_config.update": "agent_api.domain_routes.workspace:agent_update_background",
    "project.change_preview": "agent_api.domain_routes.workspace:agent_change_preview",
    "project.impacts.get": "agent_api.domain_routes.project:agent_get_project_impacts",
    "project.impacts.reuse_preview": "agent_api.domain_routes.project:agent_preview_storyboard_reuse",
    "project.impacts.reuse_confirm": "agent_api.domain_routes.project:agent_confirm_storyboard_reuse",
    "project.impacts.decision.update": "agent_api.domain_routes.project:agent_update_impact_decision",
    "project.impacts.image_reuse_confirm": "agent_api.domain_routes.project:agent_confirm_storyboard_image_reuse",
    "project.ai_mode.get": "agent_api.domain_routes.project:agent_get_project_ai_mode",
    "project.ai_mode.update": "agent_api.domain_routes.project:agent_update_project_ai_mode",
    "settings.get": "agent_api.domain_routes.system_ext:agent_get_settings",
    "settings.update": "agent_api.domain_routes.system_ext:agent_update_settings",
    "settings.config.export": "agent_api.domain_routes.system_ext:agent_export_config",
    "settings.config.export.secrets": "agent_api.domain_routes.system_ext:agent_export_config_secrets",
    "settings.config.import": "agent_api.domain_routes.system_ext:agent_import_config",
    "config.import": "agent_api.domain_routes.workspace:agent_import_config",
    "settings.llm.test": "agent_api.domain_routes.system_ext:agent_test_llm_connection",
    "settings.image.test": "agent_api.domain_routes.system_ext:agent_test_image_connection",
    "settings.tts.test": "agent_api.domain_routes.system_ext:agent_test_tts_connection",
    "settings.comfyui_workflow.get": "agent_api.domain_routes.system_ext:agent_get_comfyui_tts_workflow",
    "credentials.list": "agent_api.domain_routes.system_ext:agent_list_credentials",
    "credentials.create": "agent_api.domain_routes.system_ext:agent_create_credential",
    "credentials.update": "agent_api.domain_routes.system_ext:agent_update_credential",
    "connections.list": "agent_api.domain_routes.system_ext:agent_list_model_connections",
    "connections.create": "agent_api.domain_routes.system_ext:agent_create_model_connection",
    "connections.get": "agent_api.domain_routes.system_ext:agent_get_model_connection",
    "connections.update": "agent_api.domain_routes.system_ext:agent_update_model_connection",
    "connections.copy": "agent_api.domain_routes.system_ext:agent_copy_model_connection",
    "connections.test": "agent_api.domain_routes.system_ext:agent_test_model_connection",
    "connections.state.update": "agent_api.domain_routes.system_ext:agent_update_model_connection_state",
    "connections.delete": "agent_api.domain_routes.system_ext:agent_delete_model_connection",
    "diagnostics.runtime": "agent_api.domain_routes.system_ext:agent_runtime_diagnostics",
    "diagnostics.governor": "agent_api.domain_routes.system_ext:agent_governor_snapshot",
    "diagnostics.error_log": "agent_api.domain_routes.system_ext:agent_get_error_log",
    "accounts.list": "agent_api.domain_routes.accounts:agent_list_accounts",
    "accounts.current": "agent_api.domain_routes.accounts:agent_current_account",
    "accounts.create": "agent_api.domain_routes.accounts:agent_create_account",
    "accounts.provision": "agent_api.domain_routes.accounts:agent_provision_account",
    "accounts.rename": "agent_api.domain_routes.accounts:agent_rename_account",
    "accounts.delete": "agent_api.domain_routes.accounts:agent_delete_account",
    "accounts.default_config.update": "agent_api.domain_routes.accounts:agent_set_default_config",
    "accounts.agent_token.create": "agent_api.domain_routes.accounts:agent_create_agent_token",
}


def _resolve_handler(spec: str):
    """Resolve a static handler registration; dotted specs never come from input."""
    if ":" in spec:
        import importlib

        module_name, attribute = spec.split(":", 1)
        return getattr(importlib.import_module(module_name), attribute)
    from agent_api import routes

    return getattr(routes, spec)


def invoke_capability(capability_id: str, revision: str, arguments: dict[str, Any], request, db):
    try:
        cap = get_capability(capability_id)
    except ValueError as exc:
        raise AgentAPIError("CAPABILITY_NOT_FOUND", "Unknown capability", 404) from exc
    if cap.status.value == "removed":
        raise AgentAPIError("CAPABILITY_NOT_FOUND", "Unknown capability", 404)
    detail = describe_capability(cap)
    if not detail["invocable"] or capability_id not in HANDLERS:
        raise AgentAPIError("UNSUPPORTED_TRANSPORT", "Use the declared resource transport", 422,
                            details={"method": cap.agent_api_method, "path": cap.agent_api_path})
    scopes = getattr(request.state, "agent_scopes", set())
    if getattr(request.state, "agent_authenticated", False) and scopes and required_scope(cap) not in scopes:
        raise AgentAPIError("FORBIDDEN", f"Missing scope: {required_scope(cap)}", 403)
    if revision != detail["contract_revision"]:
        raise AgentAPIError("CONTRACT_CHANGED", "Refresh the capability before calling it", 409,
                            details={"capability_id": cap.id, "contract_revision": detail["contract_revision"],
                                     "executed": False, "repair_actions": [{"action": "describe", "capability_id": cap.id}]})
    try:
        parsed = input_model(cap).model_validate(arguments)
    except ValidationError as exc:
        raise AgentAPIError("VALIDATION_ERROR", "Invalid capability arguments", 422,
                            details={"errors": exc.errors(include_input=False, include_context=False)}) from exc
    values = parsed.model_dump(mode="python")
    names = path_names(cap)
    if any(not values[name] or "/" in values[name] or "\\" in values[name] for name in names):
        raise AgentAPIError("VALIDATION_ERROR", "Invalid resource identifier", 422)

    endpoint = _resolve_handler(HANDLERS[capability_id])
    kwargs: dict[str, Any] = {}
    for name, parameter in inspect.signature(endpoint).parameters.items():
        if name == "db":
            kwargs[name] = db
        elif name == "request":
            kwargs[name] = request
        elif name == "payload":
            # Preserve fields_set (pipeline start/resume distinguishes omitted defaults).
            kwargs[name] = cap.request_model.model_validate({
                key: value for key, value in arguments.items() if key in cap.request_model.model_fields
            })
        elif name == "status_filter":
            kwargs[name] = values.get("status_filter")
        elif name in values:
            kwargs[name] = values[name]
        elif parameter.default is inspect.Parameter.empty:
            raise RuntimeError(f"Missing adapter binding: {cap.id}.{name}")
    result = endpoint(**kwargs)
    if isinstance(result, JSONResponse):
        if result.status_code >= 400:
            return result
        data = json.loads(result.body)
    else:
        data = jsonable_encoder(result)
    if cap.response_model is not BaseModel:
        try:
            cap.response_model.model_validate(data)
        except ValidationError as exc:
            raise AgentAPIError("OUTPUT_CONTRACT_ERROR", "Service result does not match its contract", 500,
                                details={"execution_may_have_completed": True,
                                         "repair_actions": [{"action": "inspect_operation_before_retry"}]}) from exc
    return result if isinstance(result, JSONResponse) else data
