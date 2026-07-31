import os
import io
import sys
import uuid
import json
import copy
import base64
import shutil
import logging
import subprocess
import re
import threading
import time
import warnings
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session
from PIL import Image
import httpx
import yaml
from openai import OpenAI
from database import ArtifactRecord, LocalJob, init_db, get_db, Project
from config_store import get_all_settings, update_settings, get_setting
from app_security import configured_allowed_hosts, configured_allowed_origins, install_access_control
from scripts.background_color import normalize_connected_background
from scripts.media_tools import (
    probe_media_duration_sec,
    resolve_media_tool as shared_resolve_media_tool,
)
from scripts.pipeline_profiles import (
    read_pipeline_profile,
    role_catalog,
    storyboard_profile_prompt,
    storyboard_requirements,
)
from artifact_fingerprint import sha256_file, sha256_json
from visual_provenance import (
    promote_candidate_provenance,
    provenance_path as visual_provenance_path,
    validate_visual_provenance_set,
    visual_provenance_status,
    write_visual_provenance,
)
from project_style_reference_service import (
    can_send_project_references,
    profile_style_prompt,
    project_generate_prompt_for_slide,
    project_reference_paths,
)
from pipeline_lifecycle import (
    project_artifact_lock,
    write_json_atomic,
)
import invalidation_service
from reveal_manifest_service import sync_reveal_manifest
from tts_artifacts import (
    artifact_paths as tts_artifact_paths,
    artifact_status as tts_artifact_status,
    build_confirmation_payload as build_audio_confirmation_payload,
    confirmation_path as tts_confirmation_path,
    is_audio_confirmed,
    nonempty_file as tts_nonempty_file,
    remove_outputs as remove_tts_outputs,
    timeline_duration_sec,
)
from pipeline_state import mark_retry_needed
from project_storage import (
    UnsafeProjectPath,
    project_run_dir as validated_project_run_dir,
    slide_file as storage_slide_file,
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
STEP3_IMAGE_PROMPT_TEMPLATE_PATH = os.path.join(REPO_ROOT, "templates", "prompts", "step3_image_system.md")
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
STEP2_PROMPTS_FILE = "step2_prompts.json"
STEP2_SCRIPT_PLAN_FILE = "slide_script_plan.json"
STEP2_VISUAL_PLAN_FILE = "slide_visual_plan.json"
STEP3_IMAGE_PROMPTS_FILE = "step3_image_prompts.json"
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
    "highlight_color": "#1E3A8A",
    "paging_window_ms": 1300,
    "token_highlight": True,
    "max_lines": 2,
    "line_height": 1.4,
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
    return project_artifact_lock(project.run_dir)


def run_subprocess_bounded(
    args: List[str],
    *,
    timeout_sec: float,
    **kwargs: Any,
) -> subprocess.CompletedProcess:
    """Run a child process with an explicit timeout and result-shaped failure."""
    try:
        return subprocess.run(args, timeout=timeout_sec, **kwargs)
    except subprocess.TimeoutExpired as exc:
        stdout = (
            exc.stdout.decode("utf-8", errors="replace")
            if isinstance(exc.stdout, bytes)
            else str(exc.stdout or "")
        )
        stderr = (
            exc.stderr.decode("utf-8", errors="replace")
            if isinstance(exc.stderr, bytes)
            else str(exc.stderr or "")
        )
        return subprocess.CompletedProcess(
            args=args,
            returncode=124,
            stdout=stdout,
            stderr=f"Timed out after {timeout_sec:g} seconds. {stderr}".strip(),
        )


def parse_json_process_stdout(result: subprocess.CompletedProcess) -> Dict[str, Any]:
    """Return validator JSON without allowing malformed stdout to crash finalization."""
    try:
        payload = json.loads(result.stdout or "{}")
    except (TypeError, json.JSONDecodeError):
        return {
            "parse_warning": "validator stdout was not valid JSON",
            "raw_stdout": str(result.stdout or ""),
        }
    return payload if isinstance(payload, dict) else {"result": payload}


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
STEP8_BUILD_PROPS_TIMEOUT_SEC = 180
STEP8_NPM_INSTALL_TIMEOUT_SEC = 600
STEP8_COLOR_PROCESS_TIMEOUT_SEC = 300
REVEAL_VISUAL_LEAD_SEC = 0.45

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
class StepUpdate(BaseModel):
    step_data: Dict[str, Any]


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
        manual_mode_slide = not groups  # no visual groups: beats are free-standing
        for index, beat in enumerate(beats, start=1):
            if not isinstance(beat, dict):
                continue
            if not str(beat.get("id") or "").strip():
                beat["id"] = f"beat_{index:02d}"
            group_id = str(beat.get("group_id") or "").strip()
            group = group_by_id.get(group_id)
            if not group:
                if manual_mode_slide:
                    # Manual mode: keep beats without group binding. Fill in
                    # content_unit_id if missing so downstream consumers don't
                    # break, but do not require a visual_anchor.
                    if not str(beat.get("content_unit_id") or "").strip():
                        beat["content_unit_id"] = f"{slide.get('slide_id', 'slide')}_unit_{index:03d}"
                    normalized_beats.append(beat)
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


def sync_reveal_manifest_to_contract(project: Project, slide_ids: Optional[List[str]] = None) -> bool:
    explicit_slide_ids = slide_ids is not None
    current_slide_ids = slide_ids if explicit_slide_ids else read_contract_slide_ids(project.run_dir)
    return sync_reveal_manifest(
        project,
        current_slide_ids,
        allow_empty=explicit_slide_ids,
    )


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

    def clamp_float(raw: Any, fallback: float, minimum: float, maximum: float) -> float:
        try:
            parsed = float(raw)
        except (TypeError, ValueError):
            parsed = fallback
        return max(minimum, min(maximum, parsed))

    def parse_bool(raw: Any, fallback: bool) -> bool:
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            normalized = raw.strip().lower()
            if normalized in {"true", "1", "yes", "on"}:
                return True
            if normalized in {"false", "0", "no", "off"}:
                return False
        if isinstance(raw, (int, float)):
            return bool(raw)
        return fallback

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
        "highlight_color": normalize_hex_color(
            payload.get("highlight_color"),
            DEFAULT_SUBTITLE_STYLE["highlight_color"],
        ),
        "paging_window_ms": clamp_int(
            payload.get("paging_window_ms"),
            DEFAULT_SUBTITLE_STYLE["paging_window_ms"],
            600,
            2500,
        ),
        "token_highlight": parse_bool(
            payload.get("token_highlight"),
            DEFAULT_SUBTITLE_STYLE["token_highlight"],
        ),
        "max_lines": clamp_int(
            payload.get("max_lines"),
            DEFAULT_SUBTITLE_STYLE["max_lines"],
            1,
            3,
        ),
        "line_height": clamp_float(
            payload.get("line_height"),
            DEFAULT_SUBTITLE_STYLE["line_height"],
            1.0,
            2.0,
        ),
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
    invalidation_service.subtitle_style_changed(project)
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
    invalidation_service.video_background_changed(
        project,
        read_contract_slide_ids(project.run_dir),
    )
    db.commit()


def sync_narration_beats_to_contract(project: Project, slide_ids: Optional[List[str]] = None) -> bool:
    explicit_slide_ids = slide_ids is not None
    current_slide_ids = slide_ids if explicit_slide_ids else read_contract_slide_ids(project.run_dir)
    if not current_slide_ids and not explicit_slide_ids:
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


def sync_narration_sources_from_contract(
    project: Project,
    previous_contract: Dict[str, Any],
    current_contract: Dict[str, Any],
) -> bool:
    """Propagate Step 2 text edits without overwriting unchanged Step 5 TTS annotations."""
    beats_path = os.path.join(project.run_dir, "planning", "narration_beats.json")
    if not os.path.exists(beats_path):
        return False

    existing_payload = read_json_file(beats_path, {})
    existing_slides = existing_payload.get("slides") if isinstance(existing_payload, dict) else None
    if not isinstance(existing_slides, list):
        return False

    def slide_map(contract: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        return {
            str(slide.get("slide_id") or "").strip(): slide
            for slide in contract.get("slides", [])
            if isinstance(slide, dict) and str(slide.get("slide_id") or "").strip()
        }

    def beat_map(slide: Dict[str, Any], field: str) -> Dict[str, Dict[str, Any]]:
        beats = slide.get(field)
        if not isinstance(beats, list):
            return {}
        return {
            str(beat.get("id") or "").strip(): beat
            for beat in beats
            if isinstance(beat, dict) and str(beat.get("id") or "").strip()
        }

    previous_slides = slide_map(previous_contract if isinstance(previous_contract, dict) else {})
    current_slides = slide_map(current_contract if isinstance(current_contract, dict) else {})
    existing_by_slide = {
        str(slide.get("slide_id") or "").strip(): slide
        for slide in existing_slides
        if isinstance(slide, dict) and str(slide.get("slide_id") or "").strip()
    }
    structural_fields = (
        "id",
        "group_id",
        "content_unit_id",
        "visible_anchor",
        "spoken_intent",
    )
    synced_slides: List[Dict[str, Any]] = []

    for slide_id, current_slide in current_slides.items():
        previous_beats = beat_map(previous_slides.get(slide_id, {}), "narration_beats")
        existing_slide = existing_by_slide.get(slide_id, {})
        existing_beats = beat_map(existing_slide, "beats")
        merged_beats: List[Dict[str, Any]] = []
        for current_beat in dedupe_narration_beats(current_slide.get("narration_beats")):
            beat_id = str(current_beat.get("id") or "").strip()
            if not beat_id:
                continue
            current_text = str(current_beat.get("spoken_text") or "").strip()
            previous_text = str(previous_beats.get(beat_id, {}).get("spoken_text") or "").strip()
            existing_beat = existing_beats.get(beat_id)
            source_changed = beat_id not in previous_beats or current_text != previous_text

            if existing_beat is not None and not source_changed:
                merged = copy.deepcopy(existing_beat)
                for field in structural_fields:
                    if field in current_beat:
                        merged[field] = copy.deepcopy(current_beat[field])
            else:
                merged = copy.deepcopy(current_beat)
                merged["source_text"] = current_text
                merged["spoken_text"] = current_text
                merged["tts_text"] = current_text
            merged_beats.append(merged)
        synced_slides.append({"slide_id": slide_id, "beats": merged_beats})

    candidate = dict(existing_payload)
    candidate["slides"] = synced_slides
    if candidate == existing_payload:
        return False
    prepared = prepare_narration_payload(project, candidate)
    if prepared == existing_payload:
        return False
    persist_narration_beats(project, candidate)
    logger.info("Synced Step 2 narration sources into Step 5 for %s slides", len(synced_slides))
    return True


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
MINIMAX_ALLOWED_EXPRESSION_RE = re.compile(
    "|".join(re.escape(tag) for tag in sorted(MINIMAX_ALLOWED_EXPRESSION_TAGS, key=len, reverse=True))
)
TTS_MARKUP_RE = re.compile(
    rf"(?:{MINIMAX_PAUSE_RE.pattern}|{MINIMAX_ALLOWED_EXPRESSION_RE.pattern})"
)
SUBTITLE_MAX_CHARS = 26
SUBTITLE_HARD_SPLIT_MARKS = "。！？；.!?;"
SUBTITLE_SOFT_SPLIT_MARKS = "，：、,:"
SUBTITLE_SPLIT_MARKS = SUBTITLE_HARD_SPLIT_MARKS + SUBTITLE_SOFT_SPLIT_MARKS
SUBTITLE_EDGE_PUNCTUATION = "，。！？；：、,.!?;: \t\r\n"


def clean_tts_text(text: str) -> str:
    value = TTS_MARKUP_RE.sub("", str(text or ""))
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
        return tag

    value = MINIMAX_EXPRESSION_RE.sub(keep_expression, value)
    value = re.sub(
        r"(<#\d+(?:\.\d{1,2})?#>\s*){2,}",
        lambda m: (MINIMAX_PAUSE_RE.search(m.group(0)).group(0) + " ") if MINIMAX_PAUSE_RE.search(m.group(0)) else " ",
        value,
    )
    value = re.sub(rf"^(?:\s*(?:{TTS_MARKUP_RE.pattern})\s*)+", "", value).strip()
    value = re.sub(rf"(?:\s*(?:{TTS_MARKUP_RE.pattern})\s*)+$", "", value).strip()
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

# ==================== 流水线状态管理 ====================

def audio_confirmation_path(project: Project) -> str:
    return str(tts_confirmation_path(project.run_dir))


def project_audio_confirmed(project: Project) -> bool:
    return is_audio_confirmed(project.run_dir, read_contract_slide_ids(project.run_dir))


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
    """Compatibility wrapper; transition ownership lives in the invalidation service."""
    invalidation_service.begin_stage(project, target_step)
    db.commit()


# 回退某一步后，后续步骤状态被标记为 pending_reconfirmation
def handle_step_navigation(project: Project, target_step: int, db: Session):
    invalidation_service.complete_stage(project, target_step)
    db.commit()


def invalidate_after_upstream_edit(project: Project, source_step: int, db: Session) -> None:
    """Keep edited source data while making every dependent stage explicitly stale."""
    invalidation_service.upstream_content_changed(project, source_step)
    db.commit()


def clear_slide_visual_derivatives(project: Project, slide_id: str) -> None:
    """Remove masks and rendered assets that belong to an older slide image."""
    invalidation_service.clear_slide_visual_derivatives(project, slide_id)


def mark_slide_image_changed(project: Project, slide_id: str, db: Session) -> None:
    invalidation_service.slide_images_changed(
        project,
        [slide_id],
        all_images_exist=all_current_slide_images_exist(project),
    )
    db.commit()

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
    default_step2_prompts,
    execute_step2,
    execute_step2_script_plan,
    execute_step2_visual_plan,
    get_step2_result,
    migrate_legacy_step2_prompt,
    normalize_slide_visual_plan,
    normalize_visual_type,
    read_prompt_template,
    run_step2_json_llm,
    step2_llm_vendor_options,
    step2_prompt_compatibility,
    step2_script_prompt_uses_legacy_contract,
    step2_visual_prompt_uses_legacy_contract,
    storyboard_validation_gate_enabled,
    update_step2_result,
    validate_visual_contract_file,
)

IMAGE_STYLE_TOP_LEVEL_KEYS = (
    "brand",
    "canvas",
    "colors",
    "layout",
    "visual_assets",
)
IMAGE_STYLE_PROMPT_KEY = "prompt_system_content"
IMAGE_STYLE_VISUAL_ASSET_FIELDS = {
    "image_style": "image_style",
    "diagram_style": "diagram_style",
    "required_background": "required_background",
    "layout_rules": "reveal_friendly_layout",
    "avoid": "avoid",
}

# Visual settings routes are source-owned by visual_settings_service.py.

# Global image-style compatibility APIs are source-owned by global_image_style_service.py.
from global_image_style_service import (
    active_style_reference_paths,
    build_image_style_prompt,
    read_image_style_template_index,
    read_style_tokens_data,
    should_send_style_reference_images,
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
    from visual_settings_service import (
        VisualSettingsDependencies,
        configure_visual_settings_service,
    )

    configure_visual_settings_service(
        VisualSettingsDependencies(
            read_settings=read_project_visual_settings,
            write_settings=write_project_visual_settings,
            sync_background=sync_project_background_color,
            invalidate_background=(
                invalidate_video_background_derivatives
            ),
            invalidate_subtitles=invalidate_subtitle_derivatives,
            preview_background_url=subtitle_preview_background_url,
            fonts=OPEN_SOURCE_CHINESE_FONTS,
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
    build_narration_annotation_input,
    get_step6_result,
    init_step6_narration,
    narration_annotation_preserves_text,
    read_narration_annotation_prompts,
    repair_step6_result,
    update_step6_result,
)
from tts_service import (
    confirm_tts_audio,
    get_slide_audio_file,
    get_tts_audio_status,
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
            run_subprocess_bounded=run_subprocess_bounded,
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
            run_subprocess_bounded=run_subprocess_bounded,
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
