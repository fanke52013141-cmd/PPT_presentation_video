from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import creation_config_service as service  # noqa: E402
import creation_config_routes as routes  # noqa: E402


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


class _DefaultConfigQuery:
    def __init__(self, account: Any) -> None:
        self.account = account

    def filter(self, *_args: Any) -> "_DefaultConfigQuery":
        return self

    def first(self) -> Any:
        return self.account


class _DefaultConfigDb:
    def __init__(self, account: Any) -> None:
        self.account = account

    def query(self, *_args: Any) -> _DefaultConfigQuery:
        return _DefaultConfigQuery(self.account)

    def commit(self) -> None:
        return None

    def refresh(self, _account: Any) -> None:
        return None


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
    assert created["versions"][0]["payload"]["subtitle"]["font_size"] == 42
    assert "style" not in created["versions"][0]["payload"]["subtitle"]


def test_package_preserves_validated_automation_concurrency() -> None:
    configured = payload()
    configured["automation"]["image_concurrency"] = 5
    configured["automation"]["mode"] = "auto"
    configured["automation"]["ai_narration_annotation"] = False
    configured["automation"]["ai_mask_annotation"] = True
    configured["tts"]["concurrency"] = 4
    configured["tts"]["seed_audio_concurrency"] = 5
    configured["tts"]["requests_per_minute"] = 20
    configured["render"] = {"acceleration": "gpu", "output_formats": ["video", "pptx"]}

    normalized = service.validate_payload(configured)

    assert normalized["automation"]["image_concurrency"] == 5
    assert normalized["automation"]["ai_narration_annotation"] is False
    assert normalized["automation"]["ai_mask_annotation"] is True
    assert normalized["tts"]["concurrency"] == 4
    assert normalized["tts"]["seed_audio_concurrency"] == 5
    assert normalized["tts"]["requests_per_minute"] == 20
    assert normalized["render"]["acceleration"] == "gpu"
    assert normalized["render"]["output_formats"] == ["video", "pptx"]


@pytest.mark.parametrize("value", [0, 6, True, "5"])
def test_seed_audio_concurrency_requires_an_integer_between_one_and_five(value: object) -> None:
    configured = payload()
    configured["tts"]["seed_audio_concurrency"] = value

    with pytest.raises(service.CreationConfigValidationError, match="seed_audio_concurrency"):
        service.validate_payload(configured)


def test_automation_annotation_switch_requires_a_boolean() -> None:
    configured = payload()
    configured["automation"]["ai_narration_annotation"] = "yes"

    with pytest.raises(service.CreationConfigValidationError, match="ai_narration_annotation"):
        service.validate_payload(configured)


def test_automation_mask_annotation_switch_requires_a_boolean() -> None:
    configured = payload()
    configured["automation"]["ai_mask_annotation"] = "yes"

    with pytest.raises(service.CreationConfigValidationError, match="ai_mask_annotation"):
        service.validate_payload(configured)


def test_copy_names_a_new_package_and_uses_current_configuration() -> None:
    source = service.create_creation_config(name="科普账号", payload=payload())
    changed = payload(subtitles=False)
    service.create_creation_config_version(source["id"], payload=changed)

    copied = service.copy_creation_config(
        source["id"], name="科普账号无字幕", version=1
    )

    assert copied["id"] != source["id"]
    assert copied["name"] == "科普账号无字幕"
    assert copied["latest_version"] == 1
    assert copied["versions"][0]["payload"]["subtitle"]["enabled"] is False


def test_legacy_version_endpoint_replaces_single_current_configuration() -> None:
    created = service.create_creation_config(name="配置", payload=payload())
    current = service.create_creation_config_version(
        created["id"], payload=payload(subtitles=False)
    )

    assert current["version"] == 1
    assert current["payload"]["subtitle"]["enabled"] is False
    assert service.get_creation_config(created["id"])["latest_version"] == 1


