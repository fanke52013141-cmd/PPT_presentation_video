import os
import sys
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from PIL import Image
from database import get_db, init_db, Project
from config_store import get_all_settings, update_settings, get_setting
from app_security import configured_allowed_hosts, configured_allowed_origins, install_access_control
from scripts.media_tools import (
    probe_media_duration_sec,
    resolve_media_tool as shared_resolve_media_tool,
)
from pipeline_lifecycle import write_json_atomic
from ai_provider_service import (
    extract_image_bytes_from_response,
    generate_image_response,
    get_openai_client,
    is_seedream_image_model,
    open_validated_image,
    process_and_save_image,
    response_has_image_data,
)
from tts_provider_service import (
    TTS_PROVIDER_DEFAULTS,
    TtsProviderDependencies,
    configure_tts_provider_dependencies,
    configured_tts_api_key,
    configured_tts_secret_key,
    first_non_empty,
    normalize_tts_provider,
    provider_tts_command,
    provider_tts_environment,
    run_tts_command_with_retries,
    tts_provider_defaults,
)
from narration_audio_service import (
    TTS_MARKUP_RE,
    NarrationAudioDependencies,
    beat_tts_text,
    clean_tts_text,
    configure_narration_audio_dependencies,
    ensure_minimax_delivery_markup,
    normalize_minimax_tts_markup,
    persist_narration_beats,
    prepare_narration_payload,
    rewrite_audio_timeline_by_beats,
    sync_narration_beats_to_contract,
    sync_narration_sources_from_contract,
)
from visual_contract_service import (
    contract_slide_ids_from_payload,
    dedupe_narration_beats,
    narration_dedupe_key,
    normalize_visual_contract,
    normalize_visual_type,
    read_contract_slide_ids,
)
from visual_settings_service import (
    DEFAULT_SUBTITLE_STYLE,
    DEFAULT_VIDEO_BACKGROUND,
    OPEN_SOURCE_CHINESE_FONTS,
    VisualSettingsDependencies,
    configure_visual_settings_service,
    normalize_hex_color,
    normalize_subtitle_style,
    read_project_visual_settings,
    sync_project_background_color,
)
from runtime_support import (
    clean_json_markdown,
    is_timeout_exception,
    json_decode_context,
    parse_int_setting,
    parse_json_process_stdout,
    parse_range_text,
    read_json_file,
    run_subprocess_bounded,
    run_subprocess_killable,
    write_debug_text,
)
from project_runtime_service import (
    all_current_slide_images_exist,
    audio_confirmation_path,
    begin_storyboard_after_article_import,
    clear_slide_visual_derivatives,
    ensure_slide_tts_text_file,
    handle_step_navigation,
    invalidate_after_upstream_edit,
    mark_slide_image_changed,
    mark_step_in_progress,
    mark_step_retry_needed,
    nonempty_file,
    project_audio_confirmed,
    read_timeline_duration_sec,
    remove_tts_artifacts,
    reveal_lock_for,
    slide_tts_artifact_paths,
    slide_tts_artifact_status,
    sync_reveal_manifest_to_contract,
    write_project_log,
)
from repository_paths import (
    DATA_DIR,
    HANDDRAWN_STYLE_TOKENS_PATH,
    IMAGE_STYLE_TEMPLATES_DIR,
    IMAGE_STYLE_TEMPLATES_INDEX,
    REPO_ROOT,
    RUNS_DIR,
    STEP2_PROMPT_TEMPLATE_FILES,
    STEP2_PROMPT_TEMPLATES_PATH,
    STORYBOARD_TEMPLATES_PATH,
    STYLE_REFERENCE_DIR,
    STYLE_REFERENCE_FILES,
    STYLE_TOKENS_PATH,
)
from global_image_style_service import (
    ensure_active_image_style_storage,
)
from project_path_service import (
    current_slide_file_or_404,
    project_run_dir_or_500,
    read_current_slide_ids_or_404,
)
from project_storage import slide_file as storage_slide_file
from template_utils import normalized_template_name, template_timestamp

# 初始化日志与数据库
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("PPTStudio")
init_db()

