"""Persistence helpers for named Step 3 image-style templates."""

from __future__ import annotations

from datetime import datetime
import base64
import binascii
import hashlib
from io import BytesIO
import json
from pathlib import Path
import shutil
import time
from typing import Any
import uuid

import yaml

from account_context import DEFAULT_ACCOUNT_ID, get_current_account_id


STATE_FILENAME = "step3_image_style.json"
BUILTIN_HANDDRAWN_TEMPLATE_ID = "handdrawn"
BUILTIN_HANDDRAWN_TEMPLATE_NAME = "手绘风格"
TEMPLATES_INDEX_VERSION = "step3_image_style_templates_v1"
MAX_PORTABLE_REFERENCE_IMAGES = 3


def _run_dir(project: Any) -> Path:
    return Path(str(project.run_dir)).resolve()


def _step3_state_path(project: Any) -> Path:
    return _run_dir(project) / "planning" / STATE_FILENAME


def _read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return fallback
    return value if isinstance(value, dict) else fallback


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _save_step3_style_state(
    project: Any,
    style: dict[str, Any],
    source: str,
) -> dict[str, Any]:
    existing = _read_json(_step3_state_path(project), {})
    state = {
        "version": "step3_image_style_v1",
        "source": source,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "image_style_profile": style if isinstance(style, dict) else {},
        "reference_images": (
            existing.get("reference_images", [])
            if isinstance(existing.get("reference_images"), list)
            else []
        ),
        "note": "Step 3 owns image style. Project creation does not set image style.",
    }
    _write_json(_step3_state_path(project), state)
    return state


def _rewrite_reference_urls(value: Any, project_id: str) -> Any:
    if isinstance(value, dict):
        result = {
            key: _rewrite_reference_urls(item, project_id)
            for key, item in value.items()
        }
        if "index" in result and isinstance(result.get("url"), str):
            try:
                index = int(result["index"])
                result["url"] = (
                    f"/api/projects/{project_id}/steps/3/image-style/"
                    f"reference-images/{index}?t={int(time.time())}"
                )
            except Exception:
                pass
        return result
    if isinstance(value, list):
        return [_rewrite_reference_urls(item, project_id) for item in value]
    return value


# ---------------------------------------------------------------------------
# 命名图片风格模板库（审查 M-06：业务逻辑自 project_style_routes 迁入）
#
# 所有函数显式接收 ProjectStyleDependencies（context）；HTTP 语义经
# context.http_exception 抛出，本模块不 import fastapi。
# ---------------------------------------------------------------------------


def _safe_account_segment(account_id: str) -> str:
    value = str(account_id or DEFAULT_ACCOUNT_ID).strip() or DEFAULT_ACCOUNT_ID
    if all(char.isalnum() or char in {"-", "_"} for char in value):
        return value
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def templates_root(context: Any) -> Path:
    """Return the current account's style library root.

    The default account keeps the historical directory so existing templates
    continue to work. Every additional account gets an isolated library.
    """
    root = Path(context.data_dir) / "step3_image_style_templates"
    account_id = get_current_account_id()
    if account_id == DEFAULT_ACCOUNT_ID:
        return root
    return root / "accounts" / _safe_account_segment(account_id)


def templates_index(context: Any) -> Path:
    return templates_root(context) / "index.json"


def builtin_sources(context: Any) -> tuple[Path, list[Path]]:
    style_path = Path(context.handdrawn_style_tokens_path)
    reference_root = Path(context.repo_root) / "references" / "style_reference"
    paths = [
        reference_root / "PPT模板.png",
        reference_root / "PPT示例.png",
    ]
    return style_path, [path for path in paths if path.is_file()]


def builtin_style(context: Any) -> dict[str, Any]:
    style_path, _ = builtin_sources(context)
    if not style_path.exists():
        raise context.http_exception(
            status_code=404, detail="内置手绘风格配置缺失"
        )
    try:
        style_tokens = yaml.safe_load(
            style_path.read_text(encoding="utf-8-sig")
        ) or {}
    except Exception as exc:
        raise context.http_exception(
            status_code=500,
            detail="内置手绘风格配置损坏",
        ) from exc
    if not isinstance(style_tokens, dict):
        raise context.http_exception(
            status_code=500, detail="内置手绘风格配置损坏"
        )
    system_content = context.build_image_style_prompt(style_tokens)
    return {
        "source": "built_in_template",
        "template_id": BUILTIN_HANDDRAWN_TEMPLATE_ID,
        "style_name": BUILTIN_HANDDRAWN_TEMPLATE_NAME,
        "style_summary": "温暖极简的手绘线稿科普风格，纯白画布、清晰分组，适合演讲内容可视化与 Mask 显现。",
        "system_content": system_content,
        "sample_reference_image_prompts": [system_content],
        "reference_image_count_target": 3,
        "style_tokens": style_tokens,
    }


