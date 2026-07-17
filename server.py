import os
import io
import sys
import uuid
import json
import copy
import base64
import binascii
import hashlib
import shutil
import logging
import subprocess
import re
import tempfile
import threading
import time
import warnings
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session
from PIL import Image
import httpx
import yaml
from openai import OpenAI
from database import init_db, get_db, Project
from config_store import get_all_settings, update_settings, get_setting
from app_security import configured_allowed_hosts, configured_allowed_origins, install_access_control
from scripts.background_color import normalize_connected_background
from scripts.media_tools import (
    media_tool_candidate_dirs as shared_media_tool_candidate_dirs,
    probe_media_duration_sec,
    resolve_media_tool as shared_resolve_media_tool,
)
from scripts.pipeline_profiles import (
    read_pipeline_profile,
    role_catalog,
    storyboard_profile_prompt,
    storyboard_requirements,
)
from artifact_fingerprint import render_input_fingerprint, sha256_json
from visual_provenance import (
    promote_candidate_provenance,
    provenance_path as visual_provenance_path,
    refresh_provenance_contract_hashes,
    validate_visual_provenance_set,
    visual_provenance_status,
    write_visual_provenance,
)
from runtime_project_style_references import (
    can_send_project_references,
    profile_style_prompt,
    project_generate_prompt_for_slide,
    project_reference_paths,
)
from pipeline_lifecycle import (
    clear_all_reveal_artifacts,
    clear_audio_confirmation as clear_audio_confirmation_artifact,
    clear_remotion_props,
    clear_slide_reveal_artifacts,
    mark_downstream_pending,
    mark_selected_stale,
    write_json_atomic,
)
from tts_artifacts import (
    artifact_paths as tts_artifact_paths,
    artifact_status as tts_artifact_status,
    build_confirmation_payload as build_audio_confirmation_payload,
    confirmation_status as tts_confirmation_status,
    confirmation_path as tts_confirmation_path,
    is_audio_confirmed,
    nonempty_file as tts_nonempty_file,
    remove_outputs as remove_tts_outputs,
    timeline_duration_sec,
)
from pipeline_state import begin_step, complete_step, current_step_after_completion, mark_retry_needed
from project_storage import (
    UnsafeProjectPath,
    legacy_video_file,
    project_run_dir as validated_project_run_dir,
    slide_file as storage_slide_file,
    video_file as storage_video_file,
    video_sidecar as storage_video_sidecar,
    videos_dir as storage_videos_dir,
)

def get_openai_client(api_key: str, base_url: str = None, timeout: float = 120.0, max_retries: int = 1) -> OpenAI:
    # 强制不使用环境变量中的代理，防止某些局域网代理的 SSL 拦截规则冲突
    # 并强制定义 User-Agent 为 Chrome 浏览器以绕过 Cloudflare WAF/JA3 爬虫过滤指纹
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
    http_client = httpx.Client(
        limits=limits,
        trust_env=False,
        headers=headers,
        timeout=timeout
    )
    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        http_client=http_client,
        timeout=timeout,
        max_retries=max_retries,
    )


def normalize_tts_provider(provider: Optional[str]) -> str:
    value = str(provider or "minimax").strip().lower()
    return TTS_PROVIDER_ALIASES.get(value, value or "minimax")


def tts_provider_defaults(provider: str) -> Dict[str, str]:
    return TTS_PROVIDER_DEFAULTS.get(provider, TTS_PROVIDER_DEFAULTS["minimax"])


def first_non_empty(*values: Optional[str]) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def configured_tts_api_key(provider: str, explicit: Optional[str] = None) -> str:
    defaults = tts_provider_defaults(provider)
    return first_non_empty(
        explicit,
        get_setting("tts_api_key"),
        os.environ.get(str(defaults.get("api_key_env") or "")),
        os.environ.get("MINIMAX_API_KEY") if provider == "minimax" else "",
    )


def configured_tts_secret_key(provider: str, explicit: Optional[str] = None) -> str:
    defaults = tts_provider_defaults(provider)
    return first_non_empty(
        explicit,
        get_setting("tts_secret_key"),
        os.environ.get(str(defaults.get("secret_key_env") or "")),
    )


def provider_tts_command(
    *,
    provider: str,
    text_file: str,
    out_audio: str,
    out_meta: str,
    out_srt: str,
    out_timeline: str,
    slide_id: str,
    endpoint: str,
    region: str,
    model: str,
    voice_id: str,
    clone_voice_id: str,
    provider_extra: str,
    speed: str,
    volume: str,
    pitch: str,
) -> List[str]:
    script = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "generic_tts.py"))
    return [
        sys.executable,
        script,
        "--provider",
        provider,
        "--text-file",
        text_file,
        "--out-audio",
        out_audio,
        "--out-meta",
        out_meta,
        "--out-srt",
        out_srt,
        "--out-timeline",
        out_timeline,
        "--slide-id",
        slide_id,
        "--endpoint",
        endpoint,
        "--region",
        region,
        "--model",
        model,
        "--voice-id",
        voice_id,
        "--clone-voice-id",
        clone_voice_id,
        "--provider-extra",
        provider_extra,
        "--speed",
        speed,
        "--volume",
        volume,
        "--pitch",
        pitch,
        "--timeout",
        str(STEP7_TTS_TIMEOUT_SEC),
    ]


def provider_tts_environment(api_key: str, secret_key: str) -> Dict[str, str]:
    environment = os.environ.copy()
    environment[TTS_API_KEY_ENV] = str(api_key or "")
    environment[TTS_SECRET_KEY_ENV] = str(secret_key or "")
    return environment

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

RUNS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "runs"))
os.makedirs(RUNS_DIR, exist_ok=True)
MAX_IMAGE_UPLOAD_BYTES = int(os.environ.get("PPT_STUDIO_MAX_IMAGE_UPLOAD_BYTES", str(20 * 1024 * 1024)))
MAX_IMAGE_PIXELS = int(os.environ.get("PPT_STUDIO_MAX_IMAGE_PIXELS", "50000000"))
MAX_CONFIG_IMPORT_BYTES = int(os.environ.get("PPT_STUDIO_MAX_CONFIG_IMPORT_BYTES", str(25 * 1024 * 1024)))
TTS_API_KEY_ENV = "PPT_STUDIO_TTS_API_KEY"
TTS_SECRET_KEY_ENV = "PPT_STUDIO_TTS_SECRET_KEY"
REPO_ROOT = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(REPO_ROOT, "data")
os.makedirs(DATA_DIR, exist_ok=True)
DEFAULT_STYLE_TOKENS_PATH = os.path.join(REPO_ROOT, "config", "style_tokens.yaml")
HANDDRAWN_STYLE_TOKENS_PATH = os.path.join(REPO_ROOT, "config", "style_tokens_handdrawn.yaml")
STYLE_TOKENS_PATH = os.path.join(DATA_DIR, "style_tokens.yaml")
DEFAULT_STYLE_REFERENCE_DIR = os.path.join(REPO_ROOT, "references", "style_reference")
STYLE_REFERENCE_DIR = os.path.join(DATA_DIR, "style_reference_active")
STYLE_REFERENCE_FILES = {
    "template": "PPT模板.png",
}
STORYBOARD_TEMPLATES_PATH = os.path.join(DATA_DIR, "storyboard_templates.json")
STEP2_PROMPT_TEMPLATES_PATH = os.path.join(DATA_DIR, "step2_prompt_templates.json")
HANDDRAWN_STORYBOARD_RULES_PATH = os.path.join(REPO_ROOT, "templates", "prompts", "storyboard_rules_handdrawn.zh.md")
STEP2_PROMPT_TEMPLATE_FILES = {
    "script_system": os.path.join(REPO_ROOT, "templates", "prompts", "step2_script_system.md"),
    "script_output_example": os.path.join(REPO_ROOT, "templates", "prompts", "step2_script_output_example.json"),
    "visual_system": os.path.join(REPO_ROOT, "templates", "prompts", "step2_visual_system.md"),
    "visual_output_example": os.path.join(REPO_ROOT, "templates", "prompts", "step2_visual_output_example.json"),
}
STEP2_PROMPTS_FILE = "step2_prompts.json"
STEP2_SCRIPT_PLAN_FILE = "slide_script_plan.json"
STEP2_VISUAL_PLAN_FILE = "slide_visual_plan.json"
IMAGE_STYLE_TEMPLATES_DIR = os.path.join(DATA_DIR, "image_style_templates")
IMAGE_STYLE_TEMPLATES_INDEX = os.path.join(IMAGE_STYLE_TEMPLATES_DIR, "index.json")
REVEAL_PIPELINE_VERSION = "exact_rle_mask_with_manual_corrections_v5"
IMAGE_GENERATION_BACKGROUND = "#FFFFFF"
DEFAULT_VIDEO_BACKGROUND = "#FEFDF9"
PROJECT_VISUAL_SETTINGS_FILE = "visual_settings.json"
DEFAULT_SUBTITLE_STYLE = {
    "font_key": "noto_sans_sc",
    "font_family": "Noto Sans SC",
    "font_size": 38,
    "font_weight": 500,
    "bottom": 18,
    "horizontal_margin": 180,
    "color": "#111111",
}
OPEN_SOURCE_CHINESE_FONTS = [
    {
        "key": "noto_sans_sc",
        "label": "Noto Sans SC（现代黑体）",
        "family": "Noto Sans SC",
        "license": "SIL OFL 1.1",
        "source": "Google Fonts",
    },
    {
        "key": "noto_serif_sc",
        "label": "Noto Serif SC（现代宋体）",
        "family": "Noto Serif SC",
        "license": "SIL OFL 1.1",
        "source": "Google Fonts",
    },
    {
        "key": "ma_shan_zheng",
        "label": "马善政毛笔体（书写感）",
        "family": "Ma Shan Zheng",
        "license": "SIL OFL 1.1",
        "source": "Google Fonts",
    },
    {
        "key": "zcool_xiaowei",
        "label": "站酷小薇体（标题宋体）",
        "family": "ZCOOL XiaoWei",
        "license": "SIL OFL 1.1",
        "source": "Google Fonts",
    },
    {
        "key": "zcool_qingke",
        "label": "站酷庆科黄油体（醒目展示）",
        "family": "ZCOOL QingKe HuangYou",
        "license": "SIL OFL 1.1",
        "source": "Google Fonts",
    },
    {
        "key": "zcool_kuaile",
        "label": "站酷快乐体（活泼手写）",
        "family": "ZCOOL KuaiLe",
        "license": "SIL OFL 1.1",
        "source": "Google Fonts",
    },
    {
        "key": "long_cang",
        "label": "龙藏体（粗犷手写）",
        "family": "Long Cang",
        "license": "SIL OFL 1.1",
        "source": "Google Fonts",
    },
    {
        "key": "liu_jian_mao_cao",
        "label": "刘建毛草（奔放草书）",
        "family": "Liu Jian Mao Cao",
        "license": "SIL OFL 1.1",
        "source": "Google Fonts",
    },
    {
        "key": "zhi_mang_xing",
        "label": "志莽行书（自然行书）",
        "family": "Zhi Mang Xing",
        "license": "SIL OFL 1.1",
        "source": "Google Fonts",
    },
    {
        "key": "lxgw_marker_gothic",
        "label": "霞鹜标楷黑（马克笔展示）",
        "family": "LXGW Marker Gothic",
        "license": "SIL OFL 1.1",
        "source": "Google Fonts",
    },
    {
        "key": "lxgw_wenkai_tc",
        "label": "霞鹜文楷 TC（清晰楷体）",
        "family": "LXGW WenKai TC",
        "license": "SIL OFL 1.1",
        "source": "Google Fonts",
    },
    {
        "key": "noto_sans_tc",
        "label": "Noto Sans TC（繁简兼容黑体）",
        "family": "Noto Sans TC",
        "license": "SIL OFL 1.1",
        "source": "Google Fonts",
    },
    {
        "key": "noto_serif_tc",
        "label": "Noto Serif TC（繁简兼容宋体）",
        "family": "Noto Serif TC",
        "license": "SIL OFL 1.1",
        "source": "Google Fonts",
    },
    {
        "key": "lxgw_wenkai",
        "label": "霞鹜文楷（本机字体优先）",
        "family": "LXGW WenKai",
        "license": "SIL OFL 1.1",
        "source": "LXGW WenKai",
    },
]
_REVEAL_LOCKS: Dict[str, threading.RLock] = {}
_REVEAL_LOCKS_GUARD = threading.Lock()

TTS_PROVIDER_ALIASES = {
    "doubao": "volcengine_seed",
    "volcengine": "volcengine_seed",
    "aliyun": "aliyun_cosyvoice",
    "dashscope": "aliyun_cosyvoice",
    "cosyvoice": "aliyun_cosyvoice",
    "tencent": "tencent_tts",
}
TTS_PROVIDER_DEFAULTS = {
    "minimax": {
        "endpoint": "https://api.minimaxi.com/v1/t2a_async_v2",
        "model": "speech-2.8-hd",
        "voice_id": "Chinese (Mandarin)_Soft_Girl",
        "api_key_env": "MINIMAX_API_KEY",
    },
    "aliyun_cosyvoice": {
        "endpoint": "https://dashscope.aliyuncs.com/api/v1",
        "model": "cosyvoice-v3-flash",
        "voice_id": "longxiaochun",
        "api_key_env": "DASHSCOPE_API_KEY",
    },
    "tencent_tts": {
        "endpoint": "https://tts.tencentcloudapi.com",
        "model": "1",
        "voice_id": "101001",
        "api_key_env": "TENCENTCLOUD_SECRET_ID",
        "secret_key_env": "TENCENTCLOUD_SECRET_KEY",
        "region": "ap-guangzhou",
    },
    "volcengine_seed": {
        "endpoint": "https://openspeech.bytedance.com/api/v1/tts",
        "model": "seed-tts-1.1",
        "voice_id": "zh_female_qingxinnvsheng_mars_bigtts",
        "api_key_env": "VOLCENGINE_TTS_TOKEN",
    },
}

def reveal_lock_for(project: Project) -> threading.RLock:
    key = os.path.abspath(project.run_dir)
    with _REVEAL_LOCKS_GUARD:
        lock = _REVEAL_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _REVEAL_LOCKS[key] = lock
        return lock


def read_json_file(path: str, fallback: Any) -> Any:
    if not os.path.exists(path):
        return copy.deepcopy(fallback)
    try:
        with open(path, "r", encoding="utf-8-sig") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read JSON file %s: %s", path, exc)
        return copy.deepcopy(fallback)


def ensure_active_image_style_storage() -> None:
    os.makedirs(STYLE_REFERENCE_DIR, exist_ok=True)
    os.makedirs(IMAGE_STYLE_TEMPLATES_DIR, exist_ok=True)
    if not os.path.exists(STYLE_TOKENS_PATH):
        shutil.copy2(DEFAULT_STYLE_TOKENS_PATH, STYLE_TOKENS_PATH)
    for filename in STYLE_REFERENCE_FILES.values():
        active_path = os.path.join(STYLE_REFERENCE_DIR, filename)
        default_path = os.path.join(DEFAULT_STYLE_REFERENCE_DIR, filename)
        if not os.path.exists(active_path) and os.path.exists(default_path):
            shutil.copy2(default_path, active_path)


def normalized_template_name(value: Any) -> str:
    name = re.sub(r"\s+", " ", str(value or "").strip())
    if not name:
        raise HTTPException(status_code=400, detail="模板名称不能为空")
    if len(name) > 60:
        raise HTTPException(status_code=400, detail="模板名称不能超过 60 个字符")
    return name


def template_timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


ensure_active_image_style_storage()


STEP1_LLM_TIMEOUT_SEC = 60.0
STEP2_LLM_TIMEOUT_SEC = 240.0
STEP5_REVEAL_BUILD_TIMEOUT_SEC = float(os.environ.get("PPT_STUDIO_REVEAL_BUILD_TIMEOUT_SEC", "300"))
STEP7_TTS_TIMEOUT_SEC = 300
STEP7_TTS_PROCESS_TIMEOUT_SEC = STEP7_TTS_TIMEOUT_SEC + 90
STEP7_TTS_RETRY_ATTEMPTS = 3
STEP7_TTS_RETRY_BASE_DELAY_SEC = 4
STEP7_BIND_TIMEOUT_SEC = 90
STEP8_RENDER_TIMEOUT_SEC = 3600
REVEAL_VISUAL_LEAD_SEC = 0.45
DEFAULT_STEP2_GENERATION_REQUIREMENT = (
    "按当前已保存的分镜规则、结构配置和文章内容生成分镜规划。"
    "优先把内容讲清楚，不要机械套用固定卡片结构。"
)

def _redact_log_value(key: str, value: Any) -> Any:
    lowered = key.lower()
    if any(token in lowered for token in ("api_key", "apikey", "authorization", "token", "secret")):
        return "***REDACTED***" if value else value
    if isinstance(value, str) and len(value) > 4000:
        return value[:4000] + f"\n... [truncated {len(value) - 4000} chars]"
    return value

def write_project_log(project: Project, event: str, **fields: Any) -> None:
    try:
        log_dir = os.path.join(project.run_dir, "logs")
        os.makedirs(log_dir, exist_ok=True)
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "project_id": project.id,
            "event": event,
        }
        record.update({key: _redact_log_value(key, value) for key, value in fields.items()})
        line = json.dumps(record, ensure_ascii=False, default=str)
        with open(os.path.join(log_dir, "pipeline.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
        logger.info("project=%s event=%s %s", project.id, event, line)
    except Exception as exc:
        logger.warning("Failed to write project log for %s: %s", getattr(project, "id", "<unknown>"), exc)

# Pydantic 响应模型
class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = ""

class SettingsUpdate(BaseModel):
    settings: Dict[str, str]

MASKED_SETTINGS_VALUE = "__PPT_STUDIO_MASKED_VALUE__"
SETTINGS_SECRET_KEYS = {
    "llm_api_key",
    "image_api_key",
    "tts_api_key",
    "tts_secret_key",
    "tts_provider_extra",
}


def mask_settings_secrets_enabled() -> bool:
    value = os.environ.get("PPT_STUDIO_MASK_SETTINGS_SECRETS")
    if value is None:
        return True
    return value.strip().lower() not in {"0", "false", "no", "off"}


def mask_sensitive_settings(settings: Dict[str, Any], *, force: bool = False) -> Dict[str, Any]:
    if not force and not mask_settings_secrets_enabled():
        return settings
    masked = dict(settings or {})
    for key in SETTINGS_SECRET_KEYS:
        if masked.get(key) not in (None, ""):
            masked[key] = MASKED_SETTINGS_VALUE
    return masked


class StepUpdate(BaseModel):
    step_data: Dict[str, Any]

class TestLlmPayload(BaseModel):
    base_url: Optional[str] = None
    api_key: str
    model: str

class TestImagePayload(BaseModel):
    base_url: Optional[str] = None
    api_key: str
    model: str
    size: Optional[str] = None

class TestTtsPayload(BaseModel):
    provider: Optional[str] = "minimax"
    endpoint: Optional[str] = None
    api_key: Optional[str] = None
    secret_key: Optional[str] = None
    region: Optional[str] = None
    model: Optional[str] = None
    voice_id: Optional[str] = None
    clone_voice_id: Optional[str] = None
    provider_extra: Optional[str] = None


def open_validated_image(image_bytes: bytes) -> Image.Image:
    if not image_bytes:
        raise ValueError("图片文件为空")
    if len(image_bytes) > MAX_IMAGE_UPLOAD_BYTES:
        raise ValueError(f"图片文件超过 {MAX_IMAGE_UPLOAD_BYTES // (1024 * 1024)} MB 限制")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(io.BytesIO(image_bytes))
            if image.width <= 0 or image.height <= 0 or image.width * image.height > MAX_IMAGE_PIXELS:
                image.close()
                raise ValueError(f"图片像素总量超过 {MAX_IMAGE_PIXELS} 限制")
            image.load()
            return image
    except ValueError:
        raise
    except (Image.UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning, OSError) as exc:
        raise ValueError("无法识别或不安全的图片文件") from exc


# 图片后处理：将任意尺寸等比例缩放，并居中贴在纯白 1920x1080 生图画布上
def process_and_save_image(image_bytes: bytes, save_path: str):
    # Keep the original aspect ratio. Non-16:9 sources are fitted and padded;
    # native 16:9 uploads fill the render canvas without stretching.
    bg_color = (255, 255, 255)
    target_width, target_height = 1920, 1080
    
    img = open_validated_image(image_bytes)
    if img.mode in ("RGBA", "LA") or "transparency" in img.info:
        rgba = img.convert("RGBA")
        white = Image.new("RGBA", rgba.size, (*bg_color, 255))
        white.alpha_composite(rgba)
        img = white.convert("RGB")
    elif img.mode != "RGB":
        img = img.convert("RGB")
        
    source_width, source_height = img.width, img.height
    img_ratio = img.width / img.height
    target_ratio = target_width / target_height
    
    if img_ratio > target_ratio:
        new_width = target_width
        new_height = int(target_width / img_ratio)
    else:
        new_height = target_height
        new_width = int(target_height * img_ratio)
        
    resized_img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
    
    # 居中贴合到 1920x1080 的温暖极简底图上
    final_img = Image.new("RGB", (target_width, target_height), bg_color)
    paste_x = (target_width - new_width) // 2
    paste_y = (target_height - new_height) // 2
    final_img.paste(resized_img, (paste_x, paste_y))
    final_img, _ = normalize_connected_background(final_img, bg_color)
    
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    final_img.save(save_path, "PNG")
    logger.info(
        "Image normalized and saved: source=%sx%s fitted=%sx%s canvas=%sx%s path=%s",
        source_width,
        source_height,
        new_width,
        new_height,
        target_width,
        target_height,
        save_path,
    )


def is_seedream_image_model(model: Optional[str], base_url: Optional[str] = None) -> bool:
    """Detect Volcengine/Doubao Seedream image models behind OpenAI-compatible APIs."""
    text = f"{model or ''} {base_url or ''}".lower()
    return any(
        marker in text
        for marker in (
            "seedream",
            "doubao",
            "volcengine",
            "volces",
            "ark.cn",
            "ark.volc",
        )
    )


def response_has_image_data(response: Any) -> bool:
    first_item = first_image_response_item(response)
    return bool(
        image_response_value(first_item, "b64_json")
        or image_response_value(first_item, "url")
    )


def first_image_response_item(response: Any) -> Any:
    data = response.get("data") if isinstance(response, dict) else getattr(response, "data", None)
    if not data:
        return None
    return data[0]


def image_response_value(item: Any, key: str) -> Any:
    if item is None:
        return None
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def extract_image_bytes_from_response(response: Any) -> bytes:
    """Read generated image bytes from OpenAI-compatible b64_json or URL responses."""
    first_item = first_image_response_item(response)
    b64_json = image_response_value(first_item, "b64_json")
    if b64_json:
        b64_text = str(b64_json)
        if "," in b64_text and b64_text.strip().startswith("data:"):
            b64_text = b64_text.split(",", 1)[1]
        return base64.b64decode(b64_text)

    image_url = image_response_value(first_item, "url")
    if image_url:
        logger.info("Image URL received, downloading generated asset.")
        with httpx.Client(timeout=60, trust_env=False) as http_client:
            img_resp = http_client.get(str(image_url))
        if img_resp.status_code != 200:
            raise RuntimeError(f"下载生成图片失败: HTTP {img_resp.status_code}")
        return img_resp.content

    raise RuntimeError("API 响应中既没有 url 也没有 b64_json，无法获取图片数据。")


def generate_image_response(
    client: OpenAI,
    model: str,
    prompt: str,
    size: str,
    base_url: Optional[str] = None,
    timeout: Optional[int] = None,
) -> Any:
    """Generate an image with provider-specific fallbacks for OpenAI-compatible services."""
    seedream_mode = is_seedream_image_model(model, base_url)
    kwargs: Dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "n": 1,
    }
    if timeout:
        kwargs["timeout"] = timeout

    if seedream_mode:
        # Volcengine Ark / Doubao Seedream uses OpenAI-compatible images.generate,
        # but does not accept OpenAI-only knobs such as quality="standard".
        try:
            return client.images.generate(
                **kwargs,
                size=size,
                response_format="b64_json",
            )
        except Exception as response_format_error:
            logger.warning("Seedream image generation with response_format failed, retrying without it: %s", response_format_error)
            try:
                return client.images.generate(
                    **kwargs,
                    size=size,
                )
            except Exception as size_error:
                logger.warning("Seedream image generation with size failed, retrying minimal params: %s", size_error)
                return client.images.generate(**kwargs)

    try:
        return client.images.generate(
            **kwargs,
            size=size,
            quality="standard",
        )
    except Exception as full_params_err:
        logger.warning(
            "Image gen with full params failed (%s). Retrying with size only for compatible providers...",
            full_params_err,
        )
        try:
            return client.images.generate(
                **kwargs,
                size=size,
            )
        except Exception as size_err:
            logger.warning("Image gen with size failed (%s). Retrying minimal params...", size_err)
            return client.images.generate(**kwargs)


def clean_json_markdown(text: str) -> str:
    text = text.strip()
    
    # 移除 ```json 和 ``` 包裹
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline:].strip()
        else:
            text = text[3:].strip()
        if text.endswith("```"):
            text = text[:-3].strip()
            
    # 特殊容错：有些大模型会在前后附加解释文本，我们尝试提取第一个 { 或 [ 到最后一个 } 或 ]
    first_brace = text.find("{")
    first_bracket = text.find("[")
    
    start_idx = -1
    end_idx = -1
    
    if first_brace != -1 and (first_bracket == -1 or first_brace < first_bracket):
        start_idx = first_brace
        end_idx = text.rfind("}")
    elif first_bracket != -1:
        start_idx = first_bracket
        end_idx = text.rfind("]")
        
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        return text[start_idx:end_idx + 1]
        
    return text


def json_decode_context(text: str, exc: json.JSONDecodeError, radius: int = 300) -> str:
    start = max(0, exc.pos - radius)
    end = min(len(text), exc.pos + radius)
    return text[start:end]


def write_debug_text(run_dir: str, filename: str, content: str) -> str:
    planning_dir = os.path.join(run_dir, "planning")
    os.makedirs(planning_dir, exist_ok=True)
    path = os.path.join(planning_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def parse_int_setting(value: str, default: int, min_value: int, max_value: int) -> int:
    try:
        parsed = int(float(str(value).strip()))
    except Exception:
        parsed = default
    return max(min_value, min(max_value, parsed))


def is_timeout_exception(exc: BaseException) -> bool:
    seen: set[int] = set()
    current: Optional[BaseException] = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        name = type(current).__name__.lower()
        text = str(current).lower()
        if isinstance(current, TimeoutError) or "timeout" in name or "timed out" in text:
            return True
        current = current.__cause__ or current.__context__
    return False


def parse_range_text(value: Any, default_min: int, default_max: int) -> tuple[int, int]:
    numbers = [int(item) for item in re.findall(r"\d+", str(value or ""))]
    if not numbers:
        return default_min, default_max
    if len(numbers) == 1:
        parsed_min = parsed_max = numbers[0]
    else:
        parsed_min, parsed_max = numbers[0], numbers[1]
    parsed_min = max(1, min(30, parsed_min))
    parsed_max = max(parsed_min, min(30, parsed_max))
    return parsed_min, parsed_max


def parse_json_or_repair_with_llm(
    *,
    cleaned_content: str,
    raw_content: str,
    client: OpenAI,
    model: str,
    run_dir: str,
    artifact_prefix: str,
    schema_hint: str = "",
    max_tokens: int = 16000,
) -> Dict[str, Any]:
    try:
        value = json.loads(cleaned_content)
    except json.JSONDecodeError as first_error:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        raw_path = write_debug_text(run_dir, f"{artifact_prefix}_{timestamp}.raw_failed.txt", raw_content)
        cleaned_path = write_debug_text(run_dir, f"{artifact_prefix}_{timestamp}.cleaned_failed.json", cleaned_content)
        context = json_decode_context(cleaned_content, first_error)
        logger.warning(
            "Invalid JSON from LLM for %s: %s. Raw saved to %s, cleaned saved to %s. Context near error: %r",
            artifact_prefix,
            first_error,
            raw_path,
            cleaned_path,
            context,
        )

        repair_prompt = (
            "You repair invalid JSON emitted by another model. "
            "Return only one valid JSON object. No markdown, no comments, no explanation. "
            "Fix syntax issues such as missing commas, unescaped quotes, trailing text, "
            "or incomplete brackets while preserving the original Chinese content and structure."
        )
        repair_user = (
            f"JSON parser error: {first_error}\n\n"
            f"Schema hint:\n{schema_hint[:12000]}\n\n"
            f"Invalid JSON to repair:\n{cleaned_content[:120000]}"
        )

        try:
            try:
                repair_response = client.chat.completions.create(
                    model=model,
                    temperature=0,
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": repair_prompt},
                        {"role": "user", "content": repair_user},
                    ],
                )
            except Exception as repair_format_error:
                logger.warning(
                    "LLM JSON repair with response_format failed for %s, retrying without it: %s",
                    artifact_prefix,
                    repair_format_error,
                )
                repair_response = client.chat.completions.create(
                    model=model,
                    temperature=0,
                    max_tokens=max_tokens,
                    messages=[
                        {"role": "system", "content": repair_prompt},
                        {"role": "user", "content": repair_user},
                    ],
                )
        except Exception as repair_error:
            logger.error("LLM JSON repair request failed for %s: %s", artifact_prefix, repair_error)
            raise first_error from repair_error

        repaired_raw = repair_response.choices[0].message.content.strip()
        repaired_cleaned = clean_json_markdown(repaired_raw)
        write_debug_text(run_dir, f"{artifact_prefix}_{timestamp}.repaired_raw.txt", repaired_raw)
        try:
            value = json.loads(repaired_cleaned)
        except json.JSONDecodeError as repair_parse_error:
            repaired_path = write_debug_text(
                run_dir,
                f"{artifact_prefix}_{timestamp}.repaired_failed.json",
                repaired_cleaned,
            )
            logger.error(
                "LLM JSON repair still invalid for %s: %s. Repaired content saved to %s. Context near error: %r",
                artifact_prefix,
                repair_parse_error,
                repaired_path,
                json_decode_context(repaired_cleaned, repair_parse_error),
            )
            raise first_error from repair_parse_error

    if not isinstance(value, dict):
        raise ValueError("LLM response must be a JSON object")
    return value


def generate_json_with_configured_llm(
    *,
    system_prompt: str,
    user_prompt: str,
    run_dir: str,
    artifact_prefix: str,
    schema_hint: str,
    temperature: float = 0.35,
    max_tokens_default: int = 12000,
) -> Dict[str, Any]:
    llm_api_key = get_setting("llm_api_key")
    llm_base_url = get_setting("llm_base_url")
    llm_model = get_setting("llm_model")
    if not llm_api_key:
        raise HTTPException(status_code=400, detail="未配置大模型 API 密钥，请在系统设置中配置后再试。")
    if not llm_model:
        raise HTTPException(status_code=400, detail="未配置大模型名称，请在系统设置中配置后再试。")
    max_tokens = parse_int_setting(
        get_setting("llm_max_tokens", str(max_tokens_default)),
        max_tokens_default,
        1024,
        64000,
    )
    client = get_openai_client(api_key=llm_api_key, base_url=llm_base_url)
    try:
        try:
            response = client.chat.completions.create(
                model=llm_model,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
        except Exception as format_error:
            logger.warning(
                "AI JSON generation with response_format failed for %s, retrying without it: %s",
                artifact_prefix,
                format_error,
            )
            response = client.chat.completions.create(
                model=llm_model,
                temperature=temperature,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system_prompt + "\n只输出纯 JSON，不要 Markdown，不要解释。"},
                    {"role": "user", "content": user_prompt},
                ],
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"AI 生成失败: {exc}") from exc

    raw_content = response.choices[0].message.content.strip()
    return parse_json_or_repair_with_llm(
        cleaned_content=clean_json_markdown(raw_content),
        raw_content=raw_content,
        client=client,
        model=llm_model,
        run_dir=run_dir,
        artifact_prefix=artifact_prefix,
        schema_hint=schema_hint,
        max_tokens=max_tokens,
    )


def strip_anchor_lead_in(spoken_text: str, anchor: str) -> str:
    text = str(spoken_text or "").strip()
    anchor = str(anchor or "").strip()
    if not text or not anchor:
        return text
    patterns = [
        rf"^围绕“{re.escape(anchor)}”[，,]\s*",
        rf"^围绕\"{re.escape(anchor)}\"[，,]\s*",
        rf"^围绕「{re.escape(anchor)}」[，,]\s*",
        rf"^围绕『{re.escape(anchor)}』[，,]\s*",
    ]
    for pattern in patterns:
        cleaned = re.sub(pattern, "", text)
        if cleaned != text:
            return cleaned.strip()
    return text


def narration_dedupe_key(value: Any) -> str:
    """Return a punctuation/markup-insensitive key for one spoken sentence."""
    text = str(value or "").strip().casefold()
    text = re.sub(r"<#\d+(?:\.\d{1,2})?#>|\([A-Za-z-]+\)", "", text)
    return re.sub(r"[\W_]+", "", text, flags=re.UNICODE)


def dedupe_narration_beats(beats: Any) -> List[Dict[str, Any]]:
    """Keep the first occurrence of each spoken sentence on a slide."""
    if not isinstance(beats, list):
        return []
    seen: set[str] = set()
    result: List[Dict[str, Any]] = []
    for beat in beats:
        if not isinstance(beat, dict):
            continue
        text = beat.get("spoken_text") or beat.get("tts_text") or beat.get("source_text") or ""
        key = narration_dedupe_key(text)
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        result.append(beat)
    return result