app = FastAPI(title="PPT Visualization Studio", description="本地手绘线稿风 PPT 视频生成系统")

# 解决跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=configured_allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "If-Match",
        "X-App-Token",
        "X-PPT-Studio-Request",
    ],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=configured_allowed_hosts())

install_access_control(app)


# 静态资源禁用浏览器缓存：保证前端改动刷新后立即生效（不影响 /api 与安全逻辑）
@app.middleware("http")
async def no_cache_static_assets(request, call_next):
    response = await call_next(request)
    path = request.url.path
    # 只对前端静态资源（html/css/js/图片等，非 /api）禁用缓存
    if path.startswith("/api") or not path or path == "/favicon.ico":
        return response
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

os.makedirs(RUNS_DIR, exist_ok=True)
MAX_CONFIG_IMPORT_BYTES = int(os.environ.get("PPT_STUDIO_MAX_CONFIG_IMPORT_BYTES", str(25 * 1024 * 1024)))
os.makedirs(DATA_DIR, exist_ok=True)
AI_KNOWLEDGE_STEP2_SCRIPT_EXTENSION = """
<AIKnowledgeAudienceOverride>
当前模板专用于中文 AI 知识视频。目标受众是已经接触过 ChatGPT、智能助手或常见 AI 产品，但并非算法专家的职场人。他们更关心机制为什么成立、能力边界在哪里、会怎样影响实际工作，以及应该如何判断和行动。

规划时优先采用“真实困惑或常见误解 → 关键机制 → 例子与边界 → 工作影响 → 判断或行动”的认知旅程，但不得机械套用。不要从“什么是 AI”开始，不堆叠术语，不把类比伪装成技术事实。文章和 generation_requirement 仍然是具体内容与事实边界。
</AIKnowledgeAudienceOverride>
""".strip()
LEGACY_STEP2_PROMPT_HASHES = {
    "script_system": {
        "eb40ad64735f5bf5f2c70477c057f632ec8ad8a238919c08aa2be3679a698042",
        "772bf5f95f6da19a387ff1df76960c5e5a7deebda170bc9f06d66031f0a81609",
    },
    "script_output_example": {"a87e75ff998d2b8a415108ba95b73d8b15a12100171439949d3eaa7d2201d603"},
    "visual_system": {"2cd1d2c659883ccb641743d2db0a3b255036c4ebc67e34075ffb918e102647f3"},
    "visual_output_example": {"d61dc2dfdd60cddd4be3bc13cfe4848ee5b119964ad726ec8ff214840cd7e9fa"},
}
LEGACY_INTERVIEW_SCRIPT_PROMPT_HASH = "7e6f9fbd452f9c94bc02b3c5226edcde21a4bb69d87d5ede8089eb8b28f7bef9"
REVEAL_PIPELINE_VERSION = "exact_rle_mask_with_manual_corrections_v5"


ensure_active_image_style_storage()


STEP2_LLM_TIMEOUT_SEC = 240.0
STEP5_REVEAL_BUILD_TIMEOUT_SEC = float(os.environ.get("PPT_STUDIO_REVEAL_BUILD_TIMEOUT_SEC", "300"))
STEP7_BIND_TIMEOUT_SEC = 90
STEP8_RENDER_TIMEOUT_SEC = 3600
STEP8_BUILD_PROPS_TIMEOUT_SEC = 180
STEP8_NPM_INSTALL_TIMEOUT_SEC = 600
STEP8_COLOR_PROCESS_TIMEOUT_SEC = 300
REVEAL_VISUAL_LEAD_SEC = 0.45

from json_llm_service import (
    parse_json_or_repair_with_llm,
)


configure_narration_audio_dependencies(
    NarrationAudioDependencies(
        dedupe_narration_beats=dedupe_narration_beats,
        probe_media_duration_sec=probe_media_duration_sec,
        read_contract_slide_ids=read_contract_slide_ids,
        read_json_file=read_json_file,
        write_json_atomic=write_json_atomic,
        repo_root=Path(REPO_ROOT),
    )
)

# ==================== 项目管理接口 ====================

