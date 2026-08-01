"""Step 1 article generation, source persistence, and compatibility migration."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
import re
from typing import Any, Callable, Dict, Optional

from fastapi import HTTPException


logger = logging.getLogger("PPTStudio.Article")


ARTICLE_GENERATION_SYSTEM_CONTENT_KEY = "article_generation_system_content"
LEGACY_DEFAULT_ARTICLE_GENERATION_SYSTEM_CONTENT_V1 = """你是一名中文长文写作编辑。

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
DEFAULT_ARTICLE_GENERATION_SYSTEM_CONTENT = """<PromptVersion>article_generation_v2_minimal</PromptVersion>

## 目的

<Role>
你是一名中文长文写作编辑。你的唯一任务是把用户提供的 `topic` 写成一篇可直接编辑、并可作为后续 Slide 规划唯一文章来源的中文 Markdown 正文。
</Role>

<SystemBackground>
后续系统会直接读取本次输出规划演讲稿和视觉内容。因此文章需要有清楚的事实边界、论述顺序和可讲解的具体信息；当前阶段不设计 Slide、画面、Mask、动画或生图提示词。
</SystemBackground>

## 输入

<InputContract>
User Content 是一个 JSON 对象，只包含：
- `topic`：用户给出的话题，也可能同时包含受众、用途、写作方向或必要背景；它是本次写作的唯一事实与范围依据。
</InputContract>

<WritingRules>
1. 根据主题选择最合适的结构，不机械套用固定章节；每一节只推进一个核心观点，前后逻辑连贯。
2. 使用清楚的一级、二级标题和必要列表，正文承担主要信息，避免空话、重复和只列提纲不解释。
3. 术语、机制、步骤、条件、对比和结论要写到足以继续讲解；仅在输入支持时使用具体数据、案例、引文或来源。
4. 不得编造无法确认的事实。信息不足但仍可完成时使用审慎表述；缺口会改变核心结论时，明确指出限制，不自行补造。
5. 不输出 Slide 划分、视觉设计、图片说明、Mask、动画或任何系统内部字段。
</WritingRules>

## 输出

<OutputContract>
只输出一篇 Markdown 正文。不要输出 JSON、代码围栏、写作过程、解释、前缀或后缀文字。
</OutputContract>

<SelfCheck>
- 内容没有超出 `topic` 的事实边界。
- 标题层级、论述顺序和结论一致。
- 正文具体且可讲解，没有为凑结构重复表达。
- 最终输出只有 Markdown 正文。
</SelfCheck>"""


@dataclass(frozen=True)
class ArticleDependencies:
    get_setting: Callable[..., Any]
    update_settings: Callable[..., Any]
    get_openai_client: Callable[..., Any]
    parse_int_setting: Callable[..., int]
    is_timeout_exception: Callable[[BaseException], bool]
    write_project_log: Callable[..., Any]
    begin_storyboard_after_article_import: Callable[..., Any]
    invalidate_after_upstream_edit: Callable[..., Any]
    llm_timeout_sec: float


_dependencies: ArticleDependencies | None = None


def configure_article_dependencies(
    dependencies: ArticleDependencies,
) -> None:
    global _dependencies
    _dependencies = dependencies


def _deps() -> ArticleDependencies:
    if _dependencies is None:
        raise RuntimeError("Article dependencies have not been configured")
    return _dependencies


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


def article_source_path(project: Any) -> str:
    """Return the single source-of-truth path for imported article content."""
    return str(Path(project.run_dir) / "inputs" / "article.md")


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8-sig")


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read JSON file %s: %s", path, exc)
        return {}
    return payload if isinstance(payload, dict) else {}


def read_project_article_source(
    project: Any,
    *,
    required: bool = True,
) -> Dict[str, str]:
    """Read article.md, with a one-time compatibility migration for legacy runs."""
    article_path = Path(article_source_path(project))
    content = _read_text(article_path)
    if not content.strip():
        legacy_brief_path = (
            Path(project.run_dir) / "planning" / "article_brief.json"
        )
        legacy_brief = _read_json(legacy_brief_path)
        legacy_content = str(legacy_brief.get("content") or "")
        if legacy_content.strip():
            article_path.parent.mkdir(parents=True, exist_ok=True)
            article_path.write_text(legacy_content, encoding="utf-8")
            content = legacy_content
            logger.info(
                "Migrated legacy article_brief.json content to %s",
                article_path,
            )
    if not content.strip() and required:
        raise HTTPException(
            status_code=400,
            detail="请先导入文章再继续",
        )
    project_title = str(getattr(project, "name", "") or "").strip()
    return {
        "title": project_title or "未命名项目",
        "content": content,
        "summary": build_article_summary(content),
    }


def read_article_generation_system_content() -> str:
    dependencies = _deps()
    value = str(
        dependencies.get_setting(
            ARTICLE_GENERATION_SYSTEM_CONTENT_KEY,
            DEFAULT_ARTICLE_GENERATION_SYSTEM_CONTENT,
        )
        or DEFAULT_ARTICLE_GENERATION_SYSTEM_CONTENT
    ).strip()
    if value == LEGACY_DEFAULT_ARTICLE_GENERATION_SYSTEM_CONTENT_V1:
        return DEFAULT_ARTICLE_GENERATION_SYSTEM_CONTENT
    return value


