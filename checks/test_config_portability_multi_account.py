"""Multi-account round-trip tests for the portable config bundle (version 3)."""

from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config_portability_service as service  # noqa: E402


def _read(path: str, default):
    target = Path(path)
    if not target.exists():
        return default
    return json.loads(target.read_text(encoding="utf-8"))


def _write(path: str, value):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _seed_stores(models: Path, configs: Path, credentials: Path) -> None:
    """Two accounts share each JSON store with strictly separated ownership."""
    _write(str(models), {
        "version": "model_connections_v1",
        "connections": {
            "model-1": {
                "id": "model-1",
                "name": "默认文本模型",
                "kind": "text",
                "account_id": "default",
                "credential_ref": "credential://one",
            },
            "model-other": {
                "id": "model-other",
                "name": "第二账号文本模型",
                "kind": "text",
                "account_id": "acct_other",
                "credential_ref": "credential://two",
            },
        },
    })
    _write(str(configs), {
        "version": "creation_config_store_v1",
        "packages": {
            "package-1": {
                "id": "package-1",
                "name": "默认创作配置",
                "account_id": "default",
                "versions": {"1": {"payload": {"schema_version": "creation_config_v1"}}},
            },
            "package-other": {
                "id": "package-other",
                "name": "第二账号创作配置",
                "account_id": "acct_other",
                "versions": {"1": {"payload": {"schema_version": "creation_config_v1"}}},
            },
        },
    })
    _write(str(credentials), {
        "version": "credential_store_v1",
        "credentials": {
            "credential://one": {
                "credential_ref": "credential://one",
                "provider": "minimax",
                "label": "MiniMax",
                "account_id": "default",
                "secret_values": {"api_token": "token-default"},
                "state": "active",
            },
            "credential://two": {
                "credential_ref": "credential://two",
                "provider": "openai",
                "label": "OpenAI",
                "account_id": "acct_other",
                "secret_values": {"api_token": "token-other"},
                "state": "active",
            },
        },
    })


def _account_rows() -> list:
    return [
        {
            "id": "default",
            "name": "默认账号",
            "description": "",
            "status": "active",
            # Unparsable default_creation_config must degrade to None fields.
            "default_creation_config": {"package_id": "", "version": "x"},
            "created_at": "2026-01-01T00:00:00",
        },
        {
            "id": "acct_other",
            "name": "第二账号",
            "description": "跨机迁移验证",
            "status": "active",
            "default_creation_config": {"package_id": "package-other", "version": 1},
            "created_at": "2026-01-02T00:00:00",
        },
    ]


def _configured_dependencies(tmp_path: Path, *, with_accounts: bool = True):
    original = service._deps()
    values = {
        field: getattr(original, field)
        for field in original.__dataclass_fields__
    }
    models = tmp_path / "model_connections.json"
    configs = tmp_path / "creation_configs.json"
    credentials = tmp_path / "credentials.json"
    _seed_stores(models, configs, credentials)
    upsert_calls: list[dict] = []
    style_imports: list = []

    def _upsert_account(**kwargs):
        upsert_calls.append(kwargs)
        return {"id": kwargs["account_id"], "name": kwargs["name"]}

    values.update(
        model_connections_path=str(models),
        creation_configs_path=str(configs),
        credentials_path=str(credentials),
        read_json_file=_read,
        write_json_atomic=_write,
        # Keep every remaining path and style-storage side effect inside
        # tmp_path so the bundle lifecycle never touches production files.
        read_image_style_template_index=lambda: [],
        ensure_active_image_style_storage=lambda: None,
        storyboard_templates_path=str(tmp_path / "storyboard_templates.json"),
        step2_prompt_templates_path=str(tmp_path / "step2_prompt_templates.json"),
        style_tokens_path=str(tmp_path / "style_tokens.yaml"),
        style_reference_dir=str(tmp_path / "style_references"),
        image_style_templates_dir=str(tmp_path / "image_style_templates"),
        image_style_templates_index=str(tmp_path / "image_style_index.json"),
        get_all_settings=lambda: {"llm_api_key": "local-machine-key"},
        update_settings=lambda changes: changes,
        export_project_style_templates=lambda: {
            "version": "step3_image_style_templates_v1",
            "templates": [{"id": "aaaaaaaaaaaa", "name": "品牌风格"}],
        },
        validate_project_style_templates=lambda _value: None,
        import_project_style_templates=style_imports.append,
    )
    if with_accounts:
        values.update(
            list_accounts=_account_rows,
            upsert_account=_upsert_account,
        )
    else:
        # Hermetic degradation: collecting other check files imports server,
        # whose startup wires the real account database into this module, so
        # the legacy branch must be requested explicitly with None instead of
        # inheriting whatever the production dependencies hold.
        values.update(
            list_accounts=None,
            upsert_account=None,
        )
    service.configure_config_portability_dependencies(
        service.ConfigPortabilityDependencies(**values)
    )
    return original, models, configs, credentials, upsert_calls, style_imports