# Project lifecycle routes are source-owned by project_service.py and project_routes.py.

try:
    from config_portability_service import (
        ConfigPortabilityDependencies,
        configure_config_portability_dependencies,
    )
    from global_image_style_service import (
        read_image_style_template_index,
    )
    from settings_routes import (
        configure_settings_routes,
        router as settings_router,
    )
    from settings_service import (
        SettingsDependencies,
        configure_settings_dependencies,
    )

    configure_tts_provider_dependencies(
        TtsProviderDependencies(
            get_setting=get_setting,
            write_project_log=write_project_log,
        )
    )
    configure_settings_dependencies(
        SettingsDependencies(
            get_all_settings=get_all_settings,
            update_settings=update_settings,
            get_setting=get_setting,
            get_openai_client=get_openai_client,
            generate_image_response=generate_image_response,
            response_has_image_data=response_has_image_data,
            normalize_tts_provider=normalize_tts_provider,
            tts_provider_defaults=tts_provider_defaults,
            configured_tts_api_key=configured_tts_api_key,
            configured_tts_secret_key=configured_tts_secret_key,
            first_non_empty=first_non_empty,
            provider_tts_command=provider_tts_command,
            provider_tts_environment=provider_tts_environment,
            tts_provider_defaults_map=TTS_PROVIDER_DEFAULTS,
        )
    )
    configure_config_portability_dependencies(
        ConfigPortabilityDependencies(
            get_all_settings=get_all_settings,
            update_settings=update_settings,
            open_validated_image=open_validated_image,
            read_json_file=read_json_file,
            write_json_atomic=write_json_atomic,
            read_image_style_template_index=(
                read_image_style_template_index
            ),
            ensure_active_image_style_storage=(
                ensure_active_image_style_storage
            ),
            template_timestamp=template_timestamp,
            storyboard_templates_path=STORYBOARD_TEMPLATES_PATH,
            step2_prompt_templates_path=(
                STEP2_PROMPT_TEMPLATES_PATH
            ),
            style_tokens_path=STYLE_TOKENS_PATH,
            style_reference_dir=STYLE_REFERENCE_DIR,
            style_reference_files=STYLE_REFERENCE_FILES,
            image_style_templates_dir=IMAGE_STYLE_TEMPLATES_DIR,
            image_style_templates_index=(
                IMAGE_STYLE_TEMPLATES_INDEX
            ),
        )
    )
    configure_settings_routes(
        max_config_import_bytes=MAX_CONFIG_IMPORT_BYTES,
    )
    app.include_router(settings_router)
except Exception as exc:
    logger.exception(
        "Explicit settings route registration failed: %s",
        exc,
    )
    raise

# ==================== 步骤 1: 导入文章 ====================

# Step 1 article routes are source-owned by article_service.py and article_routes.py.
from article_service import read_project_article_source

try:
    from article_routes import router as article_router
    from article_service import (
        ArticleDependencies,
        configure_article_dependencies,
    )

    configure_article_dependencies(
        ArticleDependencies(
            get_setting=get_setting,
            update_settings=update_settings,
            get_openai_client=get_openai_client,
            parse_int_setting=parse_int_setting,
            is_timeout_exception=is_timeout_exception,
            write_project_log=write_project_log,
            begin_storyboard_after_article_import=(
                begin_storyboard_after_article_import
            ),
            invalidate_after_upstream_edit=(
                invalidate_after_upstream_edit
            ),
            llm_timeout_sec=STEP2_LLM_TIMEOUT_SEC,
        )
    )
    app.include_router(article_router)
except Exception as exc:
    logger.exception(
        "Explicit article route registration failed: %s",
        exc,
    )
    raise

# ==================== 步骤 2: 智能分镜规划 ====================