def build_article_generation_user_content(topic: str) -> str:
    return json.dumps(
        {"topic": str(topic or "").strip()},
        ensure_ascii=False,
    )


def get_article_generation_settings() -> Dict[str, Any]:
    return {
        "success": True,
        "system_content": read_article_generation_system_content(),
    }


def update_article_generation_settings(
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    system_content = str(payload.get("system_content") or "").strip()
    if not system_content:
        raise HTTPException(
            status_code=400,
            detail="文章生成 System Content 不能为空",
        )
    if len(system_content) > 20000:
        raise HTTPException(
            status_code=400,
            detail="文章生成 System Content 不能超过 20000 个字符",
        )
    _deps().update_settings(
        {ARTICLE_GENERATION_SYSTEM_CONTENT_KEY: system_content}
    )
    return {
        "success": True,
        "system_content": system_content,
    }


def generate_article_from_topic(
    project: Any,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    dependencies = _deps()
    topic = str(payload.get("topic") or "").strip()
    if not topic:
        raise HTTPException(status_code=400, detail="请输入文章话题")
    if len(topic) > 500:
        raise HTTPException(
            status_code=400,
            detail="文章话题不能超过 500 个字符",
        )

    api_key = dependencies.get_setting("llm_api_key")
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="未配置大模型 API 密钥，请先在系统设置中配置",
        )
    model = dependencies.get_setting("llm_model")
    base_url = dependencies.get_setting("llm_base_url")
    system_content = read_article_generation_system_content()
    client = dependencies.get_openai_client(
        api_key=api_key,
        base_url=base_url,
        timeout=dependencies.llm_timeout_sec,
        max_retries=0,
    )
    try:
        response = client.chat.completions.create(
            model=model,
            temperature=min(
                float(
                    dependencies.get_setting(
                        "llm_temperature",
                        "0.7",
                    )
                ),
                0.7,
            ),
            max_tokens=dependencies.parse_int_setting(
                dependencies.get_setting(
                    "llm_max_tokens",
                    "50000",
                ),
                50000,
                1024,
                64000,
            ),
            timeout=dependencies.llm_timeout_sec,
            messages=[
                {
                    "role": "system",
                    "content": system_content,
                },
                {
                    "role": "user",
                    "content": build_article_generation_user_content(
                        topic
                    ),
                },
            ],
        )
    except Exception as exc:
        if dependencies.is_timeout_exception(exc):
            raise HTTPException(
                status_code=504,
                detail="文章生成超时，请稍后重试",
            ) from exc
        raise HTTPException(
            status_code=502,
            detail=f"文章生成失败：{exc}",
        ) from exc

    content = str(response.choices[0].message.content or "").strip()
    if content.startswith("```"):
        content = re.sub(
            r"^```(?:markdown|md)?\s*|\s*```$",
            "",
            content,
            flags=re.I | re.S,
        ).strip()
    if not content:
        raise HTTPException(
            status_code=502,
            detail="大模型没有返回文章内容",
        )
    dependencies.write_project_log(
        project,
        "step1_article_generated",
        topic=topic,
        model=model,
        character_count=len(content),
    )
    return {
        "success": True,
        "topic": topic,
        "content": content,
    }


def import_article(
    project: Any,
    content: Optional[str],
    db: Any,
) -> Dict[str, Any]:
    if not content or not content.strip():
        raise HTTPException(
            status_code=400,
            detail="请输入有效的文章内容",
        )
    article_path = Path(article_source_path(project))
    article_path.parent.mkdir(parents=True, exist_ok=True)
    article_path.write_text(content, encoding="utf-8")
    _deps().begin_storyboard_after_article_import(project, db)
    return {
        "success": True,
        "brief": read_project_article_source(project),
    }


def get_step1_result(project: Any) -> Dict[str, Any]:
    article_source = read_project_article_source(
        project,
        required=False,
    )
    if not article_source["content"].strip():
        return {
            "success": False,
            "message": "尚未导入文章",
        }
    return {
        "success": True,
        "brief": article_source,
    }


def update_step1_result(
    project: Any,
    payload: Dict[str, Any],
    db: Any,
) -> Dict[str, Any]:
    current_source = read_project_article_source(
        project,
        required=False,
    )
    next_content = str(
        payload.get("content") or ""
        if "content" in payload
        else current_source["content"]
    )
    article_path = Path(article_source_path(project))
    article_changed = _read_text(article_path) != next_content
    if article_changed:
        article_path.parent.mkdir(parents=True, exist_ok=True)
        article_path.write_text(next_content, encoding="utf-8")
        _deps().invalidate_after_upstream_edit(project, 1, db)
    return {
        "success": True,
        "brief": read_project_article_source(
            project,
            required=False,
        ),
    }
