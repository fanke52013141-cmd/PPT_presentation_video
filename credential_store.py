"""Credential reference storage for model connections.

The default adapter is deliberately injected and local.  Production deployments
can replace it with an OS keyring or secret manager without changing connection
or project payloads.  Secrets are returned only to an internal runtime caller;
the HTTP layer exposes the stable ``credential://`` reference and metadata.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import threading
from typing import Any, Callable, Mapping
from uuid import uuid4


STORE_VERSION = "credential_store_v1"


class CredentialError(ValueError):
    pass


class CredentialNotFound(CredentialError):
    pass


class CredentialUnavailable(CredentialError):
    pass


@dataclass(frozen=True)
class CredentialDependencies:
    read_store: Callable[[], Any]
    write_store: Callable[[dict[str, Any]], Any]
    now: Callable[[], str] = lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    new_id: Callable[[], str] = lambda: uuid4().hex


_dependencies: CredentialDependencies | None = None
_lock = threading.RLock()


def configure_credential_dependencies(dependencies: CredentialDependencies) -> None:
    global _dependencies
    _dependencies = dependencies


def _deps() -> CredentialDependencies:
    if _dependencies is None:
        raise RuntimeError("Credential dependencies have not been configured")
    return _dependencies


def _store() -> dict[str, Any]:
    raw = _deps().read_store()
    if raw is None:
        return {"version": STORE_VERSION, "credentials": {}}
    if not isinstance(raw, dict) or not isinstance(raw.get("credentials"), dict):
        raise CredentialError("凭据存储格式不正确")
    if raw.get("version", STORE_VERSION) != STORE_VERSION:
        raise CredentialError("凭据存储版本不受支持")
    return deepcopy(raw)


def _clean(value: Any, field: str, limit: int) -> str:
    result = str(value or "").strip()
    if not result:
        raise CredentialError(f"{field} 不能为空")
    if len(result) > limit:
        raise CredentialError(f"{field} 不能超过 {limit} 个字符")
    return result


def _clean_secrets(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or not value:
        raise CredentialError("secret_values 必须是非空对象")
    result: dict[str, str] = {}
    for key, raw in value.items():
        name = _clean(key, "secret_values 字段名", 80)
        if not isinstance(raw, str) or not raw.strip():
            raise CredentialError("secret_values 只能包含非空字符串")
        if len(raw) > 10000:
            raise CredentialError("凭据值过长")
        result[name] = raw
    return result


def _metadata(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "credential_ref": str(item["credential_ref"]),
        "provider": str(item["provider"]),
        "label": str(item["label"]),
        "state": str(item.get("state") or "active"),
        "configured": bool(item.get("secret_values")),
        "created_at": str(item["created_at"]),
        "updated_at": str(item["updated_at"]),
    }


def create_credential(*, provider: Any, label: Any, secret_values: Any) -> dict[str, Any]:
    with _lock:
        store = _store()
        credential_id = _clean(_deps().new_id(), "credential_id", 200)
        reference = f"credential://{credential_id}"
        if reference in store["credentials"]:
            raise CredentialError("凭据引用冲突，请重试")
        timestamp = _deps().now()
        item = {
            "credential_ref": reference,
            "provider": _clean(provider, "provider", 80),
            "label": _clean(label, "label", 120),
            "secret_values": _clean_secrets(secret_values),
            "state": "active",
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        store["credentials"][reference] = item
        _deps().write_store(store)
        return _metadata(item)


def list_credentials(*, include_disabled: bool = False) -> list[dict[str, Any]]:
    with _lock:
        items = [_metadata(item) for item in _store()["credentials"].values()]
    return sorted(
        (item for item in items if include_disabled or item["state"] == "active"),
        key=lambda item: (item["provider"].casefold(), item["label"].casefold()),
    )


def get_credential(credential_ref: str) -> dict[str, Any]:
    with _lock:
        item = _store()["credentials"].get(str(credential_ref))
        if not isinstance(item, dict):
            raise CredentialNotFound("凭据不存在")
        if item.get("state") != "active":
            raise CredentialUnavailable("凭据已停用")
        return deepcopy(item.get("secret_values") or {})


def update_credential(
    credential_ref: str,
    *,
    label: Any = None,
    secret_values: Any = None,
    state: str | None = None,
) -> dict[str, Any]:
    with _lock:
        store = _store()
        item = store["credentials"].get(str(credential_ref))
        if not isinstance(item, dict):
            raise CredentialNotFound("凭据不存在")
        if label is not None:
            item["label"] = _clean(label, "label", 120)
        if secret_values is not None:
            item["secret_values"] = _clean_secrets(secret_values)
        if state is not None:
            if state not in {"active", "disabled"}:
                raise CredentialError("state 必须是 active 或 disabled")
            item["state"] = state
        item["updated_at"] = _deps().now()
        _deps().write_store(store)
        return _metadata(item)
