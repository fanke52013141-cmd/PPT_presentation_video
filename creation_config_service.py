"""Versioned, credential-free creation configuration packages.

This module owns the pure package lifecycle.  Its JSON store is intentionally
small and injected so callers can later use a SQLite-backed adapter without
changing the package API.  It does not import FastAPI, SQLAlchemy, or the
application composition root.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from threading import RLock
from typing import Any, Callable, Protocol
from uuid import uuid4
from functools import wraps
from account_context import get_current_account_id


STORE_VERSION = "creation_config_store_v1"
PAYLOAD_VERSION = "creation_config_v1"
MAX_PAYLOAD_BYTES = 512 * 1024
MAX_PAYLOAD_DEPTH = 16
MAX_PAYLOAD_ITEMS = 3_000
MAX_PACKAGE_NAME_LENGTH = 80
MAX_DESCRIPTION_LENGTH = 1_000
MAX_TAG_COUNT = 20
MAX_TAG_LENGTH = 40

_ALLOWED_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "prompts",
        "model_bindings",
        "step_contracts",
        "image_style",
        "tts",
        "subtitle",
        "subtitles",
        "automation",
        "digital_human",
        "mask",
    }
)
_PROMPT_MODULE_KEYS = frozenset(
    {
        "article_generation",
        "storyboard",
        "visualization",
        "image_generation",
        "ai_mask",
        "narration_annotation",
    }
)
_MODEL_BINDING_KEYS = frozenset(
    {
        "article_generation",
        "storyboard",
        "visualization",
        "image_generation",
        "ai_mask",
        "narration_annotation",
        "tts",
    }
)
_STEP_CONTRACT_KEYS = frozenset(
    {
        "article_generation",
        "storyboard",
        "visualization",
        "image_generation",
        "ai_mask",
        "narration_annotation",
        "tts",
        "output",
    }
)
_JSON_SCHEMA_TYPES = frozenset(
    {"object", "array", "string", "number", "integer", "boolean", "null"}
)
_SENSITIVE_KEY_PARTS = frozenset(
    {
        "apikey",
        "accesskey",
        "secret",
        "password",
        "passwd",
        "token",
        "authorization",
        "credential",
        "privatekey",
        "clientsecret",
    }
)
_DISALLOWED_CONNECTION_FIELDS = frozenset(
    {
        "provider",
        "endpoint",
        "baseurl",
        "model",
        "url",
        "host",
    }
)


class CreationConfigError(ValueError):
    """Base class for safe, user-visible configuration package errors."""


class CreationConfigNotFound(CreationConfigError):
    pass


class CreationConfigConflict(CreationConfigError):
    pass


class CreationConfigValidationError(CreationConfigError):
    pass


class CreationConfigStoreProtocol(Protocol):
    def read(self) -> dict[str, Any]: ...

    def write(self, value: dict[str, Any]) -> None: ...


class JsonCreationConfigStore:
    """A narrow JSON persistence adapter with atomic writes and process lock."""

    def __init__(
        self,
        path: Path | str,
        *,
        write_json_atomic: Callable[[Path | str, dict[str, Any]], None],
    ) -> None:
        self.path = Path(path)
        self._write_json_atomic = write_json_atomic
        self._lock = RLock()

    def read(self) -> dict[str, Any]:
        with self._lock:
            if not self.path.exists():
                return {"version": STORE_VERSION, "packages": {}}
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise CreationConfigError("创作配置存储文件无法读取") from exc
            if not isinstance(raw, dict) or not isinstance(raw.get("packages"), dict):
                raise CreationConfigError("创作配置存储文件格式不正确")
            return deepcopy(raw)

    def write(self, value: dict[str, Any]) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._write_json_atomic(self.path, deepcopy(value))


@dataclass(frozen=True)
class CreationConfigDependencies:
    store: CreationConfigStoreProtocol
    now: Callable[[], str]
    new_id: Callable[[], str]


_dependencies: CreationConfigDependencies | None = None
_config_lock = RLock()


def _synchronized(function: Callable[..., Any]) -> Callable[..., Any]:
    """Keep read/modify/write lifecycle operations atomic per process."""
    @wraps(function)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        with _config_lock:
            return function(*args, **kwargs)

    return wrapper


def configure_creation_config_dependencies(
    dependencies: CreationConfigDependencies,
) -> None:
    global _dependencies
    _dependencies = dependencies


def _deps() -> CreationConfigDependencies:
    if _dependencies is None:
        raise RuntimeError("Creation configuration dependencies have not been configured")
    return _dependencies


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_creation_config_id() -> str:
    return uuid4().hex


def _normalized_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def _key_is_sensitive(key: Any) -> bool:
    normalized = _normalized_key(key)
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _reject_sensitive_values(value: Any, *, path: str = "payload") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if _key_is_sensitive(key):
                raise CreationConfigValidationError(
                    f"{path}.{key} 包含敏感字段；配置包只能引用 connection_id 和 revision"
                )
            _reject_sensitive_values(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_sensitive_values(child, path=f"{path}[{index}]")


def redact_sensitive_payload(value: Any) -> Any:
    """Return a defensive, presentation-safe copy of an arbitrary payload."""
    if isinstance(value, dict):
        return {
            str(key): "__PPT_STUDIO_REDACTED__"
            if _key_is_sensitive(key)
            else redact_sensitive_payload(child)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive_payload(child) for child in value]
    return deepcopy(value)


def _validate_json_shape(value: Any, *, path: str = "payload") -> int:
    if value is None or isinstance(value, (str, bool, int, float)):
        return 1
    if isinstance(value, list):
        return 1 + sum(
            _validate_json_shape(child, path=f"{path}[{index}]")
            for index, child in enumerate(value)
        )
    if isinstance(value, dict):
        return 1 + sum(
            _validate_json_shape(child, path=f"{path}.{key}")
            for key, child in value.items()
        )
    raise CreationConfigValidationError(f"{path} 必须是 JSON 可序列化的值")


def _max_depth(value: Any) -> int:
    if not isinstance(value, (dict, list)):
        return 0
    children = value.values() if isinstance(value, dict) else value
    return 1 + max((_max_depth(child) for child in children), default=0)


def _require_connection_reference(value: Any, *, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CreationConfigValidationError(f"{path} 必须是连接引用对象")
    normalized_keys = {_normalized_key(key): key for key in value}
    extras = set(normalized_keys) - {"connectionid", "revision"}
    if extras:
        raise CreationConfigValidationError(
            f"{path} 只能保存 connection_id 和 revision"
        )
    connection_id = value.get("connection_id")
    revision = value.get("revision")
    if not isinstance(connection_id, str) or not connection_id.strip():
        raise CreationConfigValidationError(f"{path}.connection_id 不能为空")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise CreationConfigValidationError(f"{path}.revision 必须是正整数")
    return {"connection_id": connection_id.strip(), "revision": revision}


def _validate_connection_fields(value: Any, *, path: str = "payload") -> None:
    """Reject inline provider settings anywhere in a connection reference."""
    if not isinstance(value, dict):
        return
    for key, child in value.items():
        normalized = _normalized_key(key)
        if normalized in _DISALLOWED_CONNECTION_FIELDS and path.endswith("model_bindings"):
            raise CreationConfigValidationError(
                f"{path}.{key} 不能保存连接详情；请使用 connection_id 和 revision"
            )
        if isinstance(child, dict):
            _validate_connection_fields(child, path=f"{path}.{key}")
        elif isinstance(child, list):
            for index, item in enumerate(child):
                _validate_connection_fields(item, path=f"{path}.{key}[{index}]")


def _validate_json_schema(schema: Any, *, path: str) -> None:
    """Validate the supported, transport-safe JSON Schema subset.

    Contracts are consumed by the prompt editor and downstream pipeline.  A
    deliberately small subset gives users useful structural guarantees without
    accepting executable references, remote schema URLs, or unbounded syntax.
    """
    if not isinstance(schema, dict):
        raise CreationConfigValidationError(f"{path}.output_schema 必须是对象")
    schema_type = schema.get("type")
    if schema_type not in _JSON_SCHEMA_TYPES:
        raise CreationConfigValidationError(
            f"{path}.output_schema.type 必须是受支持的 JSON Schema 类型"
        )
    if schema_type == "object":
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            raise CreationConfigValidationError(
                f"{path}.output_schema.properties 必须是对象"
            )
        required = schema.get("required", [])
        if not isinstance(required, list) or not all(
            isinstance(item, str) and item in properties for item in required
        ):
            raise CreationConfigValidationError(
                f"{path}.output_schema.required 必须引用 properties 中的字段"
            )
        for name, child in properties.items():
            if not isinstance(name, str) or not name:
                raise CreationConfigValidationError(
                    f"{path}.output_schema.properties 的字段名不能为空"
                )
            _validate_json_schema(child, path=f"{path}.output_schema.properties.{name}")
    if schema_type == "array" and "items" in schema:
        _validate_json_schema(schema["items"], path=f"{path}.output_schema.items")
    enum = schema.get("enum")
    if enum is not None and (not isinstance(enum, list) or not enum):
        raise CreationConfigValidationError(
            f"{path}.output_schema.enum 必须是非空数组"
        )


def _validate_step_contracts(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CreationConfigValidationError("step_contracts 必须是对象")
    unknown = sorted(set(value) - _STEP_CONTRACT_KEYS)
    if unknown:
        raise CreationConfigValidationError(
            f"step_contracts 包含不支持的步骤: {', '.join(unknown)}"
        )
    normalized: dict[str, Any] = {}
    for step, contract in value.items():
        if not isinstance(contract, dict):
            raise CreationConfigValidationError(f"step_contracts.{step} 必须是对象")
        extras = sorted(set(contract) - {"input_template", "output_schema"})
        if extras:
            raise CreationConfigValidationError(
                f"step_contracts.{step} 包含不支持的字段: {', '.join(extras)}"
            )
        item = deepcopy(contract)
        if "input_template" in item and not isinstance(item["input_template"], (dict, list)):
            raise CreationConfigValidationError(
                f"step_contracts.{step}.input_template 必须是对象或数组"
            )
        if "output_schema" in item:
            _validate_json_schema(item["output_schema"], path=f"step_contracts.{step}")
        if not item:
            continue
        normalized[step] = item
    return normalized


def _validate_image_style(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CreationConfigValidationError("image_style 必须是对象")
    allowed = {
        "template_id", "package_id", "version", "style_version",
        "reference_policy", "reference_mode", "minimum_reference_images",
    }
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise CreationConfigValidationError(
            f"image_style 包含不支持的字段: {', '.join(unknown)}"
        )
    template_id = str(value.get("template_id") or value.get("package_id") or "").strip()
    if not template_id:
        raise CreationConfigValidationError("image_style.template_id 不能为空")
    if len(template_id) > 120 or any(char in template_id for char in ("/", "\\", "\x00")):
        raise CreationConfigValidationError("image_style.template_id 无效")
    raw_version = value.get("version", value.get("style_version", 1))
    if not isinstance(raw_version, int) or isinstance(raw_version, bool) or raw_version < 1:
        raise CreationConfigValidationError("image_style.version 必须是正整数")
    policy = str(
        value.get("reference_policy") or value.get("reference_mode") or "preferred"
    ).strip().lower()
    if policy not in {"required", "preferred", "text_only"}:
        raise CreationConfigValidationError(
            "image_style.reference_policy 必须是 required、preferred 或 text_only"
        )
    minimum = value.get("minimum_reference_images", 1)
    if not isinstance(minimum, int) or isinstance(minimum, bool) or not 0 <= minimum <= 3:
        raise CreationConfigValidationError(
            "image_style.minimum_reference_images 必须是 0 到 3 的整数"
        )
    if policy == "required" and minimum < 1:
        raise CreationConfigValidationError("required 模式至少需要 1 张参考图")
    if policy == "text_only":
        minimum = 0
    return {
        "template_id": template_id,
        "version": raw_version,
        "reference_policy": policy,
        "minimum_reference_images": minimum,
    }


def validate_step_output(contract: Any, output: Any, *, path: str = "output") -> None:
    """Validate a model response against the stored schema subset.

    Pipeline modules can call this before handing a model result to their next
    stage.  No contract means legacy projects retain their prior behavior.
    """
    if not isinstance(contract, dict) or not isinstance(contract.get("output_schema"), dict):
        return
    schema = contract["output_schema"]
    expected = schema["type"]
    type_ok = {
        "object": isinstance(output, dict),
        "array": isinstance(output, list),
        "string": isinstance(output, str),
        "number": isinstance(output, (int, float)) and not isinstance(output, bool),
        "integer": isinstance(output, int) and not isinstance(output, bool),
        "boolean": isinstance(output, bool),
        "null": output is None,
    }[expected]
    if not type_ok:
        raise CreationConfigValidationError(f"{path} 必须符合 {expected} 输出契约")
    if "enum" in schema and output not in schema["enum"]:
        raise CreationConfigValidationError(f"{path} 不在输出契约允许的枚举值中")
    if expected == "object":
        for name in schema.get("required", []):
            if name not in output:
                raise CreationConfigValidationError(f"{path} 缺少输出契约要求的字段: {name}")
        for name, child in schema.get("properties", {}).items():
            if name in output:
                validate_step_output({"output_schema": child}, output[name], path=f"{path}.{name}")
    if expected == "array" and "items" in schema:
        for index, item in enumerate(output):
            validate_step_output({"output_schema": schema["items"]}, item, path=f"{path}[{index}]")


def validate_payload(payload: Any) -> dict[str, Any]:
    """Normalize the supported package payload and reject credentials early."""
    if not isinstance(payload, dict):
        raise CreationConfigValidationError("payload 必须是对象")
    _reject_sensitive_values(payload)
    item_count = _validate_json_shape(payload)
    if item_count > MAX_PAYLOAD_ITEMS:
        raise CreationConfigValidationError("payload 项目过多")
    if _max_depth(payload) > MAX_PAYLOAD_DEPTH:
        raise CreationConfigValidationError("payload 嵌套层级过深")
    try:
        serialized = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise CreationConfigValidationError("payload 必须是有效 JSON") from exc
    if len(serialized.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise CreationConfigValidationError("payload 超过 512KB 限制")

    unknown = sorted(set(payload) - _ALLOWED_TOP_LEVEL_KEYS)
    if unknown:
        raise CreationConfigValidationError(
            f"payload 包含不支持的配置模块: {', '.join(unknown)}"
        )
    normalized = deepcopy(payload)
    version = normalized.get("schema_version", PAYLOAD_VERSION)
    if version != PAYLOAD_VERSION:
        raise CreationConfigValidationError(
            f"schema_version 必须是 {PAYLOAD_VERSION}"
        )
    normalized["schema_version"] = PAYLOAD_VERSION

    # Accept the natural plural spelling at the HTTP boundary, but persist one
    # canonical key so package hashes and project snapshots remain stable.
    if "subtitles" in normalized:
        if "subtitle" in normalized:
            raise CreationConfigValidationError(
                "payload 不能同时包含 subtitle 和 subtitles"
            )
        normalized["subtitle"] = normalized.pop("subtitles")

    prompts = normalized.get("prompts")
    if prompts is not None:
        if not isinstance(prompts, dict):
            raise CreationConfigValidationError("prompts 必须是对象")
        unknown_prompts = sorted(set(prompts) - _PROMPT_MODULE_KEYS)
        if unknown_prompts:
            raise CreationConfigValidationError(
                f"prompts 包含不支持的模块: {', '.join(unknown_prompts)}"
            )

    step_contracts = normalized.get("step_contracts")
    if step_contracts is not None:
        normalized["step_contracts"] = _validate_step_contracts(step_contracts)

    bindings = normalized.get("model_bindings")
    if bindings is not None:
        if not isinstance(bindings, dict):
            raise CreationConfigValidationError("model_bindings 必须是对象")
        unknown_bindings = sorted(set(bindings) - _MODEL_BINDING_KEYS)
        if unknown_bindings:
            raise CreationConfigValidationError(
                f"model_bindings 包含不支持的模块: {', '.join(unknown_bindings)}"
            )
        normalized["model_bindings"] = {
            key: _require_connection_reference(value, path=f"model_bindings.{key}")
            for key, value in bindings.items()
        }
        _validate_connection_fields(bindings, path="model_bindings")

    image_style = normalized.get("image_style")
    if image_style is not None:
        normalized["image_style"] = _validate_image_style(image_style)

    tts = normalized.get("tts")
    if tts is not None:
        if not isinstance(tts, dict):
            raise CreationConfigValidationError("tts 必须是对象")
        if "connection" in tts:
            normalized["tts"] = deepcopy(tts)
            normalized["tts"]["connection"] = _require_connection_reference(
                tts["connection"], path="tts.connection"
            )

    subtitle = normalized.get("subtitle")
    if subtitle is not None:
        if not isinstance(subtitle, dict):
            raise CreationConfigValidationError("subtitle 必须是对象")
        if "enabled" in subtitle and not isinstance(subtitle["enabled"], bool):
            raise CreationConfigValidationError("subtitle.enabled 必须是布尔值")

    mask = normalized.get("mask")
    if mask is not None:
        if not isinstance(mask, dict):
            raise CreationConfigValidationError("mask 必须是对象")
        if "enabled" in mask and not isinstance(mask["enabled"], bool):
            raise CreationConfigValidationError("mask.enabled 必须是布尔值")

    return normalized


def content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def deep_merge(base: Any, override: Any) -> Any:
    """Merge mappings recursively while preserving explicit false/null values."""
    if not isinstance(base, dict) or not isinstance(override, dict):
        return deepcopy(override)
    merged = deepcopy(base)
    for key, value in override.items():
        merged[key] = deep_merge(merged[key], value) if key in merged else deepcopy(value)
    return merged


def _normalized_name(value: Any) -> str:
    name = re.sub(r"\s+", " ", str(value or "").strip())
    if not name:
        raise CreationConfigValidationError("创作配置名称不能为空")
    if len(name) > MAX_PACKAGE_NAME_LENGTH:
        raise CreationConfigValidationError(
            f"创作配置名称不能超过 {MAX_PACKAGE_NAME_LENGTH} 个字符"
        )
    return name


def _normalized_description(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) > MAX_DESCRIPTION_LENGTH:
        raise CreationConfigValidationError(
            f"创作配置说明不能超过 {MAX_DESCRIPTION_LENGTH} 个字符"
        )
    return text


def _normalized_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise CreationConfigValidationError("tags 必须是数组")
    if len(value) > MAX_TAG_COUNT:
        raise CreationConfigValidationError(f"tags 不能超过 {MAX_TAG_COUNT} 个")
    tags: list[str] = []
    for raw in value:
        tag = re.sub(r"\s+", " ", str(raw or "").strip())
        if not tag:
            continue
        if len(tag) > MAX_TAG_LENGTH:
            raise CreationConfigValidationError(
                f"单个标签不能超过 {MAX_TAG_LENGTH} 个字符"
            )
        if tag not in tags:
            tags.append(tag)
    return tags


def _store() -> dict[str, Any]:
    store = _deps().store.read()
    store.setdefault("version", STORE_VERSION)
    store.setdefault("packages", {})
    if store["version"] != STORE_VERSION or not isinstance(store["packages"], dict):
        raise CreationConfigError("创作配置存储版本不受支持")
    return store


def _package_or_raise(store: dict[str, Any], package_id: str) -> dict[str, Any]:
    package = store["packages"].get(package_id)
    if not isinstance(package, dict) or (
        str(package.get("account_id") or "default") != get_current_account_id()
    ):
        raise CreationConfigNotFound("未找到创作配置包")
    return package


def _version_or_raise(package: dict[str, Any], version: int | None) -> dict[str, Any]:
    requested = package.get("latest_version") if version is None else version
    if not isinstance(requested, int) or requested < 1:
        raise CreationConfigError("创作配置版本数据不正确")
    record = (package.get("versions") or {}).get(str(requested))
    if not isinstance(record, dict):
        raise CreationConfigNotFound("未找到创作配置版本")
    return record


def _public_version(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": record["version"],
        "created_at": record["created_at"],
        "content_hash": record["content_hash"],
        "payload": redact_sensitive_payload(record["payload"]),
    }


def _public_package(package: dict[str, Any], *, include_payload: bool = False) -> dict[str, Any]:
    result = {
        "id": package["id"],
        "name": package["name"],
        "description": package["description"],
        "tags": deepcopy(package["tags"]),
        "archived": bool(package.get("archived")),
        "created_at": package["created_at"],
        "updated_at": package["updated_at"],
        "latest_version": package["latest_version"],
        "account_id": str(package.get("account_id") or "default"),
    }
    latest = _version_or_raise(package, None)
    result["content_hash"] = latest["content_hash"]
    if include_payload:
        result["versions"] = [
            _public_version(record)
            for _, record in sorted(
                package["versions"].items(), key=lambda item: int(item[0])
            )
        ]
    return result


@_synchronized
def list_creation_configs(*, include_archived: bool = False) -> list[dict[str, Any]]:
    store = _store()
    packages = [
        _public_package(package)
        for package in store["packages"].values()
        if str(package.get("account_id") or "default") == get_current_account_id()
        and (include_archived or not package.get("archived"))
    ]
    return sorted(packages, key=lambda item: (item["archived"], item["name"].casefold()))


@_synchronized
def get_creation_config(package_id: str) -> dict[str, Any]:
    return _public_package(_package_or_raise(_store(), package_id), include_payload=True)


@_synchronized
def create_creation_config(
    *,
    name: Any,
    description: Any = "",
    tags: Any = None,
    payload: Any,
) -> dict[str, Any]:
    normalized_payload = validate_payload(payload)
    dependencies = _deps()
    store = _store()
    package_id = dependencies.new_id()
    timestamp = dependencies.now()
    package = {
        "id": package_id,
        "name": _normalized_name(name),
        "description": _normalized_description(description),
        "tags": _normalized_tags(tags),
        "archived": False,
        "created_at": timestamp,
        "updated_at": timestamp,
        "latest_version": 1,
        "versions": {
            "1": {
                "version": 1,
                "created_at": timestamp,
                "content_hash": content_hash(normalized_payload),
                "payload": normalized_payload,
            }
        },
        "account_id": get_current_account_id(),
    }
    if package_id in store["packages"]:
        raise CreationConfigConflict("创作配置 ID 冲突，请重试")
    store["packages"][package_id] = package
    dependencies.store.write(store)
    return _public_package(package, include_payload=True)


@_synchronized
def create_creation_config_version(package_id: str, *, payload: Any) -> dict[str, Any]:
    normalized_payload = validate_payload(payload)
    dependencies = _deps()
    store = _store()
    package = _package_or_raise(store, package_id)
    if package.get("archived"):
        raise CreationConfigConflict("已归档的创作配置不能新增版本")
    next_version = int(package["latest_version"]) + 1
    timestamp = dependencies.now()
    package["versions"][str(next_version)] = {
        "version": next_version,
        "created_at": timestamp,
        "content_hash": content_hash(normalized_payload),
        "payload": normalized_payload,
    }
    package["latest_version"] = next_version
    package["updated_at"] = timestamp
    dependencies.store.write(store)
    return _public_version(package["versions"][str(next_version)])


@_synchronized
def copy_creation_config(
    package_id: str,
    *,
    name: Any = None,
    description: Any = None,
    tags: Any = None,
    version: int | None = None,
) -> dict[str, Any]:
    source = _package_or_raise(_store(), package_id)
    source_version = _version_or_raise(source, version)
    return create_creation_config(
        name=name if name is not None else f"{source['name']} 副本",
        description=source["description"] if description is None else description,
        tags=source["tags"] if tags is None else tags,
        payload=deepcopy(source_version["payload"]),
    )


@_synchronized
def archive_creation_config(package_id: str, *, archived: bool = True) -> dict[str, Any]:
    dependencies = _deps()
    store = _store()
    package = _package_or_raise(store, package_id)
    package["archived"] = bool(archived)
    package["updated_at"] = dependencies.now()
    dependencies.store.write(store)
    return _public_package(package)


@_synchronized
def get_creation_config_version(package_id: str, version: int | None = None) -> dict[str, Any]:
    package = _package_or_raise(_store(), package_id)
    return _public_version(_version_or_raise(package, version))


@_synchronized
def resolve_creation_config(
    package_id: str,
    *,
    version: int | None = None,
    overrides: Any = None,
) -> dict[str, Any]:
    package = _package_or_raise(_store(), package_id)
    if package.get("archived"):
        raise CreationConfigConflict("已归档的创作配置不能用于新项目")
    source = _version_or_raise(package, version)
    if overrides is None:
        overrides = {}
    if not isinstance(overrides, dict):
        raise CreationConfigValidationError("overrides 必须是对象")
    _reject_sensitive_values(overrides, path="overrides")
    overrides = deepcopy(overrides)
    if "subtitles" in overrides:
        if "subtitle" in overrides:
            raise CreationConfigValidationError(
                "overrides 不能同时包含 subtitle 和 subtitles"
            )
        overrides["subtitle"] = overrides.pop("subtitles")
    resolved = validate_payload(deep_merge(source["payload"], overrides))
    return {
        "package_id": package["id"],
        "package_name": package["name"],
        "version": source["version"],
        "source_content_hash": source["content_hash"],
        "content_hash": content_hash(resolved),
        "payload": redact_sensitive_payload(resolved),
    }


@_synchronized
def import_creation_config(
    *,
    name: Any,
    description: Any = "",
    tags: Any = None,
    payload: Any,
) -> dict[str, Any]:
    """Import is intentionally a normal create, including secret rejection."""
    return create_creation_config(
        name=name,
        description=description,
        tags=tags,
        payload=payload,
    )
