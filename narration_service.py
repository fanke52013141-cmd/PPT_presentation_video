"""Step 6 narration initialization, annotation, repair, and persistence."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
import re
import subprocess
import sys
from typing import Any, Callable, Dict, List, Optional

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from config_store import get_setting, update_settings
from database import Project, get_db


logger = logging.getLogger("PPTStudio.Narration")


def _not_configured(*_args: Any, **_kwargs: Any) -> Any:
    raise RuntimeError("Narration dependencies have not been configured")


beat_tts_text: Callable[..., Any] = _not_configured
clean_json_markdown: Callable[..., Any] = _not_configured
clean_tts_text: Callable[..., Any] = _not_configured
ensure_minimax_delivery_markup: Callable[..., Any] = _not_configured
get_openai_client: Callable[..., Any] = _not_configured
handle_step_navigation: Callable[..., Any] = _not_configured
normalize_minimax_tts_markup: Callable[..., Any] = _not_configured
parse_int_setting: Callable[..., Any] = _not_configured
parse_json_or_repair_with_llm: Callable[..., Any] = _not_configured
persist_narration_beats: Callable[..., Any] = _not_configured
prepare_narration_payload: Callable[..., Any] = _not_configured
read_contract_slide_ids: Callable[..., Any] = _not_configured
read_json_file: Callable[..., Any] = _not_configured
sync_narration_beats_to_contract: Callable[..., Any] = _not_configured
TTS_MARKUP_RE = re.compile(r"$^")


@dataclass(frozen=True)
class NarrationDependencies:
    beat_tts_text: Callable[..., Any]
    clean_json_markdown: Callable[..., Any]
    clean_tts_text: Callable[..., Any]
    ensure_minimax_delivery_markup: Callable[..., Any]
    get_openai_client: Callable[..., Any]
    handle_step_navigation: Callable[..., Any]
    normalize_minimax_tts_markup: Callable[..., Any]
    parse_int_setting: Callable[..., Any]
    parse_json_or_repair_with_llm: Callable[..., Any]
    persist_narration_beats: Callable[..., Any]
    prepare_narration_payload: Callable[..., Any]
    read_contract_slide_ids: Callable[..., Any]
    read_json_file: Callable[..., Any]
    sync_narration_beats_to_contract: Callable[..., Any]
    tts_markup_re: Any


def configure_narration_dependencies(
    dependencies: NarrationDependencies,
) -> None:
    global TTS_MARKUP_RE
    global beat_tts_text
    global clean_json_markdown
    global clean_tts_text
    global ensure_minimax_delivery_markup
    global get_openai_client
    global handle_step_navigation
    global normalize_minimax_tts_markup
    global parse_int_setting
    global parse_json_or_repair_with_llm
    global persist_narration_beats
    global prepare_narration_payload
    global read_contract_slide_ids
    global read_json_file
    global sync_narration_beats_to_contract

    beat_tts_text = dependencies.beat_tts_text
    clean_json_markdown = dependencies.clean_json_markdown
    clean_tts_text = dependencies.clean_tts_text
    ensure_minimax_delivery_markup = (
        dependencies.ensure_minimax_delivery_markup
    )
    get_openai_client = dependencies.get_openai_client
    handle_step_navigation = dependencies.handle_step_navigation
    normalize_minimax_tts_markup = (
        dependencies.normalize_minimax_tts_markup
    )
    parse_int_setting = dependencies.parse_int_setting
    parse_json_or_repair_with_llm = (
        dependencies.parse_json_or_repair_with_llm
    )
    persist_narration_beats = dependencies.persist_narration_beats
    prepare_narration_payload = dependencies.prepare_narration_payload
    read_contract_slide_ids = dependencies.read_contract_slide_ids
    read_json_file = dependencies.read_json_file
    sync_narration_beats_to_contract = (
        dependencies.sync_narration_beats_to_contract
    )
    TTS_MARKUP_RE = dependencies.tts_markup_re

def init_step6_narration(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    # 如果不存在 narration，从 visual contract 自动导出初版
    contract_path = os.path.join(project.run_dir, "planning", "visual_contract.json")
    if not os.path.exists(contract_path):
        raise HTTPException(status_code=400, detail="分镜规划不存在，请返回第二步生成分镜")

    beats_path = os.path.join(project.run_dir, "planning", "narration_beats.json")
    existing_beats = read_json_file(beats_path, {})
    if isinstance(existing_beats.get("slides"), list):
        return {"success": True, "beats": existing_beats, "reused": True}
        
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
LEGACY_DEFAULT_NARRATION_ANNOTATION_SYSTEM_CONTENT_V1 = """You are a Chinese voiceover director preparing MiniMax TTS text.

