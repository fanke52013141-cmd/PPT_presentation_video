"""Provision a ready-to-create account from the current local account.

The account layer deliberately isolates model connections and credentials.
This service creates fresh connection and credential references for a target
account, then rewrites the copied creation-package bindings to those fresh
references.  It never exposes a secret in a response payload.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from sqlalchemy.orm import Session

from account_context import account_scope, get_current_account_id
from account_service import create_account, get_account, set_default_creation_config
from database import Account
from credential_store import create_credential, get_credential
from creation_config_service import (
    create_creation_config,
    get_creation_config_version,
)
from model_connection_models import ModelConnectionCreate
from model_connection_service import (
    create_model_connection,
    resolve_model_connection,
)


class AccountProvisioningError(ValueError):
    """Raised when a source configuration cannot become a runnable account."""


def _connection_references(payload: dict[str, Any]) -> dict[str, int]:
    """Return every connection used by a creation package, once per revision."""
    references: dict[str, int] = {}
    bindings = payload.get("model_bindings")
    if isinstance(bindings, dict):
        for item in bindings.values():
            if not isinstance(item, dict):
                continue
            connection_id = str(item.get("connection_id") or "").strip()
            revision = item.get("revision")
            if connection_id and isinstance(revision, int) and revision > 0:
                references[connection_id] = revision

    tts = payload.get("tts")
    connection = tts.get("connection") if isinstance(tts, dict) else None
    if isinstance(connection, dict):
        connection_id = str(connection.get("connection_id") or "").strip()
        revision = connection.get("revision")
        if connection_id and isinstance(revision, int) and revision > 0:
            references[connection_id] = revision
    return references


def _rewrite_connection_references(
    payload: dict[str, Any],
    mapping: dict[str, dict[str, Any]],
) -> None:
    bindings = payload.get("model_bindings")
    if isinstance(bindings, dict):
        for key, item in bindings.items():
            if not isinstance(item, dict):
                continue
            source_id = str(item.get("connection_id") or "").strip()
            target = mapping.get(source_id)
            if target is None:
                raise AccountProvisioningError(
                    f"配置包的模型连接无法复制: {key}"
                )
            item["connection_id"] = target["connection_id"]
            item["revision"] = target["revision"]

    tts = payload.get("tts")
    connection = tts.get("connection") if isinstance(tts, dict) else None
    if isinstance(connection, dict):
        source_id = str(connection.get("connection_id") or "").strip()
        target = mapping.get(source_id)
        if target is None:
            raise AccountProvisioningError("配置包的语音模型连接无法复制")
        connection["connection_id"] = target["connection_id"]
        connection["revision"] = target["revision"]


def _set_style_and_persona(
    payload: dict[str, Any],
    *,
    image_style_template_id: str,
    voice_id: str,
    storyboard_system_content: str,
) -> None:
    image_style = payload.setdefault("image_style", {})
    if not isinstance(image_style, dict):
        raise AccountProvisioningError("来源配置的图片风格格式不正确")
    image_style["template_id"] = image_style_template_id
    image_style["version"] = 1

    tts = payload.setdefault("tts", {})
    if not isinstance(tts, dict):
        raise AccountProvisioningError("来源配置的语音设置格式不正确")
    tts["voice_id"] = voice_id

    prompts = payload.setdefault("prompts", {})
    if not isinstance(prompts, dict):
        raise AccountProvisioningError("来源配置的提示词格式不正确")
    storyboard = prompts.setdefault("storyboard", {})
    if not isinstance(storyboard, dict):
        raise AccountProvisioningError("来源配置的演讲稿提示词格式不正确")
    storyboard["system_content"] = storyboard_system_content


def provision_account_from_current(
    db: Session,
    *,
    name: str,
    description: str,
    source_package_id: str,
    source_package_version: int | None,
    package_name: str,
    package_description: str,
    tags: list[str],
    image_style_template_id: str,
    voice_id: str,
    storyboard_system_content: str,
) -> dict[str, Any]:
    """Create a fully runnable account by copying one current-account package.

    The source package must already resolve in the caller's account.  Credential
    values move only from the local credential store to a new local credential
    reference; returned values contain account/package/model metadata only.
    """
    source_account_id = get_current_account_id()
    source_account = get_account(db, source_account_id)
    normalized_name = str(name or "").strip()
    if not normalized_name:
        raise AccountProvisioningError("账号名称不能为空")
    if db.query(Account).filter(
        Account.name == normalized_name,
        Account.status == "active",
    ).first():
        raise AccountProvisioningError("同名创作账号已存在")
    if not str(voice_id or "").strip():
        raise AccountProvisioningError("音色 ID 不能为空")
    if not str(storyboard_system_content or "").strip():
        raise AccountProvisioningError("演讲稿提示词不能为空")

    with account_scope(source_account_id):
        source_version = get_creation_config_version(
            source_package_id,
            source_package_version,
        )
        source_payload = deepcopy(source_version.get("payload"))
        if not isinstance(source_payload, dict):
            raise AccountProvisioningError("来源创作配置没有有效内容")

        source_connections: list[dict[str, Any]] = []
        for connection_id, revision in _connection_references(source_payload).items():
            try:
                connection = resolve_model_connection(connection_id, revision)
            except Exception as exc:
                raise AccountProvisioningError(
                    f"来源模型连接不可用: {connection_id}"
                ) from exc
            secrets: dict[str, Any] | None = None
            if connection.credential_ref:
                try:
                    secrets = get_credential(connection.credential_ref)
                except Exception as exc:
                    raise AccountProvisioningError(
                        f"来源模型凭据不可用: {connection_id}"
                    ) from exc
            source_connections.append(
                {
                    "source_id": connection_id,
                    "connection": connection,
                    "secrets": secrets,
                }
            )

    account = create_account(
        db,
        name=normalized_name,
        description=str(description or "").strip(),
    )
    target_account_id = str(account["id"])
    connection_mapping: dict[str, dict[str, Any]] = {}
    with account_scope(target_account_id):
        for item in source_connections:
            connection = item["connection"]
            credential_ref: str | None = None
            if isinstance(item["secrets"], dict):
                credential = create_credential(
                    provider=connection.provider,
                    label=f"{normalized_name} · {connection.kind} 模型凭据",
                    secret_values=item["secrets"],
                )
                credential_ref = str(credential["credential_ref"])
            copied = create_model_connection(
                ModelConnectionCreate(
                    name=f"{normalized_name} · {connection.kind} 模型",
                    kind=connection.kind,
                    provider=connection.provider,
                    model=connection.model,
                    endpoint=connection.endpoint,
                    credential_ref=credential_ref,
                    public_config=dict(connection.public_config),
                )
            )
            connection_mapping[item["source_id"]] = {
                "connection_id": copied["id"],
                "revision": copied["current_revision"],
            }

        target_payload = deepcopy(source_payload)
        _rewrite_connection_references(target_payload, connection_mapping)
        _set_style_and_persona(
            target_payload,
            image_style_template_id=str(image_style_template_id or "").strip(),
            voice_id=str(voice_id).strip(),
            storyboard_system_content=str(storyboard_system_content).strip(),
        )
        package = create_creation_config(
            name=package_name,
            description=package_description,
            tags=tags,
            payload=target_payload,
        )
    account = set_default_creation_config(
        db,
        target_account_id,
        package["id"],
        package["latest_version"],
    )

    return {
        "account": account,
        "package": package,
        "copied_model_count": len(connection_mapping),
    }
