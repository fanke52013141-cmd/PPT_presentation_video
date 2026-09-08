"""Portable global configuration export and import lifecycle."""

from __future__ import annotations

import base64
import binascii
import copy
from dataclasses import dataclass
from datetime import datetime
import io
import json
import os
import posixpath
import re
from typing import Any, Callable, Dict, List, Mapping, Optional
import uuid
import zipfile

from settings_service import (
    mask_sensitive_settings,
    preserve_masked_secrets,
)
from account_context import account_scope, get_current_account_id
from credential_store import STORE_VERSION as CREDENTIAL_STORE_VERSION


@dataclass(frozen=True)
class ConfigPortabilityDependencies:
    get_all_settings: Callable[[], Dict[str, Any]]
    update_settings: Callable[[Dict[str, str]], Any]
    open_validated_image: Callable[[bytes], Any]
    read_json_file: Callable[[str, Any], Any]
    write_json_atomic: Callable[[str, Any], Any]
    read_image_style_template_index: Callable[[], List[Dict[str, Any]]]
    ensure_active_image_style_storage: Callable[[], None]
    template_timestamp: Callable[[], str]
    storyboard_templates_path: str
    step2_prompt_templates_path: str
    style_tokens_path: str
    style_reference_dir: str
    style_reference_files: Mapping[str, str]
    image_style_templates_dir: str
    image_style_templates_index: str
    # Reusable configuration stores are deliberately injected here so the
    # portable bundle stays independent from the route layer and can be
    # replaced by a database adapter later.
    model_connections_path: Optional[str] = None
    creation_configs_path: Optional[str] = None
    credentials_path: Optional[str] = None
    export_project_style_templates: Optional[Callable[[], Dict[str, Any]]] = None
    validate_project_style_templates: Optional[Callable[[Any], None]] = None
    import_project_style_templates: Optional[Callable[[Any], Any]] = None
    # Multi-account portability: enumerate every account row for export and
    # recreate exported account rows (keeping their exported IDs) on import.
    # Both stay optional so single-account test doubles keep working and the
    # bundle degrades to the legacy current-account snapshot when absent.
    list_accounts: Optional[Callable[[], List[Dict[str, Any]]]] = None
    upsert_account: Optional[Callable[..., Dict[str, Any]]] = None


_dependencies: ConfigPortabilityDependencies | None = None


def configure_config_portability_dependencies(
    dependencies: ConfigPortabilityDependencies,
) -> None:
    global _dependencies
    _dependencies = dependencies


def _deps() -> ConfigPortabilityDependencies:
    if _dependencies is None:
        raise RuntimeError(
            "Config portability dependencies have not been configured"
        )
    return _dependencies


def read_text_file_if_exists(path: str) -> str:
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8-sig") as file:
        return file.read()


