import os
import io
import sys
import uuid
import json
import copy
import shutil
import logging
import subprocess
import re
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from PIL import Image
import httpx
import yaml
from openai import OpenAI

def get_openai_client(api_key: str, base_url: str = None) -> OpenAI:
    # 强制不使用环境变量中的代理，防止某些局域网代理的 SSL 拦截规则冲突
    # 并强制定义 User-Agent 为 Chrome 浏览器以绕过 Cloudflare WAF/JA3 爬虫过滤指纹
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
    http_client = httpx.Client(
        limits=limits,
        trust_env=False,
        headers=headers
    )
    return OpenAI(api_key=api_key, base_url=base_url, http_client=http_client)

from database import init_db, get_db, Project, Setting
from config_store import get_all_settings, update_settings, get_setting

# 初始化日志与数据库
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("PPTStudio")
init_db()

app = FastAPI(title="PPT Visualization Studio", description="本地手绘线稿风 PPT 视频生成系统")

# 解决跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

RUNS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "runs"))
os.makedirs(RUNS_DIR, exist_ok=True)
REPO_ROOT = os.path.abspath(os.path.dirname(__file__))
STYLE_TOKENS_PATH = os.path.join(REPO_ROOT, "config", "style_tokens.yaml")
STYLE_REFERENCE_DIR = os.path.join(REPO_ROOT, "references", "style_reference")
STYLE_REFERENCE_FILES = {
    "template": "PPT模板.png",
    "example": "PPT示例.png",
}

# Pydantic 响应模型
class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = ""

class SettingsUpdate(BaseModel):
    settings: Dict[str, str]

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

class TestTtsPayload(BaseModel):
    endpoint: str
    api_key: str
    model: str
    voice_id: str

# 图片后处理：将任意尺寸等比例缩放，并居中贴在 #FFFDF7 暖白背景的 1920x1080 画布上
def process_and_save_image(image_bytes: bytes, save_path: str):
    bg_color = (255, 253, 247)  # #FFFDF7
    target_width, target_height = 1920, 1080
    
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode != "RGB":
        img = img.convert("RGB")
        
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
    
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    final_img.save(save_path, "PNG")
    logger.info(f"Image processed and saved to: {save_path}")

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


def normalize_visual_contract(contract: Dict[str, Any]) -> Dict[str, Any]:
    slides = contract.get("slides")
    if not isinstance(slides, list):
        return contract

    for slide in slides:
        if not isinstance(slide, dict):
            continue
        groups = slide.get("visual_groups")
        if not isinstance(groups, list):
            continue

        group_by_id: Dict[str, Dict[str, Any]] = {}
        for index, group in enumerate(groups, start=1):
            if not isinstance(group, dict):
                continue
            group_id = str(group.get("id") or f"group_{index:02d}").strip()
            group["id"] = group_id
            role = str(group.get("role") or "content_body").strip()
            group["role"] = role
            if not str(group.get("content_unit_id") or "").strip():
                group["content_unit_id"] = f"{group_id}_unit"
            if not str(group.get("speak_policy") or "").strip():
                group["speak_policy"] = "display_only" if role in {"subtitle", "decoration"} else "speak"
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
        referenced_group_ids = set()
        for index, beat in enumerate(beats, start=1):
            if not isinstance(beat, dict):
                continue
            if not str(beat.get("id") or "").strip():
                beat["id"] = f"beat_{index:02d}"
            group_id = str(beat.get("group_id") or "").strip()
            group = group_by_id.get(group_id)
            if not group:
                continue
            if group.get("speak_policy") == "display_only":
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
            referenced_group_ids.add(group_id)
            normalized_beats.append(beat)

        for group_id, group in group_by_id.items():
            if group.get("speak_policy") == "display_only" or group.get("role") == "decoration":
                continue
            if group_id in referenced_group_ids:
                continue
            anchor = str(group.get("visible_text") or group_id).strip()
            normalized_beats.append(
                {
                    "id": f"beat_auto_{len(normalized_beats) + 1:02d}",
                    "content_unit_id": group.get("content_unit_id"),
                    "group_id": group_id,
                    "visible_anchor": anchor,
                    "spoken_intent": str(group.get("narration_function") or f"解释{anchor}").strip(),
                    "spoken_text": f"请看画面中的{anchor}，这里说明的是{str(group.get('narration_function') or anchor).strip()}。",
                }
            )
        slide["narration_beats"] = normalized_beats

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


def prune_unlinked_mask_groups(project: Project, payload: Dict[str, Any]) -> Dict[str, Any]:
    contract_path = os.path.join(project.run_dir, "planning", "visual_contract.json")
    if not os.path.exists(contract_path) or not isinstance(payload.get("slides"), list):
        return payload

    try:
        with open(contract_path, "r", encoding="utf-8") as f:
            contract = json.load(f)
    except Exception as exc:
        logger.warning("Failed to load visual contract while pruning Mask groups: %s", exc)
        return payload

    narrated_groups_by_slide = {}
    for slide in contract.get("slides", []) or []:
        if not isinstance(slide, dict):
            continue
        slide_id = str(slide.get("slide_id") or "").strip()
        narrated_groups_by_slide[slide_id] = {
            str(beat.get("group_id") or "").strip()
            for beat in slide.get("narration_beats", []) or []
            if isinstance(beat, dict) and str(beat.get("group_id") or "").strip()
        }

    def is_linked(group: Dict[str, Any], narrated_group_ids: set[str]) -> bool:
        fragments = group.get("narration_fragments")
        if isinstance(fragments, list) and any(
            isinstance(fragment, dict) and (fragment.get("id") or fragment.get("text"))
            for fragment in fragments
        ):
            return True
        if str(group.get("narration_beat_id") or "").strip():
            return True
        beat_ids = group.get("narration_beat_ids")
        if isinstance(beat_ids, list) and any(str(value or "").strip() for value in beat_ids):
            return True
        if str(group.get("spoken_text") or "").strip():
            return True
        linked_ids = {
            str(group.get(key) or "").strip()
            for key in ("narration_group_id", "visual_group_id", "group_id", "id")
            if str(group.get(key) or "").strip()
        }
        return bool(linked_ids & narrated_group_ids)

    for slide in payload.get("slides", []):
        if not isinstance(slide, dict):
            continue
        slide_id = str(slide.get("slide_id") or "").strip()
        narrated_group_ids = narrated_groups_by_slide.get(slide_id, set())
        for field in ("semantic_blocks", "groups", "reveal_boxes"):
            groups = slide.get(field)
            if not isinstance(groups, list):
                continue
            slide[field] = [
                group for group in groups
                if isinstance(group, dict) and is_linked(group, narrated_group_ids)
            ]
    return payload


def read_current_slide_ids_or_404(project: Project) -> List[str]:
    slide_ids = read_contract_slide_ids(project.run_dir)
    if not slide_ids:
        raise HTTPException(status_code=400, detail="分镜规划尚未生成，请先完成第二步")
    return slide_ids