def test_multi_account_bundle_exports_every_scoped_store(tmp_path: Path):
    original, _m, _c, _cred, _upserts, _styles = _configured_dependencies(tmp_path)
    try:
        bundle = service.build_config_export_bundle(
            {"llm_api_key": "masked"}, contains_secrets=False
        )
    finally:
        service.configure_config_portability_dependencies(original)

    assert bundle["version"] == 3
    accounts = bundle["accounts"]
    assert [account["id"] for account in accounts] == ["default", "acct_other"]

    default_entry, other_entry = accounts
    # Each account exports only its own scoped records.
    assert list(default_entry["reusable_config"]["models"]["connections"]) == ["model-1"]
    assert list(other_entry["reusable_config"]["models"]["connections"]) == ["model-other"]
    assert list(default_entry["reusable_config"]["creation_configs"]["packages"]) == ["package-1"]
    assert list(other_entry["reusable_config"]["creation_configs"]["packages"]) == ["package-other"]

    # Normal exports keep credential metadata but never the secret values.
    for entry in accounts:
        credential_bundle = entry["reusable_config"]["credentials"]
        assert credential_bundle["included"] is False
        for item in credential_bundle["credentials"].values():
            assert "secret_values" not in item
            assert item["configured"] is True

    # The top-level snapshot stays the current-account view for older importers.
    assert list(bundle["reusable_config"]["models"]["connections"]) == ["model-1"]
    assert bundle["reusable_config"]["credentials"]["included"] is False


def test_sensitive_multi_account_bundle_round_trips_every_account(tmp_path: Path):
    original, models, configs, credentials, upsert_calls, style_imports = (
        _configured_dependencies(tmp_path)
    )
    try:
        bundle = service.build_config_export_bundle(
            {"llm_api_key": "local-machine-key"}, contains_secrets=True
        )
        assert bundle["contains_secrets"] is True
        for entry in bundle["accounts"]:
            assert entry["reusable_config"]["credentials"]["included"] is True

        # Simulate a fresh machine: wipe every scoped store before importing.
        _write(str(models), {"version": "model_connections_v1", "connections": {}})
        _write(str(configs), {"version": "creation_config_store_v1", "packages": {}})
        _write(str(credentials), {"version": "credential_store_v1", "credentials": {}})

        # A foreign current-account snapshot in the top-level reusable_config
        # must be ignored by the multi-account import branch.
        bundle["reusable_config"]["models"]["connections"]["poison"] = {
            "id": "poison",
            "name": "不应被导入",
            "account_id": "default",
        }

        result = service.import_full_config(bundle)

        restored_models = _read(str(models), {})
        restored_configs = _read(str(configs), {})
        restored_credentials = _read(str(credentials), {})
    finally:
        service.configure_config_portability_dependencies(original)

    assert result["success"] is True
    assert "已导入 2 个账号" in result["message"]
    assert "凭据均已随包还原" in result["message"]

    # Both account rows were upserted keeping their exported IDs, and the
    # default_creation_config was parsed (or degraded) deterministically.
    assert [call["account_id"] for call in upsert_calls] == ["default", "acct_other"]
    assert upsert_calls[0]["default_package_id"] is None
    assert upsert_calls[0]["default_package_version"] is None
    assert upsert_calls[1]["default_package_id"] == "package-other"
    assert upsert_calls[1]["default_package_version"] == 1

    # Ownership survives 1:1 inside each store.
    assert restored_models["connections"]["model-1"]["account_id"] == "default"
    assert restored_models["connections"]["model-other"]["account_id"] == "acct_other"
    assert restored_configs["packages"]["package-1"]["account_id"] == "default"
    assert restored_configs["packages"]["package-other"]["account_id"] == "acct_other"

    # Secrets round-trip for both accounts.
    assert (
        restored_credentials["credentials"]["credential://one"]["secret_values"]
        == {"api_token": "token-default"}
    )
    assert (
        restored_credentials["credentials"]["credential://two"]["secret_values"]
        == {"api_token": "token-other"}
    )

    # The poisoned top-level snapshot never reached the stores.
    assert "poison" not in restored_models["connections"]

    # Style resources were restored once per account scope.
    assert len(style_imports) == 2


def test_legacy_bundle_without_accounts_imports_into_current_account(tmp_path: Path):
    original, models, _c, _cred, upsert_calls, _styles = _configured_dependencies(
        tmp_path
    )
    try:
        payload = {
            "settings": {},
            "reusable_config": {
                "models": {
                    "version": "model_connections_v1",
                    "connections": {
                        "model-legacy": {
                            "id": "model-legacy",
                            "name": "旧包模型",
                            "account_id": "elsewhere",
                        },
                    },
                },
                "creation_configs": {
                    "version": "creation_config_store_v1",
                    "packages": {},
                },
                "credentials": {
                    "version": "credential_store_v1",
                    "credentials": {},
                    "included": False,
                },
            },
            "image_style": {},
        }
        result = service.import_full_config(payload)
        restored_models = _read(str(models), {})
    finally:
        service.configure_config_portability_dependencies(original)

    assert result["success"] is True
    assert "凭据需在当前账号重新配置" in result["message"]
    # A legacy bundle never upserts account rows.
    assert upsert_calls == []
    # Everything lands in the current account (default outside any scope).
    assert restored_models["connections"]["model-legacy"]["account_id"] == "default"


def test_bundle_without_account_dependencies_degrades_to_legacy(tmp_path: Path):
    original, models, _c, _cred, _upserts, _styles = _configured_dependencies(
        tmp_path, with_accounts=False
    )
    try:
        bundle = service.build_config_export_bundle({}, contains_secrets=True)
        assert bundle["accounts"] == []
        # Simulate a fresh machine so the merge-based legacy import can be
        # observed in isolation.
        _write(str(models), {"version": "model_connections_v1", "connections": {}})
        result = service.import_full_config(bundle)
        restored_models = _read(str(models), {})
    finally:
        service.configure_config_portability_dependencies(original)

    assert result["success"] is True
    assert "模型、创作配置和凭据已导入" in result["message"]
    # Degraded legacy branch restores only the current-account snapshot.
    assert restored_models["connections"]["model-1"]["account_id"] == "default"
    assert "model-other" not in restored_models["connections"]