def file_to_config_reference(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {
            "exists": False,
            "data": "",
            "mime": "",
            "filename": os.path.basename(path),
        }
    with open(path, "rb") as file:
        return {
            "exists": True,
            "data": base64.b64encode(file.read()).decode("ascii"),
            "mime": "image/png",
            "filename": os.path.basename(path),
        }


def config_references_from_dir(
    reference_dir: str,
) -> Dict[str, Dict[str, Any]]:
    return {
        kind: file_to_config_reference(
            os.path.join(reference_dir, filename)
        )
        for kind, filename in _deps().style_reference_files.items()
    }


def safe_image_template_id(value: Any) -> Optional[str]:
    template_id = str(value or "").strip()
    return (
        template_id
        if re.fullmatch(r"[0-9a-f]{12}", template_id)
        else None
    )


def exported_image_style_templates() -> List[Dict[str, Any]]:
    dependencies = _deps()
    templates: List[Dict[str, Any]] = []
    for item in dependencies.read_image_style_template_index():
        if not isinstance(item, dict):
            continue
        template_id = safe_image_template_id(item.get("id"))
        if not template_id:
            continue
        template_dir = os.path.join(
            dependencies.image_style_templates_dir,
            template_id,
        )
        templates.append(
            {
                "id": template_id,
                "name": str(item.get("name") or ""),
                "created_at": str(item.get("created_at") or ""),
                "updated_at": str(item.get("updated_at") or ""),
                "style_tokens_yaml": read_text_file_if_exists(
                    os.path.join(template_dir, "style_tokens.yaml")
                ),
                "references": config_references_from_dir(
                    os.path.join(template_dir, "references")
                ),
            }
        )
    return templates


def decode_config_reference_bytes(reference: Any) -> Optional[bytes]:
    if not isinstance(reference, dict) or not reference.get("exists"):
        return None
    data = str(reference.get("data") or "")
    if not data:
        return None
    try:
        decoded = base64.b64decode(data, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("配置中的参考图 Base64 数据无效") from exc
    image = _deps().open_validated_image(decoded)
    image.close()
    return decoded


def decode_config_reference(
    reference: Any,
    target_path: str,
) -> None:
    decoded = decode_config_reference_bytes(reference)
    if decoded is None:
        if (
            not isinstance(reference, dict)
            or not reference.get("exists")
        ):
            if os.path.exists(target_path):
                os.remove(target_path)
        return
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    image = _deps().open_validated_image(decoded).convert("RGB")
    image.save(target_path, "PNG")


def write_config_references(
    reference_bundle: Any,
    reference_dir: str,
) -> None:
    if not isinstance(reference_bundle, dict):
        return
    for kind, filename in _deps().style_reference_files.items():
        if kind in reference_bundle:
            decode_config_reference(
                reference_bundle[kind],
                os.path.join(reference_dir, filename),
            )


def normalize_imported_template_list(
    value: Any,
) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: List[Dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict) or item.get("built_in"):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        result.append(
            {
                key: item_value
                for key, item_value in item.items()
                if key != "built_in"
            }
        )
    return result


def _account_owned_items(value: Any, collection_key: str) -> Dict[str, Any]:
    """Return only current-account records from a versioned JSON store."""
    if not isinstance(value, dict) or not isinstance(value.get(collection_key), dict):
        return {}
    account_id = get_current_account_id()
    return {
        str(item_id): item
        for item_id, item in value[collection_key].items()
        if isinstance(item, dict)
        and str(item.get("account_id") or "default") == account_id
    }


def _export_reusable_config(*, contains_secrets: bool) -> Dict[str, Any]:
    """Export the new model/config stores without leaking secrets by default."""
    dependencies = _deps()
    result: Dict[str, Any] = {
        "account_id": get_current_account_id(),
        "models": {"version": "model_connections_v1", "connections": {}},
        "creation_configs": {
            "version": "creation_config_store_v1", "packages": {}
        },
        "credentials": {
            "version": CREDENTIAL_STORE_VERSION,
            "credentials": {},
            "included": False,
        },
        "image_style_resources": {
            "version": "step3_image_style_templates_v1",
            "templates": [],
        },
    }
    if dependencies.export_project_style_templates:
        exported_styles = dependencies.export_project_style_templates()
        if isinstance(exported_styles, dict):
            result["image_style_resources"] = exported_styles
    if dependencies.model_connections_path:
        raw_models = dependencies.read_json_file(
            dependencies.model_connections_path,
            {"version": "model_connections_v1", "connections": {}},
        )
        result["models"] = {
            "version": "model_connections_v1",
            "connections": _account_owned_items(raw_models, "connections"),
        }
    if dependencies.creation_configs_path:
        raw_configs = dependencies.read_json_file(
            dependencies.creation_configs_path,
            {"version": "creation_config_store_v1", "packages": {}},
        )
        result["creation_configs"] = {
            "version": "creation_config_store_v1",
            "packages": _account_owned_items(raw_configs, "packages"),
        }
    if contains_secrets and dependencies.credentials_path:
        raw_credentials = dependencies.read_json_file(
            dependencies.credentials_path,
            {"version": CREDENTIAL_STORE_VERSION, "credentials": {}},
        )
        result["credentials"] = {
            "version": CREDENTIAL_STORE_VERSION,
            "credentials": _account_owned_items(raw_credentials, "credentials"),
            "included": True,
        }
    else:
        # Normal exports include enough information for the UI to explain why
        # a credential must be configured again, but never include its value.
        if dependencies.credentials_path:
            raw_credentials = dependencies.read_json_file(
                dependencies.credentials_path,
                {"version": CREDENTIAL_STORE_VERSION, "credentials": {}},
            )
            result["credentials"]["credentials"] = {
                ref: {
                    "credential_ref": item.get("credential_ref"),
                    "provider": item.get("provider"),
                    "label": item.get("label"),
                    "state": item.get("state", "active"),
                    "configured": bool(item.get("secret_values")),
                    "created_at": item.get("created_at"),
                    "updated_at": item.get("updated_at"),
                    "account_id": item.get("account_id"),
                }
                for ref, item in _account_owned_items(raw_credentials, "credentials").items()
            }
    return result


def _export_account_entry(
    account: Dict[str, Any],
    *,
    contains_secrets: bool,
) -> Optional[Dict[str, Any]]:
    """Export one account row plus its account-scoped reusable stores."""
    account_id = str(account.get("id") or "").strip()
    if not account_id:
        return None
    with account_scope(account_id):
        reusable = _export_reusable_config(contains_secrets=contains_secrets)
    return {
        "id": account_id,
        "name": account.get("name"),
        "description": account.get("description"),
        "status": account.get("status"),
        "default_creation_config": account.get("default_creation_config"),
        "created_at": account.get("created_at"),
        "reusable_config": reusable,
    }


def _export_all_accounts(*, contains_secrets: bool) -> List[Dict[str, Any]]:
    """Export every account row with its own scoped reusable configuration.

    Agent tokens are intentionally excluded: the database only stores their
    SHA-256 hashes, so they can never be replayed on another machine.  Re-create
    Agent tokens on the target machine after importing.
    """
    list_accounts = _deps().list_accounts
    if list_accounts is None:
        return []
    entries: List[Dict[str, Any]] = []
    for account in list_accounts() or []:
        if not isinstance(account, dict):
            continue
        entry = _export_account_entry(account, contains_secrets=contains_secrets)
        if entry is not None:
            entries.append(entry)
    return entries


def build_config_export_bundle(
    settings: Dict[str, Any],
    *,
    contains_secrets: bool,
) -> Dict[str, Any]:
    dependencies = _deps()
    return {
        "app": "PPT Visualization Studio",
        "type": "ppt_studio_config_bundle",
        "version": 3,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "contains_secrets": contains_secrets,
        "warning": (
            "This file contains API keys and secrets. Keep it private."
            if contains_secrets
            else (
                "Credential fields are masked. Existing saved "
                "credentials are preserved when this file is imported."
            )
        ),
        "settings": settings,
        "storyboard_templates": dependencies.read_json_file(
            dependencies.storyboard_templates_path,
            [],
        ),
        "step2_prompt_templates": dependencies.read_json_file(
            dependencies.step2_prompt_templates_path,
            [],
        ),
        "image_style": {
            "active_style_tokens_yaml": read_text_file_if_exists(
                dependencies.style_tokens_path
            ),
            "active_references": config_references_from_dir(
                dependencies.style_reference_dir
            ),
            "templates": exported_image_style_templates(),
        },
        "reusable_config": _export_reusable_config(
            contains_secrets=contains_secrets,
        ),
        # Every account with its own model connections, creation configs,
        # credentials, and image-style resources.  The top-level
        # reusable_config above stays as the current-account snapshot so older
        # importers keep working with this bundle.
        "accounts": _export_all_accounts(
            contains_secrets=contains_secrets,
        ),
    }


def export_full_config() -> Dict[str, Any]:
    settings = mask_sensitive_settings(
        _deps().get_all_settings(),
        force=True,
    )
    return build_config_export_bundle(
        settings,
        contains_secrets=False,
    )


def export_full_config_with_secrets() -> Dict[str, Any]:
    return build_config_export_bundle(
        _deps().get_all_settings(),
        contains_secrets=True,
    )


def validate_config_references(payload: Dict[str, Any]) -> None:
    image_style = (
        payload.get("image_style")
        if isinstance(payload.get("image_style"), dict)
        else {}
    )
    bundles = [image_style.get("active_references")]
    for item in image_style.get("templates") or []:
        if isinstance(item, dict):
            bundles.append(item.get("references"))
    for bundle in bundles:
        if not isinstance(bundle, dict):
            continue
        for reference in bundle.values():
            decode_config_reference_bytes(reference)
    reusable = payload.get("reusable_config")
    if isinstance(reusable, dict) and _deps().validate_project_style_templates:
        _deps().validate_project_style_templates(
            reusable.get("image_style_resources")
        )
    for account in payload.get("accounts") or []:
        if not isinstance(account, dict):
            continue
        reusable = account.get("reusable_config")
        if (
            isinstance(reusable, dict)
            and _deps().validate_project_style_templates
        ):
            _deps().validate_project_style_templates(
                reusable.get("image_style_resources")
            )


def _import_reusable_config(payload: Any) -> None:
    """Restore reusable stores into the current account, preserving IDs."""
    if not isinstance(payload, dict):
        return
    dependencies = _deps()
    current_account_id = get_current_account_id()

    if dependencies.import_project_style_templates:
        dependencies.import_project_style_templates(
            payload.get("image_style_resources")
        )

    models = payload.get("models")
    if dependencies.model_connections_path and isinstance(models, dict):
        connections = models.get("connections")
        if isinstance(connections, dict):
            existing = dependencies.read_json_file(
                dependencies.model_connections_path,
                {"version": "model_connections_v1", "connections": {}},
            )
            if not isinstance(existing, dict):
                existing = {"version": "model_connections_v1", "connections": {}}
            target = existing.setdefault("connections", {})
            if not isinstance(target, dict):
                target = {}
                existing["connections"] = target
            for item_id, item in connections.items():
                if not isinstance(item, dict):
                    continue
                imported = dict(item)
                imported["account_id"] = current_account_id
                target[str(item_id)] = imported
            existing["version"] = "model_connections_v1"
            dependencies.write_json_atomic(dependencies.model_connections_path, existing)

    creation_configs = payload.get("creation_configs")
    if dependencies.creation_configs_path and isinstance(creation_configs, dict):
        packages = creation_configs.get("packages")
        if isinstance(packages, dict):
            existing = dependencies.read_json_file(
                dependencies.creation_configs_path,
                {"version": "creation_config_store_v1", "packages": {}},
            )
            if not isinstance(existing, dict):
                existing = {"version": "creation_config_store_v1", "packages": {}}
            target = existing.setdefault("packages", {})
            if not isinstance(target, dict):
                target = {}
                existing["packages"] = target
            for item_id, item in packages.items():
                if not isinstance(item, dict):
                    continue
                imported = dict(item)
                imported["account_id"] = current_account_id
                target[str(item_id)] = imported
            existing["version"] = "creation_config_store_v1"
            dependencies.write_json_atomic(dependencies.creation_configs_path, existing)

    credentials = payload.get("credentials")
    if (
        dependencies.credentials_path
        and isinstance(credentials, dict)
        and credentials.get("included") is True
    ):
        items = credentials.get("credentials")
        if isinstance(items, dict):
            existing = dependencies.read_json_file(
                dependencies.credentials_path,
                {"version": CREDENTIAL_STORE_VERSION, "credentials": {}},
            )
            if not isinstance(existing, dict):
                existing = {"version": CREDENTIAL_STORE_VERSION, "credentials": {}}
            target = existing.setdefault("credentials", {})
            if not isinstance(target, dict):
                target = {}
                existing["credentials"] = target
            for reference, item in items.items():
                if not isinstance(item, dict) or not isinstance(item.get("secret_values"), dict):
                    continue
                imported = dict(item)
                imported["account_id"] = current_account_id
                target[str(reference)] = imported
            existing["version"] = CREDENTIAL_STORE_VERSION
            dependencies.write_json_atomic(dependencies.credentials_path, existing)


def _upsert_imported_accounts(
    accounts: List[Any],
) -> List[Dict[str, Any]]:
    """Recreate exported account rows on this machine, keeping their IDs.

    Stable IDs keep the ownership links inside the portable bundle (model
    connections, creation configs, credentials, per-account style directories)
    valid on the target machine.  Returns the normalized account payloads that
    were accepted for upsert.
    """
    upsert_account = _deps().upsert_account
    if upsert_account is None:
        return []
    accepted: List[Dict[str, Any]] = []
    for account in accounts:
        if not isinstance(account, dict):
            continue
        account_id = str(account.get("id") or "").strip()
        if not account_id:
            continue
        default_cfg = account.get("default_creation_config")
        default_package_id: Optional[str] = None
        default_package_version: Optional[int] = None
        if isinstance(default_cfg, dict):
            package_id = str(default_cfg.get("package_id") or "").strip()
            if package_id:
                default_package_id = package_id
            try:
                default_package_version = int(default_cfg.get("version"))
            except (TypeError, ValueError):
                default_package_version = None
        upsert_account(
            account_id=account_id,
            name=str(account.get("name") or "").strip() or account_id,
            description=str(account.get("description") or ""),
            status=str(account.get("status") or "active"),
            default_package_id=default_package_id,
            default_package_version=default_package_version,
        )
        accepted.append(account)
    return accepted


def _import_accounts_reusable_configs(accounts: List[Dict[str, Any]]) -> None:
    """Restore each exported account's scoped stores inside its own context."""
    for account in accounts:
        account_id = str(account.get("id") or "").strip()
        reusable = account.get("reusable_config")
        if not account_id or not isinstance(reusable, dict):
            continue
        with account_scope(account_id):
            # Inside the account scope the existing importer keeps every
            # record's exported account_id, so ownership is preserved 1:1.
            _import_reusable_config(reusable)


def _account_credentials_included(account: Dict[str, Any]) -> bool:
    reusable = account.get("reusable_config")
    if not isinstance(reusable, dict):
        return False
    credential_bundle = reusable.get("credentials")
    return (
        isinstance(credential_bundle, dict)
        and credential_bundle.get("included") is True
    )


def _account_display_name(account: Dict[str, Any]) -> str:
    return str(
        account.get("name")
        or account.get("id")
        or ""
    ).strip()


def _import_accounts_message(accounts: List[Dict[str, Any]]) -> str:
    names = "、".join(
        name for name in map(_account_display_name, accounts) if name
    )[:60]
    message = f"；已导入 {len(accounts)} 个账号（{names}）的模型与创作配置"
    missing = [
        _account_display_name(account)
        for account in accounts
        if _account_display_name(account)
        and not _account_credentials_included(account)
    ]
    if missing:
        message += f"；账号 {('、'.join(missing))[:60]} 需重新配置凭据"
    else:
        message += "；凭据均已随包还原"
    return message


def import_full_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    dependencies = _deps()
    # [配置包压缩包 20260908] ZIP 容器里的 config.json 用 "asset" 路径引用
    # 图片而不是内联 Base64。直接把这份 JSON 发给 JSON 导入会导致参考图被
    # 当作缺失并删除本地文件，这里显式拒绝并提示导入完整压缩包。
    _assert_no_unresolved_zip_assets(payload)
    validate_config_references(payload)
    accounts_payload = (
        payload.get("accounts")
        if isinstance(payload.get("accounts"), list)
        else []
    )
    imported_accounts = _upsert_imported_accounts(accounts_payload)
    if imported_accounts:
        # Multi-account bundle: restore every account's scoped stores inside
        # that account's own context.  The top-level reusable_config snapshot
        # exists for older importers and is skipped here so a foreign
        # current-account snapshot can never overwrite this machine's stores.
        _import_accounts_reusable_configs(imported_accounts)
    else:
        # Legacy version 2 bundle (or a v3 bundle without account rows):
        # everything belongs to the current account.
        _import_reusable_config(payload.get("reusable_config"))

    settings = payload.get("settings")
    if isinstance(settings, dict):
        imported_settings = {
            str(key): str(value)
            for key, value in settings.items()
        }
        imported_settings = preserve_masked_secrets(
            imported_settings,
            dependencies.get_all_settings(),
        )
        dependencies.update_settings(imported_settings)

    storyboard_templates = payload.get("storyboard_templates")
    if isinstance(storyboard_templates, list):
        dependencies.write_json_atomic(
            dependencies.storyboard_templates_path,
            normalize_imported_template_list(storyboard_templates),
        )

    step2_prompt_templates = payload.get("step2_prompt_templates")
    if isinstance(step2_prompt_templates, list):
        dependencies.write_json_atomic(
            dependencies.step2_prompt_templates_path,
            normalize_imported_template_list(step2_prompt_templates),
        )

    image_style = (
        payload.get("image_style")
        if isinstance(payload.get("image_style"), dict)
        else {}
    )
    dependencies.ensure_active_image_style_storage()
    active_style = str(
        image_style.get("active_style_tokens_yaml") or ""
    ).strip()
    if active_style:
        with open(
            dependencies.style_tokens_path,
            "w",
            encoding="utf-8",
            newline="\n",
        ) as file:
            file.write(active_style.rstrip() + "\n")
    write_config_references(
        image_style.get("active_references"),
        dependencies.style_reference_dir,
    )

    imported_image_templates = []
    has_image_template_payload = isinstance(
        image_style.get("templates"),
        list,
    )
    for item in image_style.get("templates") or []:
        if not isinstance(item, dict):
            continue
        template_id = (
            safe_image_template_id(item.get("id"))
            or uuid.uuid4().hex[:12]
        )
        name = str(item.get("name") or "").strip()
        style_text = str(
            item.get("style_tokens_yaml") or ""
        ).strip()
        if not name or not style_text:
            continue
        template_dir = os.path.abspath(
            os.path.join(
                dependencies.image_style_templates_dir,
                template_id,
            )
        )
        base_dir = os.path.abspath(
            dependencies.image_style_templates_dir
        )
        if os.path.commonpath([base_dir, template_dir]) != base_dir:
            continue
        os.makedirs(
            os.path.join(template_dir, "references"),
            exist_ok=True,
        )
        with open(
            os.path.join(template_dir, "style_tokens.yaml"),
            "w",
            encoding="utf-8",
            newline="\n",
        ) as file:
            file.write(style_text.rstrip() + "\n")
        write_config_references(
            item.get("references"),
            os.path.join(template_dir, "references"),
        )
        imported_image_templates.append(
            {
                "id": template_id,
                "name": name[:60],
                "created_at": str(
                    item.get("created_at")
                    or dependencies.template_timestamp()
                ),
                "updated_at": str(
                    item.get("updated_at")
                    or dependencies.template_timestamp()
                ),
            }
        )
    if has_image_template_payload:
        dependencies.write_json_atomic(
            dependencies.image_style_templates_index,
            imported_image_templates,
        )
    if imported_accounts:
        reusable_message = _import_accounts_message(imported_accounts)
    else:
        reusable = payload.get("reusable_config")
        reusable_message = ""
        if isinstance(reusable, dict):
            credential_bundle = reusable.get("credentials")
            if (
                not isinstance(credential_bundle, dict)
                or credential_bundle.get("included") is not True
            ):
                reusable_message = "；模型与创作配置已导入，凭据需在当前账号重新配置"
            else:
                reusable_message = "；模型、创作配置和凭据已导入"
    return {"success": True, "message": "配置已导入" + reusable_message}


# ---------------------------------------------------------------------------
# [配置包压缩包 20260908] ZIP 容器（config.json + assets/）支持
#
# 配置包里的风格参考图以 Base64 内联在 JSON 中。ZIP 容器把它们抽取为
# assets/ 目录下的独立图片文件，config.json 用 "asset": "assets/xxx" 路径
# 引用，方便解压后直接查看或替换图片，再重新压缩导入。导入时按原路径读取
# 并重新内联为 Base64，之后完全复用既有的 import_full_config 校验与落盘
# 流程（多账号、legacy 兼容、凭据保护均不变）。
# ---------------------------------------------------------------------------

CONFIG_ZIP_ENTRY = "config.json"
CONFIG_ZIP_ASSETS_PREFIX = "assets/"
CONFIG_ZIP_README_ENTRY = "README.txt"
# 压缩包内参考图片的解压总大小上限，防止畸形压缩包放大内存占用。
CONFIG_ZIP_MAX_ASSET_BYTES = 64 * 1024 * 1024

_CONFIG_ZIP_README_TEXT = """PPT 可视化工作室 配置包
========================

config.json
    全部配置数据：账号、模型连接、创作配置、凭据、提示词模板、图片风格设置。
    风格参考图片以 "asset": "assets/xxxx.png" 形式引用 assets/ 目录下的文件。

assets/
    风格参考图片本体，文件名带数字前缀用于保证唯一性。

导入方式
    在「设置 → 配置包」中直接选择此 .zip 文件导入即可，无需解压。

手动调整
    可解压后修改 config.json 或替换 assets/ 中的图片，然后重新压缩为
    .zip（保持 config.json、assets/、README.txt 位于压缩包根目录）再导入。
"""

_MIME_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

_ZIP_ASSET_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def _zip_asset_path(sequence: int, filename: Any, mime: Any) -> str:
    """Build a unique, filesystem-friendly asset path inside the ZIP."""
    raw_name = os.path.basename(str(filename or "").strip())
    safe_name = _ZIP_ASSET_UNSAFE_CHARS.sub("_", raw_name).strip("._-")
    if not safe_name:
        safe_name = "reference"
    stem, extension = os.path.splitext(safe_name)
    if not extension:
        extension = _MIME_EXTENSIONS.get(
            str(mime or "").strip().lower(),
            ".png",
        )
    return f"{CONFIG_ZIP_ASSETS_PREFIX}{sequence:04d}_{stem[:60]}{extension}"


def _iter_image_reference_values(payload: Any):
    """Yield every inline image-reference dict inside a config bundle.

    Covers the three storage locations of the version-3 bundle:
    image_style.active_references / image_style.templates[].references
    (kind-keyed config references) and the per-account step3
    image_style_resources.templates[].references.images[] entries.
    """
    if not isinstance(payload, dict):
        return
    image_style = payload.get("image_style")
    if isinstance(image_style, dict):
        active = image_style.get("active_references")
        if isinstance(active, dict):
            for reference in active.values():
                if isinstance(reference, dict):
                    yield reference
        templates = image_style.get("templates")
        if isinstance(templates, list):
            for item in templates:
                if not isinstance(item, dict):
                    continue
                refs = item.get("references")
                if isinstance(refs, dict):
                    for reference in refs.values():
                        if isinstance(reference, dict):
                            yield reference
    reusable_roots: List[Dict[str, Any]] = []
    reusable = payload.get("reusable_config")
    if isinstance(reusable, dict):
        reusable_roots.append(reusable)
    accounts = payload.get("accounts")
    if isinstance(accounts, list):
        for account in accounts:
            if (
                isinstance(account, dict)
                and isinstance(account.get("reusable_config"), dict)
            ):
                reusable_roots.append(account["reusable_config"])
    for reusable in reusable_roots:
        resources = reusable.get("image_style_resources")
        if not isinstance(resources, dict):
            continue
        templates = resources.get("templates")
        if not isinstance(templates, list):
            continue
        for template in templates:
            if not isinstance(template, dict):
                continue
            refs = template.get("references")
            if not isinstance(refs, dict):
                continue
            images = refs.get("images")
            if not isinstance(images, list):
                continue
            for image in images:
                if isinstance(image, dict):
                    yield image


def _assert_no_unresolved_zip_assets(payload: Any) -> None:
    """Reject a bare ZIP config.json handed to the plain JSON importer."""
    for reference in _iter_image_reference_values(payload):
        if isinstance(reference.get("asset"), str) and reference.get("asset"):
            raise ValueError(
                "该配置内容来自压缩包的 config.json，"
                "请导入完整的 .zip 压缩包而不是单独的 JSON 文件"
            )


def _extract_bundle_assets(bundle: Dict[str, Any]) -> Dict[str, bytes]:
    """Replace inline Base64 image data with ZIP asset path references.

    Mutates the bundle in place and returns the extracted binary payloads
    keyed by their ZIP-internal asset paths.  Malformed Base64 stays inline
    so the existing validation reports it instead of the ZIP layer.
    """
    assets: Dict[str, bytes] = {}
    sequence = 0
    for reference in _iter_image_reference_values(bundle):
        data = reference.get("data")
        if not isinstance(data, str) or not data:
            continue
        try:
            raw = base64.b64decode(data, validate=True)
        except (ValueError, binascii.Error):
            continue
        sequence += 1
        asset_path = _zip_asset_path(
            sequence,
            reference.get("filename"),
            reference.get("mime"),
        )
        assets[asset_path] = raw
        reference.pop("data", None)
        reference["asset"] = asset_path
    return assets


def build_config_zip_bytes(bundle: Dict[str, Any]) -> bytes:
    """Serialize a config bundle into a ZIP container with external assets."""
    assets = _extract_bundle_assets(bundle)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            CONFIG_ZIP_ENTRY,
            json.dumps(bundle, ensure_ascii=False, indent=2),
        )
        for asset_path, raw in assets.items():
            archive.writestr(asset_path, raw)
        archive.writestr(CONFIG_ZIP_README_ENTRY, _CONFIG_ZIP_README_TEXT)
    return buffer.getvalue()


def export_full_config_zip() -> bytes:
    return build_config_zip_bytes(export_full_config())


def export_full_config_with_secrets_zip() -> bytes:
    return build_config_zip_bytes(export_full_config_with_secrets())


def _read_zip_bundle_payload(data: bytes) -> Dict[str, Any]:
    """Parse a ZIP config package and inline its assets back into Base64."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, EOFError) as exc:
        raise ValueError("配置包不是有效的 ZIP 压缩文件") from exc
    with archive:
        try:
            raw_config = archive.read(CONFIG_ZIP_ENTRY)
        except KeyError as exc:
            raise ValueError("配置压缩包缺少 config.json") from exc
        try:
            payload = json.loads(raw_config.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("config.json 内容无效") from exc
        if not isinstance(payload, dict):
            raise ValueError("config.json 内容无效")
        asset_files: Dict[str, bytes] = {}
        total_bytes = 0
        for name in archive.namelist():
            if not name.startswith(CONFIG_ZIP_ASSETS_PREFIX):
                continue
            if name.endswith("/"):
                continue
            total_bytes += archive.getinfo(name).file_size
            if total_bytes > CONFIG_ZIP_MAX_ASSET_BYTES:
                raise ValueError(
                    "压缩包内参考图片总大小超过限制（64MB）"
                )
            asset_files[name] = archive.read(name)
    _inline_zip_assets(payload, asset_files)
    return payload


def _inline_zip_assets(
    payload: Dict[str, Any],
    asset_files: Mapping[str, bytes],
) -> None:
    """Restore inline Base64 image data from ZIP asset paths, in place."""
    for reference in _iter_image_reference_values(payload):
        asset_path = reference.get("asset")
        if not isinstance(asset_path, str) or not asset_path:
            continue
        normalized = posixpath.normpath(asset_path.replace("\\", "/"))
        if (
            posixpath.isabs(normalized)
            or normalized.startswith("..")
            or normalized == CONFIG_ZIP_ASSETS_PREFIX.rstrip("/")
            or not normalized.startswith(CONFIG_ZIP_ASSETS_PREFIX)
        ):
            raise ValueError(f"压缩包资源路径无效：{asset_path}")
        raw = asset_files.get(normalized)
        if raw is None:
            raise ValueError(f"压缩包缺少参考图片：{asset_path}")
        reference["data"] = base64.b64encode(raw).decode("ascii")
        reference.pop("asset", None)


def import_full_config_zip(data: bytes) -> Dict[str, Any]:
    """Import a ZIP config package (config.json + assets/) in one call."""
    payload = _read_zip_bundle_payload(data)
    return import_full_config(payload)


def import_config_bundle_bytes(data: bytes) -> Dict[str, Any]:
    """Accept either a ZIP config package or a legacy plain-JSON bundle.

    The container format is sniffed from the payload's leading bytes so the
    route layer can forward the raw upload body without caring about the
    extension the browser reported.
    """
    if data[:2] == b"PK":
        return import_full_config_zip(data)
    try:
        payload = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            "无法识别的配置包格式：请提供 .zip 压缩包或 JSON 配置文件"
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError(
            "无法识别的配置包格式：请提供 .zip 压缩包或 JSON 配置文件"
        )
    return import_full_config(payload)