def sync_reveal_manifest_to_contract(project: Project, slide_ids: Optional[List[str]] = None) -> bool:
    """Keep mask annotations aligned with the slides that still exist in Step 2."""
    current_slide_ids = slide_ids if slide_ids is not None else read_contract_slide_ids(project.run_dir)
    if not current_slide_ids:
        return False

    manifest_path = os.path.join(project.run_dir, "reveal_manifest.json")
    if not os.path.exists(manifest_path):
        return False

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
    synced_slides = [by_id[slide_id] for slide_id in current_slide_ids if slide_id in by_id]
    if synced_slides == slides:
        return False

    manifest["slides"] = synced_slides
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    logger.info(
        "Synced reveal manifest to visual contract: kept %s of %s slides",
        len(synced_slides),
        len(slides),
    )
    return True


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
    synced_slides = [by_id[slide_id] for slide_id in current_slide_ids if slide_id in by_id]
    if synced_slides == slides:
        return False

    payload["slides"] = synced_slides
    with open(beats_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
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
SUBTITLE_SPLIT_MARKS = "，。！？；：、,.!?;:"


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
    if len(value) <= max_chars:
        return [value]

    chunks: List[str] = []
    remaining = value
    while len(remaining) > max_chars:
        window = remaining[: max_chars + 1]
        cut_at = max((window.rfind(mark) for mark in SUBTITLE_SPLIT_MARKS), default=-1)
        if cut_at < max(8, max_chars // 2) or cut_at >= max_chars:
            cut_at = max_chars - 1
        chunk = remaining[: cut_at + 1].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[cut_at + 1 :].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


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
    duration = float(timeline.get("audio_content_duration_sec") or timeline.get("duration_sec") or 0)
    if duration <= 0:
        return
    clean_beats = [
        {
            "id": str(beat.get("id") or f"{slide_id}_beat_{idx + 1:03d}"),
            "text": clean_tts_text(beat_tts_text(beat)),
        }
        for idx, beat in enumerate(beats)
        if clean_tts_text(beat_tts_text(beat))
    ]
    if not clean_beats:
        return
    weights = [max(1, len(item["text"])) for item in clean_beats]
    total_weight = sum(weights)
    cursor = 0.0
    segments = []
    for beat_index, (item, weight) in enumerate(zip(clean_beats, weights), start=1):
        beat_end = duration if beat_index == len(clean_beats) else cursor + duration * weight / total_weight
        chunks = split_subtitle_text(item["text"])
        chunk_weights = [max(1, len(chunk)) for chunk in chunks]
        chunk_total = sum(chunk_weights)
        chunk_cursor = cursor
        for chunk_index, (chunk, chunk_weight) in enumerate(zip(chunks, chunk_weights), start=1):
            chunk_end = (
                beat_end
                if chunk_index == len(chunks)
                else chunk_cursor + (beat_end - cursor) * chunk_weight / chunk_total
            )
            segments.append({
                "id": item["id"] if chunk_index == 1 else f"{item['id']}__part_{chunk_index:02d}",
                "beat_id": item["id"],
                "start": round(chunk_cursor, 3),
                "end": round(chunk_end, 3),
                "text": chunk,
                "timing_source": "beat_estimated_split",
                "max_cjk_chars": SUBTITLE_MAX_CHARS,
                "max_lines": 1,
            })
            chunk_cursor = chunk_end
        cursor = beat_end
    timeline["segments"] = segments
    timeline["timing_source"] = "beat_estimated_split"
    timeline["subtitle_display"] = {
        "max_lines": 1,
        "max_cjk_chars": SUBTITLE_MAX_CHARS,
    }
    timeline["audio_content_duration_sec"] = round(duration, 3)
    timeline["duration_sec"] = round(duration + float(timeline.get("audio_start_sec", 0.0) or 0.0), 3)
    with open(timeline_path, "w", encoding="utf-8") as f:
        json.dump(timeline, f, ensure_ascii=False, indent=2)

# ==================== 项目管理接口 ====================

@app.post("/api/projects")
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)):
    project_id = str(uuid.uuid4())[:8] + "_" + datetime.now().strftime("%H%M%S")
    run_dir = os.path.join(RUNS_DIR, project_id)
    
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
            "step_status": db_project.get_step_status()
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
        "run_dir": project.run_dir
    }

@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    # 物理删除 runs 文件夹
    if os.path.exists(project.run_dir):
        try:
            shutil.rmtree(project.run_dir)
        except Exception as e:
            logger.error(f"Failed to delete directory {project.run_dir}: {e}")
            
    db.delete(project)
    db.commit()
    return {"success": True, "message": "项目删除成功"}

# ==================== 设置管理接口 ====================

@app.get("/api/settings")
def get_settings():
    return get_all_settings()

@app.put("/api/settings")
def update_system_settings(payload: SettingsUpdate):
    update_settings(payload.settings)
    return {"success": True, "message": "设置更新成功"}

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
        try:
            response = client.images.generate(
                model=payload.model,
                prompt="a single dot",
                size="1024x1024",
                n=1,
                timeout=15
            )
        except Exception:
            response = client.images.generate(
                model=payload.model,
                prompt="a single dot",
                n=1,
                timeout=15
            )
        if response.data:
            return {"success": True, "message": "连接成功！生图接口响应正常。"}
        return {"success": False, "message": "未返回有效图片数据。"}
    except Exception as e:
        return {"success": False, "message": f"连接失败: {str(e)}"}

@app.post("/api/settings/test-tts")
def test_tts_connection(payload: TestTtsPayload):
    try:
        url = payload.endpoint
        headers = {
            "Authorization": f"Bearer {payload.api_key}",
            "Content-Type": "application/json"
        }
        body = {
            "model": payload.model,
            "text": "测试",
            "voice_setting": {
                "voice_id": payload.voice_id,
                "speed": 1.0,
                "vol": 1.0,
                "pitch": 0
            },
            "audio_setting": {
                "audio_sample_rate": 32000,
                "bitrate": 128000,
                "format": "mp3",
                "channel": 1
            }
        }
        res = httpx.post(url, headers=headers, json=body, timeout=15)
        if res.status_code != 200:
            return {"success": False, "message": f"接口请求失败: HTTP {res.status_code}, 内容: {res.text[:100]}"}
        
        content_type = res.headers.get("content-type", "")
        if "audio" in content_type or len(res.content) > 100:
            if b"{" in res.content[:50]:
                try:
                    err_json = res.json()
                    status_msg = err_json.get("base_resp", {}).get("status_msg", "")
                    if status_msg and status_msg != "success":
                        return {"success": False, "message": f"连接失败: {status_msg}"}
                except Exception:
                    pass
            return {"success": True, "message": "连接成功！TTS 合成接口可以正常响应。"}
        return {"success": False, "message": f"未返回音频数据。响应内容: {res.text[:100]}"}
    except Exception as e:
        return {"success": False, "message": f"连接失败: {str(e)}"}

# ==================== 流水线状态管理 ====================

# 回退某一步后，后续步骤状态被标记为 pending_reconfirmation
def handle_step_navigation(project: Project, target_step: int, db: Session):
    current_status = project.get_step_status()
    
    # Downstream completed artifacts become stale when an upstream step changes.
    # Steps that were merely unlocked or waiting should go back to plain pending.
    for s_idx in range(target_step + 1, 9):
        s_str = str(s_idx)
        if current_status.get(s_str) == "completed":
            current_status[s_str] = "pending_reconfirmation"
        elif current_status.get(s_str) in ["in_progress", "pending_reconfirmation"]:
            current_status[s_str] = "pending"
            
    current_status[str(target_step)] = "completed"
    project.current_step = target_step
    project.set_step_status(current_status)
    db.commit()

