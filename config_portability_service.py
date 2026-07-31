"""Portable global configuration export and import lifecycle."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import datetime
import os
import re
from typing import Any, Callable, Dict, List, Mapping, Optional
import uuid

from settings_service import (
    mask_sensitive_settings,
    preserve_masked_secrets,
)


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


def build_config_export_bundle(
    settings: Dict[str, Any],
    *,
    contains_secrets: bool,
) -> Dict[str, Any]:
    dependencies = _deps()
    return {
        "app": "PPT Visualization Studio",
        "type": "ppt_studio_config_bundle",
        "version": 2,
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


def import_full_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    dependencies = _deps()
    validate_config_references(payload)

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
    return {"success": True, "message": "配置已导入"}
