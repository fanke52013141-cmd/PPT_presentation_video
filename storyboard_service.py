"""Step 2 storyboard planning, templates, and contract lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, Callable, Dict, List, Optional
import uuid

from fastapi import Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
import yaml

from config_store import get_setting
from database import Project, get_db
import invalidation_service
from pipeline_lifecycle import write_json_atomic
from project_storage import slide_file as storage_slide_file
from repository_paths import (
    DATA_DIR,
    REPO_ROOT,
    STEP2_PROMPT_TEMPLATE_FILES,
    STEP2_PROMPT_TEMPLATES_PATH,
    STORYBOARD_TEMPLATES_PATH,
)
from scripts.pipeline_profiles import (
    read_pipeline_profile,
    role_catalog,
    storyboard_profile_prompt,
    storyboard_requirements,
)
from storyboard_llm import StoryboardLlmCapabilities, execute_step2_json_llm
logger = logging.getLogger("PPTStudio.Storyboard")

STEP2_LLM_TIMEOUT_SEC = 600.0


def _not_configured(*_args: Any, **_kwargs: Any) -> Any:
    raise RuntimeError("Storyboard dependencies have not been configured")


clean_json_markdown: Callable[..., Any] = _not_configured
contract_slide_ids_from_payload: Callable[..., Any] = _not_configured
get_openai_client: Callable[..., Any] = _not_configured
handle_step_navigation: Callable[..., Any] = _not_configured
invalidate_after_upstream_edit: Callable[..., Any] = _not_configured
is_timeout_exception: Callable[..., Any] = _not_configured
mark_step_retry_needed: Callable[..., Any] = _not_configured
narration_dedupe_key: Callable[..., Any] = _not_configured
normalize_visual_contract: Callable[..., Any] = _not_configured
normalized_template_name: Callable[..., Any] = _not_configured
parse_int_setting: Callable[..., Any] = _not_configured
parse_json_or_repair_with_llm: Callable[..., Any] = _not_configured
parse_range_text: Callable[..., Any] = _not_configured
read_json_file: Callable[..., Any] = _not_configured
read_project_article_source: Callable[..., Any] = _not_configured
sync_narration_beats_to_contract: Callable[..., Any] = _not_configured
sync_narration_sources_from_contract: Callable[..., Any] = _not_configured
sync_reveal_manifest_to_contract: Callable[..., Any] = _not_configured
template_timestamp: Callable[..., Any] = _not_configured
write_project_log: Callable[..., Any] = _not_configured

AI_KNOWLEDGE_STEP2_SCRIPT_EXTENSION = ""
LEGACY_STEP2_PROMPT_HASHES: dict[str, set[str]] = {}
LEGACY_INTERVIEW_SCRIPT_PROMPT_HASH = ""


@dataclass(frozen=True)
class StoryboardDependencies:
    clean_json_markdown: Callable[..., Any]
    contract_slide_ids_from_payload: Callable[..., Any]
    get_openai_client: Callable[..., Any]
    handle_step_navigation: Callable[..., Any]
    invalidate_after_upstream_edit: Callable[..., Any]
    is_timeout_exception: Callable[..., Any]
    mark_step_retry_needed: Callable[..., Any]
    narration_dedupe_key: Callable[..., Any]
    normalize_visual_contract: Callable[..., Any]
    normalized_template_name: Callable[..., Any]
    parse_int_setting: Callable[..., Any]
    parse_json_or_repair_with_llm: Callable[..., Any]
    parse_range_text: Callable[..., Any]
    read_json_file: Callable[..., Any]
    read_project_article_source: Callable[..., Any]
    sync_narration_beats_to_contract: Callable[..., Any]
    sync_narration_sources_from_contract: Callable[..., Any]
    sync_reveal_manifest_to_contract: Callable[..., Any]
    template_timestamp: Callable[..., Any]
    write_project_log: Callable[..., Any]
    ai_knowledge_script_extension: str
    legacy_prompt_hashes: dict[str, set[str]]
    legacy_interview_script_prompt_hash: str


_DEPENDENCIES: StoryboardDependencies | None = None


def configure_storyboard_dependencies(
    dependencies: StoryboardDependencies,
) -> None:
    global _DEPENDENCIES
    global AI_KNOWLEDGE_STEP2_SCRIPT_EXTENSION
    global LEGACY_INTERVIEW_SCRIPT_PROMPT_HASH
    global LEGACY_STEP2_PROMPT_HASHES
    global clean_json_markdown
    global contract_slide_ids_from_payload
    global get_openai_client
    global handle_step_navigation
    global invalidate_after_upstream_edit
    global is_timeout_exception
    global mark_step_retry_needed
    global narration_dedupe_key
    global normalize_visual_contract
    global normalized_template_name
    global parse_int_setting
    global parse_json_or_repair_with_llm
    global parse_range_text
    global read_json_file
    global read_project_article_source
    global sync_narration_beats_to_contract
    global sync_narration_sources_from_contract
    global sync_reveal_manifest_to_contract
    global template_timestamp
    global write_project_log

    _DEPENDENCIES = dependencies
    clean_json_markdown = dependencies.clean_json_markdown
    contract_slide_ids_from_payload = (
        dependencies.contract_slide_ids_from_payload
    )
    get_openai_client = dependencies.get_openai_client
    handle_step_navigation = dependencies.handle_step_navigation
    invalidate_after_upstream_edit = (
        dependencies.invalidate_after_upstream_edit
    )
    is_timeout_exception = dependencies.is_timeout_exception
    mark_step_retry_needed = dependencies.mark_step_retry_needed
    narration_dedupe_key = dependencies.narration_dedupe_key
    normalize_visual_contract = dependencies.normalize_visual_contract
    normalized_template_name = dependencies.normalized_template_name
    parse_int_setting = dependencies.parse_int_setting
    parse_json_or_repair_with_llm = (
        dependencies.parse_json_or_repair_with_llm
    )
    parse_range_text = dependencies.parse_range_text
    read_json_file = dependencies.read_json_file
    read_project_article_source = (
        dependencies.read_project_article_source
    )
    sync_narration_beats_to_contract = (
        dependencies.sync_narration_beats_to_contract
    )
    sync_narration_sources_from_contract = (
        dependencies.sync_narration_sources_from_contract
    )
    sync_reveal_manifest_to_contract = (
        dependencies.sync_reveal_manifest_to_contract
    )
    template_timestamp = dependencies.template_timestamp
    write_project_log = dependencies.write_project_log
    AI_KNOWLEDGE_STEP2_SCRIPT_EXTENSION = (
        dependencies.ai_knowledge_script_extension
    )
    LEGACY_STEP2_PROMPT_HASHES = dependencies.legacy_prompt_hashes
    LEGACY_INTERVIEW_SCRIPT_PROMPT_HASH = (
        dependencies.legacy_interview_script_prompt_hash
    )
    configure_storyboard_prompt_templates(
        read_json=dependencies.read_json_file,
        normalize_template_name=dependencies.normalized_template_name,
        timestamp=dependencies.template_timestamp,
        ai_knowledge_script_extension=(
            dependencies.ai_knowledge_script_extension
        ),
        legacy_prompt_hashes=dependencies.legacy_prompt_hashes,
        legacy_interview_script_prompt_hash=(
            dependencies.legacy_interview_script_prompt_hash
        ),
    )

from storyboard_profiles import (
    apply_storyboard_profile_patch,
    default_storyboard_profile_text,
    default_storyboard_rules,
    handdrawn_storyboard_rules,
    parse_storyboard_profile_text,
    read_project_pipeline_profile,
    sanitize_storyboard_profile,
    storyboard_profile_editor_data,
    storyboard_profile_path,
    storyboard_rules_path,
    visual_contract_schema_text,
)


from storyboard_prompt_templates import (
    STEP2_PROMPTS_FILE,
    STEP2_SCRIPT_PLAN_FILE,
    STEP2_VISUAL_PLAN_FILE,
    built_in_step2_prompt_templates,
    compose_step2_system_prompt,
    configure_storyboard_prompt_templates,
    default_step2_prompts,
    delete_step2_prompt_template,
    get_step2_prompt_template,
    get_step2_prompt_templates,
    list_step2_prompt_templates,
    migrate_legacy_step2_prompt,
    normalize_step2_prompt_type,
    normalized_prompt_hash,
    read_prompt_template,
    read_step2_prompts,
    save_step2_prompt_template,
    step2_prompt_compatibility,
    step2_prompt_response,
    step2_prompt_template_detail,
    step2_prompts_path,
    step2_script_plan_path,
    step2_script_prompt_uses_legacy_contract,
    step2_visual_plan_path,
    step2_visual_prompt_uses_legacy_contract,
)


from storyboard_planning import (
    build_step2_script_user_prompt,
    build_step2_visual_user_prompt,
    clean_planning_block,
    clean_planning_text,
    compose_visual_contract_from_plans,
    element_visible_text,
    narration_sequence_key,
    normalize_body_points,
    normalize_narration_segments,
    normalize_slide_body,
    normalize_slide_script_plan,
    normalize_slide_visual_plan,
    normalize_visual_elements,
    stable_plan_id,
    validate_slide_visual_mapping,
)


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
    llm_config = configured_step2_llm()
    return execute_step2_json_llm(
        capabilities=StoryboardLlmCapabilities(
            get_openai_client=get_openai_client,
            is_timeout_exception=is_timeout_exception,
            clean_json_markdown=clean_json_markdown,
            parse_json_or_repair_with_llm=parse_json_or_repair_with_llm,
            write_project_log=write_project_log,
            logger=logger,
        ),
        project=project,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        artifact_prefix=artifact_prefix,
        schema_hint=schema_hint,
        trace_id=trace_id,
        llm_config=llm_config,
        vendor_options=step2_llm_vendor_options(llm_config[2], llm_config[1]),
        timeout_sec=STEP2_LLM_TIMEOUT_SEC,
    )


def script_plan_schema_hint() -> str:
    return read_prompt_template(STEP2_PROMPT_TEMPLATE_FILES["script_output_example"])


def visual_plan_schema_hint() -> str:
    return read_prompt_template(STEP2_PROMPT_TEMPLATE_FILES["visual_output_example"])


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


def get_storyboard_templates():
    return {"success": True, "templates": list_storyboard_templates()}


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
    slide_count_requirement, _ = storyboard_requirements(article_content, profile)
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
2. 视觉分组数量由内容和独立 Reveal 需求决定；一个完整正文视觉组同样合法，不设置固定上下限。不要固定套用“主标题/正文/总结”模板；可以按内容需要使用判断链、冲突地图、对象关系图、推理路径、时间压力图、对比、表格、流程、FAQ、场景拆解或行动清单。
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


def get_step2_prompts(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return step2_prompt_response(project)


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


def execute_step2_script_plan(
    project_id: str,
    payload: Optional[Dict[str, Any]] = None,
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    article_source = read_project_article_source(project)
    project_title = article_source["title"]
    article_content = article_source["content"]
    generation_requirement = str((payload or {}).get("requirement") or "").strip()
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


def get_step2_script_plan(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    plan = read_plan_json(step2_script_plan_path(project), "尚未生成演讲稿规划")
    return {"success": True, "script_plan": plan}


def update_step2_script_plan(project_id: str, payload: Dict[str, Any], db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    article_source = read_project_article_source(project)
    project_title = article_source["title"]
    plan = normalize_slide_script_plan(payload, project_title)
    write_json_atomic(step2_script_plan_path(project), plan)
    return {"success": True, "script_plan": plan}


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


def get_step2_visual_plan(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    plan = read_plan_json(step2_visual_plan_path(project), "尚未生成视觉规划")
    return {"success": True, "visual_plan": plan}


def update_step2_visual_plan(project_id: str, payload: Dict[str, Any], db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    script_plan = read_plan_json(step2_script_plan_path(project), "请先生成演讲稿规划")
    plan = normalize_slide_visual_plan(payload, script_plan)
    write_json_atomic(step2_visual_plan_path(project), plan)
    return {"success": True, "visual_plan": plan}


def compose_step2_visual_contract(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    article_source = read_project_article_source(project)
    project_title = article_source["title"]
    article_summary = article_source["summary"]
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


def get_step2_prompt_preview(
    project_id: str,
    payload: Optional[Dict[str, Any]] = None,
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    article_source = read_project_article_source(project)

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

    project_title = article_source["title"]
    article_content = article_source["content"]
    article_summary = article_source["summary"]
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



def execute_step2(
    project_id: str,
    payload: Optional[Dict[str, Any]] = None,
    db: Session = Depends(get_db),
):
    """Compatibility endpoint delegated to the narration-first Step 2 pipeline."""

    execute_step2_script_plan(project_id, payload if isinstance(payload, dict) else {}, db)
    execute_step2_visual_plan(project_id, db)
    result = compose_step2_visual_contract(project_id, db)
    return {
        **result,
        "deprecated_route": True,
        "preferred_routes": [
            f"/api/projects/{project_id}/steps/2/script/execute",
            f"/api/projects/{project_id}/steps/2/visual/execute",
            f"/api/projects/{project_id}/steps/2/compose",
        ],
    }


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

def update_step2_result(project_id: str, payload: Dict[str, Any], db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    payload = normalize_visual_contract(payload, read_project_pipeline_profile(project))
    contract_path = os.path.join(project.run_dir, "planning", "visual_contract.json")
    existing_contract = read_json_file(contract_path, {})
    previous_slide_ids = contract_slide_ids_from_payload(existing_contract)
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
    removed_slide_ids = [slide_id for slide_id in previous_slide_ids if slide_id not in current_slide_ids]
    for slide_id in removed_slide_ids:
        slide_path = Path(storage_slide_file(project.run_dir, slide_id, "visual_draft.png")).parent
        if slide_path.exists():
            shutil.rmtree(slide_path)

    if not current_slide_ids:
        validation = {
            "valid": False,
            "editable_empty": True,
            "contract_sha256": hashlib.sha256(Path(contract_path).read_bytes()).hexdigest(),
            "validated_at": datetime.now().isoformat(timespec="seconds"),
            "returncode": 0,
            "stdout": "",
            "stderr": "分镜列表为空；可以继续添加分镜，但不能进入图片生成。",
            "source": "manual_empty_storyboard",
            "trace_id": "",
        }
        write_json_atomic(visual_contract_validation_path(project), validation)
        sync_reveal_manifest_to_contract(project, [])
        sync_narration_beats_to_contract(project, [])
        sync_narration_sources_from_contract(project, existing_contract, payload)
        invalidation_service.empty_storyboard_changed(project)
        db.commit()
        payload = read_json_file(contract_path, payload)
        return {"success": True, "contract": payload, "validation": validation, "changed": True}

    validation = validate_visual_contract_file(project, contract_path, source="manual_autosave")
    if validation.get("valid"):
        sync_reveal_manifest_to_contract(project, current_slide_ids)
        sync_narration_beats_to_contract(project, current_slide_ids)
        sync_narration_sources_from_contract(project, existing_contract, payload)
        payload = read_json_file(contract_path, payload)
    invalidate_after_upstream_edit(project, 2, db)

    return {"success": True, "contract": payload, "validation": validation, "changed": True}


class ManualSkeletonSlide(BaseModel):
    slide_id: Optional[str] = None
    main_title: str
    narration: str


class ManualSkeletonPayload(BaseModel):
    slides: List[ManualSkeletonSlide]


def submit_step2_manual_skeleton(
    project_id: str,
    payload: ManualSkeletonPayload,
    db: Session = Depends(get_db),
):
    """Manual mode: build a visual_contract.json from title + narration only.

    Each slide produces an empty visual_groups[] (full-slide static render)
    and one narration_beat entry bound to the spoken text. AI Mask is not
    triggered; the user can still click "运行 AI 标注" later if desired.
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    if not payload.slides:
        raise HTTPException(status_code=400, detail="slides 不能为空")

    article_source = read_project_article_source(project, required=False)
    project_title = article_source.get("title") or project.name or project_id
    article_summary = article_source.get("summary", "")

    contract_slides: List[Dict[str, Any]] = []
    for index, slide in enumerate(payload.slides, start=1):
        slide_id = (slide.slide_id or f"slide_{index:03d}").strip()
        main_title = (slide.main_title or "").strip()
        narration = (slide.narration or "").strip()
        if not main_title:
            raise HTTPException(status_code=400, detail=f"{slide_id} 标题不能为空")
        if not narration:
            raise HTTPException(status_code=400, detail=f"{slide_id} 演讲稿不能为空")
        contract_slides.append({
            "slide_id": slide_id,
            "main_title": main_title,
            "subtitle": "",
            "core_message": narration,
            "body_content": [narration],
            "visual_groups": [],
            "narration_beats": [
                {
                    "id": f"{slide_id}_beat_001",
                    "group_id": None,
                    "visible_anchor": "",
                    "spoken_intent": main_title,
                    "spoken_text": narration,
                    "content_unit_id": f"{slide_id}_unit_001",
                }
            ],
        })

    previous_contract = read_json_file(
        os.path.join(project.run_dir, "planning", "visual_contract.json"),
        {},
    )
    contract = {
        "version": "visual_contract_v1",
        "presentation_policy": {
            "subtitle_policy": "no_slides_have_subtitle",
            "subtitle_decided_by": "system_no_subtitle_contract",
            "visual_narration_mapping": "manual_free_v1",
        },
        "topic": {
            "topic_id": "topic_" + project_id,
            "topic_name": project_title,
            "topic_summary": article_summary,
        },
        "slides": contract_slides,
    }

    trace_id = uuid.uuid4().hex[:8]
    contract = finalize_step2_contract(
        project=project,
        project_id=project_id,
        db=db,
        contract=contract,
        project_title=project_title,
        article_summary=article_summary,
        trace_id=trace_id,
        source="manual_skeleton_submit",
    )
    sync_narration_sources_from_contract(project, previous_contract, contract)
    # Ensure the project reflects manual mode so the frontend can render the
    # correct UI affordances (e.g., hide auto-trigger AI Mask).
    if project.ai_mode != "manual":
        project.ai_mode = "manual"
        db.commit()
        db.refresh(project)
    return {"success": True, "contract": contract, "ai_mode": project.ai_mode}


# ==================== 步骤 3-4: 图片生成与管理 ====================