Add only light delivery markup to the existing narration. Preserve the original meaning and words. Do not rewrite technical terms.

Rules:
1. Every beat longer than 12 Chinese characters must contain at least one MiniMax pause tag.
2. Normally add one to three pause tags such as <#0.2#>, <#0.35#>, <#0.5#> at natural clause boundaries.
3. Never put pause tags at the beginning or end, never use consecutive pause tags, and keep pause values between 0.01 and 99.99 seconds.
4. Expression tags are optional and must use only MiniMax speech-2.8 tags such as (breath), (sighs), (chuckle), (emm), (laughs), (inhale), (exhale), (gasps), (whistles), or (applause).
5. Avoid expression tags inside numbers, English identifiers, code terms, Token, API, LLM, or backtick content.
6. Return strict JSON only. Do not output Markdown or explanations."""
LEGACY_DEFAULT_NARRATION_ANNOTATION_OUTPUT_EXAMPLE_V1 = """{
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
DEFAULT_NARRATION_ANNOTATION_SYSTEM_CONTENT = """<PromptVersion>narration_annotation_v2_minimal</PromptVersion>

<Role>
你是一名中文旁白 TTS 标注编辑。你的唯一任务是在原始旁白中加入少量 MiniMax 停顿或自然语气标签，不改写旁白内容。
</Role>

<SystemBackground>
输入中的每个 beat 已经与一个画面 Reveal 单元绑定。`source_text` 是用户确认过的最终旁白；系统会把你返回的 `tts_text` 直接用于语音合成，并会在服务端校验去除标签后的文字必须与 `source_text` 完全一致。
</SystemBackground>

<InputContract>
User Content 是一个 JSON 对象：
{
  "slides": [
    {
      "slide_id": "输入中的 Slide ID",
      "beats": [
        {"id": "输入中的 beat ID", "source_text": "原始旁白"}
      ]
    }
  ]
}

只使用输入中真实存在的 `slide_id`、`id` 和 `source_text`，不得创造、删除、合并、拆分或重排 Slide/beat。
</InputContract>

<AnnotationRules>
1. 除插入合法标签外，`source_text` 中的汉字、字母、数字、标点、术语和顺序必须保持不变。
2. 停顿只用于自然分句、转折、对比、举例或结论边界。短句可以不加；较长 beat 通常 1–3 个，宁少勿多。
3. 停顿格式为 `<#x#>`，常用 `0.2`、`0.35`、`0.5` 秒；不得位于整段开头或结尾，不得连续出现。
4. 语气标签默认不用；只有语义明确需要时，才可少量使用 `(breath)`、`(sighs)`、`(chuckle)`、`(emm)`、`(laughs)`、`(inhale)`、`(exhale)`、`(gasps)`、`(whistles)` 或 `(applause)`。
5. 不在数字、英文标识符、代码术语、Token、API、LLM 或反引号内容内部插入标签。
</AnnotationRules>

<OutputContract>
只输出一个合法 JSON 对象。保留输入中的 Slide 和 beat 顺序；每个 beat 只输出 `id` 与 `tts_text`，不要复制 `source_text`，不要输出解释或额外字段。
</OutputContract>

<SelfCheck>
- 所有 `slide_id` 和 beat `id` 都来自输入，且没有遗漏或重复。
- 去除所有 TTS 标签后，`tts_text` 与对应 `source_text` 完全一致。
- 没有段首/段尾标签、连续停顿或不允许的语气标签。
- 最终输出只有严格 JSON。
</SelfCheck>"""
DEFAULT_NARRATION_ANNOTATION_OUTPUT_EXAMPLE = """{
  "slides": [
    {
      "slide_id": "slide_001",
      "beats": [
        {
          "id": "beat_001",
          "tts_text": "首先看核心概念，<#0.35#>再理解它的实际作用。"
        },
        {
          "id": "beat_002",
          "tts_text": "这是一句短旁白。"
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
    if system_content == LEGACY_DEFAULT_NARRATION_ANNOTATION_SYSTEM_CONTENT_V1:
        system_content = DEFAULT_NARRATION_ANNOTATION_SYSTEM_CONTENT
    if output_example == LEGACY_DEFAULT_NARRATION_ANNOTATION_OUTPUT_EXAMPLE_V1:
        output_example = DEFAULT_NARRATION_ANNOTATION_OUTPUT_EXAMPLE
    return system_content, output_example


def build_narration_annotation_input(incoming: Dict[str, Any]) -> Dict[str, Any]:
    slides: List[Dict[str, Any]] = []
    for slide in incoming.get("slides", []) or []:
        if not isinstance(slide, dict):
            continue
        beats: List[Dict[str, str]] = []
        for index, beat in enumerate(slide.get("beats", []) or [], start=1):
            if not isinstance(beat, dict):
                continue
            # The editable TTS field is the latest user-visible narration.  Re-annotation
            # must never revive a stale source_text/spoken_text value.
            source_text = clean_tts_text(beat_tts_text(beat))
            if not source_text:
                continue
            beats.append({
                "id": str(beat.get("id") or f"beat_{index:03d}"),
                "source_text": source_text,
            })
        slides.append({"slide_id": str(slide.get("slide_id") or ""), "beats": beats})
    return {"slides": slides}


def narration_annotation_preserves_text(candidate: str, source_text: str) -> bool:
    def signature(value: str) -> str:
        without_markup = TTS_MARKUP_RE.sub("", str(value or ""))
        return re.sub(r"\s+", " ", without_markup).strip()

    return signature(candidate) == signature(source_text)


def compose_narration_annotation_prompt(system_content: str, output_example: str) -> str:
    return (
        str(system_content or "").strip()
        + "\n\n<OutputExample>\n"
        + str(output_example or "").strip()
        + "\n</OutputExample>"
    )


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
    annotation_system_content, annotation_output_example = read_narration_annotation_prompts()
    system_prompt = compose_narration_annotation_prompt(
        annotation_system_content,
        annotation_output_example,
    )
    user_prompt = json.dumps(build_narration_annotation_input(incoming), ensure_ascii=False)

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
            original = clean_tts_text(beat_tts_text(beat))
            beat["source_text"] = original
            beat["spoken_text"] = original
            if beat_id in by_id:
                candidate = by_id[beat_id]
                if not narration_annotation_preserves_text(candidate, original):
                    logger.warning(
                        "Narration annotation changed source text; falling back to original: slide=%s beat=%s",
                        slide_id,
                        beat_id,
                    )
                    candidate = str(original or "")
                beat["tts_text"] = ensure_minimax_delivery_markup(normalize_minimax_tts_markup(candidate, original))
                changed += 1

    if changed == 0:
        raise HTTPException(status_code=500, detail="AI returned no usable narration annotations.")

    incoming = persist_narration_beats(project, incoming)
    handle_step_navigation(project, 6, db)
    return {"success": True, "beats": incoming, "annotated_count": changed}

def update_step6_result(project_id: str, payload: Dict[str, Any], db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    persist_narration_beats(project, payload)
        
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