# Step 2 storyboard routes are source-owned by storyboard_routes.py.
from storyboard_service import (
    build_step2_script_user_prompt,
    build_step2_visual_user_prompt,
    build_storyboard_request,
    built_in_step2_prompt_templates,
    compose_step2_system_prompt,
    compose_step2_visual_contract,
    compose_visual_contract_from_plans,
    default_step2_prompts,
    execute_step2,
    execute_step2_script_plan,
    execute_step2_visual_plan,
    get_step2_result,
    migrate_legacy_step2_prompt,
    normalize_slide_visual_plan,
    run_step2_json_llm,
    step2_llm_vendor_options,
    step2_prompt_compatibility,
    step2_script_prompt_uses_legacy_contract,
    step2_visual_prompt_uses_legacy_contract,
    storyboard_validation_gate_enabled,
    update_step2_result,
    validate_visual_contract_file,
)

# Visual settings routes are source-owned by visual_settings_service.py.

# Global image-style compatibility APIs are source-owned by global_image_style_service.py.
from global_image_style_service import (
    build_image_style_prompt,
    read_image_style_template_index,
    read_style_tokens_data,
)

# Step 3 image workflow is source-owned by image_workflow_service.py.
from image_workflow_service import (
    compact_slide_element_lines,
    compose_step3_single_slide_prompt,
    confirm_images,
    generate_slide_image,
    get_slide_prompts,
    read_step3_image_system_content,
)

# ==================== 步骤 6: 演讲稿编辑 ====================

# Step 5 Mask editing is source-owned by dedicated services.
from mask_manifest_service import (
    build_current_reveal_assets,
    get_step5_result,
    refresh_reveal_semantic_blocks,
    repair_step5_result,
    update_step5_result,
)

try:
    from mask_editor_routes import router as mask_editor_router
    from mask_manifest_service import (
        MaskManifestDependencies,
        configure_mask_manifest_dependencies,
    )
    from mask_preview_service import (
        MaskPreviewDependencies,
        configure_mask_preview_dependencies,
    )
    from scripts.build_reveal_scene import compose_preview_image
    from storyboard_background_render import apply_storyboard_background

    configure_mask_manifest_dependencies(
        MaskManifestDependencies(
            normalize_visual_type=normalize_visual_type,
            reveal_lock_for=reveal_lock_for,
            read_contract_slide_ids=read_contract_slide_ids,
            sync_reveal_manifest_to_contract=(
                sync_reveal_manifest_to_contract
            ),
            storage_slide_file=storage_slide_file,
            write_json_atomic=write_json_atomic,
            handle_step_navigation=handle_step_navigation,
            sync_project_background_color=sync_project_background_color,
            write_project_log=write_project_log,
            apply_storyboard_background=apply_storyboard_background,
            repo_root=Path(REPO_ROOT),
            python_executable=sys.executable,
            build_timeout_sec=STEP5_REVEAL_BUILD_TIMEOUT_SEC,
        )
    )
    configure_mask_preview_dependencies(
        MaskPreviewDependencies(
            reveal_lock_for=reveal_lock_for,
            sync_project_background_color=sync_project_background_color,
            current_slide_file_or_404=current_slide_file_or_404,
            project_run_dir_or_500=project_run_dir_or_500,
            read_json_file=read_json_file,
            apply_storyboard_background=apply_storyboard_background,
            compose_preview_image=compose_preview_image,
            repo_root=Path(REPO_ROOT),
            python_executable=sys.executable,
            build_timeout_sec=STEP5_REVEAL_BUILD_TIMEOUT_SEC,
        )
    )
    app.include_router(mask_editor_router)
except Exception as exc:
    logger.exception(
        "Explicit Mask editor route registration failed: %s",
        exc,
    )
    raise

# Narration and TTS routes are source-owned by dedicated services.
try:
    from image_workflow_routes import router as image_workflow_router
    from image_workflow_service import (
        ImageWorkflowDependencies,
        configure_image_workflow_dependencies,
    )

    configure_image_workflow_dependencies(
        ImageWorkflowDependencies(
            all_current_slide_images_exist=(
                all_current_slide_images_exist
            ),
            current_slide_file_or_404=current_slide_file_or_404,
            extract_image_bytes_from_response=(
                extract_image_bytes_from_response
            ),
            generate_image_response=generate_image_response,
            get_openai_client=get_openai_client,
            handle_step_navigation=handle_step_navigation,
            mark_slide_image_changed=mark_slide_image_changed,
            process_and_save_image=process_and_save_image,
            read_current_slide_ids_or_404=(
                read_current_slide_ids_or_404
            ),
            read_json_file=read_json_file,
            refresh_reveal_semantic_blocks=(
                refresh_reveal_semantic_blocks
            ),
            reveal_lock_for=reveal_lock_for,
            sync_reveal_manifest_to_contract=(
                sync_reveal_manifest_to_contract
            ),
            write_project_log=write_project_log,
        )
    )
    app.include_router(image_workflow_router)
