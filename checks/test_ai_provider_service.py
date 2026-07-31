from __future__ import annotations

import base64
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ai_provider_service as provider  # noqa: E402


class FailingImageApi:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls: list[dict[str, Any]] = []

    def generate(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if len(self.calls) <= self.failures:
            raise RuntimeError(f"failure {len(self.calls)}")
        return {"data": [{"b64_json": "result"}]}


def test_provider_module_has_no_application_wiring() -> None:
    source = (ROOT / "ai_provider_service.py").read_text(
        encoding="utf-8"
    )
    server_source = (ROOT / "server.py").read_text(encoding="utf-8")
    for forbidden in (
        "APIRouter",
        "Depends(",
        "get_db",
        "server_module",
        "import server",
    ):
        assert forbidden not in source
    assert "def get_openai_client(" not in server_source
    assert "def open_validated_image(" not in server_source
    assert "def generate_image_response(" not in server_source
    assert "from ai_provider_service import (" in server_source


def test_openai_client_transport_contract_is_preserved() -> None:
    sentinel = object()
    http_args: dict[str, Any] = {}
    openai_args: dict[str, Any] = {}

    def create_http_client(**kwargs: Any) -> object:
        http_args.update(kwargs)
        return sentinel

    def create_openai(**kwargs: Any) -> object:
        openai_args.update(kwargs)
        return sentinel

    with patch(
        "ai_provider_service.httpx.Client",
        side_effect=create_http_client,
    ), patch(
        "ai_provider_service.OpenAI",
        side_effect=create_openai,
    ):
        result = provider.get_openai_client(
            api_key="secret",
            base_url="https://example.invalid",
            timeout=45,
            max_retries=0,
        )
    assert result is sentinel
    assert http_args["trust_env"] is False
    assert http_args["timeout"] == 45
    assert "Chrome/120.0.0.0" in http_args["headers"]["User-Agent"]
    assert openai_args == {
        "api_key": "secret",
        "base_url": "https://example.invalid",
        "http_client": sentinel,
        "timeout": 45,
        "max_retries": 0,
    }


def test_seedream_fallback_order_is_preserved() -> None:
    images = FailingImageApi(failures=2)
    client = SimpleNamespace(images=images)
    result = provider.generate_image_response(
        client=client,
        model="doubao-seedream-4",
        prompt="prompt",
        size="1920x1080",
        base_url="https://ark.cn",
        timeout=15,
    )
    assert result["data"]
    assert images.calls == [
        {
            "model": "doubao-seedream-4",
            "prompt": "prompt",
            "n": 1,
            "timeout": 15,
            "size": "1920x1080",
            "response_format": "b64_json",
        },
        {
            "model": "doubao-seedream-4",
            "prompt": "prompt",
            "n": 1,
            "timeout": 15,
            "size": "1920x1080",
        },
        {
            "model": "doubao-seedream-4",
            "prompt": "prompt",
            "n": 1,
            "timeout": 15,
        },
    ]


def test_generic_image_fallback_order_is_preserved() -> None:
    images = FailingImageApi(failures=2)
    client = SimpleNamespace(images=images)
    provider.generate_image_response(
        client=client,
        model="gpt-image-1",
        prompt="prompt",
        size="1024x1024",
    )
    assert images.calls == [
        {
            "model": "gpt-image-1",
            "prompt": "prompt",
            "n": 1,
            "size": "1024x1024",
            "quality": "standard",
        },
        {
            "model": "gpt-image-1",
            "prompt": "prompt",
            "n": 1,
            "size": "1024x1024",
        },
        {
            "model": "gpt-image-1",
            "prompt": "prompt",
            "n": 1,
        },
    ]


def test_image_response_decoding_contract_is_preserved() -> None:
    content = b"image-bytes"
    encoded = base64.b64encode(content).decode("ascii")
    response = {
        "data": [
            {
                "b64_json": (
                    f"data:image/png;base64,{encoded}"
                )
            }
        ]
    }
    assert provider.response_has_image_data(response)
    assert provider.extract_image_bytes_from_response(response) == content

    object_response = SimpleNamespace(
        data=[SimpleNamespace(url="https://example.invalid/image.png")]
    )
    assert provider.response_has_image_data(object_response)