def read_templates(
    context: Any,
    *,
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    value = _read_json(templates_index(context), {"templates": []})
    items = value.get("templates", []) if isinstance(value, dict) else []
    normalized = [item for item in items if isinstance(item, dict)]
    if include_archived:
        return normalized
    return [item for item in normalized if not item.get("archived")]


def write_templates(context: Any, items: list[dict[str, Any]]) -> None:
    _write_json(
        templates_index(context),
        {"version": TEMPLATES_INDEX_VERSION, "templates": items},
    )


def template_dir_or_404(context: Any, template_id: str) -> Path:
    if len(template_id) != 12 or any(
        char not in "0123456789abcdef" for char in template_id
    ):
        raise context.http_exception(
            status_code=404, detail="图片风格模板不存在"
        )
    root = templates_root(context).resolve()
    path = (root / template_id).resolve()
    if path.parent != root or not path.exists():
        raise context.http_exception(
            status_code=404, detail="图片风格模板不存在"
        )
    return path


def template_detail(context: Any, template_id: str) -> dict[str, Any]:
    if template_id == BUILTIN_HANDDRAWN_TEMPLATE_ID:
        _, paths = builtin_sources(context)
        images = [
            {
                "index": index,
                "filename": path.name,
                "source": "built_in_template",
                "url": (
                    f"/api/image-style/project-templates/{template_id}"
                    f"/reference-images/{index}?t={int(path.stat().st_mtime)}"
                ),
            }
            for index, path in enumerate(paths[:3], start=1)
        ]
        item = {
            "id": template_id,
            "name": BUILTIN_HANDDRAWN_TEMPLATE_NAME,
            "built_in": True,
            "version": 1,
            "account_id": get_current_account_id(),
            "content_hash": hashlib.sha256(
                json.dumps(
                    {
                        "style": builtin_style(context),
                        "reference_sha256s": [
                            hashlib.sha256(path.read_bytes()).hexdigest()
                            for path in paths[:3]
                        ],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
            "reference_count": len(images),
        }
        return {
            "success": True,
            "template": item,
            "style": builtin_style(context),
            "references": {
                "scope": "step3_image_style_template",
                "style_name": item["name"],
                "images": images,
            },
        }
    source = template_dir_or_404(context, template_id)
    style = _read_json(source / "style.json", {})
    manifest = _read_json(source / "references.json", {})
    normalized = []
    for item in (manifest.get("images", []) if isinstance(manifest, dict) else [])[:3]:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index"))
        except Exception:
            continue
        filename = Path(str(item.get("filename") or f"style_reference_{index:02d}.png")).name
        path = (source / "references" / filename).resolve()
        if path.parent != (source / "references").resolve() or not path.is_file():
            continue
        normalized.append({
            **item,
            "index": index,
            "filename": filename,
            "url": (
                f"/api/image-style/project-templates/{template_id}"
                f"/reference-images/{index}?t={int(path.stat().st_mtime)}"
            ),
        })
    summary = next(
        (
            item
            for item in read_templates(context, include_archived=True)
            if str(item.get("id") or "") == template_id
        ),
        {},
    )
    return {
        "success": True,
        "template": summary,
        "style": style if isinstance(style, dict) else {},
        "references": {
            "scope": "step3_image_style_template",
            "style_name": str(
                (style or {}).get("style_name") or summary.get("name") or ""
            ),
            "images": normalized,
        },
    }


def save_named_template(
    context: Any,
    project: Any,
    name: str,
) -> dict[str, Any]:
    """把项目当前的 Step 3 风格 + 参考图快照保存为命名模板。"""
    name = str(name or "").strip()
    if not name:
        raise context.http_exception(status_code=400, detail="模板名称不能为空")
    if len(name) > 120:
        raise context.http_exception(
            status_code=400, detail="模板名称不能超过 120 个字符"
        )
    from project_style_reference_store import (
        manifest_path,
        references_dir,
    )

    state = _read_json(_step3_state_path(project), {})
    style = (
        state.get("image_style_profile")
        if isinstance(state.get("image_style_profile"), dict)
        else {}
    )
    if not str(style.get("system_content") or "").strip():
        raise context.http_exception(
            status_code=400, detail="请先保存图片生成 System Content"
        )
    manifest = _read_json(manifest_path(project), {})
    if not (manifest.get("images", []) if isinstance(manifest, dict) else []):
        raise context.http_exception(
            status_code=400, detail="请先生成或上传至少 1 张效果预览"
        )
    items = read_templates(context)
    if any(
        str(item.get("name") or "").strip().casefold() == name.casefold()
        for item in items
    ):
        raise context.http_exception(
            status_code=400, detail="模板名称已存在，请换一个名称"
        )
    template_id = uuid.uuid4().hex[:12]
    target = templates_root(context) / template_id
    target.mkdir(parents=True, exist_ok=False)
    _write_json(target / "style.json", style)
    _write_json(target / "references.json", manifest)
    source_refs = references_dir(project)
    if source_refs.exists():
        shutil.copytree(source_refs, target / "references", dirs_exist_ok=True)
    content_payload = {
        "style": style,
        "references": manifest,
    }
    item = {
        "id": template_id,
        "name": name,
        "version": 1,
        "account_id": get_current_account_id(),
        "content_hash": hashlib.sha256(
            json.dumps(
                content_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "reference_count": len(manifest.get("images", [])),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    items.append(item)
    write_templates(context, items)
    return {"template": item, "templates": items}


def apply_named_template(
    context: Any,
    project: Any,
    template_id: str,
) -> dict[str, Any]:
    """把模板风格与参考图套用到项目，返回 (style, manifest)。"""
    from project_style_reference_store import (
        references_dir,
        write_normalized_manifest,
    )

    built_in = template_id == BUILTIN_HANDDRAWN_TEMPLATE_ID
    source = None if built_in else template_dir_or_404(context, template_id)
    style = (
        builtin_style(context)
        if built_in
        else _read_json(source / "style.json", {})
    )
    if not style:
        raise context.http_exception(
            status_code=400, detail="图片风格模板内容损坏"
        )
    _save_step3_style_state(
        project,
        style,
        "built_in_template" if built_in else "named_template",
    )
    target_refs = references_dir(project)
    if target_refs.exists():
        shutil.rmtree(target_refs)
    if built_in:
        _, source_images = builtin_sources(context)
        target_refs.mkdir(parents=True, exist_ok=True)
        images = []
        for index, source_image in enumerate(source_images[:3], start=1):
            filename = f"style_reference_{index:02d}.png"
            context.process_and_save_image(
                source_image.read_bytes(),
                str(target_refs / filename),
            )
            images.append({
                "index": index,
                "filename": filename,
                "source": "built_in_template",
            })
        manifest = {
            "version": "step3_style_references_v1",
            "scope": "step3_image_style",
            "style_name": BUILTIN_HANDDRAWN_TEMPLATE_NAME,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "images": images,
        }
    else:
        source_refs = source / "references"
        if source_refs.exists():
            shutil.copytree(source_refs, target_refs)
        manifest = _read_json(source / "references.json", {})
    write_normalized_manifest(
        project,
        manifest if isinstance(manifest, dict) else {},
    )
    return {"style": style, "manifest": manifest if isinstance(manifest, dict) else {}}


def delete_named_template(context: Any, template_id: str) -> list[dict[str, Any]]:
    if template_id == BUILTIN_HANDDRAWN_TEMPLATE_ID:
        raise context.http_exception(
            status_code=400, detail="内置手绘风格不能删除"
        )
    template_dir_or_404(context, template_id)
    items = read_templates(context, include_archived=True)
    matched = False
    for item in items:
        if str(item.get("id") or "") != template_id:
            continue
        item["archived"] = True
        item["archived_at"] = datetime.now().isoformat(timespec="seconds")
        matched = True
        break
    if not matched:
        raise context.http_exception(status_code=404, detail="图片风格模板不存在")
    write_templates(context, items)
    return [item for item in items if not item.get("archived")]


def export_portable_templates(context: Any) -> dict[str, Any]:
    """Export account-owned reusable styles, including their generation refs."""
    exported: list[dict[str, Any]] = []
    for summary in read_templates(context, include_archived=True):
        template_id = str(summary.get("id") or "")
        if len(template_id) != 12:
            continue
        source = template_dir_or_404(context, template_id)
        style = _read_json(source / "style.json", {})
        manifest = _read_json(source / "references.json", {})
        images: list[dict[str, Any]] = []
        for item in (
            manifest.get("images", []) if isinstance(manifest, dict) else []
        )[:MAX_PORTABLE_REFERENCE_IMAGES]:
            if not isinstance(item, dict):
                continue
            try:
                index = int(item.get("index"))
            except (TypeError, ValueError):
                continue
            filename = Path(
                str(item.get("filename") or f"style_reference_{index:02d}.png")
            ).name
            image_path = (source / "references" / filename).resolve()
            if (
                image_path.parent != (source / "references").resolve()
                or not image_path.is_file()
            ):
                continue
            images.append({
                "index": index,
                "filename": filename,
                "source": str(item.get("source") or "portable_config"),
                "mime": "image/png",
                "data": base64.b64encode(image_path.read_bytes()).decode("ascii"),
            })
        exported.append({
            "id": template_id,
            "name": str(summary.get("name") or ""),
            "version": int(summary.get("version") or 1),
            "content_hash": str(summary.get("content_hash") or ""),
            "created_at": str(summary.get("created_at") or ""),
            "archived": bool(summary.get("archived")),
            "style": style if isinstance(style, dict) else {},
            "references": {
                "version": str(
                    (manifest or {}).get("version")
                    or "step3_style_references_v1"
                ),
                "scope": "step3_image_style",
                "style_name": str(
                    (manifest or {}).get("style_name")
                    or summary.get("name")
                    or ""
                ),
                "images": images,
            },
        })
    return {
        "version": TEMPLATES_INDEX_VERSION,
        "templates": exported,
    }


def _decode_portable_reference(context: Any, item: Any) -> bytes:
    if not isinstance(item, dict):
        raise ValueError("图片风格参考图格式无效")
    try:
        decoded = base64.b64decode(str(item.get("data") or ""), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("图片风格参考图 Base64 数据无效") from exc
    if not decoded:
        raise ValueError("图片风格参考图内容为空")
    try:
        image = context.image_class.open(BytesIO(decoded))
        image.verify()
        image.close()
    except Exception as exc:
        raise ValueError("图片风格参考图不是有效图片") from exc
    return decoded


def normalize_portable_templates(context: Any, value: Any) -> list[dict[str, Any]]:
    if value in (None, {}):
        return []
    if not isinstance(value, dict):
        raise ValueError("图片风格资源包格式无效")
    templates = value.get("templates")
    if templates is None:
        return []
    if not isinstance(templates, list):
        raise ValueError("图片风格资源列表格式无效")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in templates:
        if not isinstance(item, dict):
            raise ValueError("图片风格资源格式无效")
        template_id = str(item.get("id") or "").strip()
        if (
            len(template_id) != 12
            or any(char not in "0123456789abcdef" for char in template_id)
            or template_id in seen
        ):
            raise ValueError("图片风格资源 ID 无效或重复")
        seen.add(template_id)
        name = str(item.get("name") or "").strip()
        style = item.get("style")
        if not name or not isinstance(style, dict) or not style:
            raise ValueError("图片风格资源缺少名称或提示词")
        references = item.get("references")
        references = references if isinstance(references, dict) else {}
        raw_images = references.get("images", [])
        if not isinstance(raw_images, list):
            raise ValueError("图片风格参考图列表格式无效")
        if len(raw_images) > MAX_PORTABLE_REFERENCE_IMAGES:
            raise ValueError("每套图片风格最多携带 3 张参考图")
        images: list[dict[str, Any]] = []
        for position, image_item in enumerate(raw_images, start=1):
            decoded = _decode_portable_reference(context, image_item)
            try:
                index = int(image_item.get("index") or position)
            except (TypeError, ValueError):
                index = position
            images.append({
                "index": max(1, index),
                "filename": f"style_reference_{position:02d}.png",
                "source": str(image_item.get("source") or "portable_config"),
                "bytes": decoded,
            })
        try:
            version = int(item.get("version") or 1)
        except (TypeError, ValueError):
            version = 1
        normalized.append({
            "id": template_id,
            "name": name[:120],
            "version": max(1, version),
            "content_hash": str(item.get("content_hash") or ""),
            "created_at": str(item.get("created_at") or ""),
            "archived": bool(item.get("archived")),
            "style": style,
            "reference_version": str(
                references.get("version") or "step3_style_references_v1"
            ),
            "style_name": str(references.get("style_name") or name),
            "images": images,
        })
    return normalized


def validate_portable_templates(context: Any, value: Any) -> None:
    normalize_portable_templates(context, value)


def import_portable_templates(context: Any, value: Any) -> list[dict[str, Any]]:
    """Merge portable styles into the current account library, preserving IDs."""
    normalized = normalize_portable_templates(context, value)
    if not normalized:
        return read_templates(context)
    root = templates_root(context)
    root.mkdir(parents=True, exist_ok=True)
    staging = root / f".import-{uuid.uuid4().hex}"
    staging.mkdir(parents=False, exist_ok=False)
    try:
        imported_summaries: list[dict[str, Any]] = []
        for item in normalized:
            target = staging / item["id"]
            references = target / "references"
            references.mkdir(parents=True, exist_ok=False)
            _write_json(target / "style.json", item["style"])
            manifest_images: list[dict[str, Any]] = []
            for image in item["images"]:
                context.process_and_save_image(
                    image["bytes"],
                    str(references / image["filename"]),
                )
                manifest_images.append({
                    "index": image["index"],
                    "filename": image["filename"],
                    "source": image["source"],
                })
            _write_json(target / "references.json", {
                "version": item["reference_version"],
                "scope": "step3_image_style",
                "style_name": item["style_name"],
                "updated_at": datetime.now().isoformat(timespec="seconds"),
                "images": manifest_images,
            })
            imported_summaries.append({
                "id": item["id"],
                "name": item["name"],
                "version": item["version"],
                "account_id": get_current_account_id(),
                "content_hash": item["content_hash"],
                "reference_count": len(manifest_images),
                "created_at": item["created_at"] or datetime.now().isoformat(timespec="seconds"),
                "archived": item["archived"],
            })
        for item in imported_summaries:
            source = staging / item["id"]
            target = root / item["id"]
            if target.exists():
                shutil.rmtree(target)
            source.replace(target)
        existing = {
            str(item.get("id") or ""): item
            for item in read_templates(context, include_archived=True)
            if isinstance(item, dict)
        }
        for item in imported_summaries:
            existing[item["id"]] = item
        write_templates(context, list(existing.values()))
        return read_templates(context)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def normalize_creation_config_binding(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    template_id = str(value.get("template_id") or value.get("package_id") or "").strip()
    if not template_id:
        return {}
    try:
        version = int(value.get("version") or value.get("style_version") or 1)
    except (TypeError, ValueError):
        version = 1
    policy = str(
        value.get("reference_policy") or value.get("reference_mode") or "preferred"
    ).strip().lower()
    if policy not in {"required", "preferred", "text_only"}:
        policy = "preferred"
    try:
        minimum = int(value.get("minimum_reference_images", 1))
    except (TypeError, ValueError):
        minimum = 1
    minimum = max(0, min(3, minimum))
    if policy == "required":
        minimum = max(1, minimum)
    elif policy == "text_only":
        minimum = 0
    return {
        "template_id": template_id,
        "version": max(1, version),
        "reference_policy": policy,
        "minimum_reference_images": minimum,
    }


def materialize_creation_config_style(
    context: Any,
    project: Any,
    binding: Any,
) -> dict[str, Any] | None:
    """Copy a reusable style into a project and persist an immutable snapshot."""
    normalized = normalize_creation_config_binding(binding)
    if not normalized:
        return None
    template_id = normalized["template_id"]
    detail = template_detail(context, template_id)
    summary = detail.get("template") if isinstance(detail, dict) else {}
    summary = summary if isinstance(summary, dict) else {}
    template_version = int(summary.get("version") or 1)
    if normalized["version"] != template_version:
        raise context.http_exception(
            status_code=409,
            detail=f"图片风格版本不可用：需要 v{normalized['version']}，当前为 v{template_version}",
        )
    applied = apply_named_template(context, project, template_id)
    manifest = applied.get("manifest") if isinstance(applied, dict) else {}
    images = manifest.get("images", []) if isinstance(manifest, dict) else []
    reference_count = len([item for item in images if isinstance(item, dict)])
    if (
        normalized["reference_policy"] == "required"
        and reference_count < normalized["minimum_reference_images"]
    ):
        raise context.http_exception(
            status_code=409,
            detail=(
                "图片风格参考图不足："
                f"至少需要 {normalized['minimum_reference_images']} 张，当前 {reference_count} 张"
            ),
        )
    snapshot = {
        "schema_version": "project_image_style_snapshot_v1",
        **normalized,
        "name": str(summary.get("name") or ""),
        "content_hash": str(summary.get("content_hash") or ""),
        "reference_count": reference_count,
        "materialized_at": datetime.now().isoformat(timespec="seconds"),
    }
    _write_json(
        _run_dir(project) / "planning" / "project_image_style_snapshot.json",
        snapshot,
    )
    state = _read_json(_step3_state_path(project), {})
    state["creation_config_binding"] = normalized
    state["note"] = "Step 3 owns the project style snapshot and generation references."
    _write_json(_step3_state_path(project), state)
    return snapshot

def rewrite_reference_urls(*args: Any, **kwargs: Any) -> Any:
    """公开包装（审查 L-06）：路由与服务经公开名调用。"""
    return _rewrite_reference_urls(*args, **kwargs)
