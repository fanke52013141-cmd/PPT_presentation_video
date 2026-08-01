"""Shared configured JSON generation and one-shot LLM repair."""

from __future__ import annotations

from datetime import datetime
import json
import logging
from typing import Any, Dict

from fastapi import HTTPException
from openai import OpenAI

from ai_provider_service import get_openai_client
from config_store import get_setting
from runtime_support import (
    clean_json_markdown,
    json_decode_context,
    parse_int_setting,
    write_debug_text,
)


logger = logging.getLogger("PPTStudio.JsonLlm")


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

