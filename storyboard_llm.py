"""Bounded Step 2 JSON-model execution and response parsing."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Callable, Dict, Optional

from fastapi import HTTPException


@dataclass(frozen=True)
class StoryboardLlmCapabilities:
    get_openai_client: Callable[..., Any]
    is_timeout_exception: Callable[[BaseException], bool]
    clean_json_markdown: Callable[[str], str]
    parse_json_or_repair_with_llm: Callable[..., Dict[str, Any]]
    write_project_log: Callable[..., None]
    logger: Any


def execute_step2_json_llm(
    *,
    capabilities: StoryboardLlmCapabilities,
    project: Any,
    system_prompt: str,
    user_prompt: str,
    artifact_prefix: str,
    schema_hint: str,
    trace_id: str,
    llm_config: tuple[str, Optional[str], str, float, int],
    vendor_options: Dict[str, Any],
    timeout_sec: float,
) -> Dict[str, Any]:
    llm_api_key, llm_base_url, llm_model, planning_temp, planning_max_tokens = llm_config
    stage_label = {
        "step2_script_plan": "Step 2A 演讲稿规划",
        "step2_visual_plan": "Step 2B 可视化规划",
    }.get(artifact_prefix, "Step 2 分镜规划")
    started_at = time.monotonic()
    capabilities.write_project_log(
        project,
        f"{artifact_prefix}_start",
        trace_id=trace_id,
        model=llm_model,
        base_url=llm_base_url,
        max_tokens=planning_max_tokens,
        thinking_disabled=bool(vendor_options),
    )
    client = capabilities.get_openai_client(
        api_key=llm_api_key,
        base_url=llm_base_url,
        timeout=timeout_sec,
        max_retries=0,
    )
    try:
        try:
            response = client.chat.completions.create(
                model=llm_model,
                temperature=planning_temp,
                max_tokens=planning_max_tokens,
                timeout=timeout_sec,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                **vendor_options,
            )
        except Exception as inner_error:
            if capabilities.is_timeout_exception(inner_error):
                raise
            capabilities.logger.warning(
                "Failed LLM call with response_format for %s, retrying without it: %s",
                artifact_prefix,
                inner_error,
            )
            response = client.chat.completions.create(
                model=llm_model,
                temperature=planning_temp,
                max_tokens=planning_max_tokens,
                timeout=timeout_sec,
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt + " 请只输出纯 JSON，不要包含 Markdown 代码块标记（如 ```json ）。",
                    },
                    {"role": "user", "content": user_prompt},
                ],
                **vendor_options,
            )
        choice = response.choices[0]
        capabilities.logger.info(
            "%s finish_reason=%s usage=%s",
            artifact_prefix,
            getattr(choice, "finish_reason", None),
            getattr(response, "usage", None),
        )
        content_str = str(choice.message.content or "").strip()
        if not content_str:
            raise ValueError("大模型返回了空内容")
        cleaned_content = capabilities.clean_json_markdown(content_str)
        return capabilities.parse_json_or_repair_with_llm(
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
        capabilities.write_project_log(
            project,
            f"{artifact_prefix}_failed",
            trace_id=trace_id,
            elapsed_sec=round(time.monotonic() - started_at, 2),
            status_code=exc.status_code,
            error=str(exc.detail),
        )
        raise
    except Exception as exc:
        timed_out = capabilities.is_timeout_exception(exc)
        capabilities.write_project_log(
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
                detail=f"{stage_label}超过 {int(timeout_sec)} 秒仍未返回，请重试或切换响应更快的模型。",
            ) from exc
        raise HTTPException(status_code=502, detail=f"{stage_label}失败：{str(exc)[:300]}") from exc
    finally:
        try:
            client.close()
        except Exception:
            pass