def normalize_visual_contract(
    contract: Dict[str, Any],
    profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    presentation_policy = contract.get("presentation_policy")
    if not isinstance(presentation_policy, dict):
        presentation_policy = {}
        contract["presentation_policy"] = presentation_policy
    presentation_policy["subtitle_policy"] = "no_slides_have_subtitle"
    presentation_policy["subtitle_decided_by"] = "system_no_subtitle_contract"
    slides = contract.get("slides")
    if not isinstance(slides, list):
        return contract
    for slide in slides:
        if not isinstance(slide, dict):
            continue
        slide["subtitle"] = ""
        groups = slide.get("visual_groups")
        if not isinstance(groups, list):
            continue
        groups = [
            group for group in groups
            if not isinstance(group, dict)
            or str(group.get("role") or "").strip().lower() != "subtitle"
        ]
        slide["visual_groups"] = groups

        group_by_id: Dict[str, Dict[str, Any]] = {}
        for index, group in enumerate(groups, start=1):
            if not isinstance(group, dict):
                continue
            group_id = str(group.get("id") or f"group_{index:02d}").strip()
            group["id"] = group_id
            role = str(group.get("role") or "content_body").strip()
            group["role"] = role
            group["visual_type"] = normalize_visual_type(
                group.get("visual_type"),
                has_text=bool(str(group.get("display_text") or "").strip()),
            )
            if not str(group.get("content_unit_id") or "").strip():
                group["content_unit_id"] = f"{group_id}_unit"
            group.pop("speak_policy", None)
            if role != "decoration" and not str(group.get("mask_target") or "").strip():
                group["mask_target"] = str(
                    group.get("visual_anchor") or group.get("visible_text") or group_id
                ).strip()
            if not group.get("reveal_order"):
                group["reveal_order"] = index
            group_by_id[group_id] = group

        beats = slide.get("narration_beats")
        if not isinstance(beats, list):
            continue
        normalized_beats = []
        for index, beat in enumerate(beats, start=1):
            if not isinstance(beat, dict):
                continue
            if not str(beat.get("id") or "").strip():
                beat["id"] = f"beat_{index:02d}"
            group_id = str(beat.get("group_id") or "").strip()
            group = group_by_id.get(group_id)
            if not group:
                continue
            if not str(beat.get("content_unit_id") or "").strip():
                beat["content_unit_id"] = group.get("content_unit_id")
            if not str(beat.get("visible_anchor") or "").strip():
                beat["visible_anchor"] = group.get("visible_text")
            anchor = str(beat.get("visible_anchor") or group.get("visible_text") or "").strip()
            spoken_text = str(beat.get("spoken_text") or "").strip()
            spoken_text = strip_anchor_lead_in(spoken_text, anchor)
            if not spoken_text:
                intent = str(beat.get("spoken_intent") or "").strip()
                beat["spoken_text"] = intent or f"请看画面中的{anchor}。"
            else:
                beat["spoken_text"] = spoken_text
            normalized_beats.append(beat)
        slide["narration_beats"] = dedupe_narration_beats(normalized_beats)

    return contract


def build_article_summary(content: str, max_chars: int = 180) -> str:
    """Create a lightweight planning summary without calling an LLM."""
    text = re.sub(r"```.*?```", " ", content, flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"\[[^\]]+\]\([^)]+\)", " ", text)
    text = re.sub(r"[#>*_`~\-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


def contract_slide_ids_from_payload(payload: Dict[str, Any]) -> List[str]:
    slide_ids: List[str] = []
    for slide in payload.get("slides", []) or []:
        if not isinstance(slide, dict):
            continue
        slide_id = str(slide.get("slide_id") or "").strip()
        if slide_id:
            slide_ids.append(slide_id)
    return slide_ids


def read_contract_slide_ids(run_dir: str) -> List[str]:
    contract_path = os.path.join(run_dir, "planning", "visual_contract.json")
    if not os.path.exists(contract_path):
        return []
    try:
        with open(contract_path, "r", encoding="utf-8") as f:
            contract = json.load(f)
    except Exception as e:
        logger.warning(f"Failed to read visual contract for slide sync: {e}")
        return []
    return contract_slide_ids_from_payload(contract)


def all_current_slide_images_exist(project: Project) -> bool:
    slide_ids = read_contract_slide_ids(project.run_dir)
    if not slide_ids:
        return False
    return all(
        os.path.exists(os.path.join(project.run_dir, "slides", slide_id, "visual_draft.png"))
        for slide_id in slide_ids
    )


def prune_stale_mask_groups(project: Project, payload: Dict[str, Any]) -> Dict[str, Any]:
    contract_path = os.path.join(project.run_dir, "planning", "visual_contract.json")
    if not os.path.exists(contract_path) or not isinstance(payload.get("slides"), list):
        return payload

    try:
        with open(contract_path, "r", encoding="utf-8") as f:
            contract = json.load(f)
    except Exception as exc:
        logger.warning("Failed to load visual contract while pruning Mask groups: %s", exc)
        return payload

    visual_groups_by_slide = {}
    for slide in contract.get("slides", []) or []:
        if not isinstance(slide, dict):
            continue
        slide_id = str(slide.get("slide_id") or "").strip()
        visual_groups_by_slide[slide_id] = {
            str(group.get("id") or "").strip()
            for group in slide.get("visual_groups", []) or []
            if isinstance(group, dict) and str(group.get("id") or "").strip()
        }

    def is_current(group: Dict[str, Any], visual_group_ids: set[str]) -> bool:
        group_id = str(group.get("id") or group.get("group_id") or "").strip()
        visual_group_id = str(group.get("visual_group_id") or "").strip()
        # AI Mask stores the exact title/subtitle pixels as a hidden static
        # group.  It is intentionally not a visual_contract group, so contract
        # pruning must preserve it or the next Save/Build operation turns the
        # opening title back into missing/fragmented dynamic content.
        if (
            group.get("is_static") is True
            or group.get("is_static_header") is True
            or str(group.get("source") or "") == "ai_static_header"
            or group_id == "__static_title_header__"
        ):
            return True
        if group_id.startswith("manual_group_"):
            return True
        if visual_group_id and visual_group_id in visual_group_ids:
            return True
        return group_id in visual_group_ids

    for slide in payload.get("slides", []):
        if not isinstance(slide, dict):
            continue
        slide_id = str(slide.get("slide_id") or "").strip()
        visual_group_ids = visual_groups_by_slide.get(slide_id, set())
        for field in ("semantic_blocks", "groups"):
            groups = slide.get(field)
            if not isinstance(groups, list):
                continue
            slide[field] = [
                group for group in groups
                if isinstance(group, dict) and is_current(group, visual_group_ids)
            ]
    return payload


def read_current_slide_ids_or_404(project: Project) -> List[str]:
    slide_ids = read_contract_slide_ids(project.run_dir)
    if not slide_ids:
        raise HTTPException(status_code=400, detail="分镜规划尚未生成，请先完成第二步")
    return slide_ids


def project_run_dir_or_500(project: Project) -> str:
    try:
        return str(validated_project_run_dir(RUNS_DIR, project.run_dir, project.id))
    except UnsafeProjectPath as exc:
        logger.error("Unsafe project run directory for %s: %s", project.id, exc)
        raise HTTPException(status_code=500, detail="项目运行目录安全校验失败") from exc


def current_slide_file_or_404(project: Project, slide_id: str, filename: str) -> str:
    run_dir = project_run_dir_or_500(project)
    if slide_id not in read_current_slide_ids_or_404(project):
        raise HTTPException(status_code=404, detail="Slide 不存在")
    try:
        return str(storage_slide_file(run_dir, slide_id, filename))
    except UnsafeProjectPath as exc:
        raise HTTPException(status_code=400, detail="Slide 路径无效") from exc


def project_video_file_or_400(project: Project, filename: str) -> str:
    run_dir = project_run_dir_or_500(project)
    try:
        return str(storage_video_file(run_dir, filename))
    except UnsafeProjectPath as exc:
        raise HTTPException(status_code=400, detail="视频文件名无效") from exc


def project_legacy_video_file(project: Project) -> str:
    return str(legacy_video_file(project_run_dir_or_500(project)))


def sync_reveal_manifest_to_contract(project: Project, slide_ids: Optional[List[str]] = None) -> bool:
    """Keep Mask slides aligned with Step 2 and repair missing template slides.

    Older implementations only removed stale slides.  If a stale browser
    autosave or interrupted initialization wrote ``slides: []``, the manifest
    remained permanently empty and AI Mask failed at the first slide.  Build a
    fresh coordinate template from the visual contract and use it only for
    missing slides, preserving every existing manual/AI annotation.
    """
    current_slide_ids = slide_ids if slide_ids is not None else read_contract_slide_ids(project.run_dir)
    if not current_slide_ids:
        return False

    manifest_path = os.path.join(project.run_dir, "reveal_manifest.json")
    if not os.path.exists(manifest_path):
        return False

    with reveal_lock_for(project):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read reveal manifest for slide sync: {e}")
            return False

        slides = manifest.get("slides", [])
        if not isinstance(slides, list):
            return False

        by_id = {
            str(slide.get("slide_id") or "").strip(): slide
            for slide in slides
            if isinstance(slide, dict) and str(slide.get("slide_id") or "").strip()
        }
        missing_slide_ids = [slide_id for slide_id in current_slide_ids if slide_id not in by_id]
        template_by_id: Dict[str, Dict[str, Any]] = {}
        if missing_slide_ids:
            contract_path = os.path.join(project.run_dir, "planning", "visual_contract.json")
            try:
                with open(contract_path, "r", encoding="utf-8-sig") as file:
                    contract = json.load(file)
                from scripts.write_reveal_manifest_template import build_manifest

                template_manifest = build_manifest(contract, Path(project.run_dir))
                template_by_id = {
                    str(slide.get("slide_id") or "").strip(): slide
                    for slide in template_manifest.get("slides", [])
                    if isinstance(slide, dict) and str(slide.get("slide_id") or "").strip()
                }
            except Exception as exc:
                logger.exception("Failed to repair missing reveal manifest slides: %s", exc)
                return False

        synced_slides = [
            by_id.get(slide_id) or template_by_id.get(slide_id)
            for slide_id in current_slide_ids
        ]
        synced_slides = [slide for slide in synced_slides if isinstance(slide, dict)]
        changed = synced_slides != slides
        if not changed:
            return False

        manifest["slides"] = synced_slides
        if missing_slide_ids:
            # Any previous completion summary is stale once a slide template
            # has to be reconstructed.  The next annotation run will write a
            # truthful replacement summary.
            manifest.pop("ai_mask_annotation", None)
        write_json_atomic(manifest_path, manifest)
    logger.info(
        "Synced reveal manifest to visual contract: %s slides (%s repaired, %s previous)",
        len(synced_slides),
        len(missing_slide_ids),
        len(slides),
    )
    return True


def normalize_hex_color(value: Any, fallback: str = DEFAULT_VIDEO_BACKGROUND) -> str:
    text = str(value or "").strip().upper()
    if re.fullmatch(r"#[0-9A-F]{6}", text):
        return text
    return fallback


def project_visual_settings_path(project: Project) -> str:
    return os.path.join(project.run_dir, PROJECT_VISUAL_SETTINGS_FILE)


def normalize_subtitle_style(value: Any) -> Dict[str, Any]:
    payload = value if isinstance(value, dict) else {}
    def clamp_int(raw: Any, fallback: int, minimum: int, maximum: int) -> int:
        try:
            parsed = int(float(raw))
        except (TypeError, ValueError):
            parsed = fallback
        return max(minimum, min(maximum, parsed))

    font_by_key = {font["key"]: font for font in OPEN_SOURCE_CHINESE_FONTS}
    font_key = str(payload.get("font_key") or DEFAULT_SUBTITLE_STYLE["font_key"]).strip()
    if font_key not in font_by_key:
        font_key = DEFAULT_SUBTITLE_STYLE["font_key"]
    font = font_by_key[font_key]
    return {
        "font_key": font_key,
        "font_family": font["family"],
        "font_size": clamp_int(payload.get("font_size"), DEFAULT_SUBTITLE_STYLE["font_size"], 22, 72),
        "font_weight": clamp_int(payload.get("font_weight"), DEFAULT_SUBTITLE_STYLE["font_weight"], 300, 800),
        "bottom": clamp_int(payload.get("bottom"), DEFAULT_SUBTITLE_STYLE["bottom"], 0, 220),
        "horizontal_margin": clamp_int(
            payload.get("horizontal_margin"),
            DEFAULT_SUBTITLE_STYLE["horizontal_margin"],
            40,
            420,
        ),
        "color": normalize_hex_color(payload.get("color"), DEFAULT_SUBTITLE_STYLE["color"]),
    }


def read_project_visual_settings(project: Project) -> Dict[str, Any]:
    path = project_visual_settings_path(project)
    payload: Dict[str, Any] = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as file:
                value = json.load(file)
            if isinstance(value, dict):
                payload = value
        except Exception as exc:
            logger.warning("Failed to read project visual settings: %s", exc)
    return {
        "generation_background": IMAGE_GENERATION_BACKGROUND,
        "video_background": normalize_hex_color(payload.get("video_background")),
        "subtitle_style": normalize_subtitle_style(payload.get("subtitle_style")),
    }


def write_project_visual_settings(
    project: Project,
    video_background: Optional[str] = None,
    subtitle_style: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    current = read_project_visual_settings(project)
    settings = {
        "generation_background": IMAGE_GENERATION_BACKGROUND,
        "video_background": normalize_hex_color(video_background, current["video_background"]),
        "subtitle_style": normalize_subtitle_style(subtitle_style or current["subtitle_style"]),
    }
    write_json_atomic(project_visual_settings_path(project), settings)
    return settings


def subtitle_preview_background_url(project: Project) -> str:
    for slide_id in read_contract_slide_ids(project.run_dir):
        path = os.path.join(project.run_dir, "slides", slide_id, "visual_draft.png")
        if os.path.exists(path):
            return f"/api/projects/{project.id}/slides/{slide_id}/image?t={int(os.path.getmtime(path))}"
    template_path = os.path.join(STYLE_REFERENCE_DIR, STYLE_REFERENCE_FILES["template"])
    if os.path.exists(template_path):
        return f"/api/image-style/reference/template?t={int(os.path.getmtime(template_path))}"
    return ""


def invalidate_subtitle_derivatives(project: Project, db: Session) -> None:
    clear_remotion_props(project.run_dir)
    current_status = project.get_step_status()
    if current_status.get("8") == "completed":
        current_status["8"] = "pending_reconfirmation"
    project.set_step_status(current_status)
    db.commit()


def sync_project_background_color(project: Project) -> Optional[str]:
    """Apply the user-selected final video background to the reveal manifest."""
    manifest_path = os.path.join(project.run_dir, "reveal_manifest.json")
    if not os.path.exists(manifest_path):
        return None
    settings = read_project_visual_settings(project)
    background_hex = settings["video_background"]
    with reveal_lock_for(project):
        with open(manifest_path, "r", encoding="utf-8") as file:
            manifest = json.load(file)
        canvas = manifest.setdefault("canvas", {})
        canvas["background"] = background_hex
        manifest.pop("background_detection", None)
        manifest["background_settings"] = {
            "generation_background": IMAGE_GENERATION_BACKGROUND,
            "video_background": background_hex,
            "outer_background_removal": "outer_connected_near_white_only",
        }
        write_json_atomic(manifest_path, manifest)
    return background_hex


def invalidate_video_background_derivatives(project: Project, db: Session) -> None:
    clear_all_reveal_artifacts(project.run_dir, read_contract_slide_ids(project.run_dir))
    current_status = project.get_step_status()
    mark_selected_stale(current_status, (5, 8))
    project.current_step = 3
    project.set_step_status(current_status)
    db.commit()


def sync_narration_beats_to_contract(project: Project, slide_ids: Optional[List[str]] = None) -> bool:
    current_slide_ids = slide_ids if slide_ids is not None else read_contract_slide_ids(project.run_dir)
    if not current_slide_ids:
        return False

    beats_path = os.path.join(project.run_dir, "planning", "narration_beats.json")
    if not os.path.exists(beats_path):
        return False

    try:
        with open(beats_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as e:
        logger.warning(f"Failed to read narration beats for slide sync: {e}")
        return False

    slides = payload.get("slides", [])
    if not isinstance(slides, list):
        return False

    by_id = {
        str(slide.get("slide_id") or "").strip(): slide
        for slide in slides
        if isinstance(slide, dict) and str(slide.get("slide_id") or "").strip()
    }
    contract = read_json_file(os.path.join(project.run_dir, "planning", "visual_contract.json"), {})
    contract_by_id = {
        str(slide.get("slide_id") or "").strip(): slide
        for slide in contract.get("slides", [])
        if isinstance(slide, dict) and str(slide.get("slide_id") or "").strip()
    }
    synced_slides = []
    for slide_id in current_slide_ids:
        existing = by_id.get(slide_id)
        if existing is not None:
            synced_slides.append(existing)
            continue
        contract_slide = contract_by_id.get(slide_id, {})
        synced_slides.append({
            "slide_id": slide_id,
            "beats": copy.deepcopy(contract_slide.get("narration_beats", [])),
        })
    normalized_slides = []
    for slide in synced_slides:
        normalized = dict(slide)
        normalized["beats"] = dedupe_narration_beats(slide.get("beats"))
        normalized_slides.append(normalized)
    if normalized_slides == slides:
        return False

    payload["slides"] = normalized_slides
    write_json_atomic(beats_path, payload)
    logger.info(
        "Synced narration beats to visual contract: kept %s of %s slides",
        len(synced_slides),
        len(slides),
    )
    return True


TTS_MARKUP_RE = re.compile(r"<#\d+(?:\.\d{1,2})?#>|\([A-Za-z-]+\)")
MINIMAX_PAUSE_RE = re.compile(r"<#(\d+(?:\.\d{1,2})?)#>")
MINIMAX_EXPRESSION_RE = re.compile(r"\([A-Za-z-]+\)")
MINIMAX_ALLOWED_EXPRESSION_TAGS = {
    "(applause)",
    "(breath)",
    "(burps)",
    "(chuckle)",
    "(clear-throat)",
    "(coughs)",
    "(crying)",
    "(emm)",
    "(exhale)",
    "(gasps)",
    "(groans)",
    "(hissing)",
    "(humming)",
    "(inhale)",
    "(laughs)",
    "(lip-smacking)",
    "(pant)",
    "(sneezes)",
    "(sniffs)",
    "(snorts)",
    "(sighs)",
    "(whistles)",
}
SUBTITLE_MAX_CHARS = 26
SUBTITLE_HARD_SPLIT_MARKS = "。！？；.!?;"
SUBTITLE_SOFT_SPLIT_MARKS = "，：、,:"
SUBTITLE_SPLIT_MARKS = SUBTITLE_HARD_SPLIT_MARKS + SUBTITLE_SOFT_SPLIT_MARKS
SUBTITLE_EDGE_PUNCTUATION = "，。！？；：、,.!?;: \t\r\n"


def clean_tts_text(text: str) -> str:
    value = TTS_MARKUP_RE.sub(" ", str(text or ""))
    return re.sub(r"\s+", " ", value).strip()


def beat_tts_text(beat: Dict[str, Any]) -> str:
    return str(beat.get("tts_text") or beat.get("spoken_text") or beat.get("source_text") or "").strip()


def normalize_minimax_tts_markup(text: str, fallback: str = "") -> str:
    value = re.sub(r"\s+", " ", str(text or fallback or "")).strip()

    def normalize_pause(match: re.Match[str]) -> str:
        seconds = max(0.01, min(99.99, float(match.group(1))))
        formatted = f"{seconds:.2f}".rstrip("0").rstrip(".")
        return f"<#{formatted}#>"

    value = MINIMAX_PAUSE_RE.sub(normalize_pause, value)
    value = re.sub(
        r"<#[^>]*#>",
        lambda match: match.group(0) if MINIMAX_PAUSE_RE.fullmatch(match.group(0)) else " ",
        value,
    )

    def keep_expression(match: re.Match[str]) -> str:
        tag = match.group(0)
        return tag if tag in MINIMAX_ALLOWED_EXPRESSION_TAGS else " "

    value = MINIMAX_EXPRESSION_RE.sub(keep_expression, value)
    value = re.sub(
        r"(<#\d+(?:\.\d{1,2})?#>\s*){2,}",
        lambda m: (MINIMAX_PAUSE_RE.search(m.group(0)).group(0) + " ") if MINIMAX_PAUSE_RE.search(m.group(0)) else " ",
        value,
    )
    value = re.sub(r"^(?:\s*(?:<#\d+(?:\.\d{1,2})?#>|\([A-Za-z-]+\))\s*)+", "", value).strip()
    value = re.sub(r"(?:\s*(?:<#\d+(?:\.\d{1,2})?#>|\([A-Za-z-]+\))\s*)+$", "", value).strip()
    return re.sub(r"\s+", " ", value).strip()


def ensure_minimax_delivery_markup(text: str) -> str:
    value = normalize_minimax_tts_markup(text)
    if not value or MINIMAX_PAUSE_RE.search(value) or len(clean_tts_text(value)) < 12:
        return value

    punctuation_matches = [
        match
        for match in re.finditer(r"[，。！？；：、,.!?;:]", value)
        if match.end() < len(value)
    ]
    if punctuation_matches:
        midpoint = len(value) / 2
        match = min(punctuation_matches, key=lambda item: abs(item.end() - midpoint))
        insert_at = match.end()
    else:
        insert_at = max(1, min(len(value) - 1, len(value) // 2))

    pause = "<#0.35#>"
    annotated = f"{value[:insert_at].rstrip()}{pause}{value[insert_at:].lstrip()}"
    return normalize_minimax_tts_markup(annotated, value)


def split_subtitle_text(text: str, max_chars: int = SUBTITLE_MAX_CHARS) -> List[str]:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if not value:
        return []

    chunks: List[str] = []
    remaining = value
    while remaining:
        if len(remaining) <= max_chars:
            chunk = remaining
            remaining = ""
        else:
            window = remaining[: max_chars + 1]
            hard_cut = max((window.rfind(mark) for mark in SUBTITLE_HARD_SPLIT_MARKS), default=-1)
            soft_cut = max((window.rfind(mark) for mark in SUBTITLE_SOFT_SPLIT_MARKS), default=-1)
            cut_at = hard_cut if hard_cut >= max(8, max_chars // 2) else soft_cut
            if cut_at < max(8, max_chars // 2) or cut_at >= max_chars:
                cut_at = max_chars - 1
            chunk = remaining[: cut_at + 1]
            remaining = remaining[cut_at + 1 :].strip()
        chunk = chunk.strip(SUBTITLE_EDGE_PUNCTUATION)
        if chunk:
            chunks.append(chunk)
    return chunks


SUBTITLE_SPEECH_RE = re.compile(r"[\w\u4e00-\u9fff]")


def subtitle_text_weight(text: str) -> int:
    compact = re.sub(r"\s+", "", str(text or ""))
    return max(1, len(compact))


def subtitle_chunks_for_timing(text: str) -> List[str]:
    chunks: List[str] = []
    for chunk in split_subtitle_text(clean_tts_text(text)):
        chunk = chunk.strip()
        if not chunk:
            continue
        if not SUBTITLE_SPEECH_RE.search(chunk):
            if chunks:
                chunks[-1] = f"{chunks[-1]}{chunk}".strip()
            continue
        chunks.append(chunk)
    return chunks


def tts_text_parts_with_pauses(text: str) -> List[Dict[str, Any]]:
    value = str(text or "")
    parts: List[Dict[str, Any]] = []
    cursor = 0
    for match in MINIMAX_PAUSE_RE.finditer(value):
        before = clean_tts_text(value[cursor:match.start()])
        if before:
            parts.append({"type": "text", "text": before})
        seconds = max(0.0, float(match.group(1)))
        if seconds > 0:
            parts.append({"type": "pause", "duration": seconds})
        cursor = match.end()
    after = clean_tts_text(value[cursor:])
    if after:
        parts.append({"type": "text", "text": after})
    return parts


def prepare_narration_payload(project: Project, payload: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(payload or {})
    slides = payload.get("slides") if isinstance(payload.get("slides"), list) else []
    current_slide_ids = read_contract_slide_ids(project.run_dir)
    if current_slide_ids:
        by_id = {
            str(slide.get("slide_id") or "").strip(): slide
            for slide in slides
            if isinstance(slide, dict) and str(slide.get("slide_id") or "").strip()
        }
        slides = [by_id[slide_id] for slide_id in current_slide_ids if slide_id in by_id]

    for slide_data in slides:
        if not isinstance(slide_data, dict):
            continue
        slide_beats = slide_data.get("beats", [])
        if not isinstance(slide_beats, list):
            slide_beats = []
            slide_data["beats"] = slide_beats
        for idx, beat in enumerate(slide_beats, start=1):
            if not isinstance(beat, dict):
                continue
            beat.setdefault("id", f"{slide_data.get('slide_id', 'slide')}_beat_{idx:03d}")
            source = str(beat.get("source_text") or beat.get("spoken_text") or "").strip()
            spoken = str(beat.get("spoken_text") or source).strip()
            beat["source_text"] = source or spoken
            beat["spoken_text"] = spoken or source
            beat["tts_text"] = normalize_minimax_tts_markup(beat.get("tts_text"), beat["spoken_text"])
        slide_data["beats"] = dedupe_narration_beats(slide_beats)
    payload["slides"] = slides
    return payload


def persist_narration_beats(project: Project, payload: Dict[str, Any]) -> Dict[str, Any]:
    payload = prepare_narration_payload(project, payload)
    beats_path = os.path.join(project.run_dir, "planning", "narration_beats.json")
    os.makedirs(os.path.dirname(beats_path), exist_ok=True)
    with open(beats_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    narration_lines = []
    tts_text_lines = []

    for slide_data in payload.get("slides", []):
        if not isinstance(slide_data, dict):
            continue
        slide_id = str(slide_data.get("slide_id") or "").strip()
        if not slide_id:
            continue
        slide_dir = os.path.join(project.run_dir, "slides", slide_id)
        os.makedirs(slide_dir, exist_ok=True)
        slide_beats = slide_data.get("beats", []) if isinstance(slide_data.get("beats"), list) else []
        slide_narration = "\n".join(clean_tts_text(beat_tts_text(beat)) for beat in slide_beats)
        slide_tts_text = "\n".join(beat_tts_text(beat) for beat in slide_beats)

        with open(os.path.join(slide_dir, "narration.txt"), "w", encoding="utf-8") as f:
            f.write(slide_narration + "\n")
        with open(os.path.join(slide_dir, "tts_text.txt"), "w", encoding="utf-8") as f:
            f.write(slide_tts_text + "\n")
        with open(os.path.join(slide_dir, "narration_beats.json"), "w", encoding="utf-8") as f:
            json.dump({"slide_id": slide_id, "beats": slide_beats}, f, ensure_ascii=False, indent=2)

        narration_lines.append(f"=== {slide_id} ===")
        tts_text_lines.append(f"=== {slide_id} ===")
        for beat in slide_beats:
            if not isinstance(beat, dict):
                continue
            g_id = beat.get("group_id") or beat.get("id") or "sentence"
            text = clean_tts_text(beat_tts_text(beat))
            narration_lines.append(f"[{g_id}] {text}")
            tts_text_lines.append(beat_tts_text(beat))

    with open(os.path.join(project.run_dir, "planning", "narration.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(narration_lines) + "\n")
    with open(os.path.join(project.run_dir, "planning", "tts_text.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(tts_text_lines) + "\n")
    return payload


def rewrite_audio_timeline_by_beats(timeline_path: str, slide_id: str, beats: List[Dict[str, Any]]) -> None:
    if not os.path.exists(timeline_path):
        return
    with open(timeline_path, "r", encoding="utf-8") as f:
        timeline = json.load(f)
    previous_duration = float(timeline.get("audio_content_duration_sec") or timeline.get("duration_sec") or 0)
    voice_path = os.path.join(os.path.dirname(timeline_path), "voice.mp3")
    probed_duration = probe_media_duration_sec(voice_path, repo_root=REPO_ROOT)
    duration = float(probed_duration or previous_duration)
    if duration <= 0:
        return
    clean_beats: List[Dict[str, Any]] = []
    for idx, beat in enumerate(beats):
        raw_text = beat_tts_text(beat)
        if not clean_tts_text(raw_text):
            continue
        parts = tts_text_parts_with_pauses(raw_text)
        if not any(part.get("type") == "text" for part in parts):
            continue
        clean_beats.append({
            "id": str(beat.get("id") or f"{slide_id}_beat_{idx + 1:03d}"),
            "parts": parts,
        })
    if not clean_beats:
        return

    provider_segments = timeline.get("segments") if timeline.get("timing_source") == "provider_sentence_timestamps" else None
    if isinstance(provider_segments, list) and provider_segments:
        beat_signatures = [
            re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", clean_tts_text("".join(
                str(part.get("text") or "") for part in beat.get("parts", []) if part.get("type") == "text"
            )))
            for beat in clean_beats
        ]
        beat_part_counts: Dict[str, int] = {}
        active_beat_index = 0
        for segment in provider_segments:
            if not isinstance(segment, dict):
                continue
            segment_signature = re.sub(
                r"[^0-9A-Za-z\u4e00-\u9fff]+",
                "",
                clean_tts_text(str(segment.get("text") or "")),
            )
            if segment_signature:
                for beat_index in range(active_beat_index, len(beat_signatures)):
                    if segment_signature in beat_signatures[beat_index]:
                        active_beat_index = beat_index
                        break
            beat_id = clean_beats[active_beat_index]["id"]
            part_number = beat_part_counts.get(beat_id, 0) + 1
            beat_part_counts[beat_id] = part_number
            segment["beat_id"] = beat_id
            segment["id"] = beat_id if part_number == 1 else f"{beat_id}__part_{part_number:02d}"
            segment["timing_source"] = "provider_sentence_timestamps"
        timeline["segments"] = provider_segments
        timeline["audio_content_duration_sec"] = round(duration, 3)
        timeline["duration_sec"] = round(duration + float(timeline.get("audio_start_sec", 0.0) or 0.0), 3)
        timeline["duration_source"] = "local_audio_ffprobe" if probed_duration else timeline.get("duration_source")
        if probed_duration:
            timeline["probed_audio_duration_sec"] = round(probed_duration, 3)
        with open(timeline_path, "w", encoding="utf-8") as f:
            json.dump(timeline, f, ensure_ascii=False, indent=2)
        return

    total_pause = sum(
        float(part.get("duration", 0.0) or 0.0)
        for item in clean_beats
        for part in item["parts"]
        if part.get("type") == "pause"
    )
    pause_budget = min(total_pause, duration * 0.45)
    pause_scale = pause_budget / total_pause if total_pause > 0 else 0.0
    speech_duration = max(0.001, duration - pause_budget)
    total_weight = 0
    chunked_parts: List[Dict[str, Any]] = []
    for item in clean_beats:
        beat_parts: List[Dict[str, Any]] = []
        for part in item["parts"]:
            if part.get("type") == "pause":
                beat_parts.append(part)
                continue
            chunks = subtitle_chunks_for_timing(str(part.get("text") or ""))
            chunk_weights = [subtitle_text_weight(chunk) for chunk in chunks]
            total_weight += sum(chunk_weights)
            beat_parts.append({"type": "text", "chunks": chunks, "weights": chunk_weights})
        chunked_parts.append({"id": item["id"], "parts": beat_parts})
    if total_weight <= 0:
        return

    cursor = 0.0
    segments: List[Dict[str, Any]] = []
    for item in chunked_parts:
        chunk_index = 0
        for part in item["parts"]:
            if part.get("type") == "pause":
                pause_duration = float(part.get("duration", 0.0) or 0.0) * pause_scale
                if pause_duration > 0:
                    if segments:
                        segments[-1]["_end"] = segments[-1]["_end"] + pause_duration
                    cursor += pause_duration
                continue
            chunks = part.get("chunks", [])
            weights = part.get("weights", [])
            for chunk, weight in zip(chunks, weights):
                chunk_index += 1
                chunk_start = cursor
                chunk_end = cursor + speech_duration * float(weight) / float(total_weight)
                segment_id = item["id"] if chunk_index == 1 else f"{item['id']}__part_{chunk_index:02d}"
                segments.append({
                    "id": segment_id,
                    "beat_id": item["id"],
                    "_start": chunk_start,
                    "_end": chunk_end,
                    "text": chunk,
                    "timing_source": "beat_pause_aware_estimated_split",
                    "max_cjk_chars": SUBTITLE_MAX_CHARS,
                    "max_lines": 1,
                })
                cursor = chunk_end
    if not segments:
        return
    if cursor < duration:
        segments[-1]["_end"] = segments[-1]["_end"] + (duration - cursor)
    normalized_segments: List[Dict[str, Any]] = []
    previous_end = 0.0
    for segment in segments:
        start = max(previous_end, min(duration, float(segment.pop("_start"))))
        end = max(start, min(duration, float(segment.pop("_end"))))
        if end <= start and start < duration:
            end = min(duration, start + 0.05)
        if end <= start:
            continue
        segment["start"] = round(start, 3)
        segment["end"] = round(end, 3)
        normalized_segments.append(segment)
        previous_end = end
    if not normalized_segments:
        return
    timeline["segments"] = normalized_segments
    timeline["timing_source"] = "beat_pause_aware_estimated_split"
    timeline["explicit_pause_sec"] = round(pause_budget, 3)
    timeline["subtitle_display"] = {
        "max_lines": 1,
        "max_cjk_chars": SUBTITLE_MAX_CHARS,
    }
    timeline["audio_content_duration_sec"] = round(duration, 3)
    timeline["duration_sec"] = round(duration + float(timeline.get("audio_start_sec", 0.0) or 0.0), 3)
    if probed_duration:
        timeline["duration_source"] = "local_audio_ffprobe"
        timeline["probed_audio_duration_sec"] = round(probed_duration, 3)
        if previous_duration > 0 and abs(previous_duration - probed_duration) > 0.05:
            timeline["previous_timeline_content_duration_sec"] = round(previous_duration, 3)
    with open(timeline_path, "w", encoding="utf-8") as f:
        json.dump(timeline, f, ensure_ascii=False, indent=2)

# ==================== 项目管理接口 ====================

@app.post("/api/projects")
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)):
    project_id = str(uuid.uuid4())[:8] + "_" + datetime.now().strftime("%H%M%S")
    run_dir = str(validated_project_run_dir(RUNS_DIR, os.path.join(RUNS_DIR, project_id), project_id))
    
    # 初始化文件夹结构
    os.makedirs(os.path.join(run_dir, "inputs"), exist_ok=True)
    os.makedirs(os.path.join(run_dir, "planning"), exist_ok=True)
    os.makedirs(os.path.join(run_dir, "slides"), exist_ok=True)
    os.makedirs(os.path.join(run_dir, "review"), exist_ok=True)
    
    # 初始化默认步骤状态字典：1到8步均为 pending
    initial_step_status = {str(i): "pending" for i in range(1, 9)}
    
    db_project = Project(
        id=project_id,
        name=payload.name,
        description=payload.description,
        current_step=1,
        status="active",
        run_dir=run_dir
    )
    db_project.set_step_status(initial_step_status)
    db.add(db_project)
    db.commit()
    db.refresh(db_project)
    
    return {
        "success": True, 
        "project": {
            "id": db_project.id,
            "name": db_project.name,
            "description": db_project.description,
            "current_step": db_project.current_step,
            "step_status": db_project.get_step_status(),
            "audio_confirmed": False
        }
    }

@app.get("/api/projects")
def list_projects(db: Session = Depends(get_db)):
    projects = db.query(Project).order_by(Project.created_at.desc()).all()
    return [{
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "current_step": p.current_step,
        "status": p.status,
        "step_status": p.get_step_status(),
        "audio_confirmed": project_audio_confirmed(p),
        "created_at": p.created_at.isoformat()
    } for p in projects]

@app.get("/api/projects/{project_id}")
def get_project(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "current_step": project.current_step,
        "status": project.status,
        "step_status": project.get_step_status(),
        "audio_confirmed": project_audio_confirmed(project),
        "run_dir": project.run_dir
    }

@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    # Only delete a direct, ID-matching child of RUNS_DIR. Never trust a
    # database path for recursive deletion without this boundary check.
    run_dir = project_run_dir_or_500(project)
    if os.path.exists(run_dir):
        try:
            shutil.rmtree(run_dir)
        except Exception as e:
            logger.error(f"Failed to delete directory {run_dir}: {e}")
            raise HTTPException(status_code=500, detail="项目文件删除失败") from e
            
    db.delete(project)
    db.commit()
    return {"success": True, "message": "项目删除成功"}

# ==================== 设置管理接口 ====================

@app.get("/api/settings")
def get_settings():
    return mask_sensitive_settings(get_all_settings())

@app.put("/api/settings")
def update_system_settings(payload: SettingsUpdate):
    settings = dict(payload.settings or {})
    if mask_settings_secrets_enabled():
        current = get_all_settings()
        for key in SETTINGS_SECRET_KEYS:
            if settings.get(key) == MASKED_SETTINGS_VALUE:
                settings[key] = current.get(key, "")
    update_settings(settings)
    return {"success": True, "message": "设置更新成功"}

def read_text_file_if_exists(path: str) -> str:
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8-sig") as file:
        return file.read()


def file_to_config_reference(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {"exists": False, "data": "", "mime": "", "filename": os.path.basename(path)}
    with open(path, "rb") as file:
        return {
            "exists": True,
            "data": base64.b64encode(file.read()).decode("ascii"),
            "mime": "image/png",
            "filename": os.path.basename(path),
        }


def config_references_from_dir(reference_dir: str) -> Dict[str, Dict[str, Any]]:
    return {
        kind: file_to_config_reference(os.path.join(reference_dir, filename))
        for kind, filename in STYLE_REFERENCE_FILES.items()
    }


def safe_image_template_id(value: Any) -> Optional[str]:
    template_id = str(value or "").strip()
    return template_id if re.fullmatch(r"[0-9a-f]{12}", template_id) else None


def exported_image_style_templates() -> List[Dict[str, Any]]:
    templates: List[Dict[str, Any]] = []
    for item in read_image_style_template_index():
        if not isinstance(item, dict):
            continue
        template_id = safe_image_template_id(item.get("id"))
        if not template_id:
            continue
        template_dir = os.path.join(IMAGE_STYLE_TEMPLATES_DIR, template_id)
        templates.append(
            {
                "id": template_id,
                "name": str(item.get("name") or ""),
                "created_at": str(item.get("created_at") or ""),
                "updated_at": str(item.get("updated_at") or ""),
                "style_tokens_yaml": read_text_file_if_exists(os.path.join(template_dir, "style_tokens.yaml")),
                "references": config_references_from_dir(os.path.join(template_dir, "references")),
            }
        )
    return templates


def decode_config_reference_bytes(reference: Any) -> Optional[bytes]:
    if not isinstance(reference, dict) or not reference.get("exists"):
        return None
    data = str(reference.get("data") or "")
    if not data:
        return None
    try:
        decoded = base64.b64decode(data, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("配置中的参考图 Base64 数据无效") from exc
    image = open_validated_image(decoded)
    image.close()
    return decoded


def decode_config_reference(reference: Any, target_path: str) -> None:
    decoded = decode_config_reference_bytes(reference)
    if decoded is None:
        if not isinstance(reference, dict) or not reference.get("exists"):
            if os.path.exists(target_path):
                os.remove(target_path)
        return
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    image = open_validated_image(decoded).convert("RGB")
    image.save(target_path, "PNG")


def write_config_references(reference_bundle: Any, reference_dir: str) -> None:
    if not isinstance(reference_bundle, dict):
        return
    for kind, filename in STYLE_REFERENCE_FILES.items():
        if kind in reference_bundle:
            decode_config_reference(reference_bundle[kind], os.path.join(reference_dir, filename))


def normalize_imported_template_list(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: List[Dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict) or item.get("built_in"):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        result.append({key: value for key, value in item.items() if key != "built_in"})
    return result


def build_config_export_bundle(settings: Dict[str, Any], *, contains_secrets: bool) -> Dict[str, Any]:
    return {
        "app": "PPT Visualization Studio",
        "type": "ppt_studio_config_bundle",
        "version": 2,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "contains_secrets": contains_secrets,
        "warning": (
            "This file contains API keys and secrets. Keep it private."
            if contains_secrets
            else "Credential fields are masked. Existing saved credentials are preserved when this file is imported."
        ),
        "settings": settings,
        "storyboard_templates": read_json_file(STORYBOARD_TEMPLATES_PATH, []),
        "step2_prompt_templates": read_json_file(STEP2_PROMPT_TEMPLATES_PATH, []),
        "image_style": {
            "active_style_tokens_yaml": read_text_file_if_exists(STYLE_TOKENS_PATH),
            "active_references": config_references_from_dir(STYLE_REFERENCE_DIR),
            "templates": exported_image_style_templates(),
        },
    }


@app.get("/api/config/export")
def export_full_config():
    return build_config_export_bundle(mask_sensitive_settings(get_all_settings(), force=True), contains_secrets=False)


@app.post("/api/config/export-with-secrets")
def export_full_config_with_secrets(payload: Dict[str, Any]):
    if str(payload.get("confirmation") or "") != "EXPORT_SECRETS":
        raise HTTPException(status_code=400, detail="Explicit secret-export confirmation is required.")
    return build_config_export_bundle(get_all_settings(), contains_secrets=True)


async def read_limited_json_request(request: Request, max_bytes: int) -> Dict[str, Any]:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                raise HTTPException(status_code=413, detail=f"配置文件超过 {max_bytes // (1024 * 1024)} MB 限制")
        except ValueError:
            raise HTTPException(status_code=400, detail="Content-Length 格式不正确")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > max_bytes:
            raise HTTPException(status_code=413, detail=f"配置文件超过 {max_bytes // (1024 * 1024)} MB 限制")
    try:
        payload = json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="配置文件不是有效 JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="配置文件格式不正确")
    return payload


def validate_config_references(payload: Dict[str, Any]) -> None:
    image_style = payload.get("image_style") if isinstance(payload.get("image_style"), dict) else {}
    bundles = [image_style.get("active_references")]
    for item in image_style.get("templates") or []:
        if isinstance(item, dict):
            bundles.append(item.get("references"))
    for bundle in bundles:
        if not isinstance(bundle, dict):
            continue
        for reference in bundle.values():
            decode_config_reference_bytes(reference)


@app.post("/api/config/import")
async def import_full_config(request: Request):
    payload = await read_limited_json_request(request, MAX_CONFIG_IMPORT_BYTES)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="配置文件格式不正确")
    try:
        validate_config_references(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    settings = payload.get("settings")
    if isinstance(settings, dict):
        imported_settings = {str(key): str(value) for key, value in settings.items()}
        current_settings = get_all_settings()
        for key in SETTINGS_SECRET_KEYS:
            if imported_settings.get(key) == MASKED_SETTINGS_VALUE:
                imported_settings[key] = current_settings.get(key, "")
        update_settings(imported_settings)

    storyboard_templates = payload.get("storyboard_templates")
    if isinstance(storyboard_templates, list):
        write_json_atomic(STORYBOARD_TEMPLATES_PATH, normalize_imported_template_list(storyboard_templates))

    step2_prompt_templates = payload.get("step2_prompt_templates")
    if isinstance(step2_prompt_templates, list):
        write_json_atomic(STEP2_PROMPT_TEMPLATES_PATH, normalize_imported_template_list(step2_prompt_templates))

    image_style = payload.get("image_style") if isinstance(payload.get("image_style"), dict) else {}
    ensure_active_image_style_storage()
    active_style = str(image_style.get("active_style_tokens_yaml") or "").strip()
    if active_style:
        with open(STYLE_TOKENS_PATH, "w", encoding="utf-8", newline="\n") as file:
            file.write(active_style.rstrip() + "\n")
    write_config_references(image_style.get("active_references"), STYLE_REFERENCE_DIR)

    imported_image_templates = []
    has_image_template_payload = isinstance(image_style.get("templates"), list)
    for item in image_style.get("templates") or []:
        if not isinstance(item, dict):
            continue
        template_id = safe_image_template_id(item.get("id")) or uuid.uuid4().hex[:12]
        name = str(item.get("name") or "").strip()
        style_text = str(item.get("style_tokens_yaml") or "").strip()
        if not name or not style_text:
            continue
        template_dir = os.path.abspath(os.path.join(IMAGE_STYLE_TEMPLATES_DIR, template_id))
        base_dir = os.path.abspath(IMAGE_STYLE_TEMPLATES_DIR)
        if os.path.commonpath([base_dir, template_dir]) != base_dir:
            continue
        os.makedirs(os.path.join(template_dir, "references"), exist_ok=True)
        with open(os.path.join(template_dir, "style_tokens.yaml"), "w", encoding="utf-8", newline="\n") as file:
            file.write(style_text.rstrip() + "\n")
        write_config_references(item.get("references"), os.path.join(template_dir, "references"))
        imported_image_templates.append(
            {
                "id": template_id,
                "name": name[:60],
                "created_at": str(item.get("created_at") or template_timestamp()),
                "updated_at": str(item.get("updated_at") or template_timestamp()),
            }
        )
    if has_image_template_payload:
        write_json_atomic(IMAGE_STYLE_TEMPLATES_INDEX, imported_image_templates)
    return {"success": True, "message": "配置已导入"}


@app.post("/api/settings/test-llm")
def test_llm_connection(payload: TestLlmPayload):
    try:
        client = get_openai_client(api_key=payload.api_key, base_url=payload.base_url)
        response = client.chat.completions.create(
            model=payload.model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=5,
            timeout=10
        )
        content = response.choices[0].message.content
        return {"success": True, "message": f"连接成功！模型响应: '{content.strip()}'"}
    except Exception as e:
        return {"success": False, "message": f"连接失败: {str(e)}"}

@app.post("/api/settings/test-image")
def test_image_connection(payload: TestImagePayload):
    try:
        client = get_openai_client(api_key=payload.api_key, base_url=payload.base_url)
        response = generate_image_response(
            client=client,
            model=payload.model,
            prompt="a single dot",
            size=payload.size or "1024x1024",
            base_url=payload.base_url,
            timeout=15,
        )
        if response_has_image_data(response):
            return {"success": True, "message": "连接成功！生图接口响应正常。"}
        return {"success": False, "message": "未返回有效图片数据。"}
    except Exception as e:
        return {"success": False, "message": f"连接失败: {str(e)}"}

@app.post("/api/settings/test-tts")
def test_tts_connection(payload: TestTtsPayload):
    provider = normalize_tts_provider(payload.provider)
    defaults = tts_provider_defaults(provider)
    endpoint = first_non_empty(payload.endpoint, get_setting("tts_endpoint"), defaults.get("endpoint"))
    api_key = configured_tts_api_key(provider, payload.api_key)
    secret_key = configured_tts_secret_key(provider, payload.secret_key)
    model = first_non_empty(payload.model, get_setting("tts_model"), defaults.get("model"))
    voice_id = first_non_empty(payload.voice_id, get_setting("tts_voice_id"), defaults.get("voice_id"))
    clone_voice_id = first_non_empty(payload.clone_voice_id, get_setting("tts_clone_voice_id"))
    region = first_non_empty(payload.region, get_setting("tts_region"), defaults.get("region"))
    provider_extra = first_non_empty(payload.provider_extra, get_setting("tts_provider_extra"))

    if provider not in TTS_PROVIDER_DEFAULTS:
        return {"success": False, "message": f"不支持的 TTS Provider: {payload.provider}"}
    if not api_key:
        return {"success": False, "message": f"缺少 {provider} API Key / SecretId。"}
    if provider == "tencent_tts" and not secret_key:
        return {"success": False, "message": "腾讯云 TTS 还需要 SecretKey。"}
    if not model or not voice_id:
        return {"success": False, "message": "请填写语音模型和音色 ID。"}

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            text_file = os.path.join(temp_dir, "tts_test.txt")
            out_audio = os.path.join(temp_dir, "voice.mp3")
            out_meta = os.path.join(temp_dir, "tts_metadata.json")
            out_srt = os.path.join(temp_dir, "tts_narration.srt")
            out_timeline = os.path.join(temp_dir, "audio_timeline.json")
            with open(text_file, "w", encoding="utf-8") as f:
                f.write("测试语音。\n")
            cmd = provider_tts_command(
                provider=provider,
                text_file=text_file,
                out_audio=out_audio,
                out_meta=out_meta,
                out_srt=out_srt,
                out_timeline=out_timeline,
                slide_id="tts_test",
                endpoint=endpoint,
                region=region,
                model=model,
                voice_id=voice_id,
                clone_voice_id=clone_voice_id,
                provider_extra=provider_extra,
                speed="1.0",
                volume="1.0",
                pitch="0" if provider == "minimax" else "1.0",
            )
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=90,
                env=provider_tts_environment(api_key, secret_key),
            )
            if res.returncode != 0:
                return {"success": False, "message": f"TTS 测试失败: {(res.stderr or res.stdout)[:600]}"}
            if not os.path.exists(out_audio) or os.path.getsize(out_audio) <= 0:
                return {"success": False, "message": "TTS 测试未生成有效音频文件。"}
        return {"success": True, "message": f"连接成功，{provider} TTS 可以正常合成音频。"}
    except subprocess.TimeoutExpired:
        return {"success": False, "message": "TTS 测试超时，请检查 endpoint、鉴权和网络。"}
    except Exception as e:
        return {"success": False, "message": f"连接失败: {str(e)}"}

# ==================== 流水线状态管理 ====================

def audio_confirmation_path(project: Project) -> str:
    return str(tts_confirmation_path(project.run_dir))


def project_audio_confirmed(project: Project) -> bool:
    return is_audio_confirmed(project.run_dir, read_contract_slide_ids(project.run_dir))


def clear_audio_confirmation(project: Project):
    clear_audio_confirmation_artifact(project.run_dir)


def _safe_process_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def nonempty_file(path: str) -> bool:
    return tts_nonempty_file(path)


def slide_tts_artifact_paths(project: Project, slide_id: str) -> Dict[str, str]:
    return {key: str(path) for key, path in tts_artifact_paths(project.run_dir, slide_id).items()}


def read_timeline_duration_sec(timeline_path: str) -> Optional[float]:
    return timeline_duration_sec(timeline_path)


def slide_tts_artifact_status(project: Project, slide_id: str) -> Dict[str, Any]:
    return tts_artifact_status(project.run_dir, slide_id)


def remove_tts_artifacts(paths: Dict[str, str]) -> None:
    remove_tts_outputs(paths)


def ensure_slide_tts_text_file(project: Project, slide_id: str, contract: Dict[str, Any]) -> str:
    paths = slide_tts_artifact_paths(project, slide_id)
    text_file = paths["text"]
    if os.path.exists(text_file):
        return text_file

    logger.warning("tts_text.txt not found for slide %s, trying to generate it from contract", slide_id)
    slide_narration = ""
    for slide in contract.get("slides", []) or []:
        if not isinstance(slide, dict) or slide.get("slide_id") != slide_id:
            continue
        beats = slide.get("narration_beats", []) if isinstance(slide.get("narration_beats"), list) else []
        slide_narration = "\n".join(
            beat_tts_text(beat)
            for beat in beats
            if isinstance(beat, dict) and clean_tts_text(beat_tts_text(beat))
        )
        break
    os.makedirs(os.path.dirname(text_file), exist_ok=True)
    with open(text_file, "w", encoding="utf-8") as f:
        f.write(slide_narration + "\n")
    return text_file


def mark_step_retry_needed(project: Project, target_step: int, db: Session) -> None:
    current_status = mark_retry_needed(project.get_step_status(), target_step)
    project.current_step = target_step
    project.set_step_status(current_status)
    db.commit()


def run_tts_command_with_retries(
    project: Project,
    slide_id: str,
    tts_args: List[str],
    tts_env: Dict[str, str],
) -> Dict[str, Any]:
    last_result: Dict[str, Any] = {
        "ok": False,
        "returncode": None,
        "stdout": "",
        "stderr": "",
        "attempts": 0,
    }
    for attempt in range(1, STEP7_TTS_RETRY_ATTEMPTS + 1):
        last_result["attempts"] = attempt
        try:
            tts_res = subprocess.run(
                tts_args,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=STEP7_TTS_PROCESS_TIMEOUT_SEC,
                env=tts_env,
            )
            last_result.update(
                {
                    "returncode": tts_res.returncode,
                    "stdout": tts_res.stdout.strip(),
                    "stderr": tts_res.stderr.strip(),
                }
            )
        except subprocess.TimeoutExpired as exc:
            last_result.update(
                {
                    "returncode": 124,
                    "stdout": _safe_process_text(exc.stdout).strip(),
                    "stderr": f"TTS process timed out after {STEP7_TTS_PROCESS_TIMEOUT_SEC}s. "
                    + _safe_process_text(exc.stderr).strip(),
                }
            )

        if last_result["returncode"] == 0:
            last_result["ok"] = True
            return last_result

        write_project_log(
            project,
            "step7_slide_tts_attempt_failed",
            slide_id=slide_id,
            attempt=attempt,
            max_attempts=STEP7_TTS_RETRY_ATTEMPTS,
            returncode=last_result["returncode"],
            stdout=last_result["stdout"],
            stderr=last_result["stderr"],
        )
        if attempt < STEP7_TTS_RETRY_ATTEMPTS:
            delay = STEP7_TTS_RETRY_BASE_DELAY_SEC * attempt
            logger.warning(
                "TTS failed for %s on attempt %s/%s; retrying in %ss",
                slide_id,
                attempt,
                STEP7_TTS_RETRY_ATTEMPTS,
                delay,
            )
            time.sleep(delay)
    return last_result


def mark_step_in_progress(project: Project, target_step: int, db: Session):
    current_status = begin_step(project.get_step_status(), target_step)
    project.current_step = target_step
    project.set_step_status(current_status)
    db.commit()


# 回退某一步后，后续步骤状态被标记为 pending_reconfirmation
def handle_step_navigation(project: Project, target_step: int, db: Session):
    current_status = complete_step(project.get_step_status(), target_step)
    if target_step < 7:
        clear_audio_confirmation(project)
    if target_step < 8:
        clear_remotion_props(project.run_dir)
    project.current_step = current_step_after_completion(project.current_step, target_step)
    project.set_step_status(current_status)
    db.commit()


def invalidate_after_upstream_edit(project: Project, source_step: int, db: Session) -> None:
    """Keep edited source data while making every dependent stage explicitly stale."""
    current_status = complete_step(project.get_step_status(), source_step)
    clear_audio_confirmation(project)
    clear_remotion_props(project.run_dir)
    project.current_step = source_step
    project.set_step_status(current_status)
    db.commit()


def clear_slide_visual_derivatives(project: Project, slide_id: str) -> None:
    """Remove masks and rendered assets that belong to an older slide image."""
    manifest_path = os.path.join(project.run_dir, "reveal_manifest.json")
    with reveal_lock_for(project):
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                changed = False
                for slide in manifest.get("slides", []) or []:
                    if not isinstance(slide, dict) or str(slide.get("slide_id") or "").strip() != slide_id:
                        continue
                    for field in ("groups", "semantic_blocks"):
                        if slide.get(field):
                            changed = True
                        slide[field] = []
                    slide["status"] = "pending"
                    changed = True
                if changed:
                    write_json_atomic(manifest_path, manifest)
            except Exception as exc:
                logger.warning("Failed to clear Mask data for %s: %s", slide_id, exc)

        clear_slide_reveal_artifacts(project.run_dir, slide_id)


def validate_current_reveal_assets(project: Project) -> None:
    with reveal_lock_for(project):
        validator = os.path.join(REPO_ROOT, "scripts", "validate_reveal_scene.py")
        command = [
            sys.executable,
            validator,
            "--run-dir",
            project.run_dir,
            "--repo-root",
            REPO_ROOT,
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(status_code=504, detail="Mask 产物校验超时，请重试") from exc
        if result.returncode != 0:
            logger.error("Reveal asset validation failed: %s", result.stderr)
            raise HTTPException(
                status_code=500,
                detail=f"Mask 产物版本或内容校验失败: {result.stderr}",
            )


def build_current_reveal_assets(project: Project) -> None:
    with reveal_lock_for(project):
        manifest_path = os.path.join(project.run_dir, "reveal_manifest.json")
        if not os.path.exists(manifest_path):
            raise HTTPException(status_code=400, detail="Mask 配置文件不存在")
        sync_project_background_color(project)
        build_scene_script = os.path.join(REPO_ROOT, "scripts", "build_reveal_scene.py")
        command = [
            sys.executable,
            build_scene_script,
            "--manifest",
            manifest_path,
            "--repo-root",
            REPO_ROOT,
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=STEP5_REVEAL_BUILD_TIMEOUT_SEC,
            )
        except subprocess.TimeoutExpired as exc:
            write_project_log(
                project,
                "step5_reveal_build_timeout",
                timeout_sec=STEP5_REVEAL_BUILD_TIMEOUT_SEC,
            )
            raise HTTPException(status_code=504, detail="构建 Mask 切层超时，已停止本次任务，请重试") from exc
        if result.returncode != 0:
            logger.error("Build reveal assets failed: %s", result.stderr)
            raise HTTPException(
                status_code=500,
                detail=f"构建精确 Mask 素材失败: {result.stderr}",
            )
        from storyboard_background_render import apply_storyboard_background

        apply_storyboard_background(Path(manifest_path).resolve())
        validate_current_reveal_assets(project)


def mark_slide_image_changed(project: Project, slide_id: str, db: Session) -> None:
    clear_slide_visual_derivatives(project, slide_id)
    clear_audio_confirmation(project)
    current_status = project.get_step_status()
    current_status["3"] = "completed" if all_current_slide_images_exist(project) else "in_progress"
    mark_downstream_pending(current_status, from_step=4)
    project.current_step = 3
    project.set_step_status(current_status)
    db.commit()

# ==================== 步骤 1: 导入文章 ====================

ARTICLE_GENERATION_SYSTEM_CONTENT_KEY = "article_generation_system_content"
DEFAULT_ARTICLE_GENERATION_SYSTEM_CONTENT = """你是一名中文长文写作编辑。

## 目的
根据用户给出的话题，生成结构完整、事实边界清楚、可继续转换为演示文稿的中文长文。

## 输入
用户提供的话题、写作方向或必要的背景材料。输入是事实与范围的主要依据；信息不足时使用审慎表述，不得虚构具体数据、引文或来源。

## 输出
只输出一篇 Markdown 正文，不要代码围栏、写作过程、解释或前后缀文字。

要求：
1. 直接输出 Markdown 正文，不要解释写作过程，不要使用代码围栏。
2. 使用清晰的一级、二级标题和必要的列表；每一节只表达一个核心观点。
3. 先建立背景和问题，再展开关键概念、机制、案例与结论。
4. 不编造无法确认的数据、引文或来源；不确定的信息要明确标注。
5. 文章需要为后续分镜规划提供足够具体的内容，但避免空泛重复。"""


@app.get("/api/settings/article-generation")
def get_article_generation_settings():
    return {
        "success": True,
        "system_content": get_setting(
            ARTICLE_GENERATION_SYSTEM_CONTENT_KEY,
            DEFAULT_ARTICLE_GENERATION_SYSTEM_CONTENT,
        ) or DEFAULT_ARTICLE_GENERATION_SYSTEM_CONTENT,
    }


@app.put("/api/settings/article-generation")
def update_article_generation_settings(payload: Dict[str, Any]):
    system_content = str(payload.get("system_content") or "").strip()
    if not system_content:
        raise HTTPException(status_code=400, detail="文章生成 System Content 不能为空")
    if len(system_content) > 20000:
        raise HTTPException(status_code=400, detail="文章生成 System Content 不能超过 20000 个字符")
    update_settings({ARTICLE_GENERATION_SYSTEM_CONTENT_KEY: system_content})
    return {"success": True, "system_content": system_content}


@app.post("/api/projects/{project_id}/steps/1/generate-article")
def generate_article_from_topic(
    project_id: str,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    topic = str(payload.get("topic") or "").strip()
    if not topic:
        raise HTTPException(status_code=400, detail="请输入文章话题")
    if len(topic) > 500:
        raise HTTPException(status_code=400, detail="文章话题不能超过 500 个字符")

    api_key = get_setting("llm_api_key")
    if not api_key:
        raise HTTPException(status_code=400, detail="未配置大模型 API 密钥，请先在系统设置中配置")
    model = get_setting("llm_model")
    base_url = get_setting("llm_base_url")
    system_content = get_setting(
        ARTICLE_GENERATION_SYSTEM_CONTENT_KEY,
        DEFAULT_ARTICLE_GENERATION_SYSTEM_CONTENT,
    ) or DEFAULT_ARTICLE_GENERATION_SYSTEM_CONTENT
    client = get_openai_client(
        api_key=api_key,
        base_url=base_url,
        timeout=STEP2_LLM_TIMEOUT_SEC,
        max_retries=0,
    )
    try:
        response = client.chat.completions.create(
            model=model,
            temperature=min(float(get_setting("llm_temperature", "0.7")), 0.7),
            max_tokens=parse_int_setting(get_setting("llm_max_tokens", "50000"), 50000, 1024, 64000),
            timeout=STEP2_LLM_TIMEOUT_SEC,
            messages=[
                {"role": "system", "content": system_content},
                {
                    "role": "user",
                    "content": f"项目名称：{(project.name or '').strip() or '未命名项目'}\n文章话题：{topic}\n\n请生成文章。",
                },
            ],
        )
    except Exception as exc:
        if is_timeout_exception(exc):
            raise HTTPException(status_code=504, detail="文章生成超时，请稍后重试") from exc
        raise HTTPException(status_code=502, detail=f"文章生成失败：{exc}") from exc
    content = str(response.choices[0].message.content or "").strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:markdown|md)?\s*|\s*```$", "", content, flags=re.I | re.S).strip()
    if not content:
        raise HTTPException(status_code=502, detail="大模型没有返回文章内容")
    write_project_log(project, "step1_article_generated", topic=topic, model=model, character_count=len(content))
    return {"success": True, "topic": topic, "content": content}

@app.post("/api/projects/{project_id}/steps/1/import")
def import_article(project_id: str, content: Optional[str] = Form(None), db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    if not content or not content.strip():
        raise HTTPException(status_code=400, detail="请输入有效的文章内容")

    article_path = os.path.join(project.run_dir, "inputs", "article.md")
    with open(article_path, "w", encoding="utf-8") as f:
        f.write(content)

    project_title = (project.name or "").strip() or "未命名项目"
    brief = {
        "title": project_title,
        "content": content,
        "summary": build_article_summary(content),
    }

    brief_path = os.path.join(project.run_dir, "planning", "article_brief.json")
    with open(brief_path, "w", encoding="utf-8") as f:
        json.dump(brief, f, ensure_ascii=False, indent=2)

    invalidate_after_upstream_edit(project, 1, db)
    return {"success": True, "brief": brief}


@app.get("/api/projects/{project_id}/steps/1/result")
def get_step1_result(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    brief_path = os.path.join(project.run_dir, "planning", "article_brief.json")
    if not os.path.exists(brief_path):
        return {"success": False, "message": "尚未导入文章"}
        
    with open(brief_path, "r", encoding="utf-8") as f:
        brief = json.load(f)
    brief["title"] = (project.name or "").strip() or brief.get("title") or "未命名项目"
    return {"success": True, "brief": brief}

@app.put("/api/projects/{project_id}/steps/1/result")
def update_step1_result(project_id: str, payload: Dict[str, Any], db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    brief_path = os.path.join(project.run_dir, "planning", "article_brief.json")
    payload["title"] = (project.name or "").strip() or payload.get("title") or "未命名项目"
    payload["summary"] = payload.get("summary") or build_article_summary(str(payload.get("content") or ""))
    existing_brief = read_json_file(brief_path, {})
    brief_changed = json.dumps(existing_brief, ensure_ascii=False, sort_keys=True) != json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
    )
    if brief_changed:
        with open(brief_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        
    # 同步回写 article.md
    article_changed = False
    if "content" in payload:
        article_path = os.path.join(project.run_dir, "inputs", "article.md")
        existing_article = read_text_file_if_exists(article_path)
        article_changed = existing_article != str(payload["content"])
        if article_changed:
            with open(article_path, "w", encoding="utf-8") as f:
                f.write(payload["content"])

    if brief_changed or article_changed:
        invalidate_after_upstream_edit(project, 1, db)
    return {"success": True, "brief": payload}

# ==================== 步骤 2: 智能分镜规划 ====================

def storyboard_rules_path(project: Project) -> str:
    return os.path.join(project.run_dir, "planning", "storyboard_rules.txt")


def storyboard_profile_path(project: Project) -> str:
    return os.path.join(project.run_dir, "planning", "pipeline_profile.yaml")


def visual_contract_schema_text() -> str:
    schema_path = os.path.join(REPO_ROOT, "schemas", "visual_contract.schema.json")
    if not os.path.exists(schema_path):
        return ""
    with open(schema_path, "r", encoding="utf-8") as f:
        return f.read()


def default_storyboard_profile_text() -> str:
    profile_path = os.path.join(REPO_ROOT, "config", "pipeline_profiles.yaml")
    with open(profile_path, "r", encoding="utf-8-sig") as f:
        return f.read()


def sanitize_storyboard_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = copy.deepcopy(profile)
    storyboard = sanitized.get("storyboard")
    if not isinstance(storyboard, dict):
        return sanitized
    default_storyboard = read_pipeline_profile().get("storyboard", {})
    default_roles = default_storyboard.get("roles", {}) if isinstance(default_storyboard, dict) else {}
    roles = storyboard.get("roles")
    if isinstance(roles, dict):
        # Page subtitles are no longer part of the production contract. Drop
        # legacy editable role definitions instead of letting an old template
        # reintroduce subtitle groups into Step 2.
        roles.pop("subtitle", None)
        for role, config in roles.items():
            if not isinstance(config, dict):
                continue
            config.pop("required", None)
            config.pop("speak_policy", None)
            description = str(config.get("description") or "")
            if any(marker in description for marker in ("只展示不朗读", "不绑定旁白", "可选副标题", "可选总结区")):
                default_config = default_roles.get(role, {}) if isinstance(default_roles, dict) else {}
                fallback_descriptions = {
                    "decoration": "装饰元素，只在确实帮助理解画面时使用。",
                }
                config["description"] = str(default_config.get("description") or fallback_descriptions.get(role) or description)

    structure_rules = storyboard.get("structure_rules")
    if isinstance(structure_rules, list):
        legacy_markers = (
            "speak_policy",
            "display_only",
            "可讲解的 visual_group",
            "旁白讲解",
            "必选结构",
            "可选结构",
        )
        retained_rules = [
            rule for rule in structure_rules
            if not any(marker in str(rule) for marker in legacy_markers)
        ]
        default_rules = default_storyboard.get("structure_rules", []) if isinstance(default_storyboard, dict) else []
        for rule in default_rules if isinstance(default_rules, list) else []:
            if rule not in retained_rules:
                retained_rules.append(rule)
        storyboard["structure_rules"] = retained_rules
    return sanitized


def parse_storyboard_profile_text(profile_text: str) -> Dict[str, Any]:
    try:
        profile = yaml.safe_load(profile_text) or {}
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=400, detail=f"分镜结构 YAML 格式错误: {exc}") from exc
    if not isinstance(profile, dict):
        raise HTTPException(status_code=400, detail="分镜结构配置必须是 YAML 对象")
    storyboard = profile.get("storyboard")
    if not isinstance(storyboard, dict):
        raise HTTPException(status_code=400, detail="分镜结构配置缺少 storyboard 对象")
    roles = storyboard.get("roles")
    if not isinstance(roles, dict) or not roles:
        raise HTTPException(status_code=400, detail="分镜结构配置至少需要一个 storyboard.roles 角色")
    return sanitize_storyboard_profile(profile)


def storyboard_profile_editor_data(profile: Dict[str, Any]) -> Dict[str, Any]:
    profile = sanitize_storyboard_profile(profile)
    storyboard = profile.get("storyboard") if isinstance(profile.get("storyboard"), dict) else {}
    roles = storyboard.get("roles") if isinstance(storyboard.get("roles"), dict) else {}
    return {
        "slide_count": copy.deepcopy(storyboard.get("slide_count") or {}),
        "visual_group_count": copy.deepcopy(storyboard.get("visual_group_count") or {}),
        "roles": {
            str(role): {
                "label": str(config.get("label") or role),
                "description": str(config.get("description") or ""),
                "enabled": config.get("enabled") is not False,
            }
            for role, config in roles.items()
            if isinstance(config, dict)
        },
        "protected_fields": [
            "slide_id",
            "visual_groups",
            "narration_beats",
            "visual_groups[].id",
            "visual_groups[].content_unit_id",
            "narration_beats[].group_id",
            "narration_beats[].content_unit_id",
        ],
    }


def apply_storyboard_profile_patch(
    profile: Dict[str, Any],
    patch: Any,
) -> Dict[str, Any]:
    if not isinstance(patch, dict):
        return sanitize_storyboard_profile(profile)
    merged = copy.deepcopy(profile)
    storyboard = merged.setdefault("storyboard", {})
    if not isinstance(storyboard, dict):
        raise HTTPException(status_code=400, detail="storyboard 必须是 YAML 对象")

    for field in ("slide_count", "visual_group_count"):
        value = patch.get(field)
        if value is None:
            continue
        if not isinstance(value, dict):
            raise HTTPException(status_code=400, detail=f"{field} 必须是对象")
        existing = storyboard.get(field)
        if not isinstance(existing, dict):
            existing = {}
        for size_key in ("short_article", "medium_article", "long_article"):
            if size_key in value:
                text = str(value.get(size_key) or "").strip()
                if not text:
                    raise HTTPException(status_code=400, detail=f"{field}.{size_key} 不能为空")
                existing[size_key] = text
        storyboard[field] = existing

    role_patch = patch.get("roles")
    if role_patch is not None:
        if not isinstance(role_patch, dict):
            raise HTTPException(status_code=400, detail="roles 必须是对象")
        current_roles = storyboard.get("roles")
        if not isinstance(current_roles, dict):
            current_roles = {}
        updated_roles: Dict[str, Any] = {}
        for role, current_config in current_roles.items():
            if not isinstance(current_config, dict):
                continue
            next_config = copy.deepcopy(current_config)
            next_config.pop("required", None)
            next_config.pop("speak_policy", None)
            next_patch = role_patch.get(role)
            if not isinstance(next_patch, dict):
                updated_roles[role] = next_config
                continue
            next_config["enabled"] = next_patch.get("enabled") is not False
            updated_roles[role] = next_config
        if not any(config.get("enabled") is not False for config in updated_roles.values()):
            raise HTTPException(status_code=400, detail="至少需要启用一个分镜结构类型")
        storyboard["roles"] = updated_roles
    return parse_storyboard_profile_text(
        yaml.safe_dump(merged, allow_unicode=True, sort_keys=False, width=1000)
    )


def read_project_pipeline_profile(project: Project) -> Dict[str, Any]:
    path = storyboard_profile_path(project)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8-sig") as f:
            return parse_storyboard_profile_text(f.read())
    return read_pipeline_profile()


def default_storyboard_rules() -> str:
    default_path = os.path.join(REPO_ROOT, "templates", "prompts", "storyboard_rules.zh.md")
    if os.path.exists(default_path):
        with open(default_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    return "旁白自然口语化；每个旁白语段只绑定一个清晰的视觉分组；画面先于对应语音约 1 秒出现。"


def handdrawn_storyboard_rules() -> str:
    if os.path.exists(HANDDRAWN_STORYBOARD_RULES_PATH):
        with open(HANDDRAWN_STORYBOARD_RULES_PATH, "r", encoding="utf-8") as f:
            return f.read().strip()
    return default_storyboard_rules()


def step2_prompts_path(project: Project) -> str:
    return os.path.join(project.run_dir, "planning", STEP2_PROMPTS_FILE)


def step2_script_plan_path(project: Project) -> str:
    return os.path.join(project.run_dir, "planning", STEP2_SCRIPT_PLAN_FILE)


def step2_visual_plan_path(project: Project) -> str:
    return os.path.join(project.run_dir, "planning", STEP2_VISUAL_PLAN_FILE)


def read_prompt_template(path: str) -> str:
    with open(path, "r", encoding="utf-8-sig") as f:
        return f.read().strip()


def default_step2_prompts() -> Dict[str, str]:
    return {
        key: read_prompt_template(path)
        for key, path in STEP2_PROMPT_TEMPLATE_FILES.items()
    }


def read_step2_prompts(project: Project) -> Dict[str, str]:
    prompts = default_step2_prompts()
    stored = read_json_file(step2_prompts_path(project), {})
    if isinstance(stored, dict):
        for key in prompts:
            value = str(stored.get(key) or "").strip()
            if value:
                prompts[key] = value
    return prompts


def normalize_step2_prompt_type(value: Any) -> str:
    prompt_type = str(value or "script").strip().lower()
    if prompt_type not in {"script", "visual"}:
        raise HTTPException(status_code=400, detail="Prompt 模板类型必须是 script 或 visual")
    return prompt_type


def step2_prompt_keys(prompt_type: str) -> tuple[str, str]:
    return ("visual_system", "visual_output_example") if prompt_type == "visual" else ("script_system", "script_output_example")


def step2_prompt_template_payload(
    template_id: str,
    name: str,
    prompt_type: str,
    prompts: Dict[str, str],
    built_in: bool = False,
    updated_at: str = "",
) -> Dict[str, Any]:
    first_key, second_key = step2_prompt_keys(prompt_type)
    return {
        "id": template_id,
        "name": name,
        "prompt_type": prompt_type,
        "built_in": built_in,
        "updated_at": updated_at,
        "prompts": {
            first_key: str(prompts.get(first_key) or ""),
            second_key: str(prompts.get(second_key) or ""),
        },
    }


def built_in_step2_prompt_templates() -> List[Dict[str, Any]]:
    defaults = default_step2_prompts()
    return [
        step2_prompt_template_payload(
            "builtin_article_to_slide",
            "原始模板 · 文章→slides",
            "script",
            defaults,
            built_in=True,
        ),
        step2_prompt_template_payload(
            "builtin_slide_to_visualization",
            "原始模板 · slides→可视化",
            "visual",
            defaults,
            built_in=True,
        ),
    ]


def list_step2_prompt_templates() -> List[Dict[str, Any]]:
    templates = built_in_step2_prompt_templates()
    stored = read_json_file(STEP2_PROMPT_TEMPLATES_PATH, [])
    if not isinstance(stored, list):
        return templates
    for item in stored:
        if not isinstance(item, dict):
            continue
        try:
            prompt_type = normalize_step2_prompt_type(item.get("prompt_type"))
            templates.append(
                step2_prompt_template_payload(
                    str(item.get("id") or ""),
                    str(item.get("name") or ""),
                    prompt_type,
                    item.get("prompts") if isinstance(item.get("prompts"), dict) else item,
                    updated_at=str(item.get("updated_at") or ""),
                )
            )
        except HTTPException as exc:
            logger.warning("Skipping invalid Step 2 prompt template %s: %s", item.get("id"), exc.detail)
    return templates


def step2_prompt_template_detail(template_id: str) -> Dict[str, Any]:
    for template in list_step2_prompt_templates():
        if template["id"] == template_id:
            return template
    raise HTTPException(status_code=404, detail="Prompt 模板不存在")


@app.get("/api/step2-prompt-templates")
def get_step2_prompt_templates():
    return {"success": True, "templates": list_step2_prompt_templates()}


@app.get("/api/step2-prompt-templates/{template_id}")
def get_step2_prompt_template(template_id: str):
    return {"success": True, "template": step2_prompt_template_detail(template_id)}


@app.post("/api/step2-prompt-templates")
def save_step2_prompt_template(payload: Dict[str, Any]):
    name = normalized_template_name(payload.get("name"))
    prompt_type = normalize_step2_prompt_type(payload.get("prompt_type"))
    protected_names = {template["name"].casefold() for template in built_in_step2_prompt_templates()}
    if name.casefold() in protected_names:
        raise HTTPException(status_code=400, detail="内置 Prompt 模板名称不可覆盖")

    first_key, second_key = step2_prompt_keys(prompt_type)
    prompts = {
        first_key: str(payload.get(first_key) or "").strip(),
        second_key: str(payload.get(second_key) or "").strip(),
    }
    if not prompts[first_key] or not prompts[second_key]:
        raise HTTPException(status_code=400, detail="Prompt 模板内容不能为空")

    stored = read_json_file(STEP2_PROMPT_TEMPLATES_PATH, [])
    if not isinstance(stored, list):
        stored = []
    existing = next(
        (
            item
            for item in stored
            if isinstance(item, dict)
            and str(item.get("prompt_type") or "").strip().lower() == prompt_type
            and str(item.get("name") or "").strip().casefold() == name.casefold()
        ),
        None,
    )
    now = template_timestamp()
    if existing is None:
        existing = {"id": uuid.uuid4().hex[:12], "created_at": now}
        stored.append(existing)
    existing.update(
        {
            "name": name,
            "prompt_type": prompt_type,
            "prompts": prompts,
            "updated_at": now,
        }
    )
    write_json_atomic(STEP2_PROMPT_TEMPLATES_PATH, stored)
    return {
        "success": True,
        "template": step2_prompt_template_payload(str(existing["id"]), name, prompt_type, prompts, updated_at=now),
        "templates": list_step2_prompt_templates(),
    }


@app.delete("/api/step2-prompt-templates/{template_id}")
def delete_step2_prompt_template(template_id: str):
    if any(template["id"] == template_id for template in built_in_step2_prompt_templates()):
        raise HTTPException(status_code=400, detail="内置 Prompt 模板不能删除")
    if not re.fullmatch(r"[0-9a-f]{12}", template_id):
        raise HTTPException(status_code=404, detail="Prompt 模板不存在")
    stored = read_json_file(STEP2_PROMPT_TEMPLATES_PATH, [])
    if not isinstance(stored, list):
        stored = []
    next_stored = [
        item
        for item in stored
        if not (isinstance(item, dict) and str(item.get("id") or "") == template_id)
    ]
    if len(next_stored) == len(stored):
        raise HTTPException(status_code=404, detail="Prompt 模板不存在")
    write_json_atomic(STEP2_PROMPT_TEMPLATES_PATH, next_stored)
    return {"success": True, "templates": list_step2_prompt_templates()}


def compose_step2_system_prompt(system_content: str, output_example: str) -> str:
    return (
        str(system_content or "").strip()
        + "\n\n<OutputExample>\n"
        + str(output_example or "").strip()
        + "\n</OutputExample>"
    )


def step2_script_prompt_uses_legacy_contract(system_content: str) -> bool:
    """Detect old prompts that require fields removed from the Step 2A input/output contract."""
    text = str(system_content or "")
    if "step2_script_v4_no_subtitle" in text:
        return False
    if "step2_script_v2" in text or "step2_script_v3_narration_first" in text:
        return True
    legacy_patterns = (
        r"body_points\s*(?:必须|應|应|需|是)",
        r"narration_segments\s*(?:必须|應|应|需|是)",
        r"讲解分段要求",
    )
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in legacy_patterns)


def step2_visual_prompt_uses_legacy_contract(system_content: str) -> bool:
    """Detect prompts that depend on Step 2A fields no longer sent to Step 2B."""
    text = str(system_content or "")
    if "step2_visual_v5_no_subtitle" in text:
        return False
    if "step2_visual_v2" in text or "step2_visual_v4_one_to_one" in text:
        return True
    legacy_patterns = (
        r"narration_segments\[\].{0,40}(?:唯一依据|唯一依據)",
        r"第\s*i\s*个\s*body_point",
        r"body_points\[i-1\]",
        r"seg_\(i\+1\)",
    )
    return any(re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL) for pattern in legacy_patterns)


def step2_prompt_compatibility(prompts: Dict[str, str]) -> Dict[str, Any]:
    script_legacy = step2_script_prompt_uses_legacy_contract(prompts.get("script_system", ""))
    visual_legacy = step2_visual_prompt_uses_legacy_contract(prompts.get("visual_system", ""))
    return {
        "contract_version": "step2_narration_visual_v4_no_subtitle",
        "script_prompt_legacy": script_legacy,
        "visual_prompt_legacy": visual_legacy,
        "compatible": not script_legacy and not visual_legacy,
    }


def step2_prompt_response(project: Project) -> Dict[str, Any]:
    prompts = read_step2_prompts(project)
    return {
        "success": True,
        "prompts": prompts,
        "defaults": default_step2_prompts(),
        "compatibility": step2_prompt_compatibility(prompts),
        "composed": {
            "script_system_content": compose_step2_system_prompt(
                prompts["script_system"],
                prompts["script_output_example"],
            ),
            "visual_system_content": compose_step2_system_prompt(
                prompts["visual_system"],
                prompts["visual_output_example"],
            ),
        },
    }


def read_project_article_brief(project: Project) -> Dict[str, Any]:
    brief_path = os.path.join(project.run_dir, "planning", "article_brief.json")
    if not os.path.exists(brief_path):
        raise HTTPException(status_code=400, detail="请先导入文章再生成分镜")
    with open(brief_path, "r", encoding="utf-8") as f:
        brief = json.load(f)
    if not isinstance(brief, dict):
        raise HTTPException(status_code=400, detail="文章导入结果格式无效")
    return brief


def stable_plan_id(value: Any, prefix: str, index: int) -> str:
    text = re.sub(r"[^a-zA-Z0-9_\\-]+", "_", str(value or "").strip())
    return text or f"{prefix}_{index:03d}"


def clean_planning_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def clean_planning_block(value: Any) -> str:
    if isinstance(value, list):
        parts = [clean_planning_text(item) for item in value]
        return "\n".join(part for part in parts if part)
    if isinstance(value, dict):
        parts = [clean_planning_text(item) for item in value.values()]
        return "\n".join(part for part in parts if part)
    return "\n".join(
        line
        for line in (clean_planning_text(line) for line in str(value or "").replace("\r", "\n").split("\n"))
        if line
    )


def normalize_slide_body(slide: Dict[str, Any]) -> str:
    body = clean_planning_block(slide.get("body") or slide.get("body_content") or slide.get("core_message"))
    if body:
        return body
    return "\n".join(point["text"] for point in normalize_body_points(slide.get("body_points")) if point.get("text"))


def normalize_visual_type(value: Any, has_text: bool = False) -> str:
    visual_type = str(value or "").strip().lower()
    if visual_type in {"text", "文字"}:
        return "text"
    if visual_type in {"picture", "illustration", "image", "diagram", "chart", "visual", "graphic", "text_and_illustration"}:
        return "picture"
    return "text" if has_text else "picture"


def normalize_body_points(value: Any, fallback_body: str = "") -> List[Dict[str, str]]:
    points = value if isinstance(value, list) else []
    normalized: List[Dict[str, str]] = []
    for index, point in enumerate(points, start=1):
        if isinstance(point, dict):
            text = clean_planning_text(point.get("text") or point.get("content") or "")
            purpose = clean_planning_text(point.get("purpose") or "")
            point_id = stable_plan_id(point.get("point_id"), "point", index)
        else:
            text = clean_planning_text(point)
            purpose = ""
            point_id = f"point_{index:03d}"
        if not text:
            continue
        normalized.append({"point_id": point_id, "text": text, "purpose": purpose})
    if not normalized and fallback_body:
        normalized.append({"point_id": "point_001", "text": clean_planning_text(fallback_body), "purpose": "正文"})
    return normalized


def normalize_narration_segments(value: Any, fallback_narration: str = "") -> List[Dict[str, str]]:
    segments = value if isinstance(value, list) else []
    normalized: List[Dict[str, str]] = []
    seen_narration: set[str] = set()
    previous_narration = ""
    for index, segment in enumerate(segments, start=1):
        if isinstance(segment, dict):
            narration = clean_planning_text(segment.get("narration") or segment.get("spoken_text") or "")
            purpose = clean_planning_text(segment.get("purpose") or segment.get("spoken_intent") or "")
            segment_id = stable_plan_id(segment.get("segment_id"), "seg", index)
        else:
            narration = clean_planning_text(segment)
            purpose = ""
            segment_id = f"seg_{index:03d}"
        if not narration or narration == previous_narration:
            continue
        narration_key = narration_dedupe_key(narration)
        if narration_key and narration_key in seen_narration:
            continue
        if narration_key:
            seen_narration.add(narration_key)
        normalized.append({"segment_id": segment_id, "narration": narration, "purpose": purpose})
        previous_narration = narration
    fallback_narration = clean_planning_text(fallback_narration)
    if not normalized and fallback_narration:
        normalized.append({"segment_id": "seg_001", "narration": fallback_narration, "purpose": "完整演讲稿"})
    return normalized


def normalize_slide_script_plan(plan: Dict[str, Any], project_title: str) -> Dict[str, Any]:
    slides = plan.get("slides") if isinstance(plan, dict) else []
    if not isinstance(slides, list) or not slides:
        raise HTTPException(status_code=500, detail="AI 没有返回可用的 slide_script_plan.slides")
    normalized_slides: List[Dict[str, Any]] = []
    for index, slide in enumerate(slides, start=1):
        if not isinstance(slide, dict):
            continue
        slide_id = stable_plan_id(slide.get("slide_id"), "slide", index)
        if not slide_id.startswith("slide_"):
            slide_id = f"slide_{index:03d}"
        narration = clean_planning_text(
            slide.get("narration")
            or slide.get("speech")
            or slide.get("script")
            or " ".join(
                clean_planning_text(segment.get("narration") if isinstance(segment, dict) else segment)
                for segment in (slide.get("narration_segments") or [])
            )
        )
        if not narration:
            raise HTTPException(status_code=500, detail=f"{slide_id} 缺少 narration")
        slide_title = clean_planning_text(slide.get("slide_title") or slide.get("title") or f"第 {index} 页")
        normalized_slides.append(
            {
                "slide_id": slide_id,
                "slide_title": slide_title,
                "narration": narration,
            }
        )
    if not normalized_slides:
        raise HTTPException(status_code=500, detail="AI 没有返回可用的 slide_script_plan.slides")
    return {"title": str(plan.get("title") or project_title).strip() or project_title, "slides": normalized_slides}


def normalize_visual_elements(value: Any) -> List[Dict[str, str]]:
    elements = value if isinstance(value, list) else []
    normalized: List[Dict[str, str]] = []
    for index, element in enumerate(elements, start=1):
        if not isinstance(element, dict):
            continue
        role = str(element.get("role") or "body").strip().lower()
        if role in {"content_body", "body_content"}:
            role = "body"
        visual_description = clean_planning_text(
            element.get("visual_description")
            or element.get("visible_text")
            or element.get("text")
            or ""
        )
        narration = clean_planning_text(element.get("narration") or "")
        visual_type = normalize_visual_type(element.get("visual_type"), has_text=bool(visual_description))
        if not visual_description:
            continue
        normalized.append(
            {
                "element_id": stable_plan_id(element.get("element_id"), "el", index),
                "role": role,
                "visual_type": visual_type,
                "visual_description": visual_description,
                "narration": narration,
            }
        )
    return normalized


def narration_sequence_key(value: Any) -> str:
    """Compare Step A narration with Step B fragments without hiding punctuation changes."""
    return re.sub(r"\s+", "", clean_planning_text(value))


def validate_slide_visual_mapping(
    slide_id: str,
    elements: List[Dict[str, str]],
    script_slide: Optional[Dict[str, Any]] = None,
) -> None:
    title_elements = [element for element in elements if element.get("role") == "title"]
    body_elements = [element for element in elements if element.get("role") == "body"]
    unsupported_roles = sorted({
        str(element.get("role") or "")
        for element in elements
        if element.get("role") not in {"title", "body"}
    })
    if unsupported_roles:
        raise HTTPException(
            status_code=500,
            detail=(
                f"{slide_id} 包含不参与一对一旁白映射的 role: {', '.join(unsupported_roles)}。"
                "系统不使用页面副标题；装饰由生图阶段处理，visual_elements 只能包含 title 和 body。"
            ),
        )
    if len(title_elements) != 1 or not elements or elements[0].get("role") != "title":
        raise HTTPException(status_code=500, detail=f"{slide_id} 必须以且仅以一个 title 元素开头")
    if not body_elements:
        raise HTTPException(status_code=500, detail=f"{slide_id} 至少需要一个 body 视觉元素")
    title = title_elements[0]
    if title.get("visual_type") != "text":
        raise HTTPException(status_code=500, detail=f"{slide_id} 的 title 必须使用 text 形式")
    for element in elements:
        if not str(element.get("narration") or "").strip():
            raise HTTPException(
                status_code=500,
                detail=f"{slide_id} 的 {element.get('element_id') or 'visual element'} 没有对应演讲片段",
            )
    if not isinstance(script_slide, dict):
        return
    expected_title = clean_planning_text(script_slide.get("slide_title") or "")
    if expected_title and clean_planning_text(title.get("visual_description")) != expected_title:
        raise HTTPException(
            status_code=500,
            detail=f"{slide_id} 的标题画面文字必须逐字等于 slide_title: {expected_title}",
        )
    source_narration = clean_planning_text(script_slide.get("narration") or "")
    combined_narration = "".join(str(element.get("narration") or "") for element in elements)
    if narration_sequence_key(combined_narration) != narration_sequence_key(source_narration):
        raise HTTPException(
            status_code=500,
            detail=(
                f"{slide_id} 的视觉元素演讲片段未能完整还原 Step A 演讲稿。"
                "每个片段必须非空、连续、无遗漏、无重复且保持原顺序。"
            ),
        )


def normalize_slide_visual_plan(
    plan: Dict[str, Any],
    script_plan: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    slides = plan.get("slides") if isinstance(plan, dict) else []
    if not isinstance(slides, list) or not slides:
        raise HTTPException(status_code=500, detail="AI 没有返回可用的 slide_visual_plan.slides")
    script_by_id = {
        str(slide.get("slide_id") or "").strip(): slide
        for slide in ((script_plan or {}).get("slides") or [])
        if isinstance(slide, dict)
    }
    normalized_slides: List[Dict[str, Any]] = []
    for index, slide in enumerate(slides, start=1):
        if not isinstance(slide, dict):
            continue
        slide_id = stable_plan_id(slide.get("slide_id"), "slide", index)
        if not slide_id.startswith("slide_"):
            slide_id = f"slide_{index:03d}"
        elements = normalize_visual_elements(slide.get("visual_elements"))
        if not elements:
            raise HTTPException(status_code=500, detail=f"{slide_id} 缺少 visual_elements")
        validate_slide_visual_mapping(slide_id, elements, script_by_id.get(slide_id))
        normalized_slides.append({"slide_id": slide_id, "visual_elements": elements})
    if not normalized_slides:
        raise HTTPException(status_code=500, detail="AI 没有返回可用的 slide_visual_plan.slides")
    return {"slides": normalized_slides}


def read_plan_json(path: str, missing_message: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=missing_message)
    with open(path, "r", encoding="utf-8-sig") as f:
        value = json.load(f)
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail="规划文件格式无效")
    return value


def configured_step2_llm() -> tuple[str, Optional[str], str, float, int]:
    llm_api_key = get_setting("llm_api_key")
    llm_base_url = get_setting("llm_base_url")
    llm_model = get_setting("llm_model")
    llm_temp = float(get_setting("llm_temperature", "0.7"))
    planning_temp = min(llm_temp, 0.2)
    planning_max_tokens = parse_int_setting(get_setting("llm_max_tokens", "50000"), 50000, 1024, 64000)
    if not llm_api_key:
        raise HTTPException(status_code=400, detail="未配置大模型 API 密钥，请在系统设置中配置后再试。")
    return llm_api_key, llm_base_url, llm_model, planning_temp, planning_max_tokens


def step2_llm_vendor_options(model: str, base_url: Optional[str]) -> Dict[str, Any]:
    """Use fast non-thinking mode for Volcengine/Doubao storyboard requests."""
    model_name = str(model or "").strip().lower()
    endpoint = str(base_url or "").strip().lower()
    if model_name.startswith("doubao-") or "volces.com" in endpoint:
        return {"extra_body": {"thinking": {"type": "disabled"}}}
    return {}


def run_step2_json_llm(
    *,
    project: Project,
    system_prompt: str,
    user_prompt: str,
    artifact_prefix: str,
    schema_hint: str,
    trace_id: str,
) -> Dict[str, Any]:
    llm_api_key, llm_base_url, llm_model, planning_temp, planning_max_tokens = configured_step2_llm()
    stage_label = {
        "step2_script_plan": "Step 2A 演讲稿规划",
        "step2_visual_plan": "Step 2B 可视化规划",
    }.get(artifact_prefix, "Step 2 分镜规划")
    started_at = time.monotonic()
    vendor_options = step2_llm_vendor_options(llm_model, llm_base_url)
    write_project_log(
        project,
        f"{artifact_prefix}_start",
        trace_id=trace_id,
        model=llm_model,
        base_url=llm_base_url,
        max_tokens=planning_max_tokens,
        thinking_disabled=bool(vendor_options),
    )
    client = get_openai_client(
        api_key=llm_api_key,
        base_url=llm_base_url,
        timeout=STEP2_LLM_TIMEOUT_SEC,
        max_retries=0,
    )
    try:
        try:
            response = client.chat.completions.create(
                model=llm_model,
                temperature=planning_temp,
                max_tokens=planning_max_tokens,
                timeout=STEP2_LLM_TIMEOUT_SEC,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                **vendor_options,
            )
        except Exception as inner_e:
            if is_timeout_exception(inner_e):
                raise
            logger.warning("Failed LLM call with response_format for %s, retrying without it: %s", artifact_prefix, inner_e)
            response = client.chat.completions.create(
                model=llm_model,
                temperature=planning_temp,
                max_tokens=planning_max_tokens,
                timeout=STEP2_LLM_TIMEOUT_SEC,
                messages=[
                    {"role": "system", "content": system_prompt + " 请只输出纯 JSON，不要包含 Markdown 代码块标记（如 ```json ）。"},
                    {"role": "user", "content": user_prompt},
                ],
                **vendor_options,
            )
        choice = response.choices[0]
        logger.info("%s finish_reason=%s usage=%s", artifact_prefix, getattr(choice, "finish_reason", None), getattr(response, "usage", None))
        content_str = str(choice.message.content or "").strip()
        if not content_str:
            raise ValueError("大模型返回了空内容")
        cleaned_content = clean_json_markdown(content_str)
        return parse_json_or_repair_with_llm(
            cleaned_content=cleaned_content,
            raw_content=content_str,
            client=client,
            model=llm_model,
            run_dir=project.run_dir,
            artifact_prefix=artifact_prefix,
            schema_hint=schema_hint,
            max_tokens=planning_max_tokens,
        )
    except HTTPException as exc:
        write_project_log(
            project,
            f"{artifact_prefix}_failed",
            trace_id=trace_id,
            elapsed_sec=round(time.monotonic() - started_at, 2),
            status_code=exc.status_code,
            error=str(exc.detail),
        )
        raise
    except Exception as exc:
        timed_out = is_timeout_exception(exc)
        write_project_log(
            project,
            f"{artifact_prefix}_failed",
            trace_id=trace_id,
            elapsed_sec=round(time.monotonic() - started_at, 2),
            timeout=timed_out,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        if timed_out:
            raise HTTPException(
                status_code=504,
                detail=f"{stage_label}超过 {int(STEP2_LLM_TIMEOUT_SEC)} 秒仍未返回，请重试或切换响应更快的模型。",
            ) from exc
        raise HTTPException(status_code=502, detail=f"{stage_label}失败：{str(exc)[:300]}") from exc
    finally:
        try:
            client.close()
        except Exception:
            pass


def script_plan_schema_hint() -> str:
    return read_prompt_template(STEP2_PROMPT_TEMPLATE_FILES["script_output_example"])


def visual_plan_schema_hint() -> str:
    return read_prompt_template(STEP2_PROMPT_TEMPLATE_FILES["visual_output_example"])


def build_step2_script_user_prompt(
    *,
    project_title: str,
    article_content: str,
    generation_requirement: str,
) -> str:
    return json.dumps(
        {
            "project_title": project_title,
            "article_content": article_content,
            "generation_requirement": generation_requirement,
            "output_goal": "生成 slide_script_plan.json。根级只包含 title、slides；每页只包含 slide_id、slide_title 和一整段 narration，不生成副标题。",
        },
        ensure_ascii=False,
        indent=2,
    )


def build_step2_visual_user_prompt(script_plan: Dict[str, Any]) -> str:
    minimal_script_plan = {
        "title": str(script_plan.get("title") or "").strip(),
        "slides": [
            {
                "slide_id": str(slide.get("slide_id") or "").strip(),
                "slide_title": str(slide.get("slide_title") or "").strip(),
                "narration": str(slide.get("narration") or "").strip(),
            }
            for slide in (script_plan.get("slides") or [])
            if isinstance(slide, dict)
        ],
    }
    return json.dumps(
        {
            "slide_script_plan": minimal_script_plan,
            "output_goal": "把每页完整 narration 按原文顺序切成非空片段；一个片段只对应一个画面文字或画面元素，全部片段拼接后必须完整还原原演讲稿。",
        },
        ensure_ascii=False,
        indent=2,
    )


def element_visible_text(element: Dict[str, str], index: int) -> str:
    description = str(element.get("visual_description") or "").strip()
    if description:
        return description[:32]
    return f"视觉元素 {index}"


def compose_visual_contract_from_plans(
    script_plan: Dict[str, Any],
    visual_plan: Dict[str, Any],
    project_id: str,
    project_title: str,
) -> Dict[str, Any]:
    script_slides = script_plan.get("slides") if isinstance(script_plan, dict) else []
    visual_slides = visual_plan.get("slides") if isinstance(visual_plan, dict) else []
    if not isinstance(script_slides, list) or not script_slides:
        raise HTTPException(status_code=400, detail="slide_script_plan.json 缺少 slides")
    if not isinstance(visual_slides, list) or not visual_slides:
        raise HTTPException(status_code=400, detail="slide_visual_plan.json 缺少 slides")

    visual_by_id = {
        str(slide.get("slide_id") or "").strip(): slide
        for slide in visual_slides
        if isinstance(slide, dict)
    }
    subtitle_policy = "no_slides_have_subtitle"
    slides: List[Dict[str, Any]] = []
    for slide_index, script_slide in enumerate(script_slides, start=1):
        if not isinstance(script_slide, dict):
            continue
        slide_id = str(script_slide.get("slide_id") or f"slide_{slide_index:03d}").strip()
        visual_slide = visual_by_id.get(slide_id)
        if not isinstance(visual_slide, dict):
            raise HTTPException(status_code=400, detail=f"{slide_id} 缺少对应的 visual plan")
        body_points = script_slide.get("body_points") if isinstance(script_slide.get("body_points"), list) else []
        visual_groups: List[Dict[str, Any]] = []
        narration_beats: List[Dict[str, Any]] = []
        for element_index, element in enumerate(visual_slide.get("visual_elements") or [], start=1):
            if not isinstance(element, dict):
                continue
            element_id = stable_plan_id(element.get("element_id"), "el", element_index)
            group_id = f"{slide_id}_{element_id}"
            content_unit_id = f"{slide_id}_unit_{element_index:03d}"
            role = str(element.get("role") or "body").strip().lower()
            role = "decoration" if role == "decoration" else ("title" if role == "title" else ("subtitle" if role == "subtitle" else "content_body"))
            visible_text = element_visible_text(element, element_index)
            description = str(element.get("visual_description") or visible_text).strip()
            narration = str(element.get("narration") or "").strip()
            narration_function_value = str(element.get("narration_function") or element.get("visual_description") or visible_text or "").strip()
            visual_type = normalize_visual_type(element.get("visual_type"))
            display_text = description if visual_type == "text" else ""
            group = {
                "id": group_id,
                "element_id": element_id,
                "role": role,
                "visible_text": visible_text,
                "display_text": display_text,
                "visual_anchor": description,
                "narration_function": narration_function_value,
                "reveal_order": element_index,
                "content_unit_id": content_unit_id,
                "mask_target": description,
                "visual_type": visual_type,
            }
            visual_groups.append(group)
            if narration:
                narration_beats.append(
                    {
                        "id": f"{slide_id}_beat_{len(narration_beats) + 1:03d}",
                        "group_id": group_id,
                        "visible_anchor": visible_text,
                        "spoken_intent": narration_function_value,
                        "spoken_text": narration,
                        "content_unit_id": content_unit_id,
                    }
                )
        if not visual_groups:
            raise HTTPException(status_code=400, detail=f"{slide_id} 没有可合成的 visual elements")
        if not narration_beats:
            raise HTTPException(status_code=400, detail=f"{slide_id} 没有可合成的 narration beats")
        body_content = [
            str(point.get("text") or "").strip()
            for point in body_points
            if isinstance(point, dict) and point.get("text")
        ]
        if not body_content and str(script_slide.get("body") or "").strip():
            body_content = [str(script_slide.get("body") or "").strip()]
        if not body_content:
            body_content = [
                str(group.get("visible_text") or "").strip()
                for group in visual_groups
                if group.get("role") == "content_body" and str(group.get("visible_text") or "").strip()
            ]
        slides.append(
            {
                "slide_id": slide_id,
                "main_title": str(script_slide.get("slide_title") or f"第 {slide_index} 页").strip(),
                "subtitle": "",
                "core_message": "；".join(body_content),
                "body_content": body_content,
                "visual_groups": visual_groups,
                "narration_beats": narration_beats,
            }
        )
    return {
        "version": "visual_contract_v1",
        "presentation_policy": {
            "subtitle_policy": subtitle_policy,
            "subtitle_decided_by": "system_no_subtitle_contract",
            "visual_narration_mapping": "one_visual_element_to_one_narration_beat_v1",
        },
        "topic": {
            "topic_id": "topic_" + project_id,
            "topic_name": project_title,
            "topic_summary": "",
        },
        "slides": slides,
    }


def storyboard_template_payload(
    template_id: str,
    name: str,
    rules: str,
    profile_text: str,
    built_in: bool = False,
    updated_at: str = "",
) -> Dict[str, Any]:
    profile = parse_storyboard_profile_text(profile_text)
    return {
        "id": template_id,
        "name": name,
        "built_in": built_in,
        "updated_at": updated_at,
        "rules": rules,
        "profile_yaml": profile_text,
        "roles": role_catalog(profile),
        "editor": storyboard_profile_editor_data(profile),
    }


def list_storyboard_templates() -> List[Dict[str, Any]]:
    templates = [
        storyboard_template_payload(
            "default",
            "内容优先通用分镜模板",
            default_storyboard_rules(),
            default_storyboard_profile_text(),
            built_in=True,
        ),
        storyboard_template_payload(
            "handdrawn_explainer",
            "手绘科普内容优先模板",
            handdrawn_storyboard_rules(),
            default_storyboard_profile_text(),
            built_in=True,
        ),
    ]
    stored = read_json_file(STORYBOARD_TEMPLATES_PATH, [])
    if not isinstance(stored, list):
        return templates
    for item in stored:
        if not isinstance(item, dict):
            continue
        try:
            templates.append(
                storyboard_template_payload(
                    str(item.get("id") or ""),
                    str(item.get("name") or ""),
                    str(item.get("rules") or ""),
                    str(item.get("profile_yaml") or ""),
                    updated_at=str(item.get("updated_at") or ""),
                )
            )
        except HTTPException as exc:
            logger.warning("Skipping invalid storyboard template %s: %s", item.get("id"), exc.detail)
    return templates


@app.get("/api/storyboard-templates")
def get_storyboard_templates():
    return {"success": True, "templates": list_storyboard_templates()}


@app.post("/api/storyboard-templates")
def save_storyboard_template(payload: Dict[str, Any]):
    name = normalized_template_name(payload.get("name"))
    protected_names = {"默认分镜模板", "内容优先通用分镜模板", "手绘科普内容优先模板"}
    if name.casefold() in {item.casefold() for item in protected_names}:
        raise HTTPException(status_code=400, detail="内置分镜模板名称不可覆盖")
    rules = str(payload.get("rules") or "").strip() or default_storyboard_rules()
    profile_text = str(payload.get("profile_yaml") or "").strip() or default_storyboard_profile_text()
    profile = parse_storyboard_profile_text(profile_text)
    profile = apply_storyboard_profile_patch(profile, payload.get("profile_patch"))
    profile_text = yaml.safe_dump(profile, allow_unicode=True, sort_keys=False, width=1000).strip()

    stored = read_json_file(STORYBOARD_TEMPLATES_PATH, [])
    if not isinstance(stored, list):
        stored = []
    existing = next(
        (
            item
            for item in stored
            if isinstance(item, dict)
            and str(item.get("name") or "").strip().casefold() == name.casefold()
        ),
        None,
    )
    now = template_timestamp()
    if existing is None:
        existing = {"id": uuid.uuid4().hex[:12], "created_at": now}
        stored.append(existing)
    existing.update(
        {
            "name": name,
            "rules": rules,
            "profile_yaml": profile_text,
            "updated_at": now,
        }
    )
    write_json_atomic(STORYBOARD_TEMPLATES_PATH, stored)
    return {
        "success": True,
        "template": storyboard_template_payload(
            str(existing["id"]),
            name,
            rules,
            profile_text,
            updated_at=now,
        ),
        "templates": list_storyboard_templates(),
    }


@app.delete("/api/storyboard-templates/{template_id}")
def delete_storyboard_template(template_id: str):
    if template_id == "default":
        raise HTTPException(status_code=400, detail="内置分镜模板不能删除")
    if not re.fullmatch(r"[0-9a-f]{12}", template_id):
        raise HTTPException(status_code=404, detail="分镜模板不存在")
    stored = read_json_file(STORYBOARD_TEMPLATES_PATH, [])
    if not isinstance(stored, list):
        stored = []
    next_stored = [
        item
        for item in stored
        if not (isinstance(item, dict) and str(item.get("id") or "") == template_id)
    ]
    if len(next_stored) == len(stored):
        raise HTTPException(status_code=404, detail="分镜模板不存在")
    write_json_atomic(STORYBOARD_TEMPLATES_PATH, next_stored)
    return {"success": True, "templates": list_storyboard_templates()}


def build_storyboard_request(
    project_title: str,
    article_summary: str,
    article_content: str,
    storyboard_rules: str,
    profile: Optional[Dict[str, Any]] = None,
) -> tuple[str, str]:
    profile = profile or read_pipeline_profile()
    slide_count_requirement, group_count_requirement = storyboard_requirements(article_content, profile)
    profile_prompt = storyboard_profile_prompt(article_content, profile)

    schema_hint = visual_contract_schema_text()

    system_prompt = f"""你是一个顶级的 PPT 视频分镜策划师和演讲稿设计师。

## 目的
把文章转成可直接驱动后续生图、Mask、Reveal、旁白和视频制作的 Visual Contract；忠实保留文章事实，不在本阶段生成图片或执行动画。

## 输入
- 项目主题、文章摘要与文章全文。
- 当前项目的分镜结构配置、用户自定义规则与 JSON Schema。
- 文章及显式规则是内容与边界依据；不得虚构来源中没有的具体事实。

## 输出
- 只返回一个符合下方 JSON Schema 的合法 JSON 对象。
- 不要 Markdown 代码围栏、解释、推理过程或任何 JSON 之外的文字。
- 输出必须同时满足 visual_groups 与 narration_beats 的绑定约束，供后续阶段直接读取。
请阅读用户输入的内容摘要和全文，先设计“如何把内容讲清楚”的理解路径和演讲稿，再把它编译成符合 PPT 动画视频制作标准的视觉合约(Visual Contract)。
视频的画面风格可由后续图片风格配置决定；这里重点规划“讲解逻辑、演讲稿、内容结构、视觉表达、旁白绑定、Mask 友好性”。
总原则：
- 内容优先，结构服务内容；不要让内容服务固定模板或角色枚举。
- 演讲稿不是附属品。每页必须有自然、连贯、适合口播的 spoken_text，用来解释推理过程、上下文和结论。
- 画面不是演讲稿的逐字复刻。visible_text 应是关键词、短句、结构标签、图示标签或结论钩子。
- visual_groups 是后续 Mask/动画/旁白绑定接口，不是页面设计模板；role 只是后处理语义标签。
- 主标题使用页面上方固定位置，不生成页面副标题；底部 y=930..1080 固定为视频字幕安全区。除此之外，主体内容区根据内容自由发挥。
- 字号比例必须明确：每页 slide 顶部标题的视觉字号为当前默认标题的 2 倍；正文内容、演讲稿对应画面文字的视觉字号约为当前默认的 2/3。
- 禁止画面元素重叠：文字、卡片、图标、箭头、线条、标签、装饰、图表之间不得互相覆盖、压住、穿插或粘连。
要求：
1. 必须要将整篇文章合理划分，分成 {slide_count_requirement} Slide（每页的 slide_id 为 slide_001, slide_002 格式）。
2. 每页 Slide 建议定义 {group_count_requirement}视觉分组(visual_groups)。不要固定套用“主标题/正文/总结”模板；可以按内容需要使用判断链、冲突地图、对象关系图、推理路径、时间压力图、对比、表格、流程、FAQ、场景拆解或行动清单。
3. 每个视觉分组（visual_groups）必须有：
   - id: 比如 title_group, body_group_01 等
   - visible_text: 页面上会显式画出来的中文字符标签（非常重要，通常为短句或关键词，绝对不能为空；不要把整段演讲稿塞进这里）
   - visual_anchor: 视觉描述（比如“顶部主标题”、“左侧判断链起点”、“中间对象关系图”、“右侧结论卡”）
   - narration_function: 解释该分组在画面中所起的视觉/解释作用
   - reveal_order: 页面渲染时层淡入淡出显示的顺序，从 1 开始依次增加
   - content_unit_id: 稳定内容单元 ID，必须和 narration_beats[].content_unit_id 对齐
   - mask_target: 后续人工 Mask 要覆盖的画面目标描述
4. 必须规划 narration_beats (旁白语段)，使说话声音与相应视觉分组绑定：
   - group_id: 指向前面定义的 visual_groups 中的 id
   - visible_anchor: 该分组对应的 visible_text 文本（不可写错，必须一致）
   - spoken_intent: 这一句话想达到的意图
   - spoken_text: 这一句话具体要朗读的中文旁白（需自然连贯，解释 visible_text）
   - content_unit_id: 必须与绑定 visual_group 的 content_unit_id 一致
   - narration_beats 是是否朗读的唯一依据：某个 visual_group 有对应 beat 才会在演讲稿中讲解，没有 beat 就只作为画面内容展示。
   - 不要为了覆盖所有 visual_groups 而强行补旁白；只为演讲稿实际需要讲解的内容创建 beat。
   - 同一页内每条 spoken_text 的内容必须唯一；严禁重复、近似复述或为了凑数量复制同一句旁白。
5. 当前项目的可配置分镜结构如下。请优先遵守：
{profile_prompt}
6. 用户自定义的分镜与演讲稿规则如下。请遵守这些内容，但不得修改输出字段、层级、ID 规则或 JSON 结构：
--- 用户分镜规则开始 ---
{storyboard_rules}
--- 用户分镜规则结束 ---
7. 请确保生成的 JSON 数据严格符合以下的 JSON Schema 格式要求：
{schema_hint}

请直接返回合法的 JSON 对象，不要包含 markdown 标记的 ```json 外壳。"""
    user_prompt = (
        f"项目主题：{project_title}\n"
        f"摘要提纲：{article_summary}\n"
        f"正文全文：\n{article_content}"
    )
    return system_prompt, user_prompt


@app.get("/api/projects/{project_id}/steps/2/rules")
def get_step2_rules(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    path = storyboard_rules_path(project)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            rules = f.read()
    else:
        rules = default_storyboard_rules()
    profile_path = storyboard_profile_path(project)
    if os.path.exists(profile_path):
        with open(profile_path, "r", encoding="utf-8-sig") as f:
            profile_text = f.read()
    else:
        profile_text = default_storyboard_profile_text()
    profile = parse_storyboard_profile_text(profile_text)
    return {
        "success": True,
        "rules": rules,
        "profile_yaml": profile_text,
        "schema_text": visual_contract_schema_text(),
        "roles": role_catalog(profile),
        "editor": storyboard_profile_editor_data(profile),
    }


@app.put("/api/projects/{project_id}/steps/2/rules")
def update_step2_rules(project_id: str, payload: Dict[str, Any], db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    rules = str(payload.get("rules") or "").strip()
    if not rules:
        rules = default_storyboard_rules()
    profile_text = str(payload.get("profile_yaml") or "").strip()
    if not profile_text:
        profile_text = default_storyboard_profile_text().strip()
    profile = parse_storyboard_profile_text(profile_text)
    profile = apply_storyboard_profile_patch(profile, payload.get("profile_patch"))
    profile_text = yaml.safe_dump(
        profile,
        allow_unicode=True,
        sort_keys=False,
        width=1000,
    ).strip()
    path = storyboard_rules_path(project)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(rules + "\n")
    with open(storyboard_profile_path(project), "w", encoding="utf-8", newline="\n") as f:
        f.write(profile_text.rstrip() + "\n")
    return {
        "success": True,
        "rules": rules,
        "profile_yaml": profile_text,
        "roles": role_catalog(profile),
        "editor": storyboard_profile_editor_data(profile),
    }


@app.get("/api/projects/{project_id}/steps/2/prompts")
def get_step2_prompts(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return step2_prompt_response(project)


@app.put("/api/projects/{project_id}/steps/2/prompts")
def update_step2_prompts(project_id: str, payload: Dict[str, Any], db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    defaults = default_step2_prompts()
    prompts: Dict[str, str] = {}
    for key, default_value in defaults.items():
        value = str(payload.get(key) or "").strip()
        prompts[key] = value or default_value
    write_json_atomic(step2_prompts_path(project), prompts)
    return step2_prompt_response(project)


@app.post("/api/projects/{project_id}/steps/2/script/execute")
def execute_step2_script_plan(
    project_id: str,
    payload: Optional[Dict[str, Any]] = None,
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    brief = read_project_article_brief(project)
    project_title = (project.name or "").strip() or str(brief.get("title") or "未命名项目")
    article_content = str(brief.get("content") or "")
    generation_requirement = str((payload or {}).get("requirement") or "").strip() or DEFAULT_STEP2_GENERATION_REQUIREMENT
    prompts = read_step2_prompts(project)
    if step2_script_prompt_uses_legacy_contract(prompts["script_system"]):
        raise HTTPException(
            status_code=409,
            detail=(
                "当前文章→Slides Prompt 仍要求旧字段 body_points/narration_segments，"
                "与 Step 2A 的精简输出合同不兼容。请载入最新内置模板或升级该自定义模板后再生成。"
            ),
        )
    trace_id = uuid.uuid4().hex[:8]
    raw_plan = run_step2_json_llm(
        project=project,
        system_prompt=compose_step2_system_prompt(prompts["script_system"], prompts["script_output_example"]),
        user_prompt=build_step2_script_user_prompt(
            project_title=project_title,
            article_content=article_content,
            generation_requirement=generation_requirement,
        ),
        artifact_prefix="step2_script_plan",
        schema_hint=script_plan_schema_hint(),
        trace_id=trace_id,
    )
    plan = normalize_slide_script_plan(raw_plan, project_title)
    write_json_atomic(step2_script_plan_path(project), plan)
    write_project_log(project, "step2_script_plan_written", trace_id=trace_id, slide_count=len(plan.get("slides", [])))
    return {"success": True, "script_plan": plan}


@app.get("/api/projects/{project_id}/steps/2/script/result")
def get_step2_script_plan(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    plan = read_plan_json(step2_script_plan_path(project), "尚未生成演讲稿规划")
    return {"success": True, "script_plan": plan}


@app.put("/api/projects/{project_id}/steps/2/script/result")
def update_step2_script_plan(project_id: str, payload: Dict[str, Any], db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    brief = read_project_article_brief(project)
    project_title = (project.name or "").strip() or str(brief.get("title") or "未命名项目")
    plan = normalize_slide_script_plan(payload, project_title)
    write_json_atomic(step2_script_plan_path(project), plan)
    return {"success": True, "script_plan": plan}


@app.post("/api/projects/{project_id}/steps/2/visual/execute")
def execute_step2_visual_plan(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    script_plan = read_plan_json(step2_script_plan_path(project), "请先生成演讲稿规划")
    prompts = read_step2_prompts(project)
    if step2_visual_prompt_uses_legacy_contract(prompts["visual_system"]):
        raise HTTPException(
            status_code=409,
            detail=(
                "当前 Slides→可视化 Prompt 仍依赖旧字段 body_points/narration_segments，"
                "但 Step 2B 现在只接收 slide_id、slide_title 和完整 narration，不接收页面副标题。"
                "请载入最新内置模板或升级该自定义模板后再生成。"
            ),
        )
    trace_id = uuid.uuid4().hex[:8]
    raw_plan = run_step2_json_llm(
        project=project,
        system_prompt=compose_step2_system_prompt(prompts["visual_system"], prompts["visual_output_example"]),
        user_prompt=build_step2_visual_user_prompt(script_plan),
        artifact_prefix="step2_visual_plan",
        schema_hint=visual_plan_schema_hint(),
        trace_id=trace_id,
    )
    plan = normalize_slide_visual_plan(raw_plan, script_plan)
    write_json_atomic(step2_visual_plan_path(project), plan)
    write_project_log(project, "step2_visual_plan_written", trace_id=trace_id, slide_count=len(plan.get("slides", [])))
    return {"success": True, "visual_plan": plan}


@app.get("/api/projects/{project_id}/steps/2/visual/result")
def get_step2_visual_plan(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    plan = read_plan_json(step2_visual_plan_path(project), "尚未生成视觉规划")
    return {"success": True, "visual_plan": plan}


@app.put("/api/projects/{project_id}/steps/2/visual/result")
def update_step2_visual_plan(project_id: str, payload: Dict[str, Any], db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    script_plan = read_plan_json(step2_script_plan_path(project), "请先生成演讲稿规划")
    plan = normalize_slide_visual_plan(payload, script_plan)
    write_json_atomic(step2_visual_plan_path(project), plan)
    return {"success": True, "visual_plan": plan}


@app.post("/api/projects/{project_id}/steps/2/compose")
def compose_step2_visual_contract(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    brief = read_project_article_brief(project)
    project_title = (project.name or "").strip() or str(brief.get("title") or "未命名项目")
    article_summary = str(brief.get("summary") or build_article_summary(str(brief.get("content") or "")))
    script_plan = read_plan_json(step2_script_plan_path(project), "请先生成演讲稿规划")
    visual_plan = normalize_slide_visual_plan(
        read_plan_json(step2_visual_plan_path(project), "请先生成视觉规划"),
        script_plan,
    )
    trace_id = uuid.uuid4().hex[:8]
    contract = compose_visual_contract_from_plans(script_plan, visual_plan, project_id, project_title)
    contract = finalize_step2_contract(
        project=project,
        project_id=project_id,
        db=db,
        contract=contract,
        project_title=project_title,
        article_summary=article_summary,
        trace_id=trace_id,
        source="narration_first_compose",
    )
    return {"success": True, "contract": contract}


@app.post("/api/projects/{project_id}/steps/2/prompt-preview")
def get_step2_prompt_preview(
    project_id: str,
    payload: Optional[Dict[str, Any]] = None,
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    brief_path = os.path.join(project.run_dir, "planning", "article_brief.json")
    if not os.path.exists(brief_path):
        raise HTTPException(status_code=400, detail="请先导入文章再查看完整分镜请求")
    with open(brief_path, "r", encoding="utf-8") as f:
        brief = json.load(f)

    storyboard_rules = str((payload or {}).get("rules") or "").strip()
    if not storyboard_rules:
        rules_path = storyboard_rules_path(project)
        if os.path.exists(rules_path):
            with open(rules_path, "r", encoding="utf-8") as f:
                storyboard_rules = f.read().strip()
        else:
            storyboard_rules = default_storyboard_rules()
    profile_text = str((payload or {}).get("profile_yaml") or "").strip()
    profile = (
        parse_storyboard_profile_text(profile_text)
        if profile_text
        else read_project_pipeline_profile(project)
    )
    profile = apply_storyboard_profile_patch(profile, (payload or {}).get("profile_patch"))

    project_title = (project.name or "").strip() or brief.get("title") or "未命名项目"
    article_content = str(brief.get("content") or "")
    article_summary = brief.get("summary") or build_article_summary(article_content)
    system_prompt, user_prompt = build_storyboard_request(
        project_title,
        article_summary,
        article_content,
        storyboard_rules,
        profile,
    )
    return {
        "success": True,
        "system_content": system_prompt,
        "user_content": user_prompt,
    }


def visual_contract_validation_path(project: Project) -> str:
    return os.path.join(project.run_dir, "planning", "visual_contract.validation.json")


def validate_visual_contract_file(
    project: Project,
    contract_path: str,
    *,
    source: str,
    trace_id: str = "",
) -> Dict[str, Any]:
    validate_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "validate_visual_contract.py"))
    validation_args = [sys.executable, validate_script, "--contract", contract_path]
    project_profile_path = storyboard_profile_path(project)
    if os.path.exists(project_profile_path):
        validation_args.extend(["--profile", project_profile_path])
    result = subprocess.run(
        validation_args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    contract_bytes = Path(contract_path).read_bytes()
    validation = {
        "valid": result.returncode == 0,
        "contract_sha256": hashlib.sha256(contract_bytes).hexdigest(),
        "validated_at": datetime.now().isoformat(timespec="seconds"),
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "source": source,
        "trace_id": trace_id,
    }
    write_json_atomic(visual_contract_validation_path(project), validation)
    return validation


def storyboard_validation_gate_enabled(project: Project) -> bool:
    profile = read_project_pipeline_profile(project)
    gates = profile.get("quality_gates") if isinstance(profile.get("quality_gates"), dict) else {}
    return bool(gates.get("pause_on_storyboard_validation_error", True))


def finalize_step2_contract(
    *,
    project: Project,
    project_id: str,
    db: Session,
    contract: Dict[str, Any],
    project_title: str,
    article_summary: str,
    trace_id: str,
    source: str,
) -> Dict[str, Any]:
    contract["version"] = "visual_contract_v1"
    if "topic" not in contract or not isinstance(contract.get("topic"), dict):
        contract["topic"] = {
            "topic_id": "topic_" + project_id,
            "topic_name": project_title,
            "topic_summary": article_summary,
        }
    contract = normalize_visual_contract(contract, read_project_pipeline_profile(project))

    contract_path = os.path.join(project.run_dir, "planning", "visual_contract.json")
    os.makedirs(os.path.dirname(contract_path), exist_ok=True)
    contract["version"] = "visual_contract_v1"
    contract["topic"] = {
        "topic_id": "topic_" + project_id,
        "topic_name": project_title,
        "topic_summary": article_summary,
    }
    with open(contract_path, "w", encoding="utf-8") as f:
        json.dump(contract, f, ensure_ascii=False, indent=2)
    write_project_log(
        project,
        "step2_contract_written",
        trace_id=trace_id,
        contract_path=contract_path,
        slide_count=len(contract.get("slides", [])) if isinstance(contract.get("slides"), list) else 0,
        source=source,
    )

    validation = validate_visual_contract_file(
        project,
        contract_path,
        source=source,
        trace_id=trace_id,
    )

    if not validation["valid"]:
        logger.warning("Visual contract validation warning:\n%s", validation["stderr"])
        write_project_log(
            project,
            "step2_contract_validation_warning",
            trace_id=trace_id,
            returncode=validation["returncode"],
            stderr=validation["stderr"],
            source=source,
        )
        if storyboard_validation_gate_enabled(project):
            mark_step_retry_needed(project, 2, db)
            raise HTTPException(
                status_code=422,
                detail="分镜合同校验失败，质量门已暂停流程：" + (validation["stderr"] or "请检查分镜结构"),
            )
    else:
        write_project_log(
            project,
            "step2_contract_validation_success",
            trace_id=trace_id,
            stdout=validation["stdout"],
            source=source,
        )

    handle_step_navigation(project, 2, db)
    write_project_log(project, "step2_execute_completed", trace_id=trace_id, source=source)
    return contract


def build_step2_scaffold_contract(
    *,
    project: Project,
    project_title: str,
    article_content: str,
    trace_id: str,
) -> Dict[str, Any]:
    profile = read_project_pipeline_profile(project)
    slide_count_text, _ = storyboard_requirements(article_content, profile)
    min_slides, max_slides = parse_range_text(slide_count_text, 4, 8)
    fallback_path = os.path.join(project.run_dir, "planning", f"visual_contract_fallback_{trace_id}.json")
    if os.path.exists(fallback_path):
        os.remove(fallback_path)

    script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "write_visual_contract.py"))
    args = [
        sys.executable,
        script_path,
        "--run-dir",
        project.run_dir,
        "--out",
        fallback_path,
        "--topic-name",
        project_title,
        "--min-slides",
        str(min_slides),
        "--max-slides",
        str(max_slides),
        "--subtitle-policy",
        "no_slides_have_subtitle",
        "--overwrite",
    ]
    write_project_log(
        project,
        "step2_scaffold_fallback_start",
        trace_id=trace_id,
        min_slides=min_slides,
        max_slides=max_slides,
        subtitle_policy="no_slides_have_subtitle",
    )
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    if result.returncode != 0 or not os.path.exists(fallback_path):
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Step2 scaffold fallback failed")
    with open(fallback_path, "r", encoding="utf-8") as f:
        contract = json.load(f)
    write_project_log(
        project,
        "step2_scaffold_fallback_generated",
        trace_id=trace_id,
        contract_path=fallback_path,
        stdout=result.stdout.strip(),
    )
    return contract


@app.post("/api/projects/{project_id}/steps/2/execute")
def execute_step2(
    project_id: str,
    payload: Optional[Dict[str, Any]] = None,
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    brief_path = os.path.join(project.run_dir, "planning", "article_brief.json")
    if not os.path.exists(brief_path):
        raise HTTPException(status_code=400, detail="请先导入文章再生成分镜")
        
    with open(brief_path, "r", encoding="utf-8") as f:
        brief = json.load(f)
    project_title = (project.name or "").strip() or brief.get("title") or "未命名项目"
    article_content = str(brief.get("content") or "")
    article_summary = brief.get("summary") or build_article_summary(article_content)
        
    llm_api_key = get_setting("llm_api_key")
    llm_base_url = get_setting("llm_base_url")
    llm_model = get_setting("llm_model")
    llm_temp = float(get_setting("llm_temperature", "0.7"))
    planning_temp = min(llm_temp, 0.2)
    planning_max_tokens = parse_int_setting(get_setting("llm_max_tokens", "50000"), 50000, 1024, 64000)
    
    if not llm_api_key:
        raise HTTPException(status_code=400, detail="未配置大模型 API 密钥，请在系统设置中配置后再试。")
        
    schema_hint = visual_contract_schema_text()
    rules_path = storyboard_rules_path(project)
    if os.path.exists(rules_path):
        with open(rules_path, "r", encoding="utf-8") as f:
            storyboard_rules = f.read().strip()
    else:
        storyboard_rules = default_storyboard_rules()
    generation_requirement = str((payload or {}).get("requirement") or "").strip()
    if not generation_requirement:
        generation_requirement = DEFAULT_STEP2_GENERATION_REQUIREMENT
    effective_storyboard_rules = (
        f"{storyboard_rules}\n\n"
        "本次生成的用户专项需求如下；只对本次生成生效，并在不破坏固定 JSON 结构和字段约束的前提下优先满足：\n"
        f"{generation_requirement}"
    )
    system_prompt, user_prompt = build_storyboard_request(
        project_title,
        article_summary,
        article_content,
        effective_storyboard_rules,
        read_project_pipeline_profile(project),
    )
    trace_id = uuid.uuid4().hex[:8]
    write_project_log(
        project,
        "step2_execute_start",
        trace_id=trace_id,
        model=llm_model,
        base_url=llm_base_url,
        max_tokens=planning_max_tokens,
        generation_requirement=generation_requirement,
    )

    try:
        client = get_openai_client(
            api_key=llm_api_key,
            base_url=llm_base_url,
            timeout=STEP2_LLM_TIMEOUT_SEC,
            max_retries=0,
        )
        try:
            response = client.chat.completions.create(
                model=llm_model,
                temperature=planning_temp,
                max_tokens=planning_max_tokens,
                timeout=STEP2_LLM_TIMEOUT_SEC,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
            )
        except Exception as inner_e:
            if is_timeout_exception(inner_e):
                raise
            logger.warning(f"Failed LLM call with response_format in step 2, retrying without it: {inner_e}")
            response = client.chat.completions.create(
                model=llm_model,
                temperature=planning_temp,
                max_tokens=planning_max_tokens,
                timeout=STEP2_LLM_TIMEOUT_SEC,
                messages=[
                    {"role": "system", "content": system_prompt + " 请只输出纯 JSON，不要包含 Markdown 代码块标记（如 ```json ）。"},
                    {"role": "user", "content": user_prompt}
                ]
            )
            
        choice = response.choices[0]
        logger.info("Step 2 LLM finish_reason=%s usage=%s", getattr(choice, "finish_reason", None), getattr(response, "usage", None))
        content_str = choice.message.content.strip()
        cleaned_content = clean_json_markdown(content_str)
        contract = parse_json_or_repair_with_llm(
            cleaned_content=cleaned_content,
            raw_content=content_str,
            client=client,
            model=llm_model,
            run_dir=project.run_dir,
            artifact_prefix="visual_contract_llm",
            schema_hint=schema_hint,
            max_tokens=planning_max_tokens,
        )
        contract = finalize_step2_contract(
            project=project,
            project_id=project_id,
            db=db,
            contract=contract,
            project_title=project_title,
            article_summary=article_summary,
            trace_id=trace_id,
            source="llm",
        )
        return {"success": True, "contract": contract, "fallback": False}
    except Exception as e:
        if is_timeout_exception(e):
            write_project_log(
                project,
                "step2_llm_timeout_fallback",
                trace_id=trace_id,
                timeout_sec=STEP2_LLM_TIMEOUT_SEC,
                error_type=type(e).__name__,
                error=str(e),
            )
            try:
                fallback_contract = build_step2_scaffold_contract(
                    project=project,
                    project_title=project_title,
                    article_content=article_content,
                    trace_id=trace_id,
                )
                fallback_contract = finalize_step2_contract(
                    project=project,
                    project_id=project_id,
                    db=db,
                    contract=fallback_contract,
                    project_title=project_title,
                    article_summary=article_summary,
                    trace_id=trace_id,
                    source="scaffold_fallback",
                )
                return {
                    "success": True,
                    "contract": fallback_contract,
                    "fallback": True,
                    "message": "AI 分镜生成超时，已生成本地可编辑分镜草稿。",
                }
            except Exception as fallback_error:
                write_project_log(
                    project,
                    "step2_scaffold_fallback_error",
                    trace_id=trace_id,
                    error_type=type(fallback_error).__name__,
                    error=str(fallback_error),
                )
        write_project_log(project, "step2_execute_error", trace_id=trace_id, error_type=type(e).__name__, error=str(e))
        logger.error(f"Write visual contract error: {e}")
        raise HTTPException(status_code=500, detail=f"本地分镜规划失败: {str(e)}")

@app.get("/api/projects/{project_id}/steps/2/result")
def get_step2_result(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    contract_path = os.path.join(project.run_dir, "planning", "visual_contract.json")
    if not os.path.exists(contract_path):
        return {"success": False, "message": "尚未生成分镜规划"}
        
    with open(contract_path, "r", encoding="utf-8") as f:
        stored_contract = json.load(f)
    contract = normalize_visual_contract(stored_contract, read_project_pipeline_profile(project))
    migration_required = json.dumps(contract, ensure_ascii=False, sort_keys=True) != json.dumps(
        stored_contract,
        ensure_ascii=False,
        sort_keys=True,
    )
    return {
        "success": True,
        "contract": contract,
        "repair": {
            "required": migration_required,
            "reasons": ["visual_contract_schema_normalization"] if migration_required else [],
            "endpoint": f"/api/projects/{project_id}/steps/2/repair",
        },
    }


@app.post("/api/projects/{project_id}/steps/2/repair")
def repair_step2_result(project_id: str, db: Session = Depends(get_db)):
    """Persist schema normalization explicitly instead of mutating on GET."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    contract_path = os.path.join(project.run_dir, "planning", "visual_contract.json")
    if not os.path.exists(contract_path):
        raise HTTPException(status_code=400, detail="尚未生成分镜规划")
    stored_contract = read_json_file(contract_path, {})
    contract = normalize_visual_contract(stored_contract, read_project_pipeline_profile(project))
    changed = json.dumps(contract, ensure_ascii=False, sort_keys=True) != json.dumps(
        stored_contract,
        ensure_ascii=False,
        sort_keys=True,
    )
    if changed:
        write_json_atomic(contract_path, contract)
        current_slide_ids = contract_slide_ids_from_payload(contract)
        sync_reveal_manifest_to_contract(project, current_slide_ids)
        sync_narration_beats_to_contract(project, current_slide_ids)
        validate_visual_contract_file(project, contract_path, source="explicit_schema_repair")
        invalidate_after_upstream_edit(project, 2, db)
    return {"success": True, "changed": changed, "contract": contract}

@app.put("/api/projects/{project_id}/steps/2/result")
def update_step2_result(project_id: str, payload: Dict[str, Any], db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    payload = normalize_visual_contract(payload, read_project_pipeline_profile(project))
    contract_path = os.path.join(project.run_dir, "planning", "visual_contract.json")
    existing_contract = read_json_file(contract_path, {})
    changed = json.dumps(existing_contract, ensure_ascii=False, sort_keys=True) != json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
    )
    if not changed:
        return {
            "success": True,
            "contract": payload,
            "validation": read_json_file(visual_contract_validation_path(project), {}),
            "changed": False,
        }
    with open(contract_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    current_slide_ids = contract_slide_ids_from_payload(payload)
    sync_reveal_manifest_to_contract(project, current_slide_ids)
    sync_narration_beats_to_contract(project, current_slide_ids)
    validation = validate_visual_contract_file(project, contract_path, source="manual_autosave")
    invalidate_after_upstream_edit(project, 2, db)

    return {"success": True, "contract": payload, "validation": validation, "changed": True}

# ==================== 步骤 3-4: 图片生成与管理 ====================

IMAGE_STYLE_TOP_LEVEL_KEYS = ("brand", "canvas", "colors", "layout", "visual_assets")
IMAGE_STYLE_PROMPT_KEY = "prompt_system_content"
IMAGE_STYLE_VISUAL_ASSET_FIELDS = {
    "image_style": "image_style",
    "diagram_style": "diagram_style",
    "required_background": "required_background",
    "layout_rules": "reveal_friendly_layout",
    "avoid": "avoid",
}


@app.get("/api/projects/{project_id}/steps/3/visual-settings")
def get_step3_visual_settings(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return {"success": True, **read_project_visual_settings(project)}


@app.put("/api/projects/{project_id}/steps/3/visual-settings")
def update_step3_visual_settings(project_id: str, payload: Dict[str, Any], db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    raw_color = str(payload.get("video_background") or "").strip().upper()
    if not re.fullmatch(r"#[0-9A-F]{6}", raw_color):
        raise HTTPException(status_code=400, detail="视频背景色必须是 #RRGGBB 格式")
    previous = read_project_visual_settings(project)
    settings = write_project_visual_settings(project, raw_color)
    sync_project_background_color(project)
    if previous["video_background"] != settings["video_background"]:
        invalidate_video_background_derivatives(project, db)
    return {"success": True, **settings}


@app.get("/api/projects/{project_id}/subtitle-settings")
def get_project_subtitle_settings(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    settings = read_project_visual_settings(project)
    return {
        "success": True,
        "subtitle_style": settings["subtitle_style"],
        "fonts": OPEN_SOURCE_CHINESE_FONTS,
        "preview_url": subtitle_preview_background_url(project),
    }


@app.put("/api/projects/{project_id}/subtitle-settings")
def update_project_subtitle_settings(
    project_id: str,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    previous = read_project_visual_settings(project)
    settings = write_project_visual_settings(
        project,
        subtitle_style=payload.get("subtitle_style") if isinstance(payload, dict) else None,
    )
    if previous["subtitle_style"] != settings["subtitle_style"]:
        invalidate_subtitle_derivatives(project, db)
    return {
        "success": True,
        "subtitle_style": settings["subtitle_style"],
        "fonts": OPEN_SOURCE_CHINESE_FONTS,
        "preview_url": subtitle_preview_background_url(project),
    }


def read_style_tokens_data() -> Dict[str, Any]:
    with open(STYLE_TOKENS_PATH, "r", encoding="utf-8") as f:
        payload = yaml.safe_load(f) or {}
    if not isinstance(payload, dict):
        raise ValueError("config/style_tokens.yaml must contain a YAML object")
    return payload


def editable_image_style_data(style_tokens: Dict[str, Any]) -> Dict[str, Any]:
    editable: Dict[str, Any] = {}
    for key in IMAGE_STYLE_TOP_LEVEL_KEYS:
        if key not in style_tokens:
            continue
        value = copy.deepcopy(style_tokens[key])
        if key == "visual_assets" and isinstance(value, dict):
            value = {
                editor_key: value[source_key]
                for editor_key, source_key in IMAGE_STYLE_VISUAL_ASSET_FIELDS.items()
                if source_key in value
            }
        editable[key] = value
    return editable


def dump_image_style_editor_text(style_tokens: Dict[str, Any]) -> str:
    prompt_text = str(style_tokens.get(IMAGE_STYLE_PROMPT_KEY) or "").strip()
    if prompt_text:
        return prompt_text
    return build_image_style_prompt(style_tokens)


def merge_image_style_update(
    style_tokens: Dict[str, Any],
    update: Dict[str, Any],
) -> Dict[str, Any]:
    unknown_keys = sorted(set(update) - set(IMAGE_STYLE_TOP_LEVEL_KEYS))
    if unknown_keys:
        raise HTTPException(
            status_code=400,
            detail=f"这些字段不属于生图配置: {', '.join(unknown_keys)}",
        )

    merged = copy.deepcopy(style_tokens)
    for key, value in update.items():
        if key != "visual_assets":
            existing_value = merged.get(key)
            if isinstance(existing_value, dict) and isinstance(value, dict):
                next_value = copy.deepcopy(existing_value)
                next_value.update(copy.deepcopy(value))
                merged[key] = next_value
            else:
                merged[key] = copy.deepcopy(value)
            continue
        if not isinstance(value, dict):
            raise HTTPException(status_code=400, detail="visual_assets 必须是 YAML 对象")
        unknown_asset_keys = sorted(set(value) - set(IMAGE_STYLE_VISUAL_ASSET_FIELDS))
        if unknown_asset_keys:
            raise HTTPException(
                status_code=400,
                detail=f"这些 visual_assets 字段不用于生图: {', '.join(unknown_asset_keys)}",
            )
        existing_assets = merged.get("visual_assets")
        if not isinstance(existing_assets, dict):
            existing_assets = {}
        for editor_key, editor_value in value.items():
            existing_assets[IMAGE_STYLE_VISUAL_ASSET_FIELDS[editor_key]] = copy.deepcopy(editor_value)
        merged["visual_assets"] = existing_assets
    canvas = merged.setdefault("canvas", {})
    if isinstance(canvas, dict):
        canvas["background"] = IMAGE_GENERATION_BACKGROUND
    colors = merged.setdefault("colors", {})
    if isinstance(colors, dict):
        for key in ("background", "surface", "paper"):
            colors[key] = IMAGE_GENERATION_BACKGROUND
    assets = merged.setdefault("visual_assets", {})
    if isinstance(assets, dict):
        assets["required_background"] = "flat_uniform_pure_white"
    return merged


def parse_image_style_payload(payload: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
    current = read_style_tokens_data()
    style_data = payload.get("style_data")
    if isinstance(style_data, dict):
        return current, merge_image_style_update(current, style_data)

    style_text = str(payload.get("style_text") or "").strip()
    if not style_text:
        raise HTTPException(status_code=400, detail="图片生成 System Content 不能为空")
    merged = copy.deepcopy(current)
    merged[IMAGE_STYLE_PROMPT_KEY] = style_text
    return current, merged


def build_image_style_prompt(style_tokens: Dict[str, Any]) -> str:
    prompt_text = str(style_tokens.get(IMAGE_STYLE_PROMPT_KEY) or "").strip()
    if prompt_text:
        return prompt_text

    brand = style_tokens.get("brand") if isinstance(style_tokens.get("brand"), dict) else {}
    canvas = style_tokens.get("canvas") if isinstance(style_tokens.get("canvas"), dict) else {}
    colors = style_tokens.get("colors") if isinstance(style_tokens.get("colors"), dict) else {}
    layout = style_tokens.get("layout") if isinstance(style_tokens.get("layout"), dict) else {}
    assets = style_tokens.get("visual_assets") if isinstance(style_tokens.get("visual_assets"), dict) else {}

    lines = ["图片风格与版式："]
    keywords = brand.get("style_keywords") if isinstance(brand.get("style_keywords"), list) else []
    if keywords:
        lines.append(f"- 整体风格：{'、'.join(str(item) for item in keywords if item)}。")

    aspect_ratio = canvas.get("aspect_ratio", "16:9")
    width = canvas.get("width", 1920)
    height = canvas.get("height", 1080)
    lines.append(
        f"- 画布：{aspect_ratio}，按 {width}x{height} 构图。"
        f"生图工作背景必须是纯白 {IMAGE_GENERATION_BACKGROUND}。"
    )

    palette_keys = ("ink", "yellow", "yellow_soft", "green_soft", "blue_soft")
    palette = [str(colors[key]) for key in palette_keys if colors.get(key)]
    if palette:
        lines.append(f"- 配色：主线条与强调色使用 {'、'.join(palette)}，保持克制和清晰。")

    title_block = layout.get("title_block") if isinstance(layout.get("title_block"), dict) else {}
    content = layout.get("content") if isinstance(layout.get("content"), dict) else {}
    subtitle_area = layout.get("subtitle_area") if isinstance(layout.get("subtitle_area"), dict) else {}
    subtitle_reserved = canvas.get("subtitle_reserved") if isinstance(canvas.get("subtitle_reserved"), dict) else {}
    if title_block:
        main_title_box = title_block.get("main_title") if isinstance(title_block.get("main_title"), dict) else {}
        title_hint = ""
        if main_title_box:
            title_hint += (
                f"主标题约在 x={main_title_box.get('x', 110)}, y={main_title_box.get('y', 55)}, "
                f"w={main_title_box.get('w', 1600)}, h={main_title_box.get('h', 86)}；"
            )
        lines.append(f"- 主标题位置固定在页面上方标题区，不生成页面副标题、下划线或占位；{title_hint}只固定位置和层级，不限制主体内容区的表达方式。")
    if content:
        lines.append(
            "- 主体内容放在页面中部开放区域"
            f"（约 x={content.get('x', 80)}, y={content.get('y', 235)}, "
            f"w={content.get('w', 1760)}, h={content.get('h', 680)}），"
            "根据内容自由选择最清楚的结构；不要机械套用卡片列表，不绘制包围整页内容的大外框。"
        )
    subtitle_y = subtitle_area.get("y") or subtitle_reserved.get("y")
    if subtitle_y is not None:
        lines.append(f"- y={subtitle_y} 以下留作视频字幕安全区，不放关键文字、人物或图形。")

    layout_rules = assets.get("reveal_friendly_layout")
    if isinstance(layout_rules, list):
        for rule in layout_rules:
            text = str(rule).strip()
            if text:
                lines.append(f"- {text}")

    avoid = assets.get("avoid")
    if isinstance(avoid, list) and avoid:
        lines.append(f"- 避免：{'、'.join(str(item) for item in avoid if item)}。")

    lines.append("- 不可变规则：画面元素严禁重叠、互相覆盖、压住、穿插或粘连；任何文字都不能被箭头、图标、卡片边框或装饰压住。")
    lines.append("- 主标题区固定布局并作为一个完整语块参与动画：必须与主体内容完全分离；标题即使包含多色文字或描边，全部字形仍归属同一个标题 Mask，不得拆成多个语块。")
    lines.append("- 每条旁白对应的主体内容必须形成一个空间连续、边界清楚的视觉岛；不同旁白视觉岛之间优先保留 48-80px 连续纯白间隔。")
    lines.append("- 大面积主配图拥有其内部和紧邻边缘的文字、图标、对号、标签与说明；其他语块的元素不得进入、跨越或贴住该配图边界。")
    lines.append("- 左右对比或前后状态只有在对应不同 narration beat 时才画成两个独立视觉岛；若共用一条旁白，改为一个统一构图，避免两个插图被迫同时 Reveal。")
    lines.append("- 当前风格词优先：如果参考图与当前风格词冲突，以当前风格词、画面表现方式和图示风格为准。")
    lines.append("- 参考图只作为标题区位置、留白、层级和示例密度参考；除非当前风格明确要求手绘/白板，否则不要复制手绘笔迹、纸感或粗糙线稿。")
    lines.append("- 严禁画面元素重叠：文字、图标、箭头、线条、标签、卡片边框之间不得互相覆盖、穿插或粘连。")
    lines.append("- 参考图只用于风格气质、标题区位置、线条粗细、配色、留白、层级和密度参考；不得覆盖“主体内容自由表达”和“元素不重叠”的规则。")
    lines.append("- 四条边和四个角必须保持连续纯白，不要纸纹、阴影、噪声、渐变或暗角。")
    lines.append("- 卡片、文字和图标内部允许使用白色；系统只会移除与画面外围连通的白色。")
    lines.append("- 只生成最终静态整页图片，不要加入图层名称、制作说明或播放器界面。")
    return "\n".join(lines)


def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def active_style_reference_paths() -> List[str]:
    return [
        os.path.join(STYLE_REFERENCE_DIR, filename)
        for filename in STYLE_REFERENCE_FILES.values()
        if os.path.exists(os.path.join(STYLE_REFERENCE_DIR, filename))
    ]


def active_references_are_default_handdrawn(reference_paths: List[str]) -> bool:
    if not reference_paths:
        return False
    for path in reference_paths:
        filename = os.path.basename(path)
        default_path = os.path.join(DEFAULT_STYLE_REFERENCE_DIR, filename)
        if not os.path.exists(default_path):
            return False
        try:
            if file_sha256(path) != file_sha256(default_path):
                return False
        except OSError:
            return False
    return True


def style_prefers_handdrawn_reference(style_tokens: Dict[str, Any]) -> bool:
    brand = style_tokens.get("brand") if isinstance(style_tokens.get("brand"), dict) else {}
    assets = style_tokens.get("visual_assets") if isinstance(style_tokens.get("visual_assets"), dict) else {}
    positive_parts: List[str] = []
    keywords = brand.get("style_keywords") if isinstance(brand.get("style_keywords"), list) else []
    positive_parts.extend(str(item) for item in keywords if item)
    positive_parts.append(str(assets.get("image_style") or ""))
    positive_parts.append(str(assets.get("diagram_style") or ""))
    text = "\n".join(positive_parts).lower()
    handdrawn_hints = (
        "手绘",
        "白板",
        "线稿",
        "手写",
        "马克笔",
        "涂鸦",
        "sketch",
        "handdrawn",
        "hand-drawn",
        "whiteboard",
        "marker",
    )
    return any(hint in text for hint in handdrawn_hints)


def should_send_style_reference_images(
    *,
    model: str,
    base_url: Optional[str],
    reference_paths: List[str],
    style_tokens: Dict[str, Any],
) -> bool:
    if not reference_paths:
        return False
    if not str(model).startswith("gpt-image") or is_seedream_image_model(model, base_url):
        return False
    if active_references_are_default_handdrawn(reference_paths) and not style_prefers_handdrawn_reference(style_tokens):
        return False
    return True


@app.get("/api/image-style")
def get_image_style():
    references = {}
    for kind, filename in STYLE_REFERENCE_FILES.items():
        path = os.path.join(STYLE_REFERENCE_DIR, filename)
        references[kind] = {
            "exists": os.path.exists(path),
            "url": f"/api/image-style/reference/{kind}?t={int(os.path.getmtime(path))}" if os.path.exists(path) else "",
        }
    style_tokens = read_style_tokens_data()
    return {
        "success": True,
        "style_text": dump_image_style_editor_text(style_tokens),
        "style_data": editable_image_style_data(style_tokens),
        "protected_rules": [
            "画布固定为 1920×1080、16:9",
            "生图背景固定为纯白 #FFFFFF，确保 Mask 外围背景可稳定移除",
            "主标题固定在页面上方标题区；不生成页面副标题",
            "y=930 以下为字幕安全区，不放关键内容",
            "画面元素严禁重叠、穿插、压住或粘连，保证后续 Mask 可标注",
            "主体内容区可以自由发挥，但所有画面元素严禁重叠、覆盖、压住、穿插或粘连",
            "高级 YAML 只允许 brand、canvas、colors、layout、visual_assets 顶层字段",
        ],
        "references": references,
    }


@app.put("/api/image-style")
def update_image_style(payload: Dict[str, Any]):
    _, merged = parse_image_style_payload(payload)
    with open(STYLE_TOKENS_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(
            merged,
            f,
            allow_unicode=True,
            sort_keys=False,
            width=1000,
        )
    return {
        "success": True,
        "style_text": dump_image_style_editor_text(merged),
        "style_data": editable_image_style_data(merged),
        "prompt_preview": build_image_style_prompt(merged),
    }


@app.post("/api/image-style/validate")
def validate_image_style(payload: Dict[str, Any]):
    _, merged = parse_image_style_payload(payload)
    return {
        "success": True,
        "style_text": dump_image_style_editor_text(merged),
        "style_data": editable_image_style_data(merged),
        "prompt_preview": build_image_style_prompt(merged),
    }


def read_image_style_template_index() -> List[Dict[str, Any]]:
    payload = read_json_file(IMAGE_STYLE_TEMPLATES_INDEX, [])
    return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def image_style_template_source(template_id: str) -> tuple[str, str]:
    if template_id == "default":
        return DEFAULT_STYLE_TOKENS_PATH, DEFAULT_STYLE_REFERENCE_DIR
    if template_id == "handdrawn_explainer":
        return HANDDRAWN_STYLE_TOKENS_PATH, DEFAULT_STYLE_REFERENCE_DIR
    if not re.fullmatch(r"[0-9a-f]{12}", template_id):
        raise HTTPException(status_code=404, detail="图片风格模板不存在")
    item = next(
        (
            entry
            for entry in read_image_style_template_index()
            if str(entry.get("id") or "") == template_id
        ),
        None,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="图片风格模板不存在")
    template_dir = os.path.join(IMAGE_STYLE_TEMPLATES_DIR, template_id)
    return os.path.join(template_dir, "style_tokens.yaml"), os.path.join(template_dir, "references")


def image_style_template_detail(template_id: str) -> Dict[str, Any]:
    if template_id == "default":
        item = {
            "id": "default",
            "name": "内容优先通用图片风格模板",
            "built_in": True,
            "updated_at": "",
        }
    elif template_id == "handdrawn_explainer":
        item = {
            "id": "handdrawn_explainer",
            "name": "手绘科普内容优先图片风格模板",
            "built_in": True,
            "updated_at": "",
        }
    else:
        item = next(
            (
                copy.deepcopy(entry)
                for entry in read_image_style_template_index()
                if str(entry.get("id") or "") == template_id
            ),
            None,
        )
        if item is None:
            raise HTTPException(status_code=404, detail="图片风格模板不存在")
        item["built_in"] = False
    style_path, reference_dir = image_style_template_source(template_id)
    if not os.path.exists(style_path):
        raise HTTPException(status_code=404, detail="图片风格模板配置缺失")
    with open(style_path, "r", encoding="utf-8-sig") as file:
        style_tokens = yaml.safe_load(file) or {}
    if not isinstance(style_tokens, dict):
        raise HTTPException(status_code=400, detail="图片风格模板配置损坏")
    references = {}
    for kind, filename in STYLE_REFERENCE_FILES.items():
        path = os.path.join(reference_dir, filename)
        references[kind] = {
            "exists": os.path.exists(path),
            "url": (
                f"/api/image-style/templates/{template_id}/reference/{kind}"
                f"?t={int(os.path.getmtime(path))}"
                if os.path.exists(path)
                else ""
            ),
        }
    return {
        **item,
        "style_text": dump_image_style_editor_text(style_tokens),
        "style_data": editable_image_style_data(style_tokens),
        "references": references,
    }


def list_image_style_templates() -> List[Dict[str, Any]]:
    result = [
        image_style_template_detail("default"),
    ]
    for item in read_image_style_template_index():
        template_id = str(item.get("id") or "")
        if not template_id:
            continue
        try:
            result.append(image_style_template_detail(template_id))
        except HTTPException as exc:
            logger.warning("Skipping invalid image style template %s: %s", template_id, exc.detail)
    return result


@app.get("/api/image-style/templates")
def get_image_style_templates():
    return {"success": True, "templates": list_image_style_templates()}


@app.get("/api/image-style/templates/{template_id}")
def get_image_style_template(template_id: str):
    return {"success": True, "template": image_style_template_detail(template_id)}


@app.post("/api/image-style/templates")
def save_image_style_template(payload: Dict[str, Any]):
    ensure_active_image_style_storage()
    name = normalized_template_name(payload.get("name"))
    protected_names = {"默认图片风格模板", "内容优先通用图片风格模板", "手绘科普内容优先图片风格模板"}
    if name.casefold() in {item.casefold() for item in protected_names}:
        raise HTTPException(status_code=400, detail="内置图片风格模板名称不可覆盖")
    index = read_image_style_template_index()
    existing = next(
        (
            item
            for item in index
            if str(item.get("name") or "").strip().casefold() == name.casefold()
        ),
        None,
    )
    now = template_timestamp()
    if existing is None:
        existing = {"id": uuid.uuid4().hex[:12], "created_at": now}
        index.append(existing)
    template_id = str(existing["id"])
    existing.update({"name": name, "updated_at": now})
    template_dir = os.path.join(IMAGE_STYLE_TEMPLATES_DIR, template_id)
    reference_dir = os.path.join(template_dir, "references")
    os.makedirs(reference_dir, exist_ok=True)
    shutil.copy2(STYLE_TOKENS_PATH, os.path.join(template_dir, "style_tokens.yaml"))
    for filename in STYLE_REFERENCE_FILES.values():
        source = os.path.join(STYLE_REFERENCE_DIR, filename)
        target = os.path.join(reference_dir, filename)
        if os.path.exists(source):
            shutil.copy2(source, target)
        elif os.path.exists(target):
            os.remove(target)
    write_json_atomic(IMAGE_STYLE_TEMPLATES_INDEX, index)
    return {
        "success": True,
        "template": image_style_template_detail(template_id),
        "templates": list_image_style_templates(),
    }


@app.delete("/api/image-style/templates/{template_id}")
def delete_image_style_template(template_id: str):
    if template_id == "default":
        raise HTTPException(status_code=400, detail="内置图片风格模板不能删除")
    if not re.fullmatch(r"[0-9a-f]{12}", template_id):
        raise HTTPException(status_code=404, detail="图片风格模板不存在")
    index = read_image_style_template_index()
    next_index = [
        item
        for item in index
        if not (isinstance(item, dict) and str(item.get("id") or "") == template_id)
    ]
    if len(next_index) == len(index):
        raise HTTPException(status_code=404, detail="图片风格模板不存在")
    write_json_atomic(IMAGE_STYLE_TEMPLATES_INDEX, next_index)
    base_dir = os.path.abspath(IMAGE_STYLE_TEMPLATES_DIR)
    template_dir = os.path.abspath(os.path.join(IMAGE_STYLE_TEMPLATES_DIR, template_id))
    if os.path.commonpath([base_dir, template_dir]) != base_dir:
        raise HTTPException(status_code=400, detail="图片风格模板路径异常")
    if os.path.exists(template_dir):
        shutil.rmtree(template_dir)
    return {"success": True, "templates": list_image_style_templates()}


@app.post("/api/image-style/templates/{template_id}/apply-references")
def apply_image_style_template_references(template_id: str):
    ensure_active_image_style_storage()
    _, source_dir = image_style_template_source(template_id)
    for filename in STYLE_REFERENCE_FILES.values():
        source = os.path.join(source_dir, filename)
        target = os.path.join(STYLE_REFERENCE_DIR, filename)
        if os.path.exists(source):
            shutil.copy2(source, target)
        elif os.path.exists(target):
            os.remove(target)
    return {
        "success": True,
        "references": {
            kind: {
                "exists": os.path.exists(os.path.join(STYLE_REFERENCE_DIR, filename)),
                "url": (
                    f"/api/image-style/reference/{kind}?t={uuid.uuid4().hex[:8]}"
                    if os.path.exists(os.path.join(STYLE_REFERENCE_DIR, filename))
                    else ""
                ),
            }
            for kind, filename in STYLE_REFERENCE_FILES.items()
        },
    }


@app.get("/api/image-style/templates/{template_id}/reference/{kind}")
def get_image_style_template_reference(template_id: str, kind: str):
    filename = STYLE_REFERENCE_FILES.get(kind)
    if not filename:
        raise HTTPException(status_code=404, detail="参考图类型不存在")
    _, reference_dir = image_style_template_source(template_id)
    path = os.path.join(reference_dir, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="模板参考图不存在")
    return FileResponse(path, media_type="image/png")


@app.get("/api/image-style/reference/{kind}")
def get_image_style_reference(kind: str):
    filename = STYLE_REFERENCE_FILES.get(kind)
    if not filename:
        raise HTTPException(status_code=404, detail="参考图类型不存在")
    path = os.path.join(STYLE_REFERENCE_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="参考图不存在")
    return FileResponse(path, media_type="image/png")


@app.post("/api/image-style/reference/{kind}")
def update_image_style_reference(kind: str, file: UploadFile = File(...)):
    ensure_active_image_style_storage()
    filename = STYLE_REFERENCE_FILES.get(kind)
    if not filename:
        raise HTTPException(status_code=404, detail="参考图类型不存在")
    content = file.file.read(MAX_IMAGE_UPLOAD_BYTES + 1)
    try:
        image = open_validated_image(content).convert("RGB")
        os.makedirs(STYLE_REFERENCE_DIR, exist_ok=True)
        image.save(os.path.join(STYLE_REFERENCE_DIR, filename), "PNG")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"参考图不是有效图片: {exc}")
    return {"success": True, "url": f"/api/image-style/reference/{kind}?t={uuid.uuid4().hex[:8]}"}


# 辅助生成某一页 PPT 生图的 Prompt。
def compact_slide_element_lines(slide: Dict[str, Any]) -> List[str]:
    slide_id = str(slide.get("slide_id") or "").strip()
    prefix = f"{slide_id}_" if slide_id else ""
    lines: List[str] = []
    for idx, group in enumerate(slide.get("visual_groups", []) or [], start=1):
        if not isinstance(group, dict):
            continue
        group_id = str(group.get("id") or "").strip()
        element_id = str(group.get("element_id") or "").strip()
        if not element_id:
            element_id = group_id[len(prefix):] if prefix and group_id.startswith(prefix) else (group_id or f"el_{idx:03d}")
        role = str(group.get("role") or "content_body").strip()
        visual_type = normalize_visual_type(
            group.get("visual_type"),
            has_text=bool(str(group.get("display_text") or "").strip()),
        )
        if visual_type == "text":
            description = str(group.get("display_text") or group.get("visual_anchor") or group.get("visible_text") or "").strip()
        else:
            description = str(group.get("visual_anchor") or group.get("mask_target") or group.get("visible_text") or "").strip()
        if not description:
            continue
        lines.append(
            f"- slide_id={slide_id}; element_id={element_id}; role={role}; "
            f"visual_type={visual_type}; visual_description={description}"
        )
    return lines


def generate_prompt_for_slide(
    slide: Dict[str, Any],
    topic_name: str,
    profile: Optional[Dict[str, Any]] = None,
) -> str:
    style_prompt = build_image_style_prompt(read_style_tokens_data())
    return compose_step3_single_slide_prompt(style_prompt, slide)


def build_step3_global_image_prompt(style_prompt: str) -> str:
    return (
        "整体风格提示词：\n"
        f"{str(style_prompt or '').strip()}\n\n"
        "全局统一生成要求：\n"
        "- 每个 Slide 生成一张独立的 16:9 PPT 静态主图，不要把多个 Slide 合并到同一张图。\n"
        "- 背景必须是纯白 #FFFFFF，四条边和四个角保持连续纯白。\n"
        "- 如果请求附带一张参考图，只把它作为整体风格、留白、层级、配色和密度参考。\n"
        "- 只根据各 Slide 的元素清单组织画面；不要加入 narration、讲稿、制作说明或额外页面。\n"
        "- 每个元素都要清晰分离，方便后续人工 Mask；元素之间不得重叠、穿插、压住或粘连。"
    )


def build_step3_slide_specific_prompt(slide: Dict[str, Any]) -> str:
    slide_id = str(slide.get("slide_id") or "").strip()
    elements_str = "\n".join(compact_slide_element_lines(slide)) or "- 无可用视觉元素"
    return (
        f"Slide ID: {slide_id}\n"
        "元素清单（程序已从 Step 2B 精简）：\n"
        f"{elements_str}"
    )


def compose_step3_single_slide_prompt(style_prompt: str, slide: Dict[str, Any]) -> str:
    return f"{build_step3_global_image_prompt(style_prompt)}\n\n当前 Slide 具体内容：\n{build_step3_slide_specific_prompt(slide)}"


def compose_step3_batch_copy_prompt(style_prompt: str, slides: List[Dict[str, Any]]) -> str:
    slide_sections = []
    for slide in slides:
        if not isinstance(slide, dict):
            continue
        slide_id = str(slide.get("slide_id") or "").strip() or "未命名"
        slide_sections.append(f"--- Slide {slide_id} ---\n{build_step3_slide_specific_prompt(slide)}")
    return (
        "请按以下统一要求，依次为每个 Slide 分别生成 1 张独立图片。\n"
        "先完整理解全局说明，再逐页读取具体内容；不要把多个 Slide 合并到一张图片中。\n\n"
        "=== 全局统一说明（仅出现一次） ===\n"
        f"{build_step3_global_image_prompt(style_prompt)}\n\n"
        "=== 各 Slide 具体内容 ===\n\n"
        + "\n\n".join(slide_sections)
    ).strip()


def enforce_white_generation_background(prompt: str) -> str:
    return (
        f"{prompt.strip()}\n\n"
        "不可覆盖的背景要求：整张图片的工作背景必须是纯白 #FFFFFF。"
        "四条边和四个角必须连续纯白；不要米白、暖白、纸纹、噪声、阴影、渐变或暗角。"
        "不要把纯白背景画进卡片或内容轮廓之外的装饰区域。\n"
        "不可覆盖的布局要求：主标题必须位于页面上方固定标题区，整页不生成页面副标题、下划线或占位；底部 y=930..1080 必须保留为视频字幕安全区。"
        "主体内容区可以自由发挥，但画面元素严禁重叠、覆盖、压住、穿插或粘连；文字、图标、箭头、卡片、标签、装饰和图表之间必须保留清晰间距，方便后续人工 Mask。"
        "\n不可覆盖的 Mask 要求：严禁画面元素重叠。文字、图标、箭头、线条、标签、卡片边框、人物和装饰之间不得互相覆盖、穿插、压住或粘连；每个语义元素之间必须留出清晰空白。"
    )


@app.get("/api/projects/{project_id}/steps/3/prompts")
def get_slide_prompts(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    contract_path = os.path.join(project.run_dir, "planning", "visual_contract.json")
    if not os.path.exists(contract_path):
        raise HTTPException(status_code=400, detail="分镜规划尚未生成")
        
    with open(contract_path, "r", encoding="utf-8") as f:
        contract = json.load(f)
        
    # 单页生成仍返回完整 Prompt；网页端批量复制另用一份全局说明 + 每页差异内容。
    slide_prompts = []
    slides = [slide for slide in contract.get("slides", []) if isinstance(slide, dict)]
    topic = contract.get("topic") if isinstance(contract.get("topic"), dict) else {}
    topic_name = str(topic.get("topic_name") or project.name or "")
    style_prompt = profile_style_prompt(project, sys.modules[__name__])
    for slide in slides:
        slide_id = slide["slide_id"]
        generated_prompt = project_generate_prompt_for_slide(
            sys.modules[__name__], project, slide, topic_name
        )
        slide_prompts.append({
            "slide_id": slide_id,
            "title": slide["main_title"],
            "prompt": generated_prompt,
            "slide_prompt": build_step3_slide_specific_prompt(slide),
        })
        
    return {
        "success": True,
        "prompts": slide_prompts,
        "global_prompt": build_step3_global_image_prompt(style_prompt),
        "batch_prompt": compose_step3_batch_copy_prompt(style_prompt, slides),
    }

@app.post("/api/projects/{project_id}/steps/3/generate")
def generate_slide_image(
    project_id: str,
    slide_id: str = Form(...),
    prompt: str = Form(...),
    preview: bool = Form(False),
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    api_key = get_setting("image_api_key")
    base_url = get_setting("image_base_url")
    model = get_setting("image_model", "gpt-image-1")
    image_filename = "visual_candidate.png" if preview else "visual_draft.png"
    save_path = current_slide_file_or_404(project, slide_id, image_filename)
    
    if not api_key:
        raise HTTPException(status_code=400, detail="未配置生图 API 密钥，请在系统设置中配置，或使用下方本地上传图片功能。")
        
    try:
        client = get_openai_client(api_key=api_key, base_url=base_url)
        image_size = get_setting("image_size", "1024x1024")
        effective_prompt = enforce_white_generation_background(prompt)
        logger.info(f"Generating image for {slide_id} using {model}, size={image_size}, prompt: {effective_prompt[:80]}")

        response = None
        used_reference_paths: List[str] = []
        project_references = project_reference_paths(project)
        if project_references:
            reference_paths = project_references
            use_reference_images = can_send_project_references(
                sys.modules[__name__], model, base_url, reference_paths
            )
        else:
            style_tokens = read_style_tokens_data()
            reference_paths = active_style_reference_paths()
            use_reference_images = should_send_style_reference_images(
                model=model,
                base_url=base_url,
                reference_paths=reference_paths,
                style_tokens=style_tokens,
            )
        if reference_paths and not use_reference_images:
            logger.info(
                "Skipping binary style reference images for %s: active references are not compatible with current model/style.",
                slide_id,
            )
        if use_reference_images:
            reference_files = []
            try:
                reference_files = [open(path, "rb") for path in reference_paths]
                response = client.images.edit(
                    model=model,
                    image=reference_files,
                    prompt=effective_prompt,
                    size=image_size,
                    n=1,
                )
                used_reference_paths = list(reference_paths)
                logger.info("Image generation used %s style reference images.", len(reference_files))
            except Exception as reference_error:
                logger.warning("Reference image generation is unavailable, falling back to images.generate: %s", reference_error)
            finally:
                for reference_file in reference_files:
                    reference_file.close()

        if response is None:
            response = generate_image_response(
                client=client,
                model=model,
                prompt=effective_prompt,
                size=image_size,
                base_url=base_url,
            )

        # ── 兼容两种响应格式：URL 和 base64 (b64_json) ──
        img_bytes = extract_image_bytes_from_response(response)

        process_and_save_image(img_bytes, save_path)
        write_visual_provenance(
            project.run_dir,
            slide_id,
            image_path=save_path,
            provider="openai_compatible",
            source_type="api_generation",
            model=model,
            prompt=effective_prompt,
            reference_paths=used_reference_paths,
            source_bytes=img_bytes,
            candidate=preview,
        )
        logger.info(f"Image saved for {slide_id}: {save_path}")
        if preview:
            return {
                "success": True,
                "candidate_url": f"/api/projects/{project_id}/slides/{slide_id}/candidate?t={uuid.uuid4().hex[:6]}",
            }
        mark_slide_image_changed(project, slide_id, db)
        
        return {"success": True, "image_url": f"/api/projects/{project_id}/slides/{slide_id}/image?t={uuid.uuid4().hex[:6]}"}
    except Exception as e:
        logger.error(f"Image generation error for {slide_id}: {e}")
        raise HTTPException(status_code=500, detail=f"生成图片失败: {str(e)}")

@app.post("/api/projects/{project_id}/steps/3/upload")
def upload_slide_image(project_id: str, slide_id: str = Form(...), file: UploadFile = File(...), db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    save_path = current_slide_file_or_404(project, slide_id, "visual_draft.png")
    try:
        content = file.file.read(MAX_IMAGE_UPLOAD_BYTES + 1)
        if len(content) > MAX_IMAGE_UPLOAD_BYTES:
            raise ValueError(f"图片文件超过 {MAX_IMAGE_UPLOAD_BYTES // (1024 * 1024)} MB 限制")
        process_and_save_image(content, save_path)
        write_visual_provenance(
            project.run_dir,
            slide_id,
            image_path=save_path,
            provider="manual_upload",
            source_type="local_upload",
            source_bytes=content,
            source_filename=str(file.filename or ""),
        )
        mark_slide_image_changed(project, slide_id, db)
        return {"success": True, "image_url": f"/api/projects/{project_id}/slides/{slide_id}/image?t={uuid.uuid4().hex[:6]}"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Upload image error for {slide_id}: {e}")
        raise HTTPException(status_code=500, detail=f"上传图片失败: {str(e)}")

# 获取指定页面的图片资源接口
@app.get("/api/projects/{project_id}/slides/{slide_id}/image")
def get_slide_image_file(project_id: str, slide_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    img_path = current_slide_file_or_404(project, slide_id, "visual_draft.png")
    if not os.path.exists(img_path):
        raise HTTPException(status_code=404, detail="图片不存在")
        
    return FileResponse(img_path, media_type="image/png")


@app.get("/api/projects/{project_id}/slides/{slide_id}/candidate")
def get_slide_candidate_file(project_id: str, slide_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    candidate_path = current_slide_file_or_404(project, slide_id, "visual_candidate.png")
    if not os.path.exists(candidate_path):
        raise HTTPException(status_code=404, detail="候选图片不存在")
    return FileResponse(candidate_path, media_type="image/png")


@app.post("/api/projects/{project_id}/steps/3/apply-candidate")
def apply_slide_candidate(project_id: str, payload: Dict[str, Any], db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    slide_id = str(payload.get("slide_id") or "").strip()
    candidate_path = current_slide_file_or_404(project, slide_id, "visual_candidate.png")
    image_path = current_slide_file_or_404(project, slide_id, "visual_draft.png")
    if not os.path.exists(candidate_path):
        raise HTTPException(status_code=404, detail="候选图片不存在，请先生成")

    os.replace(candidate_path, image_path)
    promote_candidate_provenance(project.run_dir, slide_id)
    mark_slide_image_changed(project, slide_id, db)
    return {
        "success": True,
        "image_url": f"/api/projects/{project_id}/slides/{slide_id}/image?t={uuid.uuid4().hex[:6]}",
    }


@app.delete("/api/projects/{project_id}/steps/3/images/{slide_id}")
def delete_slide_image(project_id: str, slide_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    image_path = current_slide_file_or_404(project, slide_id, "visual_draft.png")
    candidate_path = current_slide_file_or_404(project, slide_id, "visual_candidate.png")
    if not os.path.exists(image_path):
        raise HTTPException(status_code=404, detail="图片不存在")
    os.remove(image_path)
    if os.path.exists(candidate_path):
        os.remove(candidate_path)
    for candidate in (
        visual_provenance_path(project.run_dir, slide_id),
        visual_provenance_path(project.run_dir, slide_id, candidate=True),
    ):
        try:
            candidate.unlink()
        except FileNotFoundError:
            pass
    mark_slide_image_changed(project, slide_id, db)
    return {"success": True, "slide_id": slide_id}

@app.get("/api/projects/{project_id}/steps/3/images")
def get_all_images(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    slides_dir = os.path.join(project.run_dir, "slides")
    contract_path = os.path.join(project.run_dir, "planning", "visual_contract.json")
    contract_slide_ids: List[str] = []
    if os.path.exists(contract_path):
        try:
            with open(contract_path, "r", encoding="utf-8") as f:
                contract = json.load(f)
            contract_slide_ids = [
                str(slide.get("slide_id", "")).strip()
                for slide in contract.get("slides", [])
                if isinstance(slide, dict) and str(slide.get("slide_id", "")).strip()
            ]
        except Exception as exc:
            logger.warning(f"Failed to read visual contract for image list filtering: {exc}")
    results = []

    if contract_slide_ids:
        for slide_id in contract_slide_ids:
            img_file = os.path.join(slides_dir, slide_id, "visual_draft.png")
            exists = os.path.exists(img_file)
            results.append({
                "slide_id": slide_id,
                "exists": exists,
                "url": f"/api/projects/{project_id}/slides/{slide_id}/image?t={uuid.uuid4().hex[:4]}" if exists else None,
                "provenance": visual_provenance_status(project.run_dir, slide_id) if exists else None,
            })
    elif os.path.exists(slides_dir):
        # 扫描 slides 目录下的子目录，按名称字母排序
        for slide_dir_name in sorted(os.listdir(slides_dir)):
            slide_path = os.path.join(slides_dir, slide_dir_name)
            if os.path.isdir(slide_path):
                img_file = os.path.join(slide_path, "visual_draft.png")
                exists = os.path.exists(img_file)
                results.append({
                    "slide_id": slide_dir_name,
                    "exists": exists,
                    "url": f"/api/projects/{project_id}/slides/{slide_dir_name}/image?t={uuid.uuid4().hex[:4]}" if exists else None,
                    "provenance": visual_provenance_status(project.run_dir, slide_dir_name) if exists else None,
                })
    return {
        "success": True,
        "images": results,
        "order_version": slide_order_version([item["slide_id"] for item in results]),
    }


def slide_order_version(slide_ids: List[str]) -> str:
    return sha256_json({"slide_ids": [str(slide_id) for slide_id in slide_ids]})


@app.put("/api/projects/{project_id}/steps/3/order")
def update_step3_order(project_id: str, payload: Dict[str, Any], db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    raw_slide_ids = payload.get("slide_ids", [])
    if not isinstance(raw_slide_ids, list):
        raise HTTPException(status_code=400, detail="slide_ids 必须是数组")
    requested_ids = [
        str(slide_id).strip()
        for slide_id in raw_slide_ids
        if str(slide_id).strip()
    ]
    if not requested_ids:
        raise HTTPException(status_code=400, detail="排序列表不能为空")
    if len(requested_ids) != len(set(requested_ids)):
        raise HTTPException(status_code=400, detail="排序列表包含重复的 slide_id")

    expected_version = str(payload.get("order_version") or "").strip()
    if not expected_version:
        raise HTTPException(status_code=428, detail="缺少排序版本，请刷新页面后重试")

    contract_path = os.path.join(project.run_dir, "planning", "visual_contract.json")
    if not os.path.exists(contract_path):
        raise HTTPException(status_code=400, detail="分镜规划尚未生成")
    changed = False
    with reveal_lock_for(project):
        with open(contract_path, "r", encoding="utf-8") as f:
            contract = json.load(f)

        slides = contract.get("slides", [])
        by_id = {
            str(slide.get("slide_id") or "").strip(): slide
            for slide in slides
            if isinstance(slide, dict) and str(slide.get("slide_id") or "").strip()
        }
        current_ids = list(by_id)
        current_version = slide_order_version(current_ids)
        if expected_version != current_version:
            raise HTTPException(status_code=409, detail="页面顺序已被其他操作更新，请刷新后重试")
        if set(requested_ids) != set(by_id):
            raise HTTPException(status_code=400, detail="排序列表与当前分镜不一致，请刷新页面后重试")

        changed = requested_ids != current_ids
        if changed:
            contract["slides"] = [by_id[slide_id] for slide_id in requested_ids]
            write_json_atomic(contract_path, contract)
            refresh_provenance_contract_hashes(project.run_dir, requested_ids)
            sync_reveal_manifest_to_contract(project, requested_ids)
            sync_narration_beats_to_contract(project, requested_ids)

    if changed:
        clear_remotion_props(project.run_dir)
        current_status = project.get_step_status()
        mark_selected_stale(current_status, (8,))
        project.set_step_status(current_status)
        db.commit()
    return {
        "success": True,
        "slide_ids": requested_ids,
        "order_version": slide_order_version(requested_ids),
    }


@app.post("/api/projects/{project_id}/steps/3/confirm")
def confirm_images(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    slide_ids = read_current_slide_ids_or_404(project)
    missing_images = [
        slide_id for slide_id in slide_ids
        if not os.path.exists(os.path.join(project.run_dir, "slides", slide_id, "visual_draft.png"))
    ]
    if missing_images:
        raise HTTPException(status_code=400, detail=f"以下页面还没有图片: {', '.join(missing_images)}")
    provenance_errors = validate_visual_provenance_set(project.run_dir, slide_ids)
    if provenance_errors:
        details = ", ".join(f"{item['slide_id']}({item['reason']})" for item in provenance_errors)
        raise HTTPException(status_code=409, detail=f"以下页面图片来源缺失或已过期，请重新生成或上传: {details}")
        
    # 步骤4：确认图片。将步骤 3 与 4 状态标记为已完成
    # 自动调用 write_reveal_manifest_template.py 生成 manifest 模板
    manifest_path = os.path.join(project.run_dir, "reveal_manifest.json")
    if not os.path.exists(manifest_path):
        template_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "write_reveal_manifest_template.py"))
        res = subprocess.run([
            sys.executable, template_script, "--run-dir", project.run_dir
        ], capture_output=True, text=True, encoding="utf-8", timeout=90)
        if res.returncode != 0:
            logger.error(f"Failed to write reveal manifest template: {res.stderr}")
            write_project_log(
                project,
                "step5_manifest_template_error",
                returncode=res.returncode,
                stdout=res.stdout.strip(),
                stderr=res.stderr.strip(),
            )
            raise HTTPException(status_code=500, detail="自动创建 Mask 标注文件失败，请确认分镜规划正常")
            
        # Final rendering is manual-mask-only. Do not run historical box-fitting
        # algorithms during normal project initialization.
    sync_reveal_manifest_to_contract(project)
    refresh_reveal_semantic_blocks(project)

    handle_step_navigation(project, 4, db)
    return {"success": True}

# ==================== 步骤 5: Mask 自动标注与编辑 ====================

NARRATION_SPLIT_DELIMITERS = set("，,。.!！；;？?")
QUOTE_PAIRS = {
    "“": "”",
    "‘": "’",
    "「": "」",
    "『": "』",
    "《": "》",
    "（": "）",
    "(": ")",
    "[": "]",
    "【": "】",
    "{": "}",
}
INLINE_QUOTE_MARKS = {"`", "\""}

ROLE_LABELS = {
    "title": "主标题",
    "subtitle": "副标题",
    "summary": "总结区",
    "diagram": "图示",
    "annotation": "注释",
    "decoration": "装饰元素",
    "content_body": "正文内容",
}


def role_label(role: str) -> str:
    return ROLE_LABELS.get(str(role or "").strip(), "正文内容")


def split_narration_text(text: str) -> List[str]:
    value = str(text or "").strip()
    if not value:
        return []
    parts: List[str] = []
    stack: List[str] = []
    start = 0
    i = 0
    while i < len(value):
        ch = value[i]
        if ch in INLINE_QUOTE_MARKS:
            if stack and stack[-1] == ch:
                stack.pop()
            else:
                stack.append(ch)
        elif ch in QUOTE_PAIRS:
            stack.append(QUOTE_PAIRS[ch])
        elif stack and ch == stack[-1]:
            stack.pop()

        is_decimal_point = (
            ch == "."
            and i > 0
            and i + 1 < len(value)
            and value[i - 1].isdigit()
            and value[i + 1].isdigit()
        )
        should_split = (ch == "\n") or (ch in NARRATION_SPLIT_DELIMITERS and not stack and not is_decimal_point)
        if should_split:
            end = i + 1
            parts.append(value[start:end].strip())
            start = end
        i += 1
    if start < len(value):
        parts.append(value[start:].strip())
    return [part.strip() for part in parts if part.strip()]


def build_narration_fragments(contract_slide: Dict[str, Any]) -> List[Dict[str, Any]]:
    fragments: List[Dict[str, Any]] = []
    for beat_idx, beat in enumerate(contract_slide.get("narration_beats", []) or []):
        if not isinstance(beat, dict):
            continue
        beat_id = str(beat.get("id") or f"beat_{beat_idx + 1}").strip()
        group_id = str(beat.get("group_id") or "").strip()
        for frag_idx, text in enumerate(split_narration_text(str(beat.get("spoken_text", ""))), start=1):
            fragments.append({
                "id": f"{beat_id}::{frag_idx}",
                "beat_id": beat_id,
                "group_id": group_id,
                "beat_index": beat_idx,
                "fragment_index": frag_idx - 1,
                "order": len(fragments) + 1,
                "text": text,
            })
    return fragments


def box_to_xyxy(box: Any) -> List[int]:
    if isinstance(box, dict):
        x = int(round(float(box.get("x", 860))))
        y = int(round(float(box.get("y", 460))))
        w = int(round(float(box.get("w", 200))))
        h = int(round(float(box.get("h", 160))))
        return [x, y, max(x + 1, x + w), max(y + 1, y + h)]
    if isinstance(box, list) and len(box) >= 4:
        return [int(round(float(v))) for v in box[:4]]
    return [860, 460, 1060, 620]


def group_has_paint(group: Dict[str, Any]) -> bool:
    manual_mask = group.get("manual_mask")
    if not isinstance(manual_mask, dict):
        return False
    rle = manual_mask.get("rle")
    if isinstance(rle, dict) and rle.get("encoding") == "row_runs_v1":
        runs = rle.get("runs")
        if isinstance(runs, list):
            for run in runs:
                if not isinstance(run, list) or len(run) < 3:
                    continue
                try:
                    if int(run[2]) > int(run[1]):
                        return True
                except (TypeError, ValueError):
                    continue
    strokes = manual_mask.get("strokes")
    if not isinstance(strokes, list):
        return False
    for stroke in strokes:
        if not isinstance(stroke, dict):
            continue
        mode = str(stroke.get("mode", "")).lower()
        if not stroke.get("eraser") and mode != "erase" and stroke.get("points"):
            return True
    return False


def semantic_block_payload(
    slide_id: str,
    index: int,
    fragment_ids: List[str],
    visual_group_id: str,
    group: Optional[Dict[str, Any]],
    fragments_by_id: Dict[str, Dict[str, Any]],
    existing_box: Any = None,
    ai_block: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    ai_block = ai_block or {}
    selected_fragments = [fragments_by_id[fid] for fid in fragment_ids if fid in fragments_by_id]
    beat_ids = []
    narration_group_ids = []
    for fragment in selected_fragments:
        if fragment.get("beat_id") and fragment["beat_id"] not in beat_ids:
            beat_ids.append(fragment["beat_id"])
        if fragment.get("group_id") and fragment["group_id"] not in narration_group_ids:
            narration_group_ids.append(fragment["group_id"])
    role = str((group or {}).get("role") or "content_body")
    visible_text = str((group or {}).get("visible_text") or ai_block.get("text_label") or f"语块 {index}").strip()
    visual_anchor = str((group or {}).get("visual_anchor") or "").strip()
    visual_type = normalize_visual_type(
        (group or {}).get("visual_type") or ai_block.get("visual_type"),
        has_text=bool(str((group or {}).get("display_text") or "").strip()),
    )
    prefix = f"{slide_id}_" if slide_id else ""
    element_id = str((group or {}).get("element_id") or "").strip()
    if not element_id:
        element_id = visual_group_id[len(prefix):] if prefix and visual_group_id.startswith(prefix) else visual_group_id
    semantic_type = str(ai_block.get("semantic_element_type") or role_label(role)).strip()
    visual_description = str(ai_block.get("visual_description") or "").strip()
    if not visual_description:
        if visual_anchor and visible_text:
            visual_description = f"{semantic_type}：画面中可见文字“{visible_text}”，位置/形态为{visual_anchor}。"
        elif visual_anchor:
            visual_description = f"{semantic_type}：{visual_anchor}。"
        else:
            visual_description = f"{semantic_type}：请结合 visible_text 和当前页画面定位对应的可见元素。"
    semantic_note = str(ai_block.get("semantic_note") or "").strip()
    if not semantic_note:
        semantic_note = "建议只涂抹该语块对应的可见元素本体，避开相邻箭头、装饰线和底部字幕安全区。"
    return {
        "group_id": f"semantic_{slide_id}_{index:02d}",
        "source": "ai_semantic",
        "visual_group_id": visual_group_id,
        "element_id": element_id,
        "role": role,
        "visual_type": visual_type,
        "text_label": visible_text or f"语块 {index}",
        "visual_anchor": visual_anchor,
        "semantic_element_type": semantic_type,
        "visual_description": visual_description,
        "semantic_note": semantic_note,
        "semantic_confidence": ai_block.get("confidence"),
        "narration_beat_id": beat_ids[0] if beat_ids else "",
        "narration_beat_ids": beat_ids,
        "narration_group_id": narration_group_ids[0] if narration_group_ids else visual_group_id,
        "narration_fragments": [
            {
                "id": fragment["id"],
                "beat_id": fragment.get("beat_id", ""),
                "group_id": fragment.get("group_id", ""),
                "text": fragment.get("text", ""),
            }
            for fragment in selected_fragments
        ],
        "spoken_text": "".join(fragment.get("text", "") for fragment in selected_fragments),
        "manual_mask": {"color": "", "strokes": []},
        "box": box_to_xyxy(existing_box),
    }


def deterministic_semantic_blocks(
    slide_id: str,
    contract_slide: Dict[str, Any],
    manifest_slide: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    groups = {
        str(group.get("id", "")).strip(): group
        for group in (contract_slide.get("visual_groups") or [])
        if isinstance(group, dict) and str(group.get("id", "")).strip()
    }
    existing_boxes = {}
    if manifest_slide:
        for field in ("semantic_blocks", "groups"):
            for group in manifest_slide.get(field, []) or []:
                if not isinstance(group, dict):
                    continue
                box = group.get("box")
                for identifier in (
                    group.get("visual_group_id"),
                    group.get("id"),
                    group.get("group_id"),
                ):
                    identifier_text = str(identifier or "").strip()
                    if identifier_text and identifier_text not in existing_boxes:
                        existing_boxes[identifier_text] = box
    fragments = build_narration_fragments(contract_slide)
    fragments_by_id = {fragment["id"]: fragment for fragment in fragments}
    group_to_fragments: Dict[str, List[str]] = {}
    for fragment in fragments:
        group_to_fragments.setdefault(fragment["group_id"], []).append(fragment["id"])
    blocks: List[Dict[str, Any]] = []
    for group_id, group in groups.items():
        if not isinstance(group, dict):
            continue
        if str(group.get("role") or "").strip().lower() == "decoration":
            continue
        fragment_ids = group_to_fragments.get(group_id) or []
        if not fragment_ids:
            continue
        blocks.append(semantic_block_payload(
            slide_id,
            len(blocks) + 1,
            fragment_ids,
            group_id,
            group,
            fragments_by_id,
            existing_boxes.get(group_id),
        ))
    return blocks


def refresh_reveal_semantic_blocks(project: Project, requested_slide_id: str = "") -> tuple[Dict[str, Any], int]:
    manifest_path = os.path.join(project.run_dir, "reveal_manifest.json")
    contract_path = os.path.join(project.run_dir, "planning", "visual_contract.json")
    if not os.path.exists(manifest_path):
        raise HTTPException(status_code=400, detail="Mask 配置文件尚未生成，请先确认图片")
    if not os.path.exists(contract_path):
        raise HTTPException(status_code=400, detail="分镜规划不存在，请先生成分镜")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    with open(contract_path, "r", encoding="utf-8") as f:
        contract = json.load(f)

    contract_slides = {
        str(slide.get("slide_id", "")).strip(): slide
        for slide in contract.get("slides", [])
        if isinstance(slide, dict) and str(slide.get("slide_id", "")).strip()
    }
    target_slides = []
    for slide in manifest.get("slides", []):
        if not isinstance(slide, dict):
            continue
        slide_id = str(slide.get("slide_id", "")).strip()
        if requested_slide_id and slide_id != requested_slide_id:
            continue
        if slide_id in contract_slides:
            target_slides.append(slide)
    if requested_slide_id and not target_slides:
        raise HTTPException(status_code=404, detail=f"找不到当前页分镜：{requested_slide_id}")

    processed_count = 0
    for manifest_slide in target_slides:
        slide_id = str(manifest_slide.get("slide_id", "")).strip()
        contract_slide = contract_slides[slide_id]
        semantic_blocks = deterministic_semantic_blocks(slide_id, contract_slide, manifest_slide)
        painted_groups = [
            group for group in manifest_slide.get("groups", []) or []
            if isinstance(group, dict) and group_has_paint(group)
        ]
        manifest_slide["semantic_blocks"] = semantic_blocks
        manifest_slide["groups"] = painted_groups
        if semantic_blocks or painted_groups:
            manifest_slide["status"] = manifest_slide.get("status") or "pending"
        processed_count += 1

    with reveal_lock_for(project):
        write_json_atomic(manifest_path, manifest)
    return manifest, processed_count



@app.post("/api/projects/{project_id}/steps/5/semantic-blocks")
def semantic_blocks_project(project_id: str, payload: Optional[Dict[str, Any]] = None, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    payload = payload or {}
    requested_slide_id = str(payload.get("slide_id") or "").strip()
    manifest, processed_count = refresh_reveal_semantic_blocks(project, requested_slide_id)
    return {
        "success": True,
        "vision_used": False,
        "processed": processed_count,
        "manifest": manifest,
        "message": "已根据分镜和旁白生成语块；自动 RLE Mask 可继续手动修正。",
    }

@app.get("/api/projects/{project_id}/steps/5/result")
def get_step5_result(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    manifest_path = os.path.join(project.run_dir, "reveal_manifest.json")
    if not os.path.exists(manifest_path):
        return {"success": False, "message": "尚未确认图片"}
    with reveal_lock_for(project):
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    expected_ids = read_contract_slide_ids(project.run_dir)
    actual_ids = [
        str(slide.get("slide_id") or "").strip()
        for slide in manifest.get("slides", [])
        if isinstance(slide, dict) and str(slide.get("slide_id") or "").strip()
    ]
    missing_ids = [slide_id for slide_id in expected_ids if slide_id not in actual_ids]
    stale_ids = [slide_id for slide_id in actual_ids if slide_id not in expected_ids]
    reasons = []
    if missing_ids:
        reasons.append("missing_contract_slides")
    if stale_ids:
        reasons.append("unreferenced_manifest_slides")
    return {
        "success": True,
        "manifest": manifest,
        "repair": {
            "required": bool(reasons),
            "reasons": reasons,
            "missing_slide_ids": missing_ids,
            "stale_slide_ids": stale_ids,
            "endpoint": f"/api/projects/{project_id}/steps/5/repair",
        },
    }


@app.post("/api/projects/{project_id}/steps/5/repair")
def repair_step5_result(project_id: str, db: Session = Depends(get_db)):
    """Explicitly reconcile a historical Mask manifest with the storyboard."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    manifest_path = os.path.join(project.run_dir, "reveal_manifest.json")
    if not os.path.exists(manifest_path):
        raise HTTPException(status_code=400, detail="尚未确认图片")
    with reveal_lock_for(project):
        before = Path(manifest_path).read_bytes()
        sync_reveal_manifest_to_contract(project)
        manifest, processed_count = refresh_reveal_semantic_blocks(project)
        changed = Path(manifest_path).read_bytes() != before
    return {
        "success": True,
        "changed": changed,
        "processed": processed_count,
        "manifest": manifest,
    }

@app.put("/api/projects/{project_id}/steps/5/draft")
def update_step5_draft(project_id: str, payload: Dict[str, Any], db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    with reveal_lock_for(project):
        current_slide_ids = read_contract_slide_ids(project.run_dir)
        if current_slide_ids and isinstance(payload.get("slides"), list):
            by_id = {
                str(slide.get("slide_id") or "").strip(): slide
                for slide in payload.get("slides", [])
                if isinstance(slide, dict) and str(slide.get("slide_id") or "").strip()
            }
            payload["slides"] = [by_id[slide_id] for slide_id in current_slide_ids if slide_id in by_id]

        payload = prune_stale_mask_groups(project, payload)
        manifest_path = os.path.join(project.run_dir, "reveal_manifest.json")
        write_json_atomic(manifest_path, payload)
    return {"success": True}


@app.post("/api/projects/{project_id}/steps/5/slides/{slide_id}/preview")
def build_step5_mask_preview(
    project_id: str,
    slide_id: str,
    payload: Optional[Dict[str, Any]] = None,
    db: Session = Depends(get_db),
):
    """Build one production-accurate static Mask preview without advancing steps."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    preview_path = current_slide_file_or_404(project, slide_id, "mask_preview.png")
    manifest_path = os.path.join(project_run_dir_or_500(project), "reveal_manifest.json")
    if not os.path.exists(manifest_path):
        raise HTTPException(status_code=400, detail="Mask 配置文件不存在")

    with reveal_lock_for(project):
        sync_project_background_color(project)
        build_scene_script = os.path.join(REPO_ROOT, "scripts", "build_reveal_scene.py")
        command = [
            sys.executable,
            build_scene_script,
            "--manifest",
            manifest_path,
            "--repo-root",
            REPO_ROOT,
            "--slide-id",
            slide_id,
            "--preview-output",
            preview_path,
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=STEP5_REVEAL_BUILD_TIMEOUT_SEC,
            )
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(status_code=504, detail="精确 Mask 预览构建超时，请重试") from exc
        if result.returncode != 0 or not os.path.exists(preview_path):
            logger.error("Build exact Mask preview failed: %s", result.stderr)
            raise HTTPException(status_code=500, detail=f"精确 Mask 预览构建失败: {result.stderr or ''}")

        # Match the final render path exactly: image-mode storyboard
        # backgrounds are applied after reveal assets are built, so regenerate
        # the static preview from those post-processed production layers.
        from storyboard_background_render import apply_storyboard_background
        from scripts.build_reveal_scene import compose_preview_image

        apply_storyboard_background(Path(manifest_path).resolve())
        compose_preview_image(Path(preview_path).parent, Path(preview_path))

        report_path = current_slide_file_or_404(project, slide_id, "reveal_report.json")
        report = read_json_file(report_path, {})
        manifest_bytes = Path(manifest_path).read_bytes()
        manifest_fingerprint = hashlib.sha256(manifest_bytes).hexdigest()
        groups = [
            *(report.get("groups") if isinstance(report.get("groups"), list) else []),
            *(report.get("static_groups") if isinstance(report.get("static_groups"), list) else []),
        ]
        cutout_stats = {
            key: sum(
                int((group.get("cutout") or {}).get(key, 0) or 0)
                for group in groups
                if isinstance(group, dict)
            )
            for key in (
                "manual_mask_pixel_count",
                "removed_outer_white_pixel_count",
                "soft_edge_pixel_count",
                "retained_pixel_count",
            )
        }

    version = int(os.path.getmtime(preview_path) * 1000)
    return {
        "success": True,
        "slide_id": slide_id,
        "manifest_fingerprint": manifest_fingerprint,
        "preview_url": f"/api/projects/{project_id}/slides/{slide_id}/mask-preview?t={version}",
        "fallback_full_slide": bool(report.get("fallback_full_slide")),
        "warnings": report.get("warnings", []),
        "cutout_stats": cutout_stats,
    }


@app.get("/api/projects/{project_id}/slides/{slide_id}/mask-preview")
def get_step5_mask_preview(project_id: str, slide_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    preview_path = current_slide_file_or_404(project, slide_id, "mask_preview.png")
    if not os.path.exists(preview_path):
        raise HTTPException(status_code=404, detail="精确 Mask 预览尚未生成")
    return FileResponse(preview_path, media_type="image/png")

@app.put("/api/projects/{project_id}/steps/5/result")
def update_step5_result(project_id: str, payload: Dict[str, Any], build_assets: bool = Query(True), db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    with reveal_lock_for(project):
        # 保存手动编辑修改的 reveal_manifest
        current_slide_ids = read_contract_slide_ids(project.run_dir)
        if current_slide_ids and isinstance(payload.get("slides"), list):
            by_id = {
                str(slide.get("slide_id") or "").strip(): slide
                for slide in payload.get("slides", [])
                if isinstance(slide, dict) and str(slide.get("slide_id") or "").strip()
            }
            payload["slides"] = [by_id[slide_id] for slide_id in current_slide_ids if slide_id in by_id]

        payload = prune_stale_mask_groups(project, payload)
        manifest_path = os.path.join(project.run_dir, "reveal_manifest.json")
        write_json_atomic(manifest_path, payload)

        built_assets = False
        if build_assets:
            # 人工最终保存时校验并构建切层 assets；草稿保存路径不需要阻塞在构建上。
            build_current_reveal_assets(project)
            built_assets = True

    handle_step_navigation(project, 5, db)
    return {"success": True, "built_assets": built_assets}

# ==================== 步骤 6: 演讲稿编辑 ====================

@app.post("/api/projects/{project_id}/steps/6/init")
def init_step6_narration(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    # 如果不存在 narration，从 visual contract 自动导出初版
    contract_path = os.path.join(project.run_dir, "planning", "visual_contract.json")
    if not os.path.exists(contract_path):
        raise HTTPException(status_code=400, detail="分镜规划不存在，请返回第二步生成分镜")
        
    write_narration_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "write_narration_from_visual_contract.py"))
    res = subprocess.run([
        sys.executable, write_narration_script, "--run-dir", project.run_dir
    ], capture_output=True, text=True, encoding="utf-8", errors="replace")
    
    if res.returncode != 0:
        logger.error(f"Init narration failed: {res.stderr}")
        raise HTTPException(status_code=500, detail="初始化演讲稿模版失败")
        
    # 合并各个 slide 独立的 narration_beats.json 到全局的 planning/narration_beats.json
    with open(contract_path, "r", encoding="utf-8") as f:
        contract = json.load(f)
        
    global_slides = []
    for s in contract.get("slides", []):
        slide_id = s["slide_id"]
        slide_beat_path = os.path.join(project.run_dir, "slides", slide_id, "narration_beats.json")
        if os.path.exists(slide_beat_path):
            with open(slide_beat_path, "r", encoding="utf-8") as sf:
                s_data = json.load(sf)
                beats = s_data.get("beats", [])
                for beat in beats:
                    if isinstance(beat, dict):
                        beat.setdefault("source_text", beat.get("spoken_text", ""))
                        beat.setdefault("tts_text", beat.get("spoken_text", ""))
                global_slides.append({
                    "slide_id": slide_id,
                    "beats": beats
                })
        else:
            global_slides.append({
                "slide_id": slide_id,
                "beats": []
            })
            
    global_beats = persist_narration_beats(project, {"slides": global_slides})
    return {"success": True, "beats": global_beats}

@app.get("/api/projects/{project_id}/steps/6/result")
def get_step6_result(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    beats_path = os.path.join(project.run_dir, "planning", "narration_beats.json")
    if not os.path.exists(beats_path):
        return {"success": False, "message": "演讲稿尚未生成"}

    with open(beats_path, "r", encoding="utf-8") as f:
        beats = json.load(f)
    expected_ids = read_contract_slide_ids(project.run_dir)
    actual_ids = [
        str(slide.get("slide_id") or "").strip()
        for slide in beats.get("slides", [])
        if isinstance(slide, dict) and str(slide.get("slide_id") or "").strip()
    ]
    missing_ids = [slide_id for slide_id in expected_ids if slide_id not in actual_ids]
    stale_ids = [slide_id for slide_id in actual_ids if slide_id not in expected_ids]
    reasons = []
    if missing_ids:
        reasons.append("missing_contract_slides")
    if stale_ids:
        reasons.append("unreferenced_narration_slides")
    return {
        "success": True,
        "beats": beats,
        "repair": {
            "required": bool(reasons),
            "reasons": reasons,
            "missing_slide_ids": missing_ids,
            "stale_slide_ids": stale_ids,
            "endpoint": f"/api/projects/{project_id}/steps/6/repair",
        },
    }


@app.post("/api/projects/{project_id}/steps/6/repair")
def repair_step6_result(project_id: str, db: Session = Depends(get_db)):
    """Explicitly align historical narration data with the current storyboard."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    beats_path = os.path.join(project.run_dir, "planning", "narration_beats.json")
    if not os.path.exists(beats_path):
        raise HTTPException(status_code=400, detail="演讲稿尚未生成")
    changed = sync_narration_beats_to_contract(project)
    beats = read_json_file(beats_path, {})
    return {"success": True, "changed": changed, "beats": beats}


NARRATION_ANNOTATION_SYSTEM_CONTENT_KEY = "narration_annotation_system_content"
NARRATION_ANNOTATION_OUTPUT_EXAMPLE_KEY = "narration_annotation_output_example"
DEFAULT_NARRATION_ANNOTATION_SYSTEM_CONTENT = """You are a Chinese voiceover director preparing MiniMax TTS text.

Add only light delivery markup to the existing narration. Preserve the original meaning and words. Do not rewrite technical terms.

Rules:
1. Every beat longer than 12 Chinese characters must contain at least one MiniMax pause tag.
2. Normally add one to three pause tags such as <#0.2#>, <#0.35#>, <#0.5#> at natural clause boundaries.
3. Never put pause tags at the beginning or end, never use consecutive pause tags, and keep pause values between 0.01 and 99.99 seconds.
4. Expression tags are optional and must use only MiniMax speech-2.8 tags such as (breath), (sighs), (chuckle), (emm), (laughs), (inhale), (exhale), (gasps), (whistles), or (applause).
5. Avoid expression tags inside numbers, English identifiers, code terms, Token, API, LLM, or backtick content.
6. Return strict JSON only. Do not output Markdown or explanations."""
DEFAULT_NARRATION_ANNOTATION_OUTPUT_EXAMPLE = """{
  "slides": [
    {
      "slide_id": "slide_001",
      "beats": [
        {
          "id": "beat_001",
          "tts_text": "首先看核心概念，<#0.35#>再理解它的实际作用。"
        }
      ]
    }
  ]
}"""


def read_narration_annotation_prompts() -> tuple[str, str]:
    system_content = str(
        get_setting(NARRATION_ANNOTATION_SYSTEM_CONTENT_KEY, DEFAULT_NARRATION_ANNOTATION_SYSTEM_CONTENT)
        or DEFAULT_NARRATION_ANNOTATION_SYSTEM_CONTENT
    ).strip()
    output_example = str(
        get_setting(NARRATION_ANNOTATION_OUTPUT_EXAMPLE_KEY, DEFAULT_NARRATION_ANNOTATION_OUTPUT_EXAMPLE)
        or DEFAULT_NARRATION_ANNOTATION_OUTPUT_EXAMPLE
    ).strip()
    return system_content, output_example


def compose_narration_annotation_prompt(system_content: str, output_example: str) -> str:
    return (
        str(system_content or "").strip()
        + "\n\n<OutputExample>\n"
        + str(output_example or "").strip()
        + "\n</OutputExample>"
    )


@app.get("/api/settings/narration-annotation")
def get_narration_annotation_settings():
    system_content, output_example = read_narration_annotation_prompts()
    return {
        "success": True,
        "prompts": {
            "system_content": system_content,
            "output_example": output_example,
            "full_prompt": compose_narration_annotation_prompt(system_content, output_example),
        },
    }


@app.put("/api/settings/narration-annotation")
def update_narration_annotation_settings(payload: Dict[str, Any]):
    prompts = payload.get("prompts") if isinstance(payload.get("prompts"), dict) else payload
    system_content = str(prompts.get("system_content") or "").strip()
    output_example = str(prompts.get("output_example") or "").strip()
    if not system_content or not output_example:
        raise HTTPException(status_code=400, detail="AI 标注的 System Content 和 Output Example 不能为空")
    if len(system_content) > 30000 or len(output_example) > 20000:
        raise HTTPException(status_code=400, detail="AI 标注 Prompt 内容过长")
    update_settings({
        NARRATION_ANNOTATION_SYSTEM_CONTENT_KEY: system_content,
        NARRATION_ANNOTATION_OUTPUT_EXAMPLE_KEY: output_example,
    })
    return {
        "success": True,
        "prompts": {
            "system_content": system_content,
            "output_example": output_example,
            "full_prompt": compose_narration_annotation_prompt(system_content, output_example),
        },
    }

@app.post("/api/projects/{project_id}/steps/6/annotate")
def annotate_step6_narration(project_id: str, payload: Optional[Dict[str, Any]] = None, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    llm_api_key = get_setting("llm_api_key")
    if not llm_api_key:
        raise HTTPException(status_code=400, detail="Please configure the LLM API key before AI narration annotation.")

    incoming = payload if isinstance(payload, dict) and isinstance(payload.get("slides"), list) else None
    if incoming is None:
        beats_path = os.path.join(project.run_dir, "planning", "narration_beats.json")
        if not os.path.exists(beats_path):
            raise HTTPException(status_code=400, detail="Narration beats do not exist. Initialize step 6 first.")
        sync_narration_beats_to_contract(project)
        with open(beats_path, "r", encoding="utf-8") as f:
            incoming = json.load(f)

    incoming = prepare_narration_payload(project, incoming)
    if not incoming.get("slides"):
        raise HTTPException(status_code=400, detail="No narration beats available for annotation.")

    llm_base_url = get_setting("llm_base_url")
    llm_model = get_setting("llm_model", "gpt-4o-mini")
    llm_max_tokens = parse_int_setting(get_setting("llm_max_tokens", "50000"), 50000, 1024, 64000)
    client = get_openai_client(api_key=llm_api_key, base_url=llm_base_url)
    compact_slides = []
    for slide in incoming.get("slides", []):
        compact_beats = []
        for idx, beat in enumerate(slide.get("beats", []) or [], start=1):
            if not isinstance(beat, dict):
                continue
            compact_beats.append({
                "id": str(beat.get("id") or f"beat_{idx:03d}"),
                "index": idx,
                "source_text": clean_tts_text(beat.get("source_text") or beat.get("spoken_text") or beat_tts_text(beat)),
                "current_tts_text": beat_tts_text(beat),
                "anchor": str(beat.get("visible_anchor") or beat.get("group_id") or ""),
            })
        compact_slides.append({"slide_id": slide.get("slide_id"), "beats": compact_beats})

    annotation_system_content, annotation_output_example = read_narration_annotation_prompts()
    system_prompt = compose_narration_annotation_prompt(
        annotation_system_content,
        annotation_output_example,
    )
    user_prompt = json.dumps({"slides": compact_slides}, ensure_ascii=False)

    try:
        try:
            response = client.chat.completions.create(
                model=llm_model,
                temperature=0.2,
                max_tokens=llm_max_tokens,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
        except Exception as format_error:
            logger.warning(f"Narration annotation response_format failed, retrying raw JSON: {format_error}")
            response = client.chat.completions.create(
                model=llm_model,
                temperature=0.2,
                max_tokens=llm_max_tokens,
                messages=[
                    {"role": "system", "content": system_prompt + " Return JSON only. No markdown."},
                    {"role": "user", "content": user_prompt},
                ],
            )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"AI narration annotation failed: {exc}")

    raw_content = response.choices[0].message.content.strip()
    ai_data = parse_json_or_repair_with_llm(
        cleaned_content=clean_json_markdown(raw_content),
        raw_content=raw_content,
        client=client,
        model=llm_model,
        run_dir=project.run_dir,
        artifact_prefix="step6_tts_annotation",
        schema_hint='{"slides":[{"slide_id":"slide_001","beats":[{"id":"beat_001","tts_text":"..."}]}]}',
        max_tokens=llm_max_tokens,
    )

    annotated_by_slide: Dict[str, Dict[str, str]] = {}
    for slide in ai_data.get("slides", []) or []:
        if not isinstance(slide, dict):
            continue
        slide_id = str(slide.get("slide_id") or "").strip()
        if not slide_id:
            continue
        annotated_by_slide[slide_id] = {}
        for beat in slide.get("beats", []) or []:
            if not isinstance(beat, dict):
                continue
            beat_id = str(beat.get("id") or "").strip()
            tts_text = str(beat.get("tts_text") or "").strip()
            if beat_id and tts_text:
                annotated_by_slide[slide_id][beat_id] = tts_text

    changed = 0
    for slide in incoming.get("slides", []):
        slide_id = str(slide.get("slide_id") or "").strip()
        by_id = annotated_by_slide.get(slide_id, {})
        for beat in slide.get("beats", []) or []:
            if not isinstance(beat, dict):
                continue
            beat_id = str(beat.get("id") or "").strip()
            original = beat.get("spoken_text") or beat.get("source_text") or beat_tts_text(beat)
            if beat_id in by_id:
                beat["tts_text"] = ensure_minimax_delivery_markup(
                    normalize_minimax_tts_markup(by_id[beat_id], original)
                )
                changed += 1

    if changed == 0:
        raise HTTPException(status_code=500, detail="AI returned no usable narration annotations.")

    incoming = persist_narration_beats(project, incoming)
    handle_step_navigation(project, 6, db)
    return {"success": True, "beats": incoming, "annotated_count": changed}

@app.put("/api/projects/{project_id}/steps/6/result")
def update_step6_result(project_id: str, payload: Dict[str, Any], db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    current_slide_ids = read_contract_slide_ids(project.run_dir)
    if current_slide_ids and isinstance(payload.get("slides"), list):
        by_id = {
            str(slide.get("slide_id") or "").strip(): slide
            for slide in payload.get("slides", [])
            if isinstance(slide, dict) and str(slide.get("slide_id") or "").strip()
        }
        payload["slides"] = [by_id[slide_id] for slide_id in current_slide_ids if slide_id in by_id]

    # 保存全局规划下的 narration_beats.json
    beats_path = os.path.join(project.run_dir, "planning", "narration_beats.json")
    with open(beats_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        
    narration_lines = []
    tts_text_lines = []
    
    # 循环写入各 Slide 独立的 narration.txt, tts_text.txt 和 narration_beats.json
    for slide_data in payload.get("slides", []):
        slide_id = slide_data["slide_id"]
        slide_dir = os.path.join(project.run_dir, "slides", slide_id)
        os.makedirs(slide_dir, exist_ok=True)
        
        slide_beats = slide_data.get("beats", [])
        for beat in slide_beats:
            if isinstance(beat, dict):
                beat.setdefault("source_text", beat.get("spoken_text", ""))
                beat.setdefault("tts_text", beat.get("spoken_text", ""))
        slide_narration = "\n".join(clean_tts_text(beat_tts_text(beat)) for beat in slide_beats)
        slide_tts_text = "\n".join(beat_tts_text(beat) for beat in slide_beats)
        
        with open(os.path.join(slide_dir, "narration.txt"), "w", encoding="utf-8") as f:
            f.write(slide_narration + "\n")
        with open(os.path.join(slide_dir, "tts_text.txt"), "w", encoding="utf-8") as f:
            f.write(slide_tts_text + "\n")
        with open(os.path.join(slide_dir, "narration_beats.json"), "w", encoding="utf-8") as f:
            json.dump({"slide_id": slide_id, "beats": slide_beats}, f, ensure_ascii=False, indent=2)
            
        narration_lines.append(f"=== {slide_id} ===")
        tts_text_lines.append(f"=== {slide_id} ===")
        for beat in slide_beats:
            g_id = beat.get("group_id") or beat.get("id") or "sentence"
            text = clean_tts_text(beat_tts_text(beat))
            narration_lines.append(f"[{g_id}] {text}")
            tts_text_lines.append(beat_tts_text(beat))
            
    narration_txt_path = os.path.join(project.run_dir, "planning", "narration.txt")
    tts_txt_path = os.path.join(project.run_dir, "planning", "tts_text.txt")
    
    with open(narration_txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(narration_lines) + "\n")
    with open(tts_txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(tts_text_lines) + "\n")
        
    # 运行校验，确保 narration 符合规范
    validate_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "validate_narration_grounding.py"))
    val_res = subprocess.run([
        sys.executable, validate_script, "--run-dir", project.run_dir
    ], capture_output=True, text=True, encoding="utf-8", errors="replace")
    
    if val_res.returncode != 0:
        logger.warning(f"Narration grounding warned:\n{val_res.stderr}")
        
    handle_step_navigation(project, 6, db)
    return {"success": True}

# ==================== 步骤 7: 语音合成 ====================


# 获取音频文件接口（供前端试听）
@app.post("/api/projects/{project_id}/steps/7/synthesize")
def synthesize_tts_resumable(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    provider = normalize_tts_provider(get_setting("tts_provider", "minimax"))
    defaults = tts_provider_defaults(provider)
    if provider not in TTS_PROVIDER_DEFAULTS:
        raise HTTPException(status_code=400, detail=f"不支持的 TTS Provider: {provider}")
    tts_api_key = configured_tts_api_key(provider)
    tts_secret_key = configured_tts_secret_key(provider)
    if not tts_api_key:
        env_name = defaults.get("api_key_env") or "TTS_API_KEY"
        raise HTTPException(status_code=400, detail=f"未配置 {provider} 语音合成密钥，也没有读取到环境变量 {env_name}。")
    if provider == "tencent_tts" and not tts_secret_key:
        raise HTTPException(status_code=400, detail="腾讯云 TTS 需要同时配置 SecretId 和 SecretKey。")

    contract_path = os.path.join(project.run_dir, "planning", "visual_contract.json")
    if not os.path.exists(contract_path):
        raise HTTPException(status_code=400, detail="分镜规划尚未生成，请返回确认第二步状态。")

    with open(contract_path, "r", encoding="utf-8") as f:
        contract = json.load(f)

    slide_ids = [
        str(slide["slide_id"])
        for slide in contract.get("slides", [])
        if isinstance(slide, dict) and slide.get("slide_id")
    ]
    if not slide_ids:
        raise HTTPException(status_code=400, detail="分镜规划中没有可生成音频的页面。")

    beats_by_slide: Dict[str, List[Dict[str, Any]]] = {}
    beats_path = os.path.join(project.run_dir, "planning", "narration_beats.json")
    if os.path.exists(beats_path):
        try:
            sync_narration_beats_to_contract(project, slide_ids)
            with open(beats_path, "r", encoding="utf-8") as f:
                beats_payload = json.load(f)
            for slide_data in beats_payload.get("slides", []) or []:
                if isinstance(slide_data, dict):
                    beats_by_slide[str(slide_data.get("slide_id", ""))] = slide_data.get("beats", []) or []
        except Exception as exc:
            logger.warning("Failed to load edited narration beats for TTS: %s", exc)

    tts_endpoint = first_non_empty(get_setting("tts_endpoint"), defaults.get("endpoint"))
    tts_model = first_non_empty(get_setting("tts_model"), defaults.get("model"))
    tts_voice_id = first_non_empty(get_setting("tts_voice_id"), defaults.get("voice_id"))
    tts_clone_voice_id = get_setting("tts_clone_voice_id", "")
    tts_region = first_non_empty(get_setting("tts_region"), defaults.get("region"))
    tts_provider_extra = get_setting("tts_provider_extra", "")
    tts_speed = get_setting("tts_speed", "1.2")
    tts_volume = get_setting("tts_volume", "1.0")
    tts_pitch = get_setting("tts_pitch", "0" if provider == "minimax" else "1.0")

    clear_audio_confirmation(project)
    mark_step_in_progress(project, 7, db)

    generated_slides: List[str] = []
    skipped_slides: List[str] = []
    failed_slides: List[Dict[str, Any]] = []

    for slide_id in slide_ids:
        paths = slide_tts_artifact_paths(project, slide_id)
        text_file = ensure_slide_tts_text_file(project, slide_id, contract)
        artifact_status = slide_tts_artifact_status(project, slide_id)

        if artifact_status["complete"]:
            logger.info("Skipping TTS for %s because audio artifacts are already complete and fresh", slide_id)
            rewrite_audio_timeline_by_beats(paths["timeline"], slide_id, beats_by_slide.get(slide_id, []))
            skipped_slides.append(slide_id)
            continue

        if artifact_status["audio_exists"] or artifact_status["missing_artifacts"] or artifact_status["stale"]:
            remove_tts_artifacts(paths)

        logger.info("Synthesizing TTS audio for slide %s via %s", slide_id, provider)
        tts_args = provider_tts_command(
            provider=provider,
            text_file=text_file,
            out_audio=paths["audio"],
            out_meta=paths["metadata"],
            out_srt=paths["srt"],
            out_timeline=paths["timeline"],
            slide_id=slide_id,
            endpoint=tts_endpoint,
            region=tts_region,
            model=tts_model,
            voice_id=tts_voice_id,
            clone_voice_id=tts_clone_voice_id,
            provider_extra=tts_provider_extra,
            speed=tts_speed,
            volume=tts_volume,
            pitch=tts_pitch,
        )

        tts_result = run_tts_command_with_retries(
            project,
            slide_id,
            tts_args,
            provider_tts_environment(tts_api_key, tts_secret_key),
        )
        if not tts_result["ok"]:
            error_text = (tts_result["stderr"] or tts_result["stdout"] or "TTS synthesis failed").strip()
            error_text = error_text[-1200:]
            logger.error("TTS synthesis failed for %s after %s attempts: %s", slide_id, tts_result["attempts"], error_text)
            write_project_log(
                project,
                "step7_slide_tts_error",
                slide_id=slide_id,
                attempts=tts_result["attempts"],
                returncode=tts_result["returncode"],
                stdout=tts_result["stdout"],
                stderr=tts_result["stderr"],
            )
            failed_slides.append({
                "slide_id": slide_id,
                "attempts": tts_result["attempts"],
                "returncode": tts_result["returncode"],
                "error": error_text,
            })
            continue

        post_status = slide_tts_artifact_status(project, slide_id)
        if not post_status["complete"]:
            error_text = "TTS command returned success but required audio artifacts are incomplete: " + ", ".join(post_status["missing_artifacts"])
            logger.error("%s for %s", error_text, slide_id)
            write_project_log(
                project,
                "step7_slide_tts_incomplete_artifacts",
                slide_id=slide_id,
                status=post_status,
            )
            failed_slides.append({
                "slide_id": slide_id,
                "attempts": tts_result["attempts"],
                "returncode": tts_result["returncode"],
                "error": error_text,
            })
            continue

        rewrite_audio_timeline_by_beats(paths["timeline"], slide_id, beats_by_slide.get(slide_id, []))
        generated_slides.append(slide_id)

    if failed_slides:
        mark_step_retry_needed(project, 7, db)
        write_project_log(
            project,
            "step7_tts_partial_failed",
            generated=generated_slides,
            skipped=skipped_slides,
            failed=failed_slides,
        )
        failed_ids = [item["slide_id"] for item in failed_slides]
        return {
            "success": False,
            "message": f"音频部分生成失败，请重试缺失页面：{', '.join(failed_ids)}",
            "generated": generated_slides,
            "skipped": skipped_slides,
            "failed": failed_slides,
            "audio_status": [slide_tts_artifact_status(project, sid) for sid in slide_ids],
            "audio_confirmed": False,
        }

    bind_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "bind_reveal_timeline.py"))
    bind_res = subprocess.run(
        [sys.executable, bind_script, "--run-dir", project.run_dir, "--lead-sec", str(REVEAL_VISUAL_LEAD_SEC)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=STEP7_BIND_TIMEOUT_SEC,
    )

    if bind_res.returncode != 0:
        logger.error("Timeline binding failed: %s", bind_res.stderr)
        write_project_log(
            project,
            "step7_timeline_bind_error",
            returncode=bind_res.returncode,
            stdout=bind_res.stdout.strip(),
            stderr=bind_res.stderr.strip(),
        )
        mark_step_retry_needed(project, 7, db)
        return {
            "success": False,
            "message": f"音频已生成，但时间轴绑定失败：{bind_res.stderr[-1200:]}",
            "generated": generated_slides,
            "skipped": skipped_slides,
            "failed": [{"slide_id": "timeline_binding", "error": bind_res.stderr[-1200:]}],
            "audio_status": [slide_tts_artifact_status(project, sid) for sid in slide_ids],
            "audio_confirmed": False,
        }

    return {
        "success": True,
        "message": "音频生成完成",
        "generated": generated_slides,
        "skipped": skipped_slides,
        "failed": [],
        "audio_status": [slide_tts_artifact_status(project, sid) for sid in slide_ids],
        "audio_confirmed": False,
    }

@app.get("/api/projects/{project_id}/steps/7/audio-status")
def get_tts_audio_status(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    slide_ids = read_current_slide_ids_or_404(project)
    slides = [slide_tts_artifact_status(project, slide_id) for slide_id in slide_ids]
    missing = [item["slide_id"] for item in slides if not item["complete"]]
    return {
        "success": True,
        "slides": slides,
        "complete": not missing,
        "missing": missing,
        "audio_confirmed": project_audio_confirmed(project),
    }

@app.get("/api/projects/{project_id}/slides/{slide_id}/audio")
def get_slide_audio_file(project_id: str, slide_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    audio_path = current_slide_file_or_404(project, slide_id, "voice.mp3")
    status = slide_tts_artifact_status(project, slide_id)
    if not status["audio_exists"]:
        raise HTTPException(status_code=404, detail="该页面音频尚未生成")
        
    if status["stale"]:
        raise HTTPException(status_code=409, detail="该页面音频已过期，请重新生成。")

    return FileResponse(audio_path, media_type="audio/mp3")

@app.post("/api/projects/{project_id}/steps/7/confirm")
def confirm_tts_audio(project_id: str, payload: Optional[Dict[str, Any]] = None, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    slide_ids = read_current_slide_ids_or_404(project)
    missing = [
        slide_id for slide_id in slide_ids
        if not slide_tts_artifact_status(project, slide_id)["complete"]
    ]
    if missing:
        raise HTTPException(status_code=400, detail=f"以下页面尚未生成音频: {', '.join(missing)}")
    beats_by_slide: Dict[str, List[Dict[str, Any]]] = {}
    beats_path = os.path.join(project.run_dir, "planning", "narration_beats.json")
    if os.path.exists(beats_path):
        try:
            sync_narration_beats_to_contract(project, slide_ids)
            with open(beats_path, "r", encoding="utf-8") as f:
                beats_payload = json.load(f)
            for slide_data in beats_payload.get("slides", []) or []:
                if isinstance(slide_data, dict):
                    beats_by_slide[str(slide_data.get("slide_id", ""))] = slide_data.get("beats", []) or []
        except Exception as exc:
            logger.warning(f"Failed to load edited narration beats while confirming TTS: {exc}")
    for slide_id in slide_ids:
        rewrite_audio_timeline_by_beats(
            os.path.join(project.run_dir, "slides", slide_id, "audio_timeline.json"),
            slide_id,
            beats_by_slide.get(slide_id, []),
        )
    bind_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "bind_reveal_timeline.py"))
    bind_res = subprocess.run([
        sys.executable, bind_script, "--run-dir", project.run_dir, "--lead-sec", str(REVEAL_VISUAL_LEAD_SEC)
    ], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if bind_res.returncode != 0:
        logger.error(f"Timeline binding failed during audio confirm: {bind_res.stderr}")
        raise HTTPException(status_code=500, detail=f"时间轴绑定失败: {bind_res.stderr}")
    confirmation_path = audio_confirmation_path(project)
    os.makedirs(os.path.dirname(confirmation_path), exist_ok=True)
    write_json_atomic(
        confirmation_path,
        build_audio_confirmation_payload(
            project.run_dir,
            slide_ids,
            confirmation_mode=str((payload or {}).get("confirmation_mode") or "user_reviewed"),
        ),
    )
    handle_step_navigation(project, 7, db)
    return {"success": True, "audio_confirmed": True}

# ==================== 步骤 8: 视频合成与渲染 ====================

def project_video_dir(project: Project) -> str:
    target = storage_videos_dir(project_run_dir_or_500(project))
    target.mkdir(parents=True, exist_ok=True)
    return str(target)


def video_metadata_path(path: str) -> str:
    return str(storage_video_sidecar(path))


def read_video_metadata(path: str) -> Dict[str, Any]:
    metadata_path = video_metadata_path(path)
    if not os.path.exists(metadata_path):
        return {}
    try:
        with open(metadata_path, "r", encoding="utf-8") as file:
            value = json.load(file)
        return value if isinstance(value, dict) else {}
    except Exception as exc:
        logger.warning("Failed to read video metadata %s: %s", metadata_path, exc)
        return {}


def current_render_input_fingerprint(project: Project) -> Dict[str, Any]:
    return render_input_fingerprint(
        project.run_dir,
        visual_settings=read_project_visual_settings(project),
        pipeline_version=REVEAL_PIPELINE_VERSION,
    )


def video_item(
    project: Project,
    path: str,
    label: Optional[str] = None,
    current_fingerprint: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    stat = os.stat(path)
    filename = os.path.basename(path)
    metadata_exists = os.path.exists(video_metadata_path(path))
    metadata = read_video_metadata(path)
    pipeline_version = str(metadata.get("reveal_pipeline_version") or "")
    video_background = normalize_hex_color(metadata.get("video_background"), fallback="")
    current_visual_settings = read_project_visual_settings(project)
    current_background = current_visual_settings["video_background"]
    has_subtitle_style_metadata = isinstance(metadata.get("subtitle_style"), dict)
    subtitle_style = normalize_subtitle_style(metadata.get("subtitle_style"))
    current_subtitle_style = current_visual_settings["subtitle_style"]
    playback_rate = float(metadata.get("playback_rate", 1.0) or 1.0)
    stored_fingerprint = metadata.get("input_fingerprint")
    current_fingerprint = current_fingerprint or current_render_input_fingerprint(project)
    if metadata_exists and not metadata:
        artifact_state = "invalid"
    elif not metadata_exists or pipeline_version != REVEAL_PIPELINE_VERSION or not isinstance(stored_fingerprint, dict):
        artifact_state = "legacy"
    elif (
        stored_fingerprint.get("digest") != current_fingerprint.get("digest")
        or video_background != current_background
        or not has_subtitle_style_metadata
        or subtitle_style != current_subtitle_style
    ):
        artifact_state = "stale"
    else:
        artifact_state = "current"
    return {
        "filename": filename,
        "label": label or filename,
        "size": stat.st_size,
        "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        "url": f"/api/projects/{project.id}/videos/{filename}",
        "reveal_pipeline_version": pipeline_version or None,
        "video_background": video_background or None,
        "subtitle_style": subtitle_style,
        "playback_rate": playback_rate,
        "source_filename": str(metadata.get("source_filename") or "") or None,
        "is_speed_variant": abs(playback_rate - 1.0) > 0.001,
        "artifact_state": artifact_state,
        "is_current": artifact_state == "current",
        "is_stale": artifact_state == "stale",
        "is_legacy": artifact_state == "legacy",
        "is_invalid": artifact_state == "invalid",
    }


def list_video_items(project: Project, project_id: str) -> List[Dict[str, Any]]:
    videos_dir = os.path.join(project.run_dir, "videos")
    items: List[Dict[str, Any]] = []
    current_fingerprint: Optional[Dict[str, Any]] = None
    if os.path.isdir(videos_dir):
        for name in os.listdir(videos_dir):
            path = os.path.join(videos_dir, name)
            if os.path.isfile(path) and name.lower().endswith(".mp4"):
                current_fingerprint = current_fingerprint or current_render_input_fingerprint(project)
                items.append(video_item(project, path, current_fingerprint=current_fingerprint))
    legacy_path = os.path.join(project.run_dir, "out.mp4")
    if os.path.exists(legacy_path) and not items:
        current_fingerprint = current_fingerprint or current_render_input_fingerprint(project)
        legacy = video_item(project, legacy_path, "out.mp4", current_fingerprint=current_fingerprint)
        legacy["url"] = f"/api/projects/{project_id}/video"
        items.append(legacy)
    items.sort(key=lambda item: item["created_at"], reverse=True)
    return items


def media_tool_candidate_dirs() -> List[str]:
    return [str(path) for path in shared_media_tool_candidate_dirs(REPO_ROOT)]


def resolve_media_tool(name: str) -> Optional[str]:
    return shared_resolve_media_tool(name, repo_root=REPO_ROOT)


def validate_remotion_public_assets(props: Dict[str, Any], public_dir: str) -> List[str]:
    missing: List[str] = []
    public_root = os.path.abspath(public_dir)

    def check_asset(value: Any) -> None:
        if not isinstance(value, str) or not value or re.match(r"^https?://", value):
            return
        asset_path = os.path.abspath(os.path.join(public_root, value.replace("/", os.sep)))
        if not asset_path.startswith(public_root + os.sep) and asset_path != public_root:
            missing.append(value)
            return
        if not os.path.exists(asset_path):
            missing.append(value)

    for slide in props.get("slides", []) if isinstance(props.get("slides"), list) else []:
        scene = slide.get("scene") if isinstance(slide, dict) else None
        layers = scene.get("layers") if isinstance(scene, dict) else None
        if isinstance(layers, list):
            for layer in layers:
                if isinstance(layer, dict):
                    check_asset(layer.get("asset"))
                    check_asset(layer.get("cutout_asset"))
        if isinstance(scene, dict) and isinstance(scene.get("canvas"), dict):
            check_asset(scene["canvas"].get("background_asset"))
        check_asset(slide.get("audio_file") if isinstance(slide, dict) else None)
    return sorted(set(missing))


def normalize_video_color_metadata(video_path: str, project: Project) -> bool:
    ffmpeg = resolve_media_tool("ffmpeg")
    if not ffmpeg:
        write_project_log(project, "step8_color_metadata_normalize_skipped", reason="ffmpeg_not_found")
        return False

    temp_path = f"{video_path}.bt709.tmp.mp4"
    if os.path.exists(temp_path):
        os.remove(temp_path)
    result = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            video_path,
            "-c",
            "copy",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
            "-colorspace",
            "bt709",
            "-movflags",
            "+faststart",
            temp_path,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0 or not os.path.exists(temp_path):
        write_project_log(
            project,
            "step8_color_metadata_normalize_error",
            returncode=result.returncode,
            stderr=(result.stderr or "")[-4000:],
        )
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return False

    os.replace(temp_path, video_path)
    write_project_log(
        project,
        "step8_color_metadata_normalize_success",
        stdout=(result.stdout or "")[-4000:],
    )
    return True


@app.post("/api/projects/{project_id}/steps/8/render")
def render_video(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    slide_ids = read_contract_slide_ids(project.run_dir)
    provenance_errors = validate_visual_provenance_set(project.run_dir, slide_ids)
    if provenance_errors:
        details = ", ".join(f"{item['slide_id']}({item['reason']})" for item in provenance_errors)
        raise HTTPException(status_code=409, detail=f"图片来源校验未通过，请返回图片步骤处理: {details}")
    audio_confirmation = tts_confirmation_status(project.run_dir, slide_ids)
    if not audio_confirmation.get("confirmed"):
        raise HTTPException(status_code=400, detail="请先在“旁白与音频”步骤试听并确认音频，再开始视频渲染。")

    # Draft autosave updates the manifest only. Always rebuild reveal assets here
    # so rendering cannot use stale crops from an earlier mask revision.
    build_current_reveal_assets(project)

    # 首先调用 build_remotion_props.py 生成渲染配置属性
    bind_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "bind_reveal_timeline.py"))
    bind_res = subprocess.run([
        sys.executable, bind_script, "--run-dir", project.run_dir, "--lead-sec", str(REVEAL_VISUAL_LEAD_SEC)
    ], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if bind_res.returncode != 0:
        logger.error(f"Timeline binding before render failed: {bind_res.stderr}")
        raise HTTPException(status_code=500, detail=f"渲染前绑定语音时间轴失败: {bind_res.stderr}")

    build_props_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "build_remotion_props.py"))
    remotion_public_dir = os.path.join(REPO_ROOT, "scripts", "remotion", "public")
    props_started = time.time()
    props_res = subprocess.run([
        sys.executable,
        build_props_script,
        "--run-dir",
        project.run_dir,
        "--repo-root",
        REPO_ROOT,
        "--remotion-public-dir",
        remotion_public_dir,
    ], capture_output=True, text=True, encoding="utf-8", errors="replace")
    
    if props_res.returncode != 0:
        logger.error(f"Build remotion props failed: {props_res.stderr}")
        write_project_log(
            project,
            "step8_build_props_error",
            returncode=props_res.returncode,
            stderr=props_res.stderr or "",
        )
        raise HTTPException(status_code=500, detail=f"构建 Remotion 配置失败: {props_res.stderr or ''}")

    write_project_log(
        project,
        "step8_build_props_success",
        elapsed_sec=round(time.time() - props_started, 3),
        stdout=(props_res.stdout or "").strip(),
    )
        
    # 接着，执行 Remotion 渲染
    # 检测 Node.js 模块依赖，执行 npm install (如果 node_modules 不存在)
    remotion_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "remotion"))
    node_modules_dir = os.path.join(remotion_dir, "node_modules")
    
    if not os.path.exists(node_modules_dir):
        logger.info("Initializing Remotion node_modules, running npm install...")
        npm_started = time.time()
        write_project_log(project, "step8_npm_install_start", cwd=remotion_dir)
        # Windows 环境下运行 npm.cmd
        npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
        npm_install = subprocess.run(
            [npm_cmd, "install"],
            cwd=remotion_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if npm_install.returncode != 0:
            logger.error(f"npm install failed:\n{npm_install.stderr}")
            write_project_log(
                project,
                "step8_npm_install_error",
                returncode=npm_install.returncode,
                stderr=npm_install.stderr or "",
            )
            raise HTTPException(status_code=500, detail=f"初始化 Remotion Node 依赖失败: {npm_install.stderr or ''}")
        write_project_log(
            project,
            "step8_npm_install_success",
            elapsed_sec=round(time.time() - npm_started, 3),
            stdout=(npm_install.stdout or "").strip(),
        )
    else:
        write_project_log(project, "step8_npm_install_skipped", node_modules_dir=node_modules_dir)
            
    # 直接调用 Remotion CLI，避免维护第二套渲染入口。
    npx_cmd = "npx.cmd" if sys.platform == "win32" else "npx"
    props_json_path = os.path.join(project.run_dir, "remotion_props.json")
    videos_dir = project_video_dir(project)
    output_filename = f"render_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.mp4"
    output_mp4_path = os.path.join(videos_dir, output_filename)
    legacy_output_path = os.path.join(project.run_dir, "out.mp4")
    
    logger.info(f"Starting Remotion render for {project_id}...")
    render_started = time.time()
    render_args = [
        npx_cmd, "remotion", "render", "src/index.tsx", "ArticleVideo", output_mp4_path,
        f"--props={props_json_path}",
        "--codec=h264",
        "--image-format=png",
        "--pixel-format=yuv420p",
        "--color-space=bt709",
    ]
    with open(props_json_path, "r", encoding="utf-8") as props_file:
        remotion_props_payload = json.load(props_file)
    missing_assets = validate_remotion_public_assets(remotion_props_payload, remotion_public_dir)
    if missing_assets:
        write_project_log(
            project,
            "step8_public_asset_validation_error",
            missing_assets=missing_assets[:50],
            missing_count=len(missing_assets),
            public_dir=remotion_public_dir,
        )
        raise HTTPException(status_code=500, detail=f"Remotion 渲染素材缺失: {missing_assets[:8]}")
    write_project_log(
        project,
        "step8_remotion_render_start",
        output=output_mp4_path,
        timeout_sec=STEP8_RENDER_TIMEOUT_SEC,
        total_duration_sec=remotion_props_payload.get("total_duration_sec"),
    )
    
    try:
        render_res = subprocess.run(
            render_args,
            cwd=remotion_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=STEP8_RENDER_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        logger.error("Remotion render timed out")
        write_project_log(project, "step8_remotion_render_timeout", timeout_sec=STEP8_RENDER_TIMEOUT_SEC)
        raise HTTPException(status_code=504, detail="视频渲染超时")

    if render_res.returncode != 0:
        logger.error(f"Remotion render failed: {render_res.stderr}")
        write_project_log(
            project,
            "step8_remotion_render_error",
            returncode=render_res.returncode,
            stdout=(render_res.stdout or "")[-4000:],
            stderr=(render_res.stderr or "")[-4000:],
        )
        raise HTTPException(status_code=500, detail=f"视频渲染失败: {render_res.stderr}")
    write_project_log(
        project,
        "step8_remotion_render_success",
        elapsed_sec=round(time.time() - render_started, 3),
        stdout=(render_res.stdout or "")[-4000:],
    )
    normalize_video_color_metadata(output_mp4_path, project)
    color_validator = os.path.join(REPO_ROOT, "scripts", "validate_render_color.py")
    color_result = subprocess.run(
        [
            sys.executable,
            color_validator,
            "--video",
            output_mp4_path,
            "--run-dir",
            project.run_dir,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if color_result.returncode != 0:
        if os.path.exists(output_mp4_path):
            os.remove(output_mp4_path)
        logger.error("Rendered video color validation failed: %s", color_result.stderr)
        raise HTTPException(
            status_code=500,
            detail=f"视频颜色校验失败，已阻止输出: {color_result.stderr}",
        )
    render_fingerprint = current_render_input_fingerprint(project)
    write_json_atomic(
        video_metadata_path(output_mp4_path),
        {
            "rendered_at": datetime.now().isoformat(timespec="seconds"),
            "reveal_pipeline_version": REVEAL_PIPELINE_VERSION,
            "video_background": read_project_visual_settings(project)["video_background"],
            "subtitle_style": read_project_visual_settings(project)["subtitle_style"],
            "manifest": "reveal_manifest.json",
            "input_fingerprint": render_fingerprint,
            "color_standard": "bt709_tv_yuv420p",
            "color_validation": json.loads(color_result.stdout),
        },
    )
    shutil.copy2(output_mp4_path, legacy_output_path)

    handle_step_navigation(project, 8, db)
    item = video_item(project, output_mp4_path)
    return {"success": True, "video_url": item["url"], "video": item, "videos": list_video_items(project, project_id)}

@app.get("/api/projects/{project_id}/videos")
def list_project_videos(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return {"success": True, "videos": list_video_items(project, project_id)}

@app.get("/api/projects/{project_id}/videos/{filename}")
def get_project_video(project_id: str, filename: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    video_path = project_video_file_or_400(project, filename)
    if not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail="视频文件不存在")
    return FileResponse(video_path, media_type="video/mp4", filename=filename)


@app.post("/api/projects/{project_id}/videos/{filename}/speed")
def create_speed_adjusted_video(
    project_id: str,
    filename: str,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    requested_path = project_video_file_or_400(project, filename)
    safe_name = filename
    try:
        speed = round(float(payload.get("speed", 1.0)), 2)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="视频语速必须是数字")
    if speed < 0.5 or speed > 2.0:
        raise HTTPException(status_code=400, detail="视频语速范围为 0.5× 到 2.0×")

    if not os.path.exists(requested_path):
        raise HTTPException(status_code=404, detail="视频文件不存在")
    requested_metadata = read_video_metadata(requested_path)
    source_name = os.path.basename(str(requested_metadata.get("source_filename") or safe_name))
    try:
        source_path = str(storage_video_file(project.run_dir, source_name))
    except UnsafeProjectPath:
        source_name, source_path = safe_name, requested_path
    if not os.path.exists(source_path):
        source_name, source_path = safe_name, requested_path
    if abs(speed - 1.0) <= 0.001:
        return {"success": True, "video": video_item(project, source_path), "videos": list_video_items(project, project_id)}

    ffmpeg = resolve_media_tool("ffmpeg")
    if not ffmpeg:
        raise HTTPException(status_code=500, detail="未找到 FFmpeg，无法生成调速视频")
    speed_tag = f"{speed:.2f}".rstrip("0").rstrip(".").replace(".", "_")
    source_stem = os.path.splitext(source_name)[0]
    output_name = f"{source_stem}_speed_{speed_tag}x.mp4"
    output_path = str(storage_video_file(project.run_dir, output_name))
    temp_path = output_path + ".tmp.mp4"
    if os.path.exists(temp_path):
        os.remove(temp_path)
    command = [
        ffmpeg,
        "-y",
        "-i",
        source_path,
        "-filter:v",
        f"setpts=PTS/{speed}",
        "-filter:a",
        f"atempo={speed}",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        temp_path,
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=STEP8_RENDER_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired as exc:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise HTTPException(status_code=504, detail="生成调速视频超时") from exc
    if result.returncode != 0 or not os.path.exists(temp_path):
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise HTTPException(status_code=500, detail=f"生成调速视频失败：{result.stderr[-800:]}")
    os.replace(temp_path, output_path)
    source_metadata = read_video_metadata(source_path)
    source_metadata.update({
        "rendered_at": datetime.now().isoformat(timespec="seconds"),
        "playback_rate": speed,
        "source_filename": source_name,
        "speed_adjustment": "ffmpeg_setpts_atempo",
    })
    write_json_atomic(video_metadata_path(output_path), source_metadata)
    item = video_item(project, output_path)
    return {"success": True, "video": item, "videos": list_video_items(project, project_id)}


@app.delete("/api/projects/{project_id}/videos/{filename}")
def delete_project_video(project_id: str, filename: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    safe_name = filename
    if safe_name == "out.mp4":
        video_path = project_legacy_video_file(project)
    else:
        video_path = project_video_file_or_400(project, safe_name)
    if not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail="视频文件不存在")
    os.remove(video_path)
    metadata_path = video_metadata_path(video_path)
    if os.path.exists(metadata_path):
        os.remove(metadata_path)

    remaining = list_video_items(project, project_id)
    legacy_path = project_legacy_video_file(project)
    regular_remaining = [
        item for item in remaining
        if item.get("filename") != "out.mp4"
        and os.path.exists(project_video_file_or_400(project, item["filename"]))
    ]
    if regular_remaining:
        newest_path = project_video_file_or_400(project, regular_remaining[0]["filename"])
        shutil.copy2(newest_path, legacy_path)
    elif os.path.exists(legacy_path):
        os.remove(legacy_path)
    return {"success": True, "videos": list_video_items(project, project_id)}

# 获取最终生成的 MP4 视频
@app.get("/api/projects/{project_id}/video/status")
def get_final_video_status(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    video_path = os.path.join(project.run_dir, "out.mp4")
    exists = os.path.exists(video_path)
    video_mtime = os.path.getmtime(video_path) if exists else 0
    latest_input_mtime = 0
    latest_input_path = None

    input_candidates = [
        os.path.join(project.run_dir, "reveal_manifest.json"),
        os.path.join(project.run_dir, "planning", "visual_contract.json"),
    ]
    slides_dir = os.path.join(project.run_dir, "slides")
    if os.path.isdir(slides_dir):
        for root, _, files in os.walk(slides_dir):
            for filename in files:
                if filename.lower().endswith((".json", ".mp3", ".srt", ".png", ".jpg", ".jpeg")):
                    input_candidates.append(os.path.join(root, filename))

    for path in input_candidates:
        if not os.path.exists(path):
            continue
        mtime = os.path.getmtime(path)
        if mtime > latest_input_mtime:
            latest_input_mtime = mtime
            latest_input_path = path

    stale = bool(exists and latest_input_mtime > video_mtime + 1)
    return {
        "exists": exists,
        "video_url": f"/api/projects/{project_id}/video" if exists else None,
        "size": os.path.getsize(video_path) if exists else 0,
        "updated_at": datetime.fromtimestamp(video_mtime).isoformat(timespec="seconds") if exists else None,
        "stale": stale,
        "latest_input_updated_at": datetime.fromtimestamp(latest_input_mtime).isoformat(timespec="seconds") if latest_input_mtime else None,
        "latest_input_path": latest_input_path,
    }

@app.get("/api/projects/{project_id}/video")
def get_final_video(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    video_path = os.path.join(project.run_dir, "out.mp4")
    if not os.path.exists(video_path):
        items = list_video_items(project, project_id)
        if items:
            video_path = os.path.join(project.run_dir, "videos", items[0]["filename"])
    if not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail="最终视频尚未渲染生成")
    return FileResponse(video_path, media_type="video/mp4")

# ==================== 前端托管 ====================

static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "static"))
os.makedirs(static_dir, exist_ok=True)

try:
    import one_click_orchestrator

    if one_click_orchestrator._register(sys.modules[__name__]) is not True:
        raise RuntimeError("one-click route dependencies are incomplete")
except Exception as exc:
    logger.exception("Explicit one-click route registration failed: %s", exc)
    raise

try:
    import diagnostics_routes

    if diagnostics_routes._register(sys.modules[__name__]) is not True:
        raise RuntimeError("diagnostics route dependencies are incomplete")
except Exception as exc:
    logger.exception("Explicit diagnostics route registration failed: %s", exc)
    raise

try:
    import storyboard_background

    if storyboard_background._register(sys.modules[__name__]) is not True:
        raise RuntimeError("storyboard background route dependencies are incomplete")
except Exception as exc:
    logger.exception("Explicit storyboard background route registration failed: %s", exc)
    raise

try:
    from project_style_routes import register_project_style_routes

    register_project_style_routes(sys.modules[__name__])
except Exception as exc:
    logger.exception("Explicit project style route registration failed: %s", exc)
    raise

try:
    import runtime_ai_mask

    if runtime_ai_mask._register(sys.modules[__name__]) is not True:
        raise RuntimeError("AI Mask route dependencies are incomplete")
except Exception as exc:
    logger.exception("Explicit AI Mask route registration failed: %s", exc)
    raise

# 挂载静态资源
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

if __name__ == "__main__":
    from start_server import main as start_main

    raise SystemExit(start_main())
