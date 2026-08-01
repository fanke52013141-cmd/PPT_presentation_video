"""Global image-style settings and legacy template compatibility."""

from __future__ import annotations

import copy
from dataclasses import dataclass
import hashlib
import logging
import os
from pathlib import Path
import re
import shutil
from typing import Any, Callable, Dict, List, Optional
import uuid

from fastapi import HTTPException, UploadFile
from fastapi.responses import FileResponse
import yaml

from pipeline_lifecycle import write_json_atomic
from repository_paths import (
    DATA_DIR,
    DEFAULT_STYLE_REFERENCE_DIR,
    DEFAULT_STYLE_TOKENS_PATH,
    HANDDRAWN_STYLE_TOKENS_PATH,
    IMAGE_STYLE_TEMPLATES_DIR,
    IMAGE_STYLE_TEMPLATES_INDEX,
    REPO_ROOT,
    STYLE_REFERENCE_DIR,
    STYLE_REFERENCE_FILES,
    STYLE_TOKENS_PATH,
)


logger = logging.getLogger("PPTStudio.GlobalImageStyle")
IMAGE_GENERATION_BACKGROUND = "#FFFFFF"
IMAGE_STYLE_TOP_LEVEL_KEYS = (
    "brand",
    "canvas",
    "colors",
    "layout",
    "visual_assets",
)
IMAGE_STYLE_PROMPT_KEY = "prompt_system_content"
IMAGE_STYLE_VISUAL_ASSET_FIELDS = {
    "image_style": "image_style",
    "diagram_style": "diagram_style",
    "required_background": "required_background",
    "layout_rules": "reveal_friendly_layout",
    "avoid": "avoid",
}
MAX_IMAGE_UPLOAD_BYTES = int(
    os.environ.get(
        "PPT_STUDIO_MAX_IMAGE_UPLOAD_BYTES",
        str(20 * 1024 * 1024),
    )
)


def _not_configured(*_args: Any, **_kwargs: Any) -> Any:
    raise RuntimeError("Global image-style dependencies have not been configured")


is_seedream_image_model: Callable[..., Any] = _not_configured
normalized_template_name: Callable[..., Any] = _not_configured
open_validated_image: Callable[..., Any] = _not_configured
read_json_file: Callable[..., Any] = _not_configured
template_timestamp: Callable[..., Any] = _not_configured


@dataclass(frozen=True)
class GlobalImageStyleDependencies:
    is_seedream_image_model: Callable[..., Any]
    normalized_template_name: Callable[..., Any]
    open_validated_image: Callable[..., Any]
    read_json_file: Callable[..., Any]
    template_timestamp: Callable[..., Any]


def configure_global_image_style_dependencies(
    dependencies: GlobalImageStyleDependencies,
) -> None:
    global is_seedream_image_model
    global normalized_template_name
    global open_validated_image
    global read_json_file
    global template_timestamp
    is_seedream_image_model = dependencies.is_seedream_image_model
    normalized_template_name = dependencies.normalized_template_name
    open_validated_image = dependencies.open_validated_image
    read_json_file = dependencies.read_json_file
    template_timestamp = dependencies.template_timestamp


def ensure_active_image_style_storage() -> None:
    os.makedirs(IMAGE_STYLE_TEMPLATES_DIR, exist_ok=True)
    if not os.path.exists(STYLE_TOKENS_PATH):
        os.makedirs(os.path.dirname(STYLE_TOKENS_PATH), exist_ok=True)
        shutil.copy2(DEFAULT_STYLE_TOKENS_PATH, STYLE_TOKENS_PATH)
    os.makedirs(STYLE_REFERENCE_DIR, exist_ok=True)
    for filename in STYLE_REFERENCE_FILES.values():
        target = os.path.join(STYLE_REFERENCE_DIR, filename)
        source = os.path.join(DEFAULT_STYLE_REFERENCE_DIR, filename)
        if not os.path.exists(target) and os.path.exists(source):
            shutil.copy2(source, target)


def read_style_tokens_data() -> Dict[str, Any]:
    with open(STYLE_TOKENS_PATH, "r", encoding="utf-8") as f:
        payload = yaml.safe_load(f) or {}
    if not isinstance(payload, dict):
        raise ValueError("config/style_tokens.yaml must contain a YAML object")
    return payload


def editable_image_style_data(style_tokens: Dict[str, Any]) -> Dict[str, Any]:
    editable: Dict[str, Any] = {}
    for key in IMAGE_STYLE_TOP_LEVEL_KEYS:
        if key not in style_tokens:
            continue
        value = copy.deepcopy(style_tokens[key])
        if key == "visual_assets" and isinstance(value, dict):
            value = {
                editor_key: value[source_key]
                for editor_key, source_key in IMAGE_STYLE_VISUAL_ASSET_FIELDS.items()
                if source_key in value
            }
        editable[key] = value
    return editable


