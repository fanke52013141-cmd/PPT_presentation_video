"""Agent HTTP composition and explicit dispatch exports; domain modules own adapters."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/agent/v1", tags=["Agent API v1"])

from agent_api.domain_routes.system import (  # noqa: F401
    agent_generation_status,
    agent_generation_stop,
    get_agent_meta,
    get_agent_identity,
    get_diagnostics,
    agent_openapi_json,
    agent_swagger_ui,
)
from agent_api.domain_routes.system import router as system_router
router.include_router(system_router)

from agent_api.domain_routes.project import (  # noqa: F401
    agent_create_project,
    agent_list_projects,
    agent_get_project,
    agent_project_state,
    agent_update_project,
    agent_delete_project,
)
from agent_api.domain_routes.project import router as project_router
router.include_router(project_router)

from agent_api.domain_routes.source import (  # noqa: F401
    agent_set_source,
)
from agent_api.domain_routes.source import router as source_router
router.include_router(source_router)

from agent_api.domain_routes.pipeline import (  # noqa: F401
    agent_start_pipeline,
    agent_pipeline_status,
    agent_pipeline_stream,
    agent_resume_pipeline,
    agent_list_checkpoints,
    agent_approve_checkpoint,
    agent_get_stage,
)
from agent_api.domain_routes.pipeline import router as pipeline_router
router.include_router(pipeline_router)

from agent_api.domain_routes.artifacts import (  # noqa: F401
    agent_get_slide_image,
    agent_get_slide_audio,
    agent_list_artifacts,
    agent_get_artifact,
    agent_download_artifact,
)
from agent_api.domain_routes.artifacts import router as artifacts_router
router.include_router(artifacts_router)

from agent_api.domain_routes.video import (  # noqa: F401
    agent_get_latest_video,
    agent_video_render,
)
from agent_api.domain_routes.video import router as video_router
router.include_router(video_router)

from agent_api.domain_routes.images import (  # noqa: F401
    agent_regenerate_image,
)
from agent_api.domain_routes.images import router as images_router
router.include_router(images_router)

from agent_api.domain_routes.narration import (  # noqa: F401
    agent_update_narration,
    agent_tts_synthesize,
)
from agent_api.domain_routes.narration import router as narration_router
router.include_router(narration_router)

from agent_api.domain_routes.digital_human import (  # noqa: F401
    agent_get_digital_human_config,
    agent_update_digital_human_config,
    agent_digital_human_health,
    agent_digital_human_generate_full,
)
from agent_api.domain_routes.digital_human import router as digital_human_router
router.include_router(digital_human_router)

from agent_api.domain_routes.article import (  # noqa: F401
    agent_get_article_settings,
    agent_update_article_settings,
    agent_get_article_result,
    agent_update_article_result,
)
from agent_api.domain_routes.article import router as article_router
router.include_router(article_router)

from agent_api.domain_routes.storyboard import (  # noqa: F401
    agent_list_storyboard_templates,
    agent_save_storyboard_template,
    agent_delete_storyboard_template,
    agent_list_step2_prompt_templates,
    agent_get_step2_prompt_template,
    agent_save_step2_prompt_template,
    agent_delete_step2_prompt_template,
    agent_get_step2_rules,
    agent_update_step2_rules,
    agent_get_step2_prompts,
    agent_update_step2_prompts,
    agent_execute_step2_script_plan,
    agent_get_step2_script_plan,
    agent_update_step2_script_plan,
    agent_execute_step2_visual_plan,
    agent_get_step2_visual_plan,
    agent_update_step2_visual_plan,
    agent_compose_step2_visual_contract,
    agent_get_step2_prompt_preview,
    agent_get_step2_result,
    agent_repair_step2_result,
    agent_update_step2_result,
    agent_submit_step2_manual_skeleton,
    agent_execute_step2,
)
from agent_api.domain_routes.storyboard import router as storyboard_router
router.include_router(storyboard_router)

from agent_api.discovery import router as discovery_router
router.include_router(discovery_router)
from agent_api.operation_routes import router as operation_router
from agent_api.operation_routes import agent_get_operation, agent_list_operations, agent_cancel_operation  # noqa: F401
router.include_router(operation_router)

# 新分域只组合路由；invoke 适配通过 dispatch 的显式 dotted-path 注册解析。
from agent_api.domain_routes.audio import router as audio_router
router.include_router(audio_router)
from agent_api.domain_routes.outputs import router as outputs_router
router.include_router(outputs_router)
from agent_api.domain_routes.images_ext import router as images_ext_router
router.include_router(images_ext_router)
from agent_api.domain_routes.style import router as style_router
router.include_router(style_router)
from agent_api.domain_routes.mask import router as mask_router
router.include_router(mask_router)
from agent_api.domain_routes.annotations import router as annotations_router
router.include_router(annotations_router)
from agent_api.domain_routes.digital_human_ext import router as digital_human_ext_router
router.include_router(digital_human_ext_router)
from agent_api.domain_routes.workspace import router as workspace_router
router.include_router(workspace_router)
from agent_api.domain_routes.system_ext import router as system_ext_router
router.include_router(system_ext_router)
from agent_api.domain_routes.accounts import router as accounts_router
router.include_router(accounts_router)