except Exception as exc:
    logger.exception(
        "Explicit image workflow route registration failed: %s",
        exc,
    )
    raise

try:
    from global_image_style_routes import (
        router as global_image_style_router,
    )
    from global_image_style_service import (
        GlobalImageStyleDependencies,
        configure_global_image_style_dependencies,
    )

    configure_global_image_style_dependencies(
        GlobalImageStyleDependencies(
            is_seedream_image_model=is_seedream_image_model,
            normalized_template_name=normalized_template_name,
            open_validated_image=open_validated_image,
            read_json_file=read_json_file,
            template_timestamp=template_timestamp,
        )
    )
    app.include_router(global_image_style_router)
except Exception as exc:
    logger.exception(
        "Explicit global image-style route registration failed: %s",
        exc,
    )
    raise

try:
    from project_routes import router as project_router
    from project_service import (
        ProjectDependencies,
        configure_project_service,
    )

    configure_project_service(
        ProjectDependencies(
            runs_root=Path(RUNS_DIR),
            project_audio_confirmed=project_audio_confirmed,
        )
    )
    app.include_router(project_router)
except Exception as exc:
    logger.exception(
        "Explicit project route registration failed: %s",
        exc,
    )
    raise

try:
    from visual_settings_routes import (
        router as visual_settings_router,
    )

    configure_visual_settings_service(
        VisualSettingsDependencies(
            read_contract_slide_ids=read_contract_slide_ids,
            reveal_lock_for=reveal_lock_for,
            write_json_atomic=write_json_atomic,
            style_reference_dir=Path(STYLE_REFERENCE_DIR),
            style_reference_template=(
                STYLE_REFERENCE_FILES["template"]
            ),
        )
    )
    app.include_router(visual_settings_router)
except Exception as exc:
    logger.exception(
        "Explicit visual settings route registration failed: %s",
        exc,
    )
    raise

from narration_service import (
    annotate_step6_narration,
    get_step6_result,
    init_step6_narration,
    repair_step6_result,
    update_step6_result,
)
from tts_service import (
    confirm_tts_audio,
    synthesize_tts_resumable,
)

