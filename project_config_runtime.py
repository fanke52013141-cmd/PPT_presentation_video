"""Safe, read-only access to a project's immutable creation-config snapshot.

The project service writes ``planning/project_config.json`` when a creation
configuration is selected.  Runtime services use this module to read the
snapshot without importing the composition root, the database, or the package
registry.  A missing or malformed snapshot represents a legacy project and
returns ``None`` so callers can retain their established global-setting
fallbacks.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


PROJECT_CONFIG_FILENAME = "project_config.json"
MAX_PROJECT_CONFIG_BYTES = 1024 * 1024


class ProjectConfigBindingError(ValueError):
    """A selected project binding cannot safely be used at runtime."""


@dataclass(frozen=True)
class ResolvedProjectModelBinding:
    """Runtime-only provider details resolved from a project snapshot.

    ``api_key`` is deliberately excluded from ``repr`` so ordinary exceptions
    and debug output cannot disclose a credential.
    """

    connection_id: str
    revision: int
    provider: str
    model: str
    endpoint: str | None
    api_key: str = field(repr=False)
    public_config: Mapping[str, Any] = field(default_factory=dict)


def project_config_path(project: Any) -> Path | None:
    """Return a project's config-snapshot path when it has a usable run dir."""
    run_dir = getattr(project, "run_dir", None)
    if not isinstance(run_dir, str) or not run_dir.strip():
        return None
    return Path(run_dir) / "planning" / PROJECT_CONFIG_FILENAME


def load_project_config(project: Any) -> dict[str, Any] | None:
    """Load a valid immutable config snapshot, or ``None`` for legacy projects.

    This intentionally suppresses filesystem and JSON errors.  A configuration
    snapshot must never make an existing project unusable; individual runtime
    services fall back to their existing global settings when it is unavailable.
    The returned value is copied so consumers cannot mutate a cached payload.
    """
    path = project_config_path(project)
    if path is None:
        return None
    try:
        if not path.is_file() or path.stat().st_size > MAX_PROJECT_CONFIG_BYTES:
            return None
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    payload = raw.get("payload")
    if not isinstance(payload, dict):
        return None
    if not isinstance(payload.get("schema_version"), str):
        return None
    return deepcopy(raw)


def get_config_value(
    project: Any,
    path: str | Iterable[str],
    default: Any = None,
) -> Any:
    """Read a nested value from a project snapshot's payload.

    ``path`` accepts a dot-delimited string or iterable of keys.  Missing keys,
    malformed paths, and absent snapshots return ``default``.  Values are deep
    copied to prevent accidental in-memory mutation from changing another
    caller's view of the snapshot.
    """
    snapshot = load_project_config(project)
    if snapshot is None:
        return default
    if isinstance(path, str):
        keys = tuple(part for part in path.split(".") if part)
    else:
        try:
            keys = tuple(str(part) for part in path)
        except TypeError:
            return default
    if not keys:
        return default
    value: Any = snapshot["payload"]
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]
    return deepcopy(value)


def resolve_project_model_binding(
    project: Any,
    binding_name: str,
    *,
    expected_kind: str,
    resolve_model_connection: Callable[[str, int], Any] | None,
    get_credential: Callable[[str], Any] | None,
) -> ResolvedProjectModelBinding | None:
    """Resolve one snapshot model binding without touching global settings.

    A missing binding returns ``None`` so callers can support legacy global
    settings.  Once a binding is present it must resolve completely; silently
    falling back to another account's global connection would violate the
    project's immutable configuration.
    """
    binding = get_config_value(project, ("model_bindings", binding_name))
    if binding is None:
        return None
    if not isinstance(binding, dict):
        raise ProjectConfigBindingError(
            f"项目模型绑定 {binding_name} 格式无效"
        )
    connection_id = binding.get("connection_id")
    revision = binding.get("revision")
    if (
        not isinstance(connection_id, str)
        or not connection_id.strip()
        or not isinstance(revision, int)
        or isinstance(revision, bool)
        or revision < 1
    ):
        raise ProjectConfigBindingError(
            f"项目模型绑定 {binding_name} 缺少有效连接版本"
        )
    if resolve_model_connection is None or get_credential is None:
        raise ProjectConfigBindingError("模型连接服务尚未配置")
    try:
        connection = resolve_model_connection(connection_id.strip(), revision)
    except Exception as exc:
        raise ProjectConfigBindingError(
            f"项目模型连接不可用: {connection_id}"
        ) from exc
    kind = str(_connection_value(connection, "kind") or "").strip()
    if kind != expected_kind:
        raise ProjectConfigBindingError(
            f"项目模型绑定 {binding_name} 需要 {expected_kind} 连接"
        )
    credential_ref = _connection_value(connection, "credential_ref")
    if not isinstance(credential_ref, str) or not credential_ref.strip():
        raise ProjectConfigBindingError("模型连接未配置凭据")
    try:
        secrets = get_credential(credential_ref)
    except Exception as exc:
        raise ProjectConfigBindingError("模型连接凭据不可用") from exc
    api_key = _api_key_from_secrets(secrets)
    if not api_key:
        raise ProjectConfigBindingError("模型连接凭据缺少 API Key")
    model = str(_connection_value(connection, "model") or "").strip()
    if not model:
        raise ProjectConfigBindingError("模型连接未配置模型名称")
    endpoint = _connection_value(connection, "endpoint")
    public_config = _connection_value(connection, "public_config")
    return ResolvedProjectModelBinding(
        connection_id=connection_id.strip(),
        revision=revision,
        provider=str(_connection_value(connection, "provider") or "").strip(),
        model=model,
        endpoint=str(endpoint).strip() if endpoint is not None else None,
        api_key=api_key,
        public_config=(
            deepcopy(public_config)
            if isinstance(public_config, Mapping)
            else {}
        ),
    )


def _connection_value(connection: Any, name: str) -> Any:
    if isinstance(connection, Mapping):
        return connection.get(name)
    return getattr(connection, name, None)


def _api_key_from_secrets(value: Any) -> str:
    if not isinstance(value, Mapping):
        return ""
    for key in ("api_key", "apiKey", "key"):
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    string_values = [
        candidate.strip()
        for candidate in value.values()
        if isinstance(candidate, str) and candidate.strip()
    ]
    return string_values[0] if len(string_values) == 1 else ""
