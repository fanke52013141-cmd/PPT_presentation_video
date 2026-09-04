"""Versioned, credential-reference-only model connection registry.

This is intentionally a small storage boundary.  It accepts injected JSON
read/write functions so the composition root can choose the production path
and atomic writer without coupling this module to FastAPI, SQLAlchemy, or the
application module.  A later database migration may replace this adapter
without changing the public registry contract.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import threading
from typing import Any, Callable, Mapping, Optional
from urllib.parse import parse_qsl, urlsplit
import uuid

from model_connection_models import (
    ModelConnectionCopy,
    ModelConnectionCreate,
    ModelConnectionStateUpdate,
    ModelConnectionUpdate,
)


REGISTRY_VERSION = "model_connections_v1"
CONNECTION_KINDS = {"text", "image", "tts"}
CONNECTION_STATES = {"active", "disabled", "archived"}
_SENSITIVE_TOKENS = {
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "password",
    "secret",
    "token",
    "access_key",
    "secret_key",
    "private_key",
}


class ModelConnectionNotFoundError(KeyError):
    pass


class ModelConnectionUnavailableError(ValueError):
    pass


@dataclass(frozen=True)
class ModelConnectionDependencies:
    """Storage and time primitives supplied at application startup."""

    read_registry: Callable[[], Any]
    write_registry: Callable[[dict[str, Any]], Any]
    now: Callable[[], datetime] = datetime.now
    new_id: Callable[[], str] = lambda: uuid.uuid4().hex


@dataclass(frozen=True)
class ResolvedModelConnection:
    """Private runtime-only config; never serialize this from an HTTP route."""

    connection_id: str
    revision: int
    kind: str
    provider: str
    model: str
    endpoint: Optional[str]
    credential_ref: Optional[str]
    public_config: Mapping[str, Any]
    state: str


_dependencies: ModelConnectionDependencies | None = None
_registry_lock = threading.RLock()


def configure_model_connection_dependencies(
    dependencies: ModelConnectionDependencies,
) -> None:
    global _dependencies
    _dependencies = dependencies


def _deps() -> ModelConnectionDependencies:
    if _dependencies is None:
        raise RuntimeError("Model connection dependencies have not been configured")
    return _dependencies


def _timestamp() -> str:
    return _deps().now().isoformat(timespec="seconds")


def _clean_text(value: Any, field: str, limit: int) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} 不能为空")
    if len(text) > limit:
        raise ValueError(f"{field} 不能超过 {limit} 个字符")
    return text


def _credential_ref(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) > 500:
        raise ValueError("credential_ref 不能超过 500 个字符")
    return text


def _is_sensitive_key(value: Any) -> bool:
    key = str(value or "").strip().lower().replace("-", "_")
    return key in _SENSITIVE_TOKENS or any(
        token in key
        for token in ("password", "secret", "token", "credential")
    )


def _clean_public_config(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("public_config 必须是对象")

    def clean(item: Any, path: str = "public_config") -> Any:
        if isinstance(item, dict):
            output: dict[str, Any] = {}
            for key, nested in item.items():
                if _is_sensitive_key(key):
                    raise ValueError(f"{path}.{key} 不能保存凭据，请使用 credential_ref")
                output[str(key)] = clean(nested, f"{path}.{key}")
            return output
        if isinstance(item, list):
            return [clean(child, path) for child in item]
        if item is None or isinstance(item, (str, int, float, bool)):
            return item
        raise ValueError(f"{path} 只能包含 JSON 基础类型")

    return clean(value)


def _clean_endpoint(value: Any) -> Optional[str]:
    if value is None:
        return None
    endpoint = str(value).strip()
    if not endpoint:
        return None
    if len(endpoint) > 1000:
        raise ValueError("endpoint 不能超过 1000 个字符")
    parsed = urlsplit(endpoint)
    if parsed.username or parsed.password:
        raise ValueError("endpoint 不能包含用户名或密码，请使用 credential_ref")
    for key, _value in parse_qsl(parsed.query, keep_blank_values=True):
        if _is_sensitive_key(key):
            raise ValueError("endpoint 不能包含凭据查询参数，请使用 credential_ref")
    return endpoint


def _new_registry() -> dict[str, Any]:
    return {"version": REGISTRY_VERSION, "connections": {}}


def _registry() -> dict[str, Any]:
    raw = _deps().read_registry()
    if not isinstance(raw, dict):
        return _new_registry()
    connections = raw.get("connections")
    if not isinstance(connections, dict):
        return _new_registry()
    normalized = deepcopy(raw)
    normalized["version"] = REGISTRY_VERSION
    normalized["connections"] = connections
    return normalized


def _connection(registry: Mapping[str, Any], connection_id: str) -> dict[str, Any]:
    item = registry.get("connections", {}).get(str(connection_id))
    if not isinstance(item, dict):
        raise ModelConnectionNotFoundError(f"模型连接不存在: {connection_id}")
    return item


def _revision(connection: Mapping[str, Any], revision: Optional[int] = None) -> dict[str, Any]:
    revisions = connection.get("revisions")
    if not isinstance(revisions, list) or not revisions:
        raise ValueError("模型连接版本数据损坏")
    target = int(revision or connection.get("current_revision") or 0)
    for item in revisions:
        if isinstance(item, dict) and item.get("revision") == target:
            return item
    raise ModelConnectionNotFoundError(f"模型连接版本不存在: {target}")


def _public_endpoint(endpoint: Optional[str]) -> Optional[str]:
    """Defence in depth for old registry data written before endpoint checks."""
    if not endpoint:
        return None
    parsed = urlsplit(str(endpoint))
    if parsed.username or parsed.password:
        return None
    query = parse_qsl(parsed.query, keep_blank_values=True)
    if any(_is_sensitive_key(key) for key, _value in query):
        return None
    return str(endpoint)


def _redact_public_config(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "__REDACTED__" if _is_sensitive_key(key) else _redact_public_config(nested)
            for key, nested in value.items()
        }
    if isinstance(value, list):
        return [_redact_public_config(item) for item in value]
    return deepcopy(value)


def _public_connection(connection: Mapping[str, Any]) -> dict[str, Any]:
    revision = _revision(connection)
    kind = str(connection.get("kind") or "")
    state = str(connection.get("state") or "active")
    if kind not in CONNECTION_KINDS or state not in CONNECTION_STATES:
        raise ValueError("模型连接数据损坏")
    return {
        "id": str(connection.get("id") or ""),
        "name": str(connection.get("name") or ""),
        "kind": kind,
        "state": state,
        "current_revision": int(connection.get("current_revision") or 0),
        "created_at": str(connection.get("created_at") or ""),
        "updated_at": str(connection.get("updated_at") or ""),
        "archived_at": connection.get("archived_at"),
        "revision": {
            "revision": int(revision["revision"]),
            "provider": str(revision.get("provider") or ""),
            "model": str(revision.get("model") or ""),
            "endpoint": _public_endpoint(revision.get("endpoint")),
            "public_config": _redact_public_config(revision.get("public_config") or {}),
            "credential_configured": bool(revision.get("credential_ref")),
            "created_at": str(revision.get("created_at") or ""),
        },
    }


def _new_revision(
    *,
    revision: int,
    provider: Any,
    model: Any,
    endpoint: Any,
    credential_ref: Any,
    public_config: Any,
    created_at: str,
) -> dict[str, Any]:
    return {
        "revision": revision,
        "provider": _clean_text(provider, "provider", 80),
        "model": _clean_text(model, "model", 160),
        "endpoint": _clean_endpoint(endpoint),
        "credential_ref": _credential_ref(credential_ref),
        "public_config": _clean_public_config(public_config),
        "created_at": created_at,
    }


def list_model_connections(
    *,
    kind: Optional[str] = None,
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    if kind is not None and kind not in CONNECTION_KINDS:
        raise ValueError("kind 必须是 text、image 或 tts")
    with _registry_lock:
        connections = _registry()["connections"].values()
        public = [_public_connection(item) for item in connections if isinstance(item, dict)]
    return sorted(
        (
            item for item in public
            if (kind is None or item["kind"] == kind)
            and (include_archived or item["state"] != "archived")
        ),
        key=lambda item: (item["name"].casefold(), item["id"]),
    )


def get_model_connection(connection_id: str) -> dict[str, Any]:
    with _registry_lock:
        return _public_connection(_connection(_registry(), connection_id))


def create_model_connection(payload: ModelConnectionCreate) -> dict[str, Any]:
    with _registry_lock:
        registry = _registry()
        now = _timestamp()
        connection_id = str(_deps().new_id()).strip()
        if not connection_id or connection_id in registry["connections"]:
            raise ValueError("无法生成唯一模型连接 ID")
        kind = str(payload.kind)
        if kind not in CONNECTION_KINDS:
            raise ValueError("kind 必须是 text、image 或 tts")
        revision = _new_revision(
            revision=1,
            provider=payload.provider,
            model=payload.model,
            endpoint=payload.endpoint,
            credential_ref=payload.credential_ref,
            public_config=payload.public_config,
            created_at=now,
        )
        connection = {
            "id": connection_id,
            "name": _clean_text(payload.name, "name", 120),
            "kind": kind,
            "state": "active",
            "current_revision": 1,
            "created_at": now,
            "updated_at": now,
            "archived_at": None,
            "revisions": [revision],
        }
        registry["connections"][connection_id] = connection
        _deps().write_registry(registry)
        return _public_connection(connection)


def copy_model_connection(
    connection_id: str,
    payload: ModelConnectionCopy,
) -> dict[str, Any]:
    with _registry_lock:
        registry = _registry()
        source = _connection(registry, connection_id)
        if source.get("state") == "archived":
            raise ModelConnectionUnavailableError("已归档连接不能复制")
        source_revision = _revision(source)
        now = _timestamp()
        target_id = str(_deps().new_id()).strip()
        if not target_id or target_id in registry["connections"]:
            raise ValueError("无法生成唯一模型连接 ID")
        revision = _new_revision(
            revision=1,
            provider=source_revision.get("provider"),
            model=source_revision.get("model"),
            endpoint=source_revision.get("endpoint"),
            credential_ref=source_revision.get("credential_ref"),
            public_config=source_revision.get("public_config"),
            created_at=now,
        )
        connection = {
            "id": target_id,
            "name": _clean_text(payload.name, "name", 120),
            "kind": source["kind"],
            "state": "active",
            "current_revision": 1,
            "created_at": now,
            "updated_at": now,
            "archived_at": None,
            "revisions": [revision],
        }
        registry["connections"][target_id] = connection
        _deps().write_registry(registry)
        return _public_connection(connection)


def update_model_connection(
    connection_id: str,
    payload: ModelConnectionUpdate,
) -> dict[str, Any]:
    updates = payload.model_dump(exclude_unset=True)
    with _registry_lock:
        registry = _registry()
        connection = _connection(registry, connection_id)
        if connection.get("state") == "archived":
            raise ModelConnectionUnavailableError("已归档连接不能编辑")
        current = _revision(connection)
        now = _timestamp()
        if "name" in updates:
            connection["name"] = _clean_text(updates["name"], "name", 120)
        next_revision_number = int(connection["current_revision"]) + 1
        next_revision = _new_revision(
            revision=next_revision_number,
            provider=updates.get("provider", current.get("provider")),
            model=updates.get("model", current.get("model")),
            endpoint=updates.get("endpoint", current.get("endpoint")),
            credential_ref=updates.get("credential_ref", current.get("credential_ref")),
            public_config=updates.get("public_config", current.get("public_config")),
            created_at=now,
        )
        connection["revisions"].append(next_revision)
        connection["current_revision"] = next_revision_number
        connection["updated_at"] = now
        _deps().write_registry(registry)
        return _public_connection(connection)


def set_model_connection_state(
    connection_id: str,
    payload: ModelConnectionStateUpdate,
) -> dict[str, Any]:
    target = str(payload.state)
    if target not in CONNECTION_STATES:
        raise ValueError("state 必须是 active、disabled 或 archived")
    with _registry_lock:
        registry = _registry()
        connection = _connection(registry, connection_id)
        now = _timestamp()
        if connection.get("state") == "archived" and target != "archived":
            raise ModelConnectionUnavailableError("已归档连接不可重新启用")
        connection["state"] = target
        connection["archived_at"] = now if target == "archived" else None
        connection["updated_at"] = now
        _deps().write_registry(registry)
        return _public_connection(connection)


def bind_model_connection(
    connection_id: str,
    revision: Optional[int] = None,
) -> ResolvedModelConnection:
    """Resolve a connection for a newly-created config/package binding.

    Disabled and archived connections remain resolvable through
    :func:`resolve_model_connection` for existing immutable project snapshots,
    but cannot be selected for a new binding.
    """
    with _registry_lock:
        registry = _registry()
        connection = _connection(registry, connection_id)
        if connection.get("state") != "active":
            raise ModelConnectionUnavailableError("停用或归档的模型连接不能用于新绑定")
        return _resolve(connection, revision)


def resolve_model_connection(
    connection_id: str,
    revision: Optional[int] = None,
) -> ResolvedModelConnection:
    """Resolve an immutable historical binding, including old revisions."""
    with _registry_lock:
        return _resolve(_connection(_registry(), connection_id), revision)


def _resolve(
    connection: Mapping[str, Any], revision: Optional[int]) -> ResolvedModelConnection:
    selected = _revision(connection, revision)
    return ResolvedModelConnection(
        connection_id=str(connection["id"]),
        revision=int(selected["revision"]),
        kind=str(connection["kind"]),
        provider=str(selected["provider"]),
        model=str(selected["model"]),
        endpoint=selected.get("endpoint"),
        credential_ref=selected.get("credential_ref"),
        public_config=deepcopy(selected.get("public_config") or {}),
        state=str(connection.get("state") or "active"),
    )