try:
    from narration_routes import router as narration_router
    from narration_service import (
        NarrationDependencies,
        configure_narration_dependencies,
    )
    from tts_routes import router as tts_router
    from tts_service import (
        TtsDependencies,
        configure_tts_dependencies,
    )

    configure_narration_dependencies(
        NarrationDependencies(
            beat_tts_text=beat_tts_text,
            clean_json_markdown=clean_json_markdown,
            clean_tts_text=clean_tts_text,
            ensure_minimax_delivery_markup=(
                ensure_minimax_delivery_markup
            ),
            get_openai_client=get_openai_client,
            handle_step_navigation=handle_step_navigation,
            normalize_minimax_tts_markup=(
                normalize_minimax_tts_markup
            ),
            parse_int_setting=parse_int_setting,
            parse_json_or_repair_with_llm=(
                parse_json_or_repair_with_llm
            ),
            persist_narration_beats=persist_narration_beats,
            prepare_narration_payload=prepare_narration_payload,
            read_contract_slide_ids=read_contract_slide_ids,
            read_json_file=read_json_file,
            sync_narration_beats_to_contract=(
                sync_narration_beats_to_contract
            ),
            tts_markup_re=TTS_MARKUP_RE,
        )
    )
    configure_tts_dependencies(
        TtsDependencies(
            audio_confirmation_path=audio_confirmation_path,
            configured_tts_api_key=configured_tts_api_key,
            configured_tts_secret_key=configured_tts_secret_key,
            current_slide_file_or_404=current_slide_file_or_404,
            ensure_slide_tts_text_file=ensure_slide_tts_text_file,
            first_non_empty=first_non_empty,
            get_setting=get_setting,
            handle_step_navigation=handle_step_navigation,
            mark_step_retry_needed=mark_step_retry_needed,
            normalize_tts_provider=normalize_tts_provider,
            project_audio_confirmed=project_audio_confirmed,
            provider_tts_command=provider_tts_command,
            provider_tts_environment=provider_tts_environment,
            read_current_slide_ids_or_404=(
                read_current_slide_ids_or_404
            ),
            remove_tts_artifacts=remove_tts_artifacts,
            rewrite_audio_timeline_by_beats=(
                rewrite_audio_timeline_by_beats
            ),
            # TTS 子进程可能生成孙进程，超时必须杀整棵进程树，避免残留与管道死锁。
            run_subprocess_bounded=run_subprocess_killable,
            run_tts_command_with_retries=(
                run_tts_command_with_retries
            ),
            slide_tts_artifact_paths=slide_tts_artifact_paths,
            slide_tts_artifact_status=slide_tts_artifact_status,
            sync_narration_beats_to_contract=(
                sync_narration_beats_to_contract
            ),
            tts_provider_defaults=tts_provider_defaults,
            write_project_log=write_project_log,
            provider_defaults=TTS_PROVIDER_DEFAULTS,
            reveal_visual_lead_sec=REVEAL_VISUAL_LEAD_SEC,
            bind_timeout_sec=STEP7_BIND_TIMEOUT_SEC,
        )
    )
    app.include_router(narration_router)
    app.include_router(tts_router)
except Exception as exc:
    logger.exception(
        "Explicit narration/TTS route registration failed: %s",
        exc,
    )
    raise

try:
    from storyboard_service import (
        StoryboardDependencies,
        configure_storyboard_dependencies,
    )
    from storyboard_routes import router as storyboard_router

    configure_storyboard_dependencies(
        StoryboardDependencies(
            clean_json_markdown=clean_json_markdown,
            contract_slide_ids_from_payload=(
                contract_slide_ids_from_payload
            ),
            get_openai_client=get_openai_client,
            handle_step_navigation=handle_step_navigation,
            invalidate_after_upstream_edit=(
                invalidate_after_upstream_edit
            ),
            is_timeout_exception=is_timeout_exception,
            mark_step_retry_needed=mark_step_retry_needed,
            narration_dedupe_key=narration_dedupe_key,
            normalize_visual_contract=normalize_visual_contract,
            normalized_template_name=normalized_template_name,
            parse_int_setting=parse_int_setting,
            parse_json_or_repair_with_llm=(
                parse_json_or_repair_with_llm
            ),
            parse_range_text=parse_range_text,
            read_json_file=read_json_file,
            read_project_article_source=read_project_article_source,
            sync_narration_beats_to_contract=(
                sync_narration_beats_to_contract
            ),
            sync_narration_sources_from_contract=(
                sync_narration_sources_from_contract
            ),
            sync_reveal_manifest_to_contract=(
                sync_reveal_manifest_to_contract
            ),
            template_timestamp=template_timestamp,
            write_project_log=write_project_log,
            ai_knowledge_script_extension=(
                AI_KNOWLEDGE_STEP2_SCRIPT_EXTENSION
            ),
            legacy_prompt_hashes=LEGACY_STEP2_PROMPT_HASHES,
            legacy_interview_script_prompt_hash=(
                LEGACY_INTERVIEW_SCRIPT_PROMPT_HASH
            ),
        )
    )
    app.include_router(storyboard_router)
except Exception as exc:
    logger.exception(
        "Explicit storyboard route registration failed: %s",
        exc,
    )
    raise

# Step 8 video rendering is source-owned by video_render_service.py and video_routes.py.

# ==================== 前端托管 ====================

static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "static"))
os.makedirs(static_dir, exist_ok=True)