def test_update_replaces_current_configuration_without_creating_a_backup() -> None:
    created = service.create_creation_config(name="配置", payload=payload())
    service.create_creation_config_version(created["id"], payload=payload(subtitles=False))

    updated = service.update_creation_config(
        created["id"], payload=payload()
    )

    assert updated["latest_version"] == 1
    assert len(updated["versions"]) == 1
    assert updated["versions"][0]["payload"]["subtitle"]["enabled"] is True


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
    assert resolved["payload"]["subtitle"]["font_size"] == 42
    assert resolved["payload"]["tts"]["connection"] == {
        "connection_id": "voice-main",
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


def test_delete_logically_archives_package_and_preserves_its_snapshot() -> None:
    created = service.create_creation_config(name="配置", payload=payload())
    version = service.get_creation_config_version(created["id"])

    deleted = service.delete_creation_config(created["id"])

    assert deleted["archived"] is True
    assert service.get_creation_config_version(created["id"])["payload"] == version["payload"]
    assert service.list_creation_configs() == []


def test_delete_route_archives_the_current_account_default_package_and_clears_default() -> None:
    created = service.create_creation_config(name="默认配置", payload=payload())
    account = type(
        "AccountStub",
        (),
        {
            "id": "default",
            "name": "默认账号",
            "description": "",
            "status": "active",
            "created_at": None,
            "default_creation_config_package_id": created["id"],
            "default_creation_config_version": 1,
        },
    )()

    result = routes.delete_creation_config(created["id"], db=_DefaultConfigDb(account))

    assert result["success"] is True
    assert result["default_cleared"] is True
    assert account.default_creation_config_package_id is None
    assert account.default_creation_config_version is None
    assert service.get_creation_config(created["id"])["archived"] is True


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


def test_image_style_binding_is_normalized_without_embedding_images() -> None:
    configured = payload()
    configured["image_style"] = {
        "package_id": "handdrawn",
        "style_version": 1,
        "reference_mode": "required",
        "minimum_reference_images": 2,
    }

    created = service.create_creation_config(name="带图片风格", payload=configured)

    assert created["versions"][0]["payload"]["image_style"] == {
        "template_id": "handdrawn",
        "version": 1,
        "reference_policy": "required",
        "minimum_reference_images": 2,
    }


def test_image_style_required_mode_rejects_zero_references() -> None:
    configured = payload()
    configured["image_style"] = {
        "template_id": "handdrawn",
        "version": 1,
        "reference_policy": "required",
        "minimum_reference_images": 0,
    }
    with pytest.raises(service.CreationConfigValidationError, match="至少需要 1 张"):
        service.create_creation_config(name="错误图片风格", payload=configured)


def test_step_contracts_are_versioned_and_validate_model_output() -> None:
    configured = payload()
    configured["step_contracts"] = {
        "article_generation": {
            "input_template": {"topic": "string"},
            "output_schema": {
                "type": "object",
                "required": ["title", "body"],
                "properties": {
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                },
            },
        },
        "tts": {
            "input_template": {"text": "string"},
            "output_schema": {
                "type": "object",
                "required": ["audio_url"],
                "properties": {"audio_url": {"type": "string"}},
            },
        },
    }
    created = service.create_creation_config(name="带契约配置", payload=configured)
    contracts = created["versions"][0]["payload"]["step_contracts"]
    service.validate_step_output(contracts["article_generation"], {"title": "标题", "body": "正文"})
    with pytest.raises(service.CreationConfigValidationError, match="缺少"):
        service.validate_step_output(contracts["article_generation"], {"title": "标题"})


def test_step_contract_rejects_invalid_schema_before_it_can_reach_a_project() -> None:
    configured = payload()
    configured["step_contracts"] = {
        "article_generation": {
            "output_schema": {
                "type": "object",
                "required": ["missing"],
                "properties": {"title": {"type": "string"}},
            }
        }
    }
    with pytest.raises(service.CreationConfigValidationError, match="required"):
        service.create_creation_config(name="错误契约", payload=configured)
