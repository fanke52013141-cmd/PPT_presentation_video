"""Persistence helpers for named Step 3 image-style templates."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import shutil
import time
from typing import Any
import uuid

import yaml


STATE_FILENAME = "step3_image_style.json"
BUILTIN_HANDDRAWN_TEMPLATE_ID = "handdrawn"
BUILTIN_HANDDRAWN_TEMPLATE_NAME = "手绘风格"
TEMPLATES_INDEX_VERSION = "step3_image_style_templates_v1"


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


def templates_root(context: Any) -> Path:
    return Path(context.data_dir) / "step3_image_style_templates"


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


def read_templates(context: Any) -> list[dict[str, Any]]:
    value = _read_json(templates_index(context), {"templates": []})
    items = value.get("templates", []) if isinstance(value, dict) else []
    return [item for item in items if isinstance(item, dict)]


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
            for item in read_templates(context)
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
    item = {
        "id": template_id,
        "name": name,
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
    source = template_dir_or_404(context, template_id)
    items = [
        item
        for item in read_templates(context)
        if str(item.get("id") or "") != template_id
    ]
    shutil.rmtree(source)
    write_templates(context, items)
    return items

def rewrite_reference_urls(*args: Any, **kwargs: Any) -> Any:
    """公开包装（审查 L-06）：路由与服务经公开名调用。"""
    return _rewrite_reference_urls(*args, **kwargs)
