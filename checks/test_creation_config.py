from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import creation_config_service as service  # noqa: E402


class MemoryStore:
    def __init__(self) -> None:
        self.value: dict[str, Any] = {
            "version": service.STORE_VERSION,
            "packages": {},
        }

    def read(self) -> dict[str, Any]:
        return deepcopy(self.value)

    def write(self, value: dict[str, Any]) -> None:
        self.value = deepcopy(value)


@pytest.fixture(autouse=True)
def configured_service() -> None:
    original = service._dependencies
    ids = iter(("config-a", "config-b", "config-c", "config-d"))
    service.configure_creation_config_dependencies(
        service.CreationConfigDependencies(
            store=MemoryStore(),
            now=lambda: "2026-09-04T00:00:00+00:00",
            new_id=lambda: next(ids),
        )
    )
    try:
        yield
    finally:
        service._dependencies = original


def payload(*, subtitles: bool = True) -> dict[str, Any]:
    return {
        "prompts": {
            "article_generation": {
                "system_content": "用清晰、友好的语气解释主题。"
            }
        },
        "model_bindings": {
            "article_generation": {
                "connection_id": "text-main",
                "revision": 2,
            },
            "image_generation": {
                "connection_id": "image-main",
                "revision": 1,
            },
        },
        "tts": {
            "connection": {"connection_id": "voice-main", "revision": 3},
            "voice_id": "Chinese (Mandarin)_Soft_Girl",
        },
        "subtitle": {"enabled": subtitles, "style": {"font_size": 42}},
        "automation": {"manual_pause_steps": ["narration"]},
    }


def test_new_package_has_initial_immutable_version_and_content_hash() -> None:
    created = service.create_creation_config(
        name="科普账号",
        description="科普长视频",
        tags=["科普", "长视频"],
        payload=payload(),
    )

    assert created["latest_version"] == 1
    assert created["versions"][0]["version"] == 1
    assert len(created["content_hash"]) == 64
    assert created["versions"][0]["payload"]["schema_version"] == service.PAYLOAD_VERSION


def test_copy_names_a_new_package_and_uses_selected_source_version() -> None:
    source = service.create_creation_config(name="科普账号", payload=payload())
    changed = payload(subtitles=False)
    service.create_creation_config_version(source["id"], payload=changed)

    copied = service.copy_creation_config(
        source["id"], name="科普账号无字幕", version=1
    )

    assert copied["id"] != source["id"]
    assert copied["name"] == "科普账号无字幕"
    assert copied["latest_version"] == 1
    assert copied["versions"][0]["payload"]["subtitle"]["enabled"] is True


def test_new_version_never_mutates_earlier_version() -> None:
    created = service.create_creation_config(name="配置", payload=payload())
    original = service.get_creation_config_version(created["id"], 1)
    version_two = service.create_creation_config_version(
        created["id"], payload=payload(subtitles=False)
    )

    assert version_two["version"] == 2
    assert service.get_creation_config_version(created["id"], 1) == original
    assert service.get_creation_config(created["id"])["latest_version"] == 2


def test_resolve_deep_merge_preserves_explicit_false_override() -> None:
    created = service.create_creation_config(name="配置", payload=payload())

    resolved = service.resolve_creation_config(
        created["id"],
        overrides={
            "subtitle": {"enabled": False},
            "tts": {"voice_id": "Chinese (Mandarin)_Mature_Male"},
        },
    )

    assert resolved["payload"]["subtitle"]["enabled"] is False
    assert resolved["payload"]["subtitle"]["style"] == {"font_size": 42}
    assert resolved["payload"]["tts"]["connection"] == {
        "connection_id": "voice-main",
        "revision": 3,
    }


def test_archived_package_is_hidden_and_cannot_resolve() -> None:
    created = service.create_creation_config(name="配置", payload=payload())
    service.archive_creation_config(created["id"])

    assert service.list_creation_configs() == []
    assert service.list_creation_configs(include_archived=True)[0]["archived"] is True
    with pytest.raises(service.CreationConfigConflict, match="归档"):
        service.resolve_creation_config(created["id"])
    with pytest.raises(service.CreationConfigConflict, match="归档"):
        service.create_creation_config_version(created["id"], payload=payload())


def test_import_rejects_secret_and_response_redaction_is_defensive() -> None:
    unsafe = payload()
    unsafe["tts"]["api_key"] = "must-not-persist"

    with pytest.raises(service.CreationConfigValidationError, match="敏感字段"):
        service.import_creation_config(name="错误配置", payload=unsafe)

    assert service.redact_sensitive_payload({"token": "abc", "safe": "ok"}) == {
        "token": "__PPT_STUDIO_REDACTED__",
        "safe": "ok",
    }


def test_connection_references_reject_inline_provider_settings() -> None:
    unsafe = payload()
    unsafe["model_bindings"]["article_generation"]["api_key"] = "x"

    with pytest.raises(service.CreationConfigValidationError):
        service.create_creation_config(name="错误配置", payload=unsafe)