def dump_image_style_editor_text(style_tokens: Dict[str, Any]) -> str:
    prompt_text = str(style_tokens.get(IMAGE_STYLE_PROMPT_KEY) or "").strip()
    if prompt_text:
        return prompt_text
    return build_image_style_prompt(style_tokens)


def merge_image_style_update(
    style_tokens: Dict[str, Any],
    update: Dict[str, Any],
) -> Dict[str, Any]:
    unknown_keys = sorted(set(update) - set(IMAGE_STYLE_TOP_LEVEL_KEYS))
    if unknown_keys:
        raise HTTPException(
            status_code=400,
            detail=f"这些字段不属于生图配置: {', '.join(unknown_keys)}",
        )

    merged = copy.deepcopy(style_tokens)
    for key, value in update.items():
        if key != "visual_assets":
            existing_value = merged.get(key)
            if isinstance(existing_value, dict) and isinstance(value, dict):
                next_value = copy.deepcopy(existing_value)
                next_value.update(copy.deepcopy(value))
                merged[key] = next_value
            else:
                merged[key] = copy.deepcopy(value)
            continue
        if not isinstance(value, dict):
            raise HTTPException(
                status_code=400, detail="visual_assets 必须是 YAML 对象"
            )
        unknown_asset_keys = sorted(set(value) - set(IMAGE_STYLE_VISUAL_ASSET_FIELDS))
        if unknown_asset_keys:
            raise HTTPException(
                status_code=400,
                detail=f"这些 visual_assets 字段不用于生图: {', '.join(unknown_asset_keys)}",
            )
        existing_assets = merged.get("visual_assets")
        if not isinstance(existing_assets, dict):
            existing_assets = {}
        for editor_key, editor_value in value.items():
            existing_assets[IMAGE_STYLE_VISUAL_ASSET_FIELDS[editor_key]] = (
                copy.deepcopy(editor_value)
            )
        merged["visual_assets"] = existing_assets
    canvas = merged.setdefault("canvas", {})
    if isinstance(canvas, dict):
        canvas["background"] = IMAGE_GENERATION_BACKGROUND
    colors = merged.setdefault("colors", {})
    if isinstance(colors, dict):
        for key in ("background", "surface", "paper"):
            colors[key] = IMAGE_GENERATION_BACKGROUND
    assets = merged.setdefault("visual_assets", {})
    if isinstance(assets, dict):
        assets["required_background"] = "flat_uniform_pure_white"
    return merged


