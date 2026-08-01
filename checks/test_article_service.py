from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import HTTPException
import pytest

import article_service as service
from route_inventory import iter_effective_routes
import server


def _dependencies(
    *,
    settings: dict[str, Any],
    client: Any = None,
    requests: list[dict[str, Any]] | None = None,
    logs: list[tuple[Any, ...]] | None = None,
    invalidations: list[int] | None = None,
) -> service.ArticleDependencies:
    request_log = requests if requests is not None else []
    event_log = logs if logs is not None else []
    invalidation_log = (
        invalidations if invalidations is not None else []
    )

    def get_client(**kwargs: Any) -> Any:
        request_log.append({"client": kwargs})
        return client

    return service.ArticleDependencies(
        get_setting=lambda key, default=None: settings.get(key, default),
        update_settings=lambda payload: settings.update(payload),
        get_openai_client=get_client,
        parse_int_setting=lambda value, *_args: int(value),
        is_timeout_exception=lambda exc: isinstance(exc, TimeoutError),
        write_project_log=lambda project, event, **fields: event_log.append(
            (project, event, fields)
        ),
        invalidate_after_upstream_edit=(
            lambda _project, step, _db: invalidation_log.append(step)
        ),
        llm_timeout_sec=12.0,
    )


def test_article_routes_are_source_owned_and_unique() -> None:
    expected = {
        ("GET", "/api/settings/article-generation"),
        ("PUT", "/api/settings/article-generation"),
        (
            "POST",
            "/api/projects/{project_id}/steps/1/generate-article",
        ),
        ("POST", "/api/projects/{project_id}/steps/1/import"),
        ("GET", "/api/projects/{project_id}/steps/1/result"),
        ("PUT", "/api/projects/{project_id}/steps/1/result"),
    }
    keys = Counter(
        (method, route.path)
        for route in iter_effective_routes(server.app)
        for method in (getattr(route, "methods", set()) or set())
        if method not in {"HEAD", "OPTIONS"}
    )
    assert all(keys[key] == 1 for key in expected)

    root = Path(__file__).resolve().parents[1]
    server_source = (root / "server.py").read_text(encoding="utf-8")
    route_source = (root / "article_routes.py").read_text(
        encoding="utf-8"
    )
    service_source = (root / "article_service.py").read_text(
        encoding="utf-8"
    )
    assert "router = APIRouter()" in route_source
    assert "app.include_router(article_router)" in server_source
    assert "APIRouter" not in service_source
    assert "Depends(" not in service_source
    assert "get_db" not in service_source
    assert "import server" not in service_source
    assert "server_module" not in service_source
    assert '@app.post("/api/projects/{project_id}/steps/1/' not in (
        server_source
    )
    assert '@app.get("/api/settings/article-generation")' not in (
        server_source
    )


def test_article_generation_preserves_runtime_prompt_contract(
    tmp_path: Path,
) -> None:
    calls: list[dict[str, Any]] = []
    logs: list[tuple[Any, ...]] = []

    class Completions:
        @staticmethod
        def create(**kwargs: Any) -> Any:
            calls.append(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content="```markdown\n# 标题\n正文\n```"
                        )
                    )
                ]
            )

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=Completions())
    )
    original = service._dependencies
    service.configure_article_dependencies(
        _dependencies(
            settings={
                "llm_api_key": "test-key",
                "llm_model": "test-model",
                "llm_base_url": "https://example.test/v1",
                "llm_temperature": "0.9",
                "llm_max_tokens": "4096",
            },
            client=client,
            requests=calls,
            logs=logs,
        )
    )
    project = SimpleNamespace(
        id="article-generation",
        name="Article",
        run_dir=str(tmp_path),
    )
    try:
        result = service.generate_article_from_topic(
            project,
            {"topic": "  测试主题  ", "ignored": "not sent"},
        )
    finally:
        service._dependencies = original

    assert result == {
        "success": True,
        "topic": "测试主题",
        "content": "# 标题\n正文",
    }
    assert not (tmp_path / "inputs" / "article.md").exists()
    assert calls[0] == {
        "client": {
            "api_key": "test-key",
            "base_url": "https://example.test/v1",
            "timeout": 12.0,
            "max_retries": 0,
        }
    }
    request = calls[1]
    assert request["model"] == "test-model"
    assert request["temperature"] == 0.7
    assert request["max_tokens"] == 4096
    assert request["timeout"] == 12.0
    assert request["messages"] == [
        {
            "role": "system",
            "content": service.DEFAULT_ARTICLE_GENERATION_SYSTEM_CONTENT,
        },
        {
            "role": "user",
            "content": json.dumps(
                {"topic": "测试主题"},
                ensure_ascii=False,
            ),
        },
    ]
    assert logs[0][1] == "step1_article_generated"
    assert logs[0][2]["character_count"] == len("# 标题\n正文")


def test_article_import_and_edit_invalidate_only_on_change(
    tmp_path: Path,
) -> None:
    invalidations: list[int] = []
    original = service._dependencies
    service.configure_article_dependencies(
        _dependencies(
            settings={},
            invalidations=invalidations,
        )
    )
    project = SimpleNamespace(
        id="article-persistence",
        name="Article project",
        run_dir=str(tmp_path),
    )
    try:
        imported = service.import_article(
            project,
            "# 初稿\n正文",
            object(),
        )
        unchanged = service.update_step1_result(
            project,
            {"content": "# 初稿\n正文"},
            object(),
        )
        updated = service.update_step1_result(
            project,
            {"content": "# 修改稿\n新正文"},
            object(),
        )
    finally:
        service._dependencies = original

    assert imported["brief"]["content"] == "# 初稿\n正文"
    assert unchanged["brief"]["content"] == "# 初稿\n正文"
    assert updated["brief"]["content"] == "# 修改稿\n新正文"
    assert invalidations == [1, 1]
    assert (
        tmp_path / "inputs" / "article.md"
    ).read_text(encoding="utf-8") == "# 修改稿\n新正文"


def test_article_generation_timeout_remains_504(
    tmp_path: Path,
) -> None:
    class Completions:
        @staticmethod
        def create(**_kwargs: Any) -> Any:
            raise TimeoutError("model timeout")

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=Completions())
    )
    original = service._dependencies
    service.configure_article_dependencies(
        _dependencies(
            settings={
                "llm_api_key": "test-key",
                "llm_model": "test-model",
            },
            client=client,
        )
    )
    try:
        with pytest.raises(HTTPException) as captured:
            service.generate_article_from_topic(
                SimpleNamespace(
                    id="article-timeout",
                    name="Article",
                    run_dir=str(tmp_path),
                ),
                {"topic": "测试"},
            )
    finally:
        service._dependencies = original
    assert captured.value.status_code == 504