try:
    from database import SessionLocal as VideoSessionLocal
    from remotion_runner import (
        RemotionRunner,
        RemotionRunnerDependencies,
    )
    from video_artifact_service import (
        VideoArtifactDependencies,
        VideoArtifactService,
    )
    from video_contracts import VideoRenderConfig
    from video_render_service import (
        VideoRenderDependencies,
        configure_video_render_service,
    )
    from video_routes import router as video_router

    video_render_config = VideoRenderConfig(
        repo_root=Path(REPO_ROOT),
        runs_root=Path(RUNS_DIR),
        pipeline_version=REVEAL_PIPELINE_VERSION,
        reveal_visual_lead_sec=REVEAL_VISUAL_LEAD_SEC,
        bind_timeout_sec=STEP7_BIND_TIMEOUT_SEC,
        build_props_timeout_sec=STEP8_BUILD_PROPS_TIMEOUT_SEC,
        npm_install_timeout_sec=STEP8_NPM_INSTALL_TIMEOUT_SEC,
        render_timeout_sec=STEP8_RENDER_TIMEOUT_SEC,
        color_process_timeout_sec=STEP8_COLOR_PROCESS_TIMEOUT_SEC,
    )
    video_artifact_service = VideoArtifactService(
        VideoArtifactDependencies(
            runs_root=video_render_config.runs_root,
            pipeline_version=video_render_config.pipeline_version,
            render_timeout_sec=video_render_config.render_timeout_sec,
            read_visual_settings=read_project_visual_settings,
            normalize_color=normalize_hex_color,
            normalize_subtitle_style=normalize_subtitle_style,
            resolve_media_tool=lambda name: shared_resolve_media_tool(
                name,
                repo_root=Path(REPO_ROOT),
            ),
        )
    )
    remotion_runner = RemotionRunner(
        RemotionRunnerDependencies(
            config=video_render_config,
            build_reveal_assets=build_current_reveal_assets,
            write_project_log=write_project_log,
            # Remotion 渲染（npx -> node -> ffmpeg）是典型多层进程树，
            # 超时必须杀掉整棵进程树，避免孙进程残留与管道死锁。
            run_subprocess_bounded=run_subprocess_killable,
            resolve_media_tool=lambda name: shared_resolve_media_tool(
                name,
                repo_root=Path(REPO_ROOT),
            ),
        )
    )
    video_render_service = configure_video_render_service(
        VideoRenderDependencies(
            session_factory=VideoSessionLocal,
            artifact_service=video_artifact_service,
            remotion_runner=remotion_runner,
            config=video_render_config,
        )
    )
    app.include_router(video_router)
except Exception as exc:
    logger.exception(
        "Explicit video render route registration failed: %s",
        exc,
    )
    raise

try:
    from database import SessionLocal as OneClickSessionLocal
    from one_click_orchestrator import (
        OneClickDependencies,
        configure_one_click_dependencies,
    )
    from one_click_routes import router as one_click_router
    from pipeline_services import (
        ImagePipelineOperations,
        MaskPipelineOperations,
        MediaPipelineOperations,
        NarrationPipelineOperations,
        PipelineOperations,
        ProjectPipelineServices,
        StoryboardPipelineOperations,
    )

    pipeline_operations = PipelineOperations(
        storyboard=StoryboardPipelineOperations(
            script_plan=execute_step2_script_plan,
            visual_plan=execute_step2_visual_plan,
            compose_contract=compose_step2_visual_contract,
        ),
        images=ImagePipelineOperations(
            slide_prompts=get_slide_prompts,
            generate_slide_image=generate_slide_image,
            confirm_images=confirm_images,
        ),
        mask=MaskPipelineOperations(
            get_result=get_step5_result,
            repair_result=repair_step5_result,
            update_result=update_step5_result,
        ),
        narration=NarrationPipelineOperations(
            get_result=get_step6_result,
            repair_result=repair_step6_result,
            initialize=init_step6_narration,
            annotate=annotate_step6_narration,
            update_result=update_step6_result,
        ),
        media=MediaPipelineOperations(
            synthesize_audio=synthesize_tts_resumable,
            confirm_audio=confirm_tts_audio,
            render_video=lambda project_id, db: (
                video_render_service.start_render(db, project_id)
            ),
        ),
    )

    configure_one_click_dependencies(
        OneClickDependencies(
            session_factory=OneClickSessionLocal,
            project_model=Project,
            get_setting=get_setting,
            resolve_media_tool=lambda name: shared_resolve_media_tool(
                name,
                repo_root=Path(REPO_ROOT),
            ),
            repo_root=Path(REPO_ROOT),
            read_project_article_source=read_project_article_source,
            write_project_log=write_project_log,
            pipeline_service_factory=lambda db, project_id: ProjectPipelineServices(
                pipeline_operations,
                db,
                project_id,
            ),
        )
    )
    app.include_router(one_click_router)