def parse_image_style_payload(
    payload: Dict[str, Any],
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    current = read_style_tokens_data()
    style_data = payload.get("style_data")
    if isinstance(style_data, dict):
        return current, merge_image_style_update(current, style_data)

    style_text = str(payload.get("style_text") or "").strip()
    if not style_text:
        raise HTTPException(status_code=400, detail="图片生成 System Content 不能为空")
    merged = copy.deepcopy(current)
    merged[IMAGE_STYLE_PROMPT_KEY] = style_text
    return current, merged


def build_image_style_prompt(style_tokens: Dict[str, Any]) -> str:
    prompt_text = str(style_tokens.get(IMAGE_STYLE_PROMPT_KEY) or "").strip()
    if prompt_text:
        return prompt_text

    brand = (
        style_tokens.get("brand") if isinstance(style_tokens.get("brand"), dict) else {}
    )
    colors = (
        style_tokens.get("colors")
        if isinstance(style_tokens.get("colors"), dict)
        else {}
    )
    assets = (
        style_tokens.get("visual_assets")
        if isinstance(style_tokens.get("visual_assets"), dict)
        else {}
    )

    lines = ["图片风格（只描述视觉语言，不重复生产规则）："]
    keywords = (
        brand.get("style_keywords")
        if isinstance(brand.get("style_keywords"), list)
        else []
    )
    if keywords:
        lines.append(
            f"- 整体风格：{'、'.join(str(item) for item in keywords if item)}。"
        )

    palette_keys = ("ink", "yellow", "yellow_soft", "green_soft", "blue_soft")
    palette = [str(colors[key]) for key in palette_keys if colors.get(key)]
    if palette:
        lines.append(
            f"- 配色：主线条与强调色使用 {'、'.join(palette)}，保持克制和清晰。"
        )

    image_style = str(assets.get("image_style") or "").strip()
    diagram_style = str(assets.get("diagram_style") or "").strip()
    if image_style:
        lines.append(f"- 图像语言：{image_style}。")
    if diagram_style:
        lines.append(f"- 图示语言：{diagram_style}。")

    avoid = assets.get("avoid")
    if isinstance(avoid, list) and avoid:
        production_terms = (
            "重叠",
            "遮挡",
            "箭头",
            "穿过",
            "穿字",
            "粘连",
            "纸纹",
            "噪声",
            "渐变",
            "阴影",
        )
        style_avoid = [
            str(item).strip()
            for item in avoid
            if str(item).strip()
            and not any(term in str(item) for term in production_terms)
        ]
        if style_avoid:
            lines.append(f"- 风格上避免：{'、'.join(style_avoid)}。")

    lines.append(
        "- 参考图只参考视觉气质、配色、线条、留白、层级和密度，不复制具体内容。"
    )
    return "\n".join(lines)


def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def active_style_reference_paths() -> List[str]:
    return [
        os.path.join(STYLE_REFERENCE_DIR, filename)
        for filename in STYLE_REFERENCE_FILES.values()
        if os.path.exists(os.path.join(STYLE_REFERENCE_DIR, filename))
    ]


def active_references_are_default_handdrawn(reference_paths: List[str]) -> bool:
    if not reference_paths:
        return False
    for path in reference_paths:
        filename = os.path.basename(path)
        default_path = os.path.join(DEFAULT_STYLE_REFERENCE_DIR, filename)
        if not os.path.exists(default_path):
            return False
        try:
            if file_sha256(path) != file_sha256(default_path):
                return False
        except OSError:
            return False
    return True


def style_prefers_handdrawn_reference(style_tokens: Dict[str, Any]) -> bool:
    brand = (
        style_tokens.get("brand") if isinstance(style_tokens.get("brand"), dict) else {}
    )
    assets = (
        style_tokens.get("visual_assets")
        if isinstance(style_tokens.get("visual_assets"), dict)
        else {}
    )
    positive_parts: List[str] = []
    keywords = (
        brand.get("style_keywords")
        if isinstance(brand.get("style_keywords"), list)
        else []
    )
    positive_parts.extend(str(item) for item in keywords if item)
    positive_parts.append(str(assets.get("image_style") or ""))
    positive_parts.append(str(assets.get("diagram_style") or ""))
    text = "\n".join(positive_parts).lower()
    handdrawn_hints = (
        "手绘",
        "白板",
        "线稿",
        "手写",
        "马克笔",
        "涂鸦",
        "sketch",
        "handdrawn",
        "hand-drawn",
        "whiteboard",
        "marker",
    )
    return any(hint in text for hint in handdrawn_hints)


def should_send_style_reference_images(
    *,
    model: str,
    base_url: Optional[str],
    reference_paths: List[str],
    style_tokens: Dict[str, Any],
) -> bool:
    if not reference_paths:
        return False
    if not str(model).startswith("gpt-image") or is_seedream_image_model(
        model, base_url
    ):
        return False
    if active_references_are_default_handdrawn(
        reference_paths
    ) and not style_prefers_handdrawn_reference(style_tokens):
        return False
    return True


def get_image_style():
    references = {}
    for kind, filename in STYLE_REFERENCE_FILES.items():
        path = os.path.join(STYLE_REFERENCE_DIR, filename)
        references[kind] = {
            "exists": os.path.exists(path),
            "url": f"/api/image-style/reference/{kind}?t={int(os.path.getmtime(path))}"
            if os.path.exists(path)
            else "",
        }
    style_tokens = read_style_tokens_data()
    return {
        "success": True,
        "style_text": dump_image_style_editor_text(style_tokens),
        "style_data": editable_image_style_data(style_tokens),
        "protected_rules": [
            "画布固定为 1920×1080、16:9",
            "生图背景固定为纯白 #FFFFFF，确保 Mask 外围背景可稳定移除",
            "主标题固定在页面上方标题区；不生成页面副标题",
            "y=930 以下为字幕安全区，不放关键内容",
            "画面元素严禁重叠、穿插、压住或粘连，保证后续 Mask 可标注",
            "主体内容区可以自由发挥，但所有画面元素严禁重叠、覆盖、压住、穿插或粘连",
            "高级 YAML 只允许 brand、canvas、colors、layout、visual_assets 顶层字段",
        ],
        "references": references,
    }


def update_image_style(payload: Dict[str, Any]):
    _, merged = parse_image_style_payload(payload)
    with open(STYLE_TOKENS_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(
            merged,
            f,
            allow_unicode=True,
            sort_keys=False,
            width=1000,
        )
    return {
        "success": True,
        "style_text": dump_image_style_editor_text(merged),
        "style_data": editable_image_style_data(merged),
        "prompt_preview": build_image_style_prompt(merged),
    }


def validate_image_style(payload: Dict[str, Any]):
    _, merged = parse_image_style_payload(payload)
    return {
        "success": True,
        "style_text": dump_image_style_editor_text(merged),
        "style_data": editable_image_style_data(merged),
        "prompt_preview": build_image_style_prompt(merged),
    }


def read_image_style_template_index() -> List[Dict[str, Any]]:
    payload = read_json_file(IMAGE_STYLE_TEMPLATES_INDEX, [])
    return (
        [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, list)
        else []
    )


def image_style_template_source(template_id: str) -> tuple[str, str]:
    if template_id == "default":
        return DEFAULT_STYLE_TOKENS_PATH, DEFAULT_STYLE_REFERENCE_DIR
    if template_id == "handdrawn_explainer":
        return HANDDRAWN_STYLE_TOKENS_PATH, DEFAULT_STYLE_REFERENCE_DIR
    if not re.fullmatch(r"[0-9a-f]{12}", template_id):
        raise HTTPException(status_code=404, detail="图片风格模板不存在")
    item = next(
        (
            entry
            for entry in read_image_style_template_index()
            if str(entry.get("id") or "") == template_id
        ),
        None,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="图片风格模板不存在")
    template_dir = os.path.join(IMAGE_STYLE_TEMPLATES_DIR, template_id)
    return os.path.join(template_dir, "style_tokens.yaml"), os.path.join(
        template_dir, "references"
    )


def image_style_template_detail(template_id: str) -> Dict[str, Any]:
    if template_id == "default":
        item = {
            "id": "default",
            "name": "内容优先通用图片风格模板",
            "built_in": True,
            "updated_at": "",
        }
    elif template_id == "handdrawn_explainer":
        item = {
            "id": "handdrawn_explainer",
            "name": "手绘科普内容优先图片风格模板",
            "built_in": True,
            "updated_at": "",
        }
    else:
        item = next(
            (
                copy.deepcopy(entry)
                for entry in read_image_style_template_index()
                if str(entry.get("id") or "") == template_id
            ),
            None,
        )
        if item is None:
            raise HTTPException(status_code=404, detail="图片风格模板不存在")
        item["built_in"] = False
    style_path, reference_dir = image_style_template_source(template_id)
    if not os.path.exists(style_path):
        raise HTTPException(status_code=404, detail="图片风格模板配置缺失")
    with open(style_path, "r", encoding="utf-8-sig") as file:
        style_tokens = yaml.safe_load(file) or {}
    if not isinstance(style_tokens, dict):
        raise HTTPException(status_code=400, detail="图片风格模板配置损坏")
    references = {}
    for kind, filename in STYLE_REFERENCE_FILES.items():
        path = os.path.join(reference_dir, filename)
        references[kind] = {
            "exists": os.path.exists(path),
            "url": (
                f"/api/image-style/templates/{template_id}/reference/{kind}"
                f"?t={int(os.path.getmtime(path))}"
                if os.path.exists(path)
                else ""
            ),
        }
    return {
        **item,
        "style_text": dump_image_style_editor_text(style_tokens),
        "style_data": editable_image_style_data(style_tokens),
        "references": references,
    }


def list_image_style_templates() -> List[Dict[str, Any]]:
    result = [
        image_style_template_detail("default"),
    ]
    for item in read_image_style_template_index():
        template_id = str(item.get("id") or "")
        if not template_id:
            continue
        try:
            result.append(image_style_template_detail(template_id))
        except HTTPException as exc:
            logger.warning(
                "Skipping invalid image style template %s: %s", template_id, exc.detail
            )
    return result


def get_image_style_templates():
    return {"success": True, "templates": list_image_style_templates()}


def get_image_style_template(template_id: str):
    return {"success": True, "template": image_style_template_detail(template_id)}


def save_image_style_template(payload: Dict[str, Any]):
    ensure_active_image_style_storage()
    name = normalized_template_name(payload.get("name"))
    protected_names = {
        "默认图片风格模板",
        "内容优先通用图片风格模板",
        "手绘科普内容优先图片风格模板",
    }
    if name.casefold() in {item.casefold() for item in protected_names}:
        raise HTTPException(status_code=400, detail="内置图片风格模板名称不可覆盖")
    index = read_image_style_template_index()
    existing = next(
        (
            item
            for item in index
            if str(item.get("name") or "").strip().casefold() == name.casefold()
        ),
        None,
    )
    now = template_timestamp()
    if existing is None:
        existing = {"id": uuid.uuid4().hex[:12], "created_at": now}
        index.append(existing)
    template_id = str(existing["id"])
    existing.update({"name": name, "updated_at": now})
    template_dir = os.path.join(IMAGE_STYLE_TEMPLATES_DIR, template_id)
    reference_dir = os.path.join(template_dir, "references")
    os.makedirs(reference_dir, exist_ok=True)
    shutil.copy2(STYLE_TOKENS_PATH, os.path.join(template_dir, "style_tokens.yaml"))
    for filename in STYLE_REFERENCE_FILES.values():
        source = os.path.join(STYLE_REFERENCE_DIR, filename)
        target = os.path.join(reference_dir, filename)
        if os.path.exists(source):
            shutil.copy2(source, target)
        elif os.path.exists(target):
            os.remove(target)
    write_json_atomic(IMAGE_STYLE_TEMPLATES_INDEX, index)
    return {
        "success": True,
        "template": image_style_template_detail(template_id),
        "templates": list_image_style_templates(),
    }


def delete_image_style_template(template_id: str):
    if template_id == "default":
        raise HTTPException(status_code=400, detail="内置图片风格模板不能删除")
    if not re.fullmatch(r"[0-9a-f]{12}", template_id):
        raise HTTPException(status_code=404, detail="图片风格模板不存在")
    index = read_image_style_template_index()
    next_index = [
        item
        for item in index
        if not (isinstance(item, dict) and str(item.get("id") or "") == template_id)
    ]
    if len(next_index) == len(index):
        raise HTTPException(status_code=404, detail="图片风格模板不存在")
    write_json_atomic(IMAGE_STYLE_TEMPLATES_INDEX, next_index)
    base_dir = os.path.abspath(IMAGE_STYLE_TEMPLATES_DIR)
    template_dir = os.path.abspath(os.path.join(IMAGE_STYLE_TEMPLATES_DIR, template_id))
    if os.path.commonpath([base_dir, template_dir]) != base_dir:
        raise HTTPException(status_code=400, detail="图片风格模板路径异常")
    if os.path.exists(template_dir):
        shutil.rmtree(template_dir)
    return {"success": True, "templates": list_image_style_templates()}


def apply_image_style_template_references(template_id: str):
    ensure_active_image_style_storage()
    _, source_dir = image_style_template_source(template_id)
    for filename in STYLE_REFERENCE_FILES.values():
        source = os.path.join(source_dir, filename)
        target = os.path.join(STYLE_REFERENCE_DIR, filename)
        if os.path.exists(source):
            shutil.copy2(source, target)
        elif os.path.exists(target):
            os.remove(target)
    return {
        "success": True,
        "references": {
            kind: {
                "exists": os.path.exists(os.path.join(STYLE_REFERENCE_DIR, filename)),
                "url": (
                    f"/api/image-style/reference/{kind}?t={uuid.uuid4().hex[:8]}"
                    if os.path.exists(os.path.join(STYLE_REFERENCE_DIR, filename))
                    else ""
                ),
            }
            for kind, filename in STYLE_REFERENCE_FILES.items()
        },
    }


def get_image_style_template_reference(template_id: str, kind: str):
    filename = STYLE_REFERENCE_FILES.get(kind)
    if not filename:
        raise HTTPException(status_code=404, detail="参考图类型不存在")
    _, reference_dir = image_style_template_source(template_id)
    path = os.path.join(reference_dir, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="模板参考图不存在")
    return FileResponse(path, media_type="image/png")


def get_image_style_reference(kind: str):
    filename = STYLE_REFERENCE_FILES.get(kind)
    if not filename:
        raise HTTPException(status_code=404, detail="参考图类型不存在")
    path = os.path.join(STYLE_REFERENCE_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="参考图不存在")
    return FileResponse(path, media_type="image/png")


def update_image_style_reference(kind: str, file: UploadFile):
    ensure_active_image_style_storage()
    filename = STYLE_REFERENCE_FILES.get(kind)
    if not filename:
        raise HTTPException(status_code=404, detail="参考图类型不存在")
    content = file.file.read(MAX_IMAGE_UPLOAD_BYTES + 1)
    try:
        image = open_validated_image(content).convert("RGB")
        os.makedirs(STYLE_REFERENCE_DIR, exist_ok=True)
        image.save(os.path.join(STYLE_REFERENCE_DIR, filename), "PNG")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"参考图不是有效图片: {exc}")
    return {
        "success": True,
        "url": f"/api/image-style/reference/{kind}?t={uuid.uuid4().hex[:8]}",
    }


# ==================== Step 3 图片生成 Prompt ====================
