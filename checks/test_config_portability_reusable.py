"""Regression tests for reusable model/config bundle portability."""

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


def _configured_dependencies(tmp_path: Path):
    original = service._deps()
    values = {
        field: getattr(original, field)
        for field in original.__dataclass_fields__
    }
    models = tmp_path / "model_connections.json"
    configs = tmp_path / "creation_configs.json"
    credentials = tmp_path / "credentials.json"
    _write(models, {
        "version": "model_connections_v1",
        "connections": {
            "model-1": {
                "id": "model-1",
                "name": "文本模型",
                "kind": "text",
                "account_id": "default",
                "revisions": [],
                "credential_ref": "credential://one",
            },
            "other-account": {"account_id": "acct_other"},
        },
    })
    _write(configs, {
        "version": "creation_config_store_v1",
        "packages": {
            "package-1": {
                "id": "package-1",
                "name": "默认创作配置",
                "account_id": "default",
                "versions": {"1": {"payload": {"schema_version": "creation_config_v1"}}},
            },
            "other-account": {"account_id": "acct_other"},
        },
    })
    _write(credentials, {
        "version": "credential_store_v1",
        "credentials": {
            "credential://one": {
                "credential_ref": "credential://one",
                "provider": "minimax",
                "label": "MiniMax",
                "account_id": "default",
                "secret_values": {"api_token": "do-not-leak"},
                "state": "active",
            }
        },
    })
    values.update(
        model_connections_path=str(models),
        creation_configs_path=str(configs),
        credentials_path=str(credentials),
        read_json_file=_read,
        write_json_atomic=_write,
        export_project_style_templates=lambda: {
            "version": "step3_image_style_templates_v1",
            "templates": [{"id": "aaaaaaaaaaaa", "name": "品牌风格"}],
        },
        validate_project_style_templates=lambda _value: None,
        import_project_style_templates=lambda value: _write(
            str(tmp_path / "imported_project_styles.json"), value
        ),
    )
    service.configure_config_portability_dependencies(
        service.ConfigPortabilityDependencies(**values)
    )
    return original, models, configs, credentials


def test_normal_bundle_includes_reusable_metadata_without_secrets(tmp_path: Path):
    original, _models, _configs, _credentials = _configured_dependencies(tmp_path)
    try:
        bundle = service._export_reusable_config(contains_secrets=False)
    finally:
        service.configure_config_portability_dependencies(original)

    assert list(bundle["models"]["connections"]) == ["model-1"]
    assert list(bundle["creation_configs"]["packages"]) == ["package-1"]
    assert bundle["image_style_resources"]["templates"][0]["id"] == "aaaaaaaaaaaa"
    assert bundle["credentials"]["included"] is False
    assert "secret_values" not in bundle["credentials"]["credentials"]["credential://one"]


def test_sensitive_bundle_round_trips_stores_into_current_account(tmp_path: Path):
    original, models, configs, credentials = _configured_dependencies(tmp_path)
    try:
        bundle = service._export_reusable_config(contains_secrets=True)
        assert bundle["credentials"]["included"] is True
        service._import_reusable_config(bundle)
        restored_models = _read(str(models), {})
        restored_configs = _read(str(configs), {})
        restored_credentials = _read(str(credentials), {})
        restored_styles = _read(str(tmp_path / "imported_project_styles.json"), {})
    finally:
        service.configure_config_portability_dependencies(original)

    assert restored_models["connections"]["model-1"]["account_id"] == "default"
    assert restored_configs["packages"]["package-1"]["account_id"] == "default"
    assert restored_credentials["credentials"]["credential://one"]["secret_values"]["api_token"] == "do-not-leak"
    assert restored_styles["templates"][0]["name"] == "品牌风格"