except Exception as exc:
    logger.exception("Explicit one-click route registration failed: %s", exc)
    raise

try:
    from diagnostics_routes import router as diagnostics_router

    app.include_router(diagnostics_router)
except Exception as exc:
    logger.exception("Explicit diagnostics route registration failed: %s", exc)
    raise

try:
    from storyboard_background import router as storyboard_background_router

    app.include_router(storyboard_background_router)
except Exception as exc:
    logger.exception("Explicit storyboard background route registration failed: %s", exc)
    raise

try:
    from project_style_context import (
        ProjectStyleDependencies,
        configure_project_style_context,
    )
    from project_style_routes import router as project_style_router

    configure_project_style_context(
        ProjectStyleDependencies(
            get_setting=get_setting,
            update_settings=update_settings,
            get_openai_client=get_openai_client,
            generate_image_response=generate_image_response,
            extract_image_bytes_from_response=extract_image_bytes_from_response,
            process_and_save_image=process_and_save_image,
            write_project_log=write_project_log,
            build_image_style_prompt=build_image_style_prompt,
            read_style_tokens_data=read_style_tokens_data,
            compose_step3_single_slide_prompt=compose_step3_single_slide_prompt,
            read_step3_image_system_content=read_step3_image_system_content,
            compact_slide_element_lines=compact_slide_element_lines,
            is_seedream_image_model=is_seedream_image_model,
            http_exception=HTTPException,
            image_class=Image,
            data_dir=Path(DATA_DIR),
            repo_root=Path(REPO_ROOT),
            handdrawn_style_tokens_path=Path(HANDDRAWN_STYLE_TOKENS_PATH),
        )
    )
    app.include_router(project_style_router)
except Exception as exc:
    logger.exception("Explicit project style route registration failed: %s", exc)
    raise

try:
    from database import SessionLocal as PptxSessionLocal
    from pptx_routes import router as pptx_router
    from pptx_service import (
        PptxServiceDependencies,
        configure_pptx_export_service,
    )

    configure_pptx_export_service(
        PptxServiceDependencies(
            session_factory=PptxSessionLocal,
            runs_root=Path(RUNS_DIR),
        )
    )
    app.include_router(pptx_router)
except Exception as exc:
    logger.exception("Explicit PPTX export route registration failed: %s", exc)
    raise

try:
    from ai_mask_routes import router as ai_mask_router
    from ai_mask_semantic_matcher import semantic_vision_matcher
    from ai_mask_service import AiMaskDependencies, configure_ai_mask_task_service

    configure_ai_mask_task_service(
        AiMaskDependencies(
            get_setting=get_setting,
            get_openai_client=get_openai_client,
            reveal_lock_for=reveal_lock_for,
            write_project_log=write_project_log,
            read_style_tokens_data=read_style_tokens_data,
            step2_llm_vendor_options=step2_llm_vendor_options,
            clean_json_markdown=clean_json_markdown,
            is_timeout_exception=is_timeout_exception,
            vision_matcher=semantic_vision_matcher,
            logger=logger,
        )
    )
    app.include_router(ai_mask_router)
except Exception as exc:
    logger.exception("Explicit AI Mask route registration failed: %s", exc)
    raise

# 挂载静态资源
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

if __name__ == "__main__":
    from start_server import main as start_main

    raise SystemExit(start_main())