@app.post("/api/projects/{project_id}/navigate")
def navigate_project(project_id: str, target_step: int = Form(...), db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    handle_step_navigation(project, target_step, db)
    return {
        "success": True,
        "project": {
            "id": project.id,
            "current_step": project.current_step,
            "step_status": project.get_step_status()
        }
    }

# ==================== 步骤 1: 导入文章 ====================

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
        "summary": build_article_summary(content),
        "content": content,
    }

    brief_path = os.path.join(project.run_dir, "planning", "article_brief.json")
    with open(brief_path, "w", encoding="utf-8") as f:
        json.dump(brief, f, ensure_ascii=False, indent=2)

    handle_step_navigation(project, 1, db)
    return {"success": True, "brief": brief}
        
    # 调用 LLM 做文章提炼
    llm_api_key = get_setting("llm_api_key")
    llm_base_url = get_setting("llm_base_url")
    llm_model = get_setting("llm_model")
    llm_temp = float(get_setting("llm_temperature", "0.7"))
    
    if not llm_api_key:
        raise HTTPException(status_code=400, detail="未配置大模型 API 密钥，请在系统设置中配置后再试。")
    
    client = get_openai_client(api_key=llm_api_key, base_url=llm_base_url)
    system_prompt = "你是一个专业的内容提炼助手。请阅读用户输入的 Markdown 文章，提炼出它的核心标题以及一份易于视频分镜表达的摘要提纲（150字以内）。请直接返回 JSON 格式结果，格式为: {\"title\": \"标题\", \"summary\": \"提炼好的摘要提纲\", \"content\": \"原文\"}"
    
    try:
        response = client.chat.completions.create(
            model=llm_model,
            temperature=llm_temp,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content}
            ]
        )
        content_str = response.choices[0].message.content.strip()
        cleaned_content = clean_json_markdown(content_str)
        brief = json.loads(cleaned_content)
        brief["content"] = content
    except Exception as e:
        logger.error(f"LLM ingest article error: {e}")
        raise HTTPException(status_code=500, detail=f"文章提炼失败: {str(e)}")
            
    brief_path = os.path.join(project.run_dir, "planning", "article_brief.json")
    with open(brief_path, "w", encoding="utf-8") as f:
        json.dump(brief, f, ensure_ascii=False, indent=2)
        
    handle_step_navigation(project, 1, db)
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
    with open(brief_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        
    # 同步回写 article.md
    if "content" in payload:
        article_path = os.path.join(project.run_dir, "inputs", "article.md")
        with open(article_path, "w", encoding="utf-8") as f:
            f.write(payload["content"])
            
    return {"success": True, "brief": payload}

# ==================== 步骤 2: 智能分镜规划 ====================

def storyboard_rules_path(project: Project) -> str:
    return os.path.join(project.run_dir, "planning", "storyboard_rules.txt")


def default_storyboard_rules() -> str:
    default_path = os.path.join(REPO_ROOT, "templates", "prompts", "storyboard_rules.zh.md")
    if os.path.exists(default_path):
        with open(default_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    return "旁白自然口语化；每个旁白语段只绑定一个清晰的视觉分组；画面先于对应语音约 1 秒出现。"


def build_storyboard_request(
    project_title: str,
    article_summary: str,
    article_content: str,
    storyboard_rules: str,
) -> tuple[str, str]:
    article_chars = len(re.sub(r"\s+", "", article_content))
    if article_chars <= 1200:
        slide_count_requirement = "4 到 6 页"
        group_count_requirement = "5-6 个"
    elif article_chars <= 3000:
        slide_count_requirement = "6 到 8 页"
        group_count_requirement = "5-7 个"
    else:
        slide_count_requirement = "8 到 12 页"
        group_count_requirement = "5-8 个"

    schema_path = os.path.join(REPO_ROOT, "schemas", "visual_contract.schema.json")
    schema_hint = ""
    if os.path.exists(schema_path):
        with open(schema_path, "r", encoding="utf-8") as f:
            schema_hint = f.read()

    system_prompt = f"""你是一个顶级的 PPT 视频分镜策划师。
请阅读用户输入的内容摘要和全文，设计出一份符合 PPT 动画视频制作标准的视觉合约(Visual Contract)。
视频的画面风格为“温暖极简手绘线稿风”。
要求：
1. 必须要将整篇文章合理划分，分成 {slide_count_requirement} Slide（每页的 slide_id 为 slide_001, slide_002 格式）。
2. 每页 Slide 必须定义 {group_count_requirement}视觉分组(visual_groups)，包含：
   - 1个 title 主标题（role 为 'title'）
   - 1个 subtitle 副标题（role 为 'subtitle'）
   - 2-4个 body/diagram 主体/图表区（role 只能是 'content_body', 'diagram', 'annotation', 'summary', 'decoration' 之一）
   - 1个 summary 总结区（role 为 'summary'）
3. 每个视觉分组（visual_groups）必须有：
   - id: 比如 title_group, subtitle_group, body_group_01 等
   - visible_text: 页面上会显式画出来的中文字符标签（非常重要，通常为 2-8 个字，绝对不能为空）
   - visual_anchor: 手绘线稿元素的视觉描述（比如“顶部主标题”、“左边带圆圈数字1的方框”、“中间一个简笔画小脑”）
   - narration_function: 解释该分组在画面中所起的视觉/解释作用
   - reveal_order: 页面渲染时层淡入淡出显示的顺序，从 1 开始依次增加
4. 必须规划 narration_beats (旁白语段)，使说话声音与相应视觉分组绑定：
   - group_id: 指向前面定义的 visual_groups 中的 id
   - visible_anchor: 该分组对应的 visible_text 文本（不可写错，必须一致）
   - spoken_intent: 这一句话想达到的意图
   - spoken_text: 这一句话具体要朗读的中文旁白（需自然连贯，解释 visible_text）
5. 用户自定义的分镜与演讲稿规则如下。请遵守这些内容，但不得修改输出字段、层级、ID 规则或 JSON 结构：
--- 用户分镜规则开始 ---
{storyboard_rules}
--- 用户分镜规则结束 ---
6. 请确保生成的 JSON 数据严格符合以下的 JSON Schema 格式要求：
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
    return {"success": True, "rules": rules}


@app.put("/api/projects/{project_id}/steps/2/rules")
def update_step2_rules(project_id: str, payload: Dict[str, Any], db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    rules = str(payload.get("rules") or "").strip()
    if not rules:
        rules = default_storyboard_rules()
    path = storyboard_rules_path(project)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(rules + "\n")
    return {"success": True, "rules": rules}


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

    project_title = (project.name or "").strip() or brief.get("title") or "未命名项目"
    article_content = str(brief.get("content") or "")
    article_summary = brief.get("summary") or build_article_summary(article_content)
    system_prompt, user_prompt = build_storyboard_request(
        project_title,
        article_summary,
        article_content,
        storyboard_rules,
    )
    return {
        "success": True,
        "system_content": system_prompt,
        "user_content": user_prompt,
    }


@app.post("/api/projects/{project_id}/steps/2/execute")
def execute_step2(project_id: str, db: Session = Depends(get_db)):
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
    planning_max_tokens = parse_int_setting(get_setting("llm_max_tokens", "16000"), 16000, 1024, 64000)
    
    if not llm_api_key:
        raise HTTPException(status_code=400, detail="未配置大模型 API 密钥，请在系统设置中配置后再试。")
        
    schema_path = os.path.join(REPO_ROOT, "schemas", "visual_contract.schema.json")
    schema_hint = ""
    if os.path.exists(schema_path):
        with open(schema_path, "r", encoding="utf-8") as f:
            schema_hint = f.read()
    rules_path = storyboard_rules_path(project)
    if os.path.exists(rules_path):
        with open(rules_path, "r", encoding="utf-8") as f:
            storyboard_rules = f.read().strip()
    else:
        storyboard_rules = default_storyboard_rules()
    system_prompt, user_prompt = build_storyboard_request(
        project_title,
        article_summary,
        article_content,
        storyboard_rules,
    )

    try:
        client = get_openai_client(api_key=llm_api_key, base_url=llm_base_url)
        try:
            response = client.chat.completions.create(
                model=llm_model,
                temperature=planning_temp,
                max_tokens=planning_max_tokens,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
            )
        except Exception as inner_e:
            logger.warning(f"Failed LLM call with response_format in step 2, retrying without it: {inner_e}")
            response = client.chat.completions.create(
                model=llm_model,
                temperature=planning_temp,
                max_tokens=planning_max_tokens,
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
        
        # 强制补充一些固定版本信息
        contract["version"] = "visual_contract_v1"
        if "topic" not in contract:
            contract["topic"] = {
                "topic_id": "topic_" + project_id,
                "topic_name": project_title,
                "topic_summary": article_summary
            }
        contract = normalize_visual_contract(contract)
            
        # 写入 JSON
        contract_path = os.path.join(project.run_dir, "planning", "visual_contract.json")
        with open(contract_path, "w", encoding="utf-8") as f:
            json.dump(contract, f, ensure_ascii=False, indent=2)
            
        # 调用原项目的验证脚本进行 contract 校验
        validate_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "validate_visual_contract.py"))
        val_res = subprocess.run([
            sys.executable, validate_script, "--contract", contract_path
        ], capture_output=True, text=True, encoding="utf-8")
        
        if val_res.returncode != 0:
            logger.warning(f"Visual contract validation warning:\n{val_res.stderr}")
            # 虽然校验可能报错，但如果不严重，仍然保存以方便用户在前台手动修改
            
        handle_step_navigation(project, 2, db)
        return {"success": True, "contract": contract}
    except Exception as e:
        logger.error(f"LLM write visual contract error: {e}")
        raise HTTPException(status_code=500, detail=f"LLM 规划分镜失败: {str(e)}")

@app.get("/api/projects/{project_id}/steps/2/result")
def get_step2_result(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    contract_path = os.path.join(project.run_dir, "planning", "visual_contract.json")
    if not os.path.exists(contract_path):
        return {"success": False, "message": "尚未生成分镜规划"}
        
    with open(contract_path, "r", encoding="utf-8") as f:
        contract = json.load(f)
    return {"success": True, "contract": contract}

@app.put("/api/projects/{project_id}/steps/2/result")
def update_step2_result(project_id: str, payload: Dict[str, Any], db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    contract_path = os.path.join(project.run_dir, "planning", "visual_contract.json")
    with open(contract_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    current_slide_ids = contract_slide_ids_from_payload(payload)
    sync_reveal_manifest_to_contract(project, current_slide_ids)
    sync_narration_beats_to_contract(project, current_slide_ids)
        
    return {"success": True, "contract": payload}

# ==================== 步骤 3-4: 图片生成与管理 ====================

IMAGE_STYLE_TOP_LEVEL_KEYS = ("brand", "canvas", "colors", "layout", "visual_assets")
IMAGE_STYLE_VISUAL_ASSET_FIELDS = {
    "image_style": "image_style",
    "diagram_style": "diagram_style",
    "required_background": "required_background",
    "layout_rules": "reveal_friendly_layout",
    "avoid": "avoid",
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
    return yaml.safe_dump(
        editable_image_style_data(style_tokens),
        allow_unicode=True,
        sort_keys=False,
        width=1000,
    ).strip()


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
            merged[key] = value
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
    return merged


def build_image_style_prompt(style_tokens: Dict[str, Any]) -> str:
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
    background = canvas.get("background") or colors.get("background") or "#FFFDF7"
    lines.append(f"- 画布：{aspect_ratio}，按 {width}x{height} 构图，纯色背景 {background}。")

    palette_keys = ("ink", "yellow", "yellow_soft", "green_soft", "blue_soft")
    palette = [str(colors[key]) for key in palette_keys if colors.get(key)]
    if palette:
        lines.append(f"- 配色：主线条与强调色使用 {'、'.join(palette)}，保持克制和清晰。")

    title_block = layout.get("title_block") if isinstance(layout.get("title_block"), dict) else {}
    content = layout.get("content") if isinstance(layout.get("content"), dict) else {}
    subtitle_area = layout.get("subtitle_area") if isinstance(layout.get("subtitle_area"), dict) else {}
    subtitle_reserved = canvas.get("subtitle_reserved") if isinstance(canvas.get("subtitle_reserved"), dict) else {}
    if title_block:
        lines.append("- 标题与副标题位于页面上方，沿用模板参考图的字号层级和左侧标题标记。")
    if content:
        lines.append("- 主体内容放在页面中部开放区域，不绘制包围整页内容的大外框。")
    subtitle_y = subtitle_area.get("y") or subtitle_reserved.get("y")
    if subtitle_y is not None:
        lines.append(f"- y={subtitle_y} 以下留作视频字幕安全区，不放关键文字、人物或图形。")

    layout_rules = assets.get("reveal_friendly_layout")
    if isinstance(layout_rules, list):
        for rule in layout_rules:
            text = str(rule).strip()
            if "纯净平面" in text:
                lines.append(f"- {text}")

    avoid = assets.get("avoid")
    if isinstance(avoid, list) and avoid:
        lines.append(f"- 避免：{'、'.join(str(item) for item in avoid if item)}。")

    lines.append("- 参考图优先：字体感觉、线条粗细、配色、留白和视觉层级以附带的模板图与示例图为准。")
    lines.append("- 只生成最终静态整页图片，不要加入图层名称、制作说明或播放器界面。")
    return "\n".join(lines)


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
        "references": references,
    }


@app.put("/api/image-style")
def update_image_style(payload: Dict[str, Any]):
    style_text = str(payload.get("style_text") or "").strip()
    if not style_text:
        raise HTTPException(status_code=400, detail="图片风格规范不能为空")
    try:
        parsed = yaml.safe_load(style_text)
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=400, detail=f"YAML 格式错误: {exc}")
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="图片风格规范必须是 YAML 对象")
    current = read_style_tokens_data()
    merged = merge_image_style_update(current, parsed)
    with open(STYLE_TOKENS_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(
            merged,
            f,
            allow_unicode=True,
            sort_keys=False,
            width=1000,
        )
    return {"success": True}


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
    filename = STYLE_REFERENCE_FILES.get(kind)
    if not filename:
        raise HTTPException(status_code=404, detail="参考图类型不存在")
    content = file.file.read()
    try:
        image = Image.open(io.BytesIO(content)).convert("RGB")
        os.makedirs(STYLE_REFERENCE_DIR, exist_ok=True)
        image.save(os.path.join(STYLE_REFERENCE_DIR, filename), "PNG")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"参考图不是有效图片: {exc}")
    return {"success": True, "url": f"/api/image-style/reference/{kind}?t={uuid.uuid4().hex[:8]}"}


# 辅助生成某一页 PPT 生图的 Prompt。
# 在这里，我们需要配合手绘风格的规则，将 visual_anchor 及 visible_text 与预定义的线稿艺术做融合。
def generate_prompt_for_slide(slide: Dict[str, Any], topic_name: str) -> str:
    group_lines = []
    for idx, g in enumerate(slide.get("visual_groups", []), start=1):
        visible_text = str(g.get("visible_text") or "").strip()
        visual_anchor = str(g.get("visual_anchor") or "").strip()
        group_lines.append(
            f"{idx}. 文字“{visible_text}”；画面：{visual_anchor}。"
        )
    groups_str = "\n".join(group_lines)
    main_title = slide.get("main_title", "")
    subtitle = slide.get("subtitle", "")
    subtitle_part = f"\n副标题：{subtitle}" if subtitle else ""
    style_prompt = build_image_style_prompt(read_style_tokens_data())
    return (
        f"请生成一张 16:9 的 PPT 手绘讲解页。\n"
        f"项目主题：{topic_name}\n主标题：{main_title}{subtitle_part}\n\n"
        "构图硬性要求：\n"
        "1. 每个视觉分组必须是独立的视觉岛，分组之间保留清晰空白。\n"
        "2. 每个分组指定的中文必须清晰、完整、原样出现，不得改写、遗漏或产生乱码。\n"
        "3. 不要合并不同分组，不要让相邻分组的文字、线条、箭头和装饰相互粘连。\n"
        "4. 主标题位于顶部，主体内容位于中部，总结区位于底部字幕安全区上方。\n"
        "5. 画布按 1920x1080 设计，底部 y=930..1080 必须留空，不放重要文字、人物或图形。\n"
        "6. 不要绘制包围整页内容的大外框。\n\n"
        f"本页必须呈现的画面内容：\n{groups_str}\n\n"
        f"{style_prompt}"
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
        
    topic_name = contract.get("topic", {}).get("topic_name", project.name)
    
    # 遍历 slide 列表，为每页拼接并自动保存生成的 prompt，供前台编辑
    slide_prompts = []
    for slide in contract.get("slides", []):
        slide_id = slide["slide_id"]
        generated_prompt = generate_prompt_for_slide(slide, topic_name)
        slide_prompts.append({
            "slide_id": slide_id,
            "title": slide["main_title"],
            "prompt": generated_prompt
        })
        
    return {"success": True, "prompts": slide_prompts}

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

    if slide_id not in read_current_slide_ids_or_404(project):
        raise HTTPException(status_code=404, detail="Slide 不存在")

    api_key = get_setting("image_api_key")
    base_url = get_setting("image_base_url")
    model = get_setting("image_model", "gpt-image-1")
    image_filename = "visual_candidate.png" if preview else "visual_draft.png"
    save_path = os.path.join(project.run_dir, "slides", slide_id, image_filename)
    
    if not api_key:
        raise HTTPException(status_code=400, detail="未配置生图 API 密钥，请在系统设置中配置，或使用下方本地上传图片功能。")
        
    try:
        import base64 as b64lib
        client = get_openai_client(api_key=api_key, base_url=base_url)
        image_size = get_setting("image_size", "1024x1024")
        logger.info(f"Generating image for {slide_id} using {model}, size={image_size}, prompt: {prompt[:80]}")

        response = None
        reference_paths = [
            os.path.join(STYLE_REFERENCE_DIR, filename)
            for filename in STYLE_REFERENCE_FILES.values()
            if os.path.exists(os.path.join(STYLE_REFERENCE_DIR, filename))
        ]
        if reference_paths and str(model).startswith("gpt-image"):
            reference_files = []
            try:
                reference_files = [open(path, "rb") for path in reference_paths]
                response = client.images.edit(
                    model=model,
                    image=reference_files,
                    prompt=prompt,
                    size=image_size,
                    n=1,
                )
                logger.info("Image generation used %s style reference images.", len(reference_files))
            except Exception as reference_error:
                logger.warning("Reference image generation is unavailable, falling back to images.generate: %s", reference_error)
            finally:
                for reference_file in reference_files:
                    reference_file.close()

        if response is None:
            try:
                response = client.images.generate(
                    model=model,
                    prompt=prompt,
                    size=image_size,
                    quality="standard",
                    n=1
                )
            except Exception as full_params_err:
                logger.warning(
                    f"Image gen with full params failed ({full_params_err}). "
                    "Retrying with minimal params (no size/quality) for newapi compatibility..."
                )
                response = client.images.generate(
                    model=model,
                    prompt=prompt,
                    n=1
                )

        # ── 兼容两种响应格式：URL 和 base64 (b64_json) ──
        img_bytes: bytes | None = None
        first_item = response.data[0]
        
        # 优先读取 b64_json（部分中转供应商直接返回 base64）
        if getattr(first_item, "b64_json", None):
            img_bytes = b64lib.b64decode(first_item.b64_json)
            logger.info(f"Image received as b64_json for {slide_id}.")
        elif getattr(first_item, "url", None):
            image_url = first_item.url
            logger.info(f"Image URL received: {image_url}. Downloading...")
            http_client = httpx.Client(timeout=60)
            img_resp = http_client.get(image_url)
            if img_resp.status_code != 200:
                raise RuntimeError(f"下载生成的图片失败: HTTP {img_resp.status_code}")
            img_bytes = img_resp.content
        else:
            raise RuntimeError("API 响应中既没有 url 也没有 b64_json，无法获取图片数据")

        process_and_save_image(img_bytes, save_path)
        logger.info(f"Image saved for {slide_id}: {save_path}")
        if preview:
            return {
                "success": True,
                "candidate_url": f"/api/projects/{project_id}/slides/{slide_id}/candidate?t={uuid.uuid4().hex[:6]}",
            }
        if all_current_slide_images_exist(project):
            handle_step_navigation(project, 3, db)
        
        return {"success": True, "image_url": f"/api/projects/{project_id}/slides/{slide_id}/image?t={uuid.uuid4().hex[:6]}"}
    except Exception as e:
        logger.error(f"Image generation error for {slide_id}: {e}")
        raise HTTPException(status_code=500, detail=f"生成图片失败: {str(e)}")

@app.post("/api/projects/{project_id}/steps/3/upload")
def upload_slide_image(project_id: str, slide_id: str = Form(...), file: UploadFile = File(...), db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    try:
        content = file.file.read()
        save_path = os.path.join(project.run_dir, "slides", slide_id, "visual_draft.png")
        process_and_save_image(content, save_path)
        if all_current_slide_images_exist(project):
            handle_step_navigation(project, 3, db)
        return {"success": True, "image_url": f"/api/projects/{project_id}/slides/{slide_id}/image?t={uuid.uuid4().hex[:6]}"}
    except Exception as e:
        logger.error(f"Upload image error for {slide_id}: {e}")
        raise HTTPException(status_code=500, detail=f"上传图片失败: {str(e)}")

# 获取指定页面的图片资源接口
@app.get("/api/projects/{project_id}/slides/{slide_id}/image")
def get_slide_image_file(project_id: str, slide_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    img_path = os.path.join(project.run_dir, "slides", slide_id, "visual_draft.png")
    if not os.path.exists(img_path):
        raise HTTPException(status_code=404, detail="图片不存在")
        
    from fastapi.responses import FileResponse
    return FileResponse(img_path, media_type="image/png")


@app.get("/api/projects/{project_id}/slides/{slide_id}/candidate")
def get_slide_candidate_file(project_id: str, slide_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    if slide_id not in read_current_slide_ids_or_404(project):
        raise HTTPException(status_code=404, detail="Slide 不存在")

    candidate_path = os.path.join(project.run_dir, "slides", slide_id, "visual_candidate.png")
    if not os.path.exists(candidate_path):
        raise HTTPException(status_code=404, detail="候选图片不存在")
    return FileResponse(candidate_path, media_type="image/png")


@app.post("/api/projects/{project_id}/steps/3/apply-candidate")
def apply_slide_candidate(project_id: str, payload: Dict[str, Any], db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    slide_id = str(payload.get("slide_id") or "").strip()
    if slide_id not in read_current_slide_ids_or_404(project):
        raise HTTPException(status_code=404, detail="Slide 不存在")

    slide_dir = os.path.join(project.run_dir, "slides", slide_id)
    candidate_path = os.path.join(slide_dir, "visual_candidate.png")
    image_path = os.path.join(slide_dir, "visual_draft.png")
    if not os.path.exists(candidate_path):
        raise HTTPException(status_code=404, detail="候选图片不存在，请先生成")

    os.replace(candidate_path, image_path)
    if all_current_slide_images_exist(project):
        handle_step_navigation(project, 3, db)
    return {
        "success": True,
        "image_url": f"/api/projects/{project_id}/slides/{slide_id}/image?t={uuid.uuid4().hex[:6]}",
    }

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
                "url": f"/api/projects/{project_id}/slides/{slide_id}/image?t={uuid.uuid4().hex[:4]}" if exists else None
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
                    "url": f"/api/projects/{project_id}/slides/{slide_dir_name}/image?t={uuid.uuid4().hex[:4]}" if exists else None
                })
    return {"success": True, "images": results}


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

    contract_path = os.path.join(project.run_dir, "planning", "visual_contract.json")
    if not os.path.exists(contract_path):
        raise HTTPException(status_code=400, detail="分镜规划尚未生成")
    with open(contract_path, "r", encoding="utf-8") as f:
        contract = json.load(f)

    slides = contract.get("slides", [])
    by_id = {
        str(slide.get("slide_id") or "").strip(): slide
        for slide in slides
        if isinstance(slide, dict) and str(slide.get("slide_id") or "").strip()
    }
    if set(requested_ids) != set(by_id):
        raise HTTPException(status_code=400, detail="排序列表与当前分镜不一致，请刷新页面后重试")

    contract["slides"] = [by_id[slide_id] for slide_id in requested_ids]
    with open(contract_path, "w", encoding="utf-8") as f:
        json.dump(contract, f, ensure_ascii=False, indent=2)
    sync_reveal_manifest_to_contract(project, requested_ids)
    sync_narration_beats_to_contract(project, requested_ids)
    return {"success": True, "slide_ids": requested_ids}


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
        
    # 步骤4：确认图片。将步骤 3 与 4 状态标记为已完成
    # 自动调用 write_reveal_manifest_template.py 生成 manifest 模板
    manifest_path = os.path.join(project.run_dir, "reveal_manifest.json")
    if not os.path.exists(manifest_path):
        template_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "write_reveal_manifest_template.py"))
        res = subprocess.run([
            sys.executable, template_script, "--run-dir", project.run_dir
        ], capture_output=True, text=True, encoding="utf-8")
        if res.returncode != 0:
            logger.error(f"Failed to write reveal manifest template: {res.stderr}")
            raise HTTPException(status_code=500, detail="自动创建 Mask 标注文件失败，请确认分镜规划正常")
            
        # 预先执行 auto_fit_reveal_boxes.py 进行算法自适应黑墨水对齐
        autofit_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "auto_fit_reveal_boxes.py"))
        fit_res = subprocess.run([
            sys.executable, autofit_script, "--manifest", manifest_path
        ], capture_output=True, text=True, encoding="utf-8")
        if fit_res.returncode != 0:
            logger.warning(f"Initial auto-fit reveal boxes warning: {fit_res.stderr}")
    sync_reveal_manifest_to_contract(project)

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
    semantic_type = str(ai_block.get("semantic_element_type") or role_label(role)).strip()
    visual_description = str(ai_block.get("visual_description") or "").strip()
    if not visual_description:
        if visual_anchor and visible_text:
            visual_description = f"{semantic_type}：画面中可见文字“{visible_text}”，位置/形态为{visual_anchor}。"
        elif visual_anchor:
            visual_description = f"{semantic_type}：{visual_anchor}。"
        else:
            visual_description = f"{semantic_type}：请结合当前页画面中与旁白含义最接近的可见元素。"
    semantic_note = str(ai_block.get("semantic_note") or "").strip()
    if not semantic_note:
        semantic_note = "建议只涂抹该语块对应的可见元素本体，避开相邻箭头、装饰线和底部字幕安全区。"
    return {
        "group_id": f"semantic_{slide_id}_{index:02d}",
        "source": "ai_semantic",
        "visual_group_id": visual_group_id,
        "role": role,
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
        for group in manifest_slide.get("groups", []) or []:
            if isinstance(group, dict):
                existing_boxes[str(group.get("id") or group.get("group_id") or "")] = group.get("box")
    fragments = build_narration_fragments(contract_slide)
    fragments_by_id = {fragment["id"]: fragment for fragment in fragments}
    beat_to_fragments: Dict[str, List[str]] = {}
    for fragment in fragments:
        beat_to_fragments.setdefault(fragment["beat_id"], []).append(fragment["id"])
    blocks: List[Dict[str, Any]] = []
    for beat in contract_slide.get("narration_beats", []) or []:
        if not isinstance(beat, dict):
            continue
        beat_id = str(beat.get("id") or "").strip()
        group_id = str(beat.get("group_id") or "").strip()
        fragment_ids = beat_to_fragments.get(beat_id) or []
        if not fragment_ids:
            continue
        group = groups.get(group_id)
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


def semantic_blocks_from_ai(
    slide_id: str,
    ai_data: Dict[str, Any],
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
        for group in manifest_slide.get("groups", []) or []:
            if isinstance(group, dict):
                existing_boxes[str(group.get("id") or group.get("group_id") or "")] = group.get("box")
    fragments = build_narration_fragments(contract_slide)
    fragments_by_id = {fragment["id"]: fragment for fragment in fragments}
    by_beat_id: Dict[str, List[str]] = {}
    by_group_id: Dict[str, List[str]] = {}
    for fragment in fragments:
        by_beat_id.setdefault(fragment.get("beat_id", ""), []).append(fragment["id"])
        by_group_id.setdefault(fragment.get("group_id", ""), []).append(fragment["id"])
    blocks: List[Dict[str, Any]] = []
    used_fragment_ids = set()
    for raw_block in ai_data.get("blocks", []) if isinstance(ai_data.get("blocks"), list) else []:
        if not isinstance(raw_block, dict):
            continue
        fragment_ids = [
            str(value).strip()
            for value in raw_block.get("fragment_ids", [])
            if str(value).strip() in fragments_by_id and str(value).strip() not in used_fragment_ids
        ] if isinstance(raw_block.get("fragment_ids"), list) else []
        beat_id = str(raw_block.get("narration_beat_id") or raw_block.get("beat_id") or "").strip()
        if not fragment_ids and beat_id:
            fragment_ids = [fid for fid in by_beat_id.get(beat_id, []) if fid not in used_fragment_ids]
        visual_group_id = str(raw_block.get("visual_group_id") or raw_block.get("group_id") or "").strip()
        if not fragment_ids and visual_group_id:
            fragment_ids = [fid for fid in by_group_id.get(visual_group_id, []) if fid not in used_fragment_ids]
        if not fragment_ids:
            continue
        if not visual_group_id:
            visual_group_id = fragments_by_id[fragment_ids[0]].get("group_id", "")
        group = groups.get(visual_group_id)
        blocks.append(semantic_block_payload(
            slide_id,
            len(blocks) + 1,
            fragment_ids,
            visual_group_id,
            group,
            fragments_by_id,
            existing_boxes.get(visual_group_id),
            raw_block,
        ))
        used_fragment_ids.update(fragment_ids)
    if len(used_fragment_ids) < len(fragments):
        fallback = deterministic_semantic_blocks(slide_id, contract_slide, manifest_slide)
        for block in fallback:
            fragment_ids = [fragment["id"] for fragment in block.get("narration_fragments", [])]
            if any(fid not in used_fragment_ids for fid in fragment_ids):
                blocks.append({
                    **block,
                    "group_id": f"semantic_{slide_id}_{len(blocks) + 1:02d}",
                })
                used_fragment_ids.update(fragment_ids)
    return blocks

@app.post("/api/projects/{project_id}/steps/5/auto-mask")
def auto_mask_project(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    manifest_path = os.path.join(project.run_dir, "reveal_manifest.json")
    if not os.path.exists(manifest_path):
        raise HTTPException(status_code=400, detail="Mask 配置文件尚未生成，请返回确认图片状态")
        
    llm_api_key = get_setting("llm_api_key")
    llm_base_url = get_setting("llm_base_url")
    vision_model = get_setting("vision_model", "gpt-4o")
    
    # 获取每一页的图片和 visual groups 以调用 Vision API 进行自动标注
    vision_used = False
    if not llm_api_key:
        logger.warning("No LLM API Key configured, skipping vision-assisted auto masking. Running auto-fit fallback.")
    else:
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
                
            client = get_openai_client(api_key=llm_api_key, base_url=llm_base_url)
            import base64
            
            for slide in manifest.get("slides", []):
                slide_id = slide["slide_id"]
                img_path = os.path.join(project.run_dir, "slides", slide_id, "visual_draft.png")
                if not os.path.exists(img_path):
                    continue
                    
                # 优化：将生图大分辨率在后端等比缩放到 960 宽，规避 Vision API 发送 Base64 消息体过大（Payload 413）或接口超时问题
                vision_width = 1920
                vision_height = 1080
                with open(img_path, "rb") as image_file:
                    try:
                        from PIL import Image
                        img = Image.open(image_file)
                        if img.width > 960:
                            ratio = 960 / img.width
                            new_h = int(img.height * ratio)
                            img = img.resize((960, new_h), Image.Resampling.LANCZOS)
                        vision_width, vision_height = img.width, img.height
                        buf = io.BytesIO()
                        img.save(buf, format="PNG")
                        base64_image = base64.b64encode(buf.getvalue()).decode('utf-8')
                    except Exception as resize_err:
                        logger.warning(f"Resize image failed for auto-mask {slide_id}: {resize_err}")
                        image_file.seek(0)
                        base64_image = base64.b64encode(image_file.read()).decode('utf-8')
                    
                # 拼接分组信息。当前 reveal manifest 使用 groups[]，
                # 旧版 reveal_boxes[] 仅作为兼容兜底。
                groups_info = []
                slide_groups = slide.get("groups") if isinstance(slide.get("groups"), list) else []
                if slide_groups:
                    for group in slide_groups:
                        box = group.get("box", {}) if isinstance(group.get("box"), dict) else {}
                        scaled_box = [
                            round(float(box.get("x", 0)) * vision_width / 1920),
                            round(float(box.get("y", 0)) * vision_height / 1080),
                            round((float(box.get("x", 0)) + float(box.get("w", 0))) * vision_width / 1920),
                            round((float(box.get("y", 0)) + float(box.get("h", 0))) * vision_height / 1080),
                        ]
                        groups_info.append(
                            f"Group ID: {group['id']}\n"
                            f"- exact visible label: {group.get('visible_text', '')}\n"
                            f"- visual anchor: {group.get('visual_anchor', '')}\n"
                            f"- prior box on the provided image: {scaled_box}"
                        )
                else:
                    for box in slide.get("reveal_boxes", []):
                        groups_info.append(f"Group ID: {box['group_id']}, text label: '{box.get('text_label', '')}'")
                groups_info_str = "\n".join(groups_info)
                if not groups_info_str:
                    continue
                
                system_prompt = (
                    "You are a precise visual segmentation annotator for a PPT-style whiteboard slide. "
                    f"The provided image is {vision_width}x{vision_height}. "
                    "For each group, locate ONLY the visual island that semantically belongs to that group. "
                    "Use the exact visible label and visual anchor to identify the correct island. "
                    "Return tight, minimal bounding boxes; do not include unrelated neighboring drawings, arrows, subtitles, or summary text. "
                    "Boxes should not overlap except for a tiny unavoidable edge touch. If two groups are close, split them at the whitespace boundary. "
                    f"The coordinates must be in the provided image coordinate system: X 0..{vision_width}, Y 0..{vision_height}. "
                    "Return a JSON object in this format: "
                    "{\"boxes\": [{\"group_id\": \"group_id\", \"box\": [x_min, y_min, x_max, y_max]}]}"
                )
                
                user_msg = (
                    f"Please find the coordinates of the bounding boxes containing these specific text labels or graphics in the 1920x1080 image:\n"
                    f"{groups_info_str}"
                )
                
                try:
                    response = client.chat.completions.create(
                        model=vision_model,
                        response_format={"type": "json_object"},
                        timeout=60,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": user_msg},
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": f"data:image/png;base64,{base64_image}"
                                        }
                                    }
                                ]
                            }
                        ]
                    )
                except Exception as inner_e:
                    logger.warning(f"Failed Vision call with response_format, retrying without it: {inner_e}")
                    response = client.chat.completions.create(
                        model=vision_model,
                        timeout=60,
                        messages=[
                            {"role": "system", "content": system_prompt + " Please return ONLY raw JSON without any markdown block wrappers like ```json."},
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": user_msg},
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": f"data:image/png;base64,{base64_image}"
                                        }
                                    }
                                ]
                            }
                        ]
                    )
                try:
                    resp_content = response.choices[0].message.content.strip()
                    cleaned_content = clean_json_markdown(resp_content)
                    vision_data = json.loads(cleaned_content)
                    boxes_dict = {b["group_id"]: b["box"] for b in vision_data.get("boxes", [])}
                    
                    if slide_groups:
                        for group in slide_groups:
                            g_id = group["id"]
                            if g_id in boxes_dict:
                                raw_x1, raw_y1, raw_x2, raw_y2 = [float(v) for v in boxes_dict[g_id]]
                                x1 = int(round(raw_x1 * 1920 / vision_width))
                                y1 = int(round(raw_y1 * 1080 / vision_height))
                                x2 = int(round(raw_x2 * 1920 / vision_width))
                                y2 = int(round(raw_y2 * 1080 / vision_height))
                                group["box"] = {
                                    "x": max(0, x1),
                                    "y": max(0, y1),
                                    "w": max(1, x2 - x1),
                                    "h": max(1, y2 - y1)
                                }
                    else:
                        for box in slide.get("reveal_boxes", []):
                            g_id = box["group_id"]
                            if g_id in boxes_dict:
                                box["box"] = [int(v) for v in boxes_dict[g_id]]
                except Exception as ex:
                    logger.error(f"Failed to parse vision response for slide {slide_id}: {ex}. Content: {response.choices[0].message.content}")
                    
            # 保存更新后的 manifest
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
            vision_used = True
                
        except Exception as e:
            logger.error(f"Vision assisted auto-masking failed: {e}. Will fallback to deterministic scripts.")
            vision_used = False
            
    # 接着运行 auto_fit_reveal_boxes.py 做黑墨水自适应边界修剪
    autofit_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "auto_fit_reveal_boxes.py"))
    fit_res = subprocess.run([
        sys.executable, autofit_script, "--manifest", manifest_path
    ], capture_output=True, text=True, encoding="utf-8")
    
    if fit_res.returncode != 0:
        logger.error(f"Auto-fit reveal boxes failed: {fit_res.stderr}")
        raise HTTPException(status_code=500, detail="墨水框线自适应调整失败，请检查图片是否含有墨水")
        
    # 生成预览图片
    preview_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "draw_reveal_manifest_preview.py"))
    out_dir = os.path.join(project.run_dir, "review")
    prev_res = subprocess.run([
        sys.executable, preview_script, "--manifest", manifest_path, "--out-dir", out_dir
    ], capture_output=True, text=True, encoding="utf-8")
    
    if prev_res.returncode != 0:
        logger.warning(f"Draw reveal manifest preview warned: {prev_res.stderr}")
        
    if vision_used:
        msg = f"视觉识别（{vision_model}）成功完成，已精确定位所有分组包围框。"
    else:
        msg = "未启用视觉识别（未配置 API Key 或识别失败），已使用墨水自适应算法自动对齐包围框。"
        
    return {"success": True, "vision_used": vision_used, "message": msg}

@app.post("/api/projects/{project_id}/steps/5/semantic-blocks")
def semantic_blocks_project(project_id: str, payload: Optional[Dict[str, Any]] = None, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    manifest_path = os.path.join(project.run_dir, "reveal_manifest.json")
    contract_path = os.path.join(project.run_dir, "planning", "visual_contract.json")
    if not os.path.exists(manifest_path):
        raise HTTPException(status_code=400, detail="Mask 配置文件尚未生成，请先确认图片")
    if not os.path.exists(contract_path):
        raise HTTPException(status_code=400, detail="分镜规划不存在，请先生成分镜")

    payload = payload or {}
    requested_slide_id = str(payload.get("slide_id") or "").strip()

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
        manifest_slide["reveal_boxes"] = [
            box for box in manifest_slide.get("reveal_boxes", []) or []
            if isinstance(box, dict) and group_has_paint(box)
        ]
        manifest_slide["status"] = "pending"
        processed_count += 1

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    msg = "已根据分镜合约生成语义分块，请按清单手动涂抹 Mask。"
    return {"success": True, "vision_used": False, "processed": processed_count, "manifest": manifest, "message": msg}

@app.get("/api/projects/{project_id}/steps/5/result")
def get_step5_result(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    manifest_path = os.path.join(project.run_dir, "reveal_manifest.json")
    if not os.path.exists(manifest_path):
        return {"success": False, "message": "尚未确认图片"}
    sync_reveal_manifest_to_contract(project)

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    return {"success": True, "manifest": manifest}

@app.put("/api/projects/{project_id}/steps/5/draft")
def update_step5_draft(project_id: str, payload: Dict[str, Any], db: Session = Depends(get_db)):
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

    payload = prune_unlinked_mask_groups(project, payload)
    manifest_path = os.path.join(project.run_dir, "reveal_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return {"success": True}

@app.put("/api/projects/{project_id}/steps/5/result")
def update_step5_result(project_id: str, payload: Dict[str, Any], db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    # 保存手动编辑修改的 reveal_manifest
    current_slide_ids = read_contract_slide_ids(project.run_dir)
    if current_slide_ids and isinstance(payload.get("slides"), list):
        by_id = {
            str(slide.get("slide_id") or "").strip(): slide
            for slide in payload.get("slides", [])
            if isinstance(slide, dict) and str(slide.get("slide_id") or "").strip()
        }
        payload["slides"] = [by_id[slide_id] for slide_id in current_slide_ids if slide_id in by_id]

    payload = prune_unlinked_mask_groups(project, payload)
    manifest_path = os.path.join(project.run_dir, "reveal_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        
    # 人工保存后，校验并构建切层 assets，运行 build_reveal_scene.py
    build_scene_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "build_reveal_scene.py"))
    build_res = subprocess.run([
        sys.executable, build_scene_script, "--manifest", manifest_path
    ], capture_output=True, text=True, encoding="utf-8")
    
    if build_res.returncode != 0:
        logger.error(f"Build reveal scene failed: {build_res.stderr}")
        raise HTTPException(status_code=500, detail=f"构建切层素材失败: {build_res.stderr}")
        
    handle_step_navigation(project, 5, db)
    return {"success": True}

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
        sys.executable, write_narration_script, "--run-dir", project.run_dir, "--overwrite"
    ], capture_output=True, text=True, encoding="utf-8")
    
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
            
    global_beats = {"slides": global_slides}
    beats_path = os.path.join(project.run_dir, "planning", "narration_beats.json")
    with open(beats_path, "w", encoding="utf-8") as f:
        json.dump(global_beats, f, ensure_ascii=False, indent=2)
        
    # 读回 narration_beats.json 展现给用户编辑
    with open(beats_path, "r", encoding="utf-8") as f:
        beats = json.load(f)
        
    return {"success": True, "beats": beats}

@app.get("/api/projects/{project_id}/steps/6/result")
def get_step6_result(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    beats_path = os.path.join(project.run_dir, "planning", "narration_beats.json")
    if not os.path.exists(beats_path):
        return {"success": False, "message": "演讲稿尚未生成"}
    sync_narration_beats_to_contract(project)

    with open(beats_path, "r", encoding="utf-8") as f:
        beats = json.load(f)
    return {"success": True, "beats": beats}

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
    llm_max_tokens = parse_int_setting(get_setting("llm_max_tokens", "16000"), 16000, 1024, 64000)
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

    system_prompt = (
        "You are a Chinese voiceover director preparing MiniMax TTS text. "
        "Add only light delivery markup to the existing narration. "
        "Return strict JSON only, with shape {\"slides\":[{\"slide_id\":\"...\",\"beats\":[{\"id\":\"...\",\"tts_text\":\"...\"}]}]}. "
        "Preserve the original meaning and words. Do not rewrite technical terms. "
        "Every beat longer than 12 Chinese characters must contain at least one MiniMax pause tag. "
        "Normally add one to three pause tags such as <#0.2#>, <#0.35#>, <#0.5#> at natural clause boundaries. "
        "Never put pause tags at the beginning or end, never use consecutive pause tags, and keep pause values between 0.01 and 99.99 seconds. "
        "Expression tags are optional and must use only MiniMax speech-2.8 tags such as "
        "(breath), (sighs), (chuckle), (emm), (laughs), (inhale), (exhale), (gasps), (whistles), or (applause). "
        "Avoid expression tags inside numbers, English identifiers, code terms, Token, API, LLM, or backtick content."
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
    ], capture_output=True, text=True, encoding="utf-8")
    
    if val_res.returncode != 0:
        logger.warning(f"Narration grounding warned:\n{val_res.stderr}")
        
    handle_step_navigation(project, 6, db)
    return {"success": True}

# ==================== 步骤 7: 语音合成 ====================

@app.post("/api/projects/{project_id}/steps/7/synthesize")
def synthesize_tts(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    tts_api_key = get_setting("tts_api_key")
    if not tts_api_key:
        tts_api_key = os.environ.get("MINIMAX_API_KEY")
        if tts_api_key:
            logger.info("已从系统环境变量中读取到 MINIMAX_API_KEY，将进行真实 TTS 合成")
            
    if not tts_api_key:
        raise HTTPException(status_code=400, detail="未配置 TTS 语音合成 API 密钥，且系统环境变量 MINIMAX_API_KEY 为空。")
        
    # 从 visual_contract 加载所有 slide_id
    contract_path = os.path.join(project.run_dir, "planning", "visual_contract.json")
    if not os.path.exists(contract_path):
        raise HTTPException(status_code=400, detail="分镜规划尚未生成，请返回确认第二步状态")
        
    with open(contract_path, "r", encoding="utf-8") as f:
        contract = json.load(f)
        
    slide_ids = [slide["slide_id"] for slide in contract.get("slides", [])]
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
            logger.warning(f"Failed to load edited narration beats for TTS: {exc}")
    
    # 动态将 setting 中的 TTS 参数写入环境变量，以便 minimax_tts.py 读取
    tts_endpoint = get_setting("tts_endpoint", "https://api.minimaxi.com/v1/t2a_async_v2")
    tts_model = get_setting("tts_model", "speech-2.8-hd")
    tts_voice_id = get_setting("tts_voice_id", "Chinese (Mandarin)_Soft_Girl")
    tts_speed = get_setting("tts_speed", "1.0")
    tts_volume = get_setting("tts_volume", "1.0")
    tts_pitch = get_setting("tts_pitch", "0")
    os.environ["MINIMAX_API_KEY"] = tts_api_key
    os.environ["MINIMAX_TTS_ENDPOINT"] = tts_endpoint
    os.environ["MINIMAX_TTS_MODEL"] = tts_model
    os.environ["MINIMAX_TTS_VOICE_ID"] = tts_voice_id
    os.environ["MINIMAX_TTS_SPEED"] = tts_speed
    os.environ["MINIMAX_TTS_VOLUME"] = tts_volume
    os.environ["MINIMAX_TTS_PITCH"] = tts_pitch
    os.environ["MINIMAX_API_URL"] = tts_endpoint
        
    tts_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "minimax_tts.py"))
    
    # 循环对每一页 slide 分别生成音频
    for slide_id in slide_ids:
        text_file = os.path.join(project.run_dir, "slides", slide_id, "tts_text.txt")
        out_audio = os.path.join(project.run_dir, "slides", slide_id, "voice.mp3")
        out_meta = os.path.join(project.run_dir, "slides", slide_id, "tts_metadata.json")
        out_srt = os.path.join(project.run_dir, "slides", slide_id, "tts_narration.srt")
        out_timeline = os.path.join(project.run_dir, "slides", slide_id, "audio_timeline.json")
        
        # 确保 text_file 存在，如果不存在，则从 contract 导出的 narration 中提取
        if not os.path.exists(text_file):
            logger.warning(f"tts_text.txt not found for slide {slide_id}, trying to generate it from contract")
            # 找到对应 slide 并提取 narration
            slide_narration = ""
            for s in contract.get("slides", []):
                if s.get("slide_id") == slide_id:
                    slide_narration = "\n".join(b["spoken_text"] for b in s.get("narration_beats", []))
                    break
            os.makedirs(os.path.dirname(text_file), exist_ok=True)
            with open(text_file, "w", encoding="utf-8") as f:
                f.write(slide_narration + "\n")
                
        with open(text_file, "r", encoding="utf-8") as f:
            tts_text = f.read().strip()
            
        logger.info(f"Synthesizing TTS audio for slide: {slide_id}")
        tts_args = [
            sys.executable, tts_script,
            "--text-file", text_file,
            "--out-audio", out_audio,
            "--out-meta", out_meta,
            "--out-srt", out_srt,
            "--out-timeline", out_timeline,
            "--slide-id", slide_id,
            "--endpoint", tts_endpoint,
            "--model", tts_model,
            "--voice-id", tts_voice_id,
            "--speed", tts_speed,
            "--volume", tts_volume,
            "--pitch", tts_pitch
        ]
        
        tts_res = subprocess.run(tts_args, capture_output=True, text=True, encoding="utf-8")
        if tts_res.returncode != 0:
            logger.error(f"TTS Synthesis failed for {slide_id}: {tts_res.stderr}")
            raise HTTPException(status_code=500, detail=f"语音合成失败: {tts_res.stderr}")
        rewrite_audio_timeline_by_beats(out_timeline, slide_id, beats_by_slide.get(slide_id, []))
            
    # 合成完毕后，运行 bind_reveal_timeline.py 绑定时间轴
    bind_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "bind_reveal_timeline.py"))
    bind_res = subprocess.run([
        sys.executable, bind_script, "--run-dir", project.run_dir, "--lead-sec", "0"
    ], capture_output=True, text=True, encoding="utf-8")
    
    if bind_res.returncode != 0:
        logger.error(f"Timeline binding failed: {bind_res.stderr}")
        raise HTTPException(status_code=500, detail=f"时间轴绑定失败: {bind_res.stderr}")
        
    handle_step_navigation(project, 7, db)
    return {"success": True}

# 获取音频文件接口（供前端试听）
@app.get("/api/projects/{project_id}/slides/{slide_id}/audio")
def get_slide_audio_file(project_id: str, slide_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    audio_path = os.path.join(project.run_dir, "slides", slide_id, "voice.mp3")
    if not os.path.exists(audio_path):
        raise HTTPException(status_code=404, detail="该页面音频尚未生成")
        
    return FileResponse(audio_path, media_type="audio/mp3")

@app.post("/api/projects/{project_id}/steps/7/confirm")
def confirm_tts_audio(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    slide_ids = read_current_slide_ids_or_404(project)
    missing = [
        slide_id for slide_id in slide_ids
        if not os.path.exists(os.path.join(project.run_dir, "slides", slide_id, "voice.mp3"))
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
        sys.executable, bind_script, "--run-dir", project.run_dir, "--lead-sec", "0"
    ], capture_output=True, text=True, encoding="utf-8")
    if bind_res.returncode != 0:
        logger.error(f"Timeline binding failed during audio confirm: {bind_res.stderr}")
        raise HTTPException(status_code=500, detail=f"时间轴绑定失败: {bind_res.stderr}")
    handle_step_navigation(project, 7, db)
    return {"success": True}

# ==================== 步骤 8: 视频合成与渲染 ====================

def project_video_dir(project: Project) -> str:
    videos_dir = os.path.join(project.run_dir, "videos")
    os.makedirs(videos_dir, exist_ok=True)
    return videos_dir


def video_item(project_id: str, path: str, label: Optional[str] = None) -> Dict[str, Any]:
    stat = os.stat(path)
    filename = os.path.basename(path)
    return {
        "filename": filename,
        "label": label or filename,
        "size": stat.st_size,
        "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        "url": f"/api/projects/{project_id}/videos/{filename}",
    }


def list_video_items(project: Project, project_id: str) -> List[Dict[str, Any]]:
    videos_dir = os.path.join(project.run_dir, "videos")
    items: List[Dict[str, Any]] = []
    if os.path.isdir(videos_dir):
        for name in os.listdir(videos_dir):
            path = os.path.join(videos_dir, name)
            if os.path.isfile(path) and name.lower().endswith(".mp4"):
                items.append(video_item(project_id, path))
    legacy_path = os.path.join(project.run_dir, "out.mp4")
    if os.path.exists(legacy_path) and not items:
        legacy = video_item(project_id, legacy_path, "out.mp4")
        legacy["url"] = f"/api/projects/{project_id}/video"
        items.append(legacy)
    items.sort(key=lambda item: item["created_at"], reverse=True)
    return items

@app.post("/api/projects/{project_id}/steps/8/render")
def render_video(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    # Draft autosave updates the manifest only. Always rebuild reveal assets here
    # so rendering cannot use stale crops from an earlier mask revision.
    manifest_path = os.path.join(project.run_dir, "reveal_manifest.json")
    build_scene_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "build_reveal_scene.py"))
    build_scene_res = subprocess.run([
        sys.executable, build_scene_script, "--manifest", manifest_path
    ], capture_output=True, text=True, encoding="utf-8")
    if build_scene_res.returncode != 0:
        logger.error(f"Reveal scene rebuild before render failed: {build_scene_res.stderr}")
        raise HTTPException(status_code=500, detail=f"渲染前重建 Mask 素材失败: {build_scene_res.stderr}")

    # 首先调用 build_remotion_props.py 生成渲染配置属性
    bind_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "bind_reveal_timeline.py"))
    bind_res = subprocess.run([
        sys.executable, bind_script, "--run-dir", project.run_dir, "--lead-sec", "0"
    ], capture_output=True, text=True, encoding="utf-8")
    if bind_res.returncode != 0:
        logger.error(f"Timeline binding before render failed: {bind_res.stderr}")
        raise HTTPException(status_code=500, detail=f"渲染前绑定语音时间轴失败: {bind_res.stderr}")

    build_props_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "build_remotion_props.py"))
    props_res = subprocess.run([
        sys.executable, build_props_script, "--run-dir", project.run_dir
    ], capture_output=True, text=True, encoding="utf-8")
    
    if props_res.returncode != 0:
        logger.error(f"Build remotion props failed: {props_res.stderr}")
        raise HTTPException(status_code=500, detail=f"构建 Remotion 配置失败: {props_res.stderr}")
        
    # 接着，执行 Remotion 渲染
    # 检测 Node.js 模块依赖，执行 npm install (如果 node_modules 不存在)
    remotion_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "remotion"))
    node_modules_dir = os.path.join(remotion_dir, "node_modules")
    
    if not os.path.exists(node_modules_dir):
        logger.info("Initializing Remotion node_modules, running npm install...")
        # Windows 环境下运行 npm.cmd
        npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
        npm_install = subprocess.run(
            [npm_cmd, "install"], cwd=remotion_dir, capture_output=True, text=True
        )
        if npm_install.returncode != 0:
            logger.error(f"npm install failed:\n{npm_install.stderr}")
            raise HTTPException(status_code=500, detail=f"初始化 Remotion Node 依赖失败: {npm_install.stderr}")
            
    # 调用 PowerShell 执行 render_remotion.ps1
    # 或者是直接用 npx remotion render
    # 原项目有 render_remotion.ps1 渲染脚本：
    # param($RunId, $RepoRoot = ".")
    # 我们直接使用 python 子进程调用 powershell 跑渲染脚本，或者将其核心命令直接通过 Node 跑：
    # npx remotion render RevealVideo out.mp4 --props="<path_to_props>"
    # 我们来看一下 scripts/render_remotion.ps1
    # 它实际上执行了：
    # npx remotion render RevealVideo "runs/$RunId/out.mp4" --props="runs/$RunId/remotion_props.json"
    # 我们直接用 subprocess.run 调用 npx
    npx_cmd = "npx.cmd" if sys.platform == "win32" else "npx"
    props_json_path = os.path.join(project.run_dir, "remotion_props.json")
    videos_dir = project_video_dir(project)
    output_filename = f"render_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.mp4"
    output_mp4_path = os.path.join(videos_dir, output_filename)
    legacy_output_path = os.path.join(project.run_dir, "out.mp4")
    
    logger.info(f"Starting Remotion render for {project_id}...")
    render_args = [
        npx_cmd, "remotion", "render", "ArticleVideo", output_mp4_path,
        f"--props={props_json_path}"
    ]
    
    render_res = subprocess.run(
        render_args, cwd=remotion_dir, capture_output=True, text=True
    )
    
    if render_res.returncode != 0:
        logger.error(f"Remotion render failed: {render_res.stderr}")
        raise HTTPException(status_code=500, detail=f"视频渲染失败: {render_res.stderr}")
    shutil.copy2(output_mp4_path, legacy_output_path)

    handle_step_navigation(project, 8, db)
    item = video_item(project_id, output_mp4_path)
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
    safe_name = os.path.basename(filename)
    if safe_name != filename or not safe_name.lower().endswith(".mp4"):
        raise HTTPException(status_code=400, detail="视频文件名无效")
    video_path = os.path.join(project.run_dir, "videos", safe_name)
    if not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail="视频文件不存在")
    return FileResponse(video_path, media_type="video/mp4", filename=safe_name)

# 获取最终生成的 MP4 视频
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

# 挂载静态资源
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    # 本地交互流程包含长耗时 AI 请求，默认关闭热重载，避免保存过程中连接被重启打断。
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
