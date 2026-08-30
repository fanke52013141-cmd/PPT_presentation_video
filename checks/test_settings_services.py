from __future__ import annotations

import base64
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config_portability_service as config_service  # noqa: E402
from route_inventory import iter_effective_routes  # noqa: E402
import server  # noqa: E402
import settings_service  # noqa: E402


SETTINGS_PATHS = {
    ("GET", "/api/settings"),
    ("PUT", "/api/settings"),
    ("GET", "/api/config/export"),
    ("POST", "/api/config/export-with-secrets"),
    ("POST", "/api/config/import"),
    ("POST", "/api/settings/test-llm"),
    ("POST", "/api/settings/test-image"),
    ("POST", "/api/settings/test-tts"),
}


def replace_settings_dependencies(
    **changes: Any,
) -> settings_service.SettingsDependencies:
    dependencies = settings_service._deps()
    values = {
        field: getattr(dependencies, field)
        for field in dependencies.__dataclass_fields__
    }
    values.update(changes)
    return settings_service.SettingsDependencies(**values)


def replace_config_dependencies(
    **changes: Any,
) -> config_service.ConfigPortabilityDependencies:
    dependencies = config_service._deps()
    values = {
        field: getattr(dependencies, field)
        for field in dependencies.__dataclass_fields__
    }
    values.update(changes)
    return config_service.ConfigPortabilityDependencies(**values)


def test_settings_routes_are_registered_exactly_once() -> None:
    route_counts: dict[tuple[str, str], int] = {}
    for route in iter_effective_routes(server.app):
        path = getattr(route, "path", "")
        for method in getattr(route, "methods", set()):
            key = (method, path)
            if key in SETTINGS_PATHS:
                route_counts[key] = route_counts.get(key, 0) + 1
    assert route_counts == {path: 1 for path in SETTINGS_PATHS}


def test_settings_service_boundaries_are_explicit() -> None:
    server_source = (ROOT / "server.py").read_text(encoding="utf-8")
    routes_source = (ROOT / "settings_routes.py").read_text(
        encoding="utf-8"
    )
    for filename in (
        "settings_service.py",
        "config_portability_service.py",
    ):
        source = (ROOT / filename).read_text(encoding="utf-8")
        assert "APIRouter" not in source
        assert "Depends(" not in source
        assert "get_db" not in source
        assert "server_module" not in source
        assert "import server" not in source
    assert "router = APIRouter()" in routes_source
    assert "app.include_router(settings_router)" in server_source
    for method in ("get", "put", "post"):
        assert f'@app.{method}("/api/settings' not in server_source
        assert f'@app.{method}("/api/config' not in server_source


def test_reference_validation_happens_before_any_import_write() -> None:
    writes: list[Any] = []
    original = config_service._deps()

    def reject_image(_content: bytes) -> Any:
        raise ValueError("invalid image")

    config_service.configure_config_portability_dependencies(
        replace_config_dependencies(
            open_validated_image=reject_image,
            update_settings=lambda values: writes.append(values),
            write_json_atomic=lambda path, value: writes.append(
                (path, value)
            ),
            ensure_active_image_style_storage=lambda: writes.append(
                "ensure"
            ),
        )
    )
    payload = {
        "settings": {"llm_model": "must-not-write"},
        "storyboard_templates": [{"name": "must-not-write"}],
        "image_style": {
            "active_references": {
                "template": {
                    "exists": True,
                    "data": base64.b64encode(b"bad").decode("ascii"),
                }
            }
        },
    }
    try:
        with pytest.raises(ValueError, match="invalid image"):
            config_service.import_full_config(payload)
    finally:
        config_service.configure_config_portability_dependencies(
            original
        )
    assert writes == []


def test_llm_connection_probe_contract_is_unchanged() -> None:
    captured: dict[str, Any] = {}

    class Completions:
        def create(self, **kwargs: Any) -> Any:
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="pong")
                    )
                ]
            )

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=Completions())
    )
    original = settings_service._deps()
    settings_service.configure_settings_dependencies(
        replace_settings_dependencies(
            get_openai_client=lambda **_kwargs: client,
        )
    )
    try:
        result = settings_service.test_llm_connection(
            settings_service.TestLlmPayload(
                api_key="key",
                base_url="https://example.invalid",
                model="model",
            )
        )
    finally:
        settings_service.configure_settings_dependencies(original)
    assert result["success"] is True
    assert captured == {
        "model": "model",
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 5,
        "timeout": 10,
    }


def test_image_connection_probe_contract_is_unchanged() -> None:
    captured: dict[str, Any] = {}
    client = object()

    def generate(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return {"data": [{"b64_json": "image"}]}

    original = settings_service._deps()
    settings_service.configure_settings_dependencies(
        replace_settings_dependencies(
            get_openai_client=lambda **_kwargs: client,
            generate_image_response=generate,
            response_has_image_data=lambda response: bool(response),
        )
    )
    try:
        result = settings_service.test_image_connection(
            settings_service.TestImagePayload(
                api_key="key",
                base_url="https://example.invalid",
                model="image-model",
            )
        )
    finally:
        settings_service.configure_settings_dependencies(original)
    assert result["success"] is True
    assert captured == {
        "client": client,
        "model": "image-model",
        "prompt": "a single dot",
        "size": "1024x1024",
        "base_url": "https://example.invalid",
        "timeout": 15,
    }


def test_tts_connection_probe_contract_is_unchanged() -> None:
    command_args: dict[str, Any] = {}
    process_args: dict[str, Any] = {}

    def provider_command(**kwargs: Any) -> list[str]:
        command_args.update(kwargs)
        command_args["text"] = Path(
            kwargs["text_file"]
        ).read_text(encoding="utf-8")
        return ["fake-tts"]

    def run_process(command: list[str], **kwargs: Any) -> Any:
        process_args["command"] = command
        process_args.update(kwargs)
        Path(command_args["out_audio"]).write_bytes(b"audio")
        return subprocess.CompletedProcess(command, 0, "", "")

    original = settings_service._deps()
    settings_service.configure_settings_dependencies(
        replace_settings_dependencies(
            get_setting=lambda *_args: "",
            configured_tts_api_key=lambda *_args: "key",
            configured_tts_secret_key=lambda *_args: "",
            provider_tts_command=provider_command,
            provider_tts_environment=lambda api_key, secret_key: {
                "API_KEY": api_key,
                "SECRET_KEY": secret_key,
            },
            run_subprocess_bounded=run_process,
        )
    )
    try:
        result = settings_service.test_tts_connection(
            settings_service.TestTtsPayload(
                provider="minimax",
            )
        )
    finally:
        settings_service.configure_settings_dependencies(original)
    assert result["success"] is True
    assert command_args["text"] == "测试语音。\n"
    assert command_args["slide_id"] == "tts_test"
    assert command_args["speed"] == "1.0"
    assert command_args["volume"] == "1.0"
    assert command_args["pitch"] == "0"
    assert process_args["timeout_sec"] == 90
    assert process_args["capture_output"] is True
    assert process_args["text"] is True
    assert process_args["encoding"] == "utf-8"
    assert process_args["errors"] == "replace"
