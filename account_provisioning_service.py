"""Provision a ready-to-create account from the current local account.

Model connections are global resources.  New accounts receive an account-local
creation package that retains the source package's connection IDs; credentials
are never copied or returned by this service.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from sqlalchemy.orm import Session

from account_context import account_scope, get_current_account_id
from account_service import create_account, set_default_creation_config
from database import Account
from creation_config_service import (
    create_creation_config,
    get_creation_config_version,
)
from model_connection_service import (
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
    """Create an account package while retaining globally shared models."""
    source_account_id = get_current_account_id()
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

        for connection_id, revision in _connection_references(source_payload).items():
            try:
                resolve_model_connection(connection_id, revision)
            except Exception as exc:
                raise AccountProvisioningError(
                    f"来源模型连接不可用: {connection_id}"
                ) from exc

    account = create_account(
        db,
        name=normalized_name,
        description=str(description or "").strip(),
    )
    target_account_id = str(account["id"])
    with account_scope(target_account_id):
        target_payload = deepcopy(source_payload)
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
        "copied_model_count": 0,
    }
