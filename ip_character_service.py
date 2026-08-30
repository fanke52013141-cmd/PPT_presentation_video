"""IP character (IP 形象) management service.

Each project may define up to two IP characters. A character carries a name,
a free-form description, a screen position preset, and an optional reference
image. Characters are persisted under ``<run_dir>/planning/ip_characters.json``
while their reference images live in ``<run_dir>/planning/ip_characters/``.

The image workflow integrates IP characters in two ways:

1. A localized prompt segment is appended to ``effective_prompt`` so the model
   knows which characters to embed and where.
2. The reference image paths are merged into ``reference_paths`` so they are
   forwarded to ``client.images.edit`` alongside the style references.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from canvas_profile_service import get_project_canvas
from database import Project
from pipeline_lifecycle import write_json_atomic


logger = logging.getLogger("PPTStudio.IPCharacter")

IP_CHARACTERS_DIRNAME = "ip_characters"
IP_CHARACTERS_MANIFEST = "ip_characters.json"
MANIFEST_VERSION = "ip_characters_v1"
MAX_IP_CHARACTERS = 2
MAX_IMAGE_UPLOAD_BYTES = int(
    os.environ.get(
        "PPT_STUDIO_MAX_IP_IMAGE_BYTES",
        str(10 * 1024 * 1024),
    )
)

# IP 形象融入提示词段的唯一标记，用于生成时去重（避免重复追加）
IP_PROMPT_MARKER = "<IPCharacterRequirements>"
DEFAULT_IP_PROMPT_TEMPLATE = (
    "<IPCharacterRequirements>\n"
    "【IP 形象融入要求】\n"
    "请把以下 IP 形象角色自然融入本页画面，保持每个角色的外观、配色与风格高度一致：\n"
    "{characters}\n"
    "约束（与生图固定规则同等重要，不得违反）：\n"
    "1. 每个已列出的角色都必须出现在画面中，不得省略或替换。\n"
    "2. 多个角色互不重叠，也不得遮挡标题、正文文字、图表或关键标签；角色与其它视觉元素之间保留清晰间隙。\n"
    "3. 角色必须位于画面内容区（y<{subtitle_safe_top}），不得进入底部字幕安全区，不得覆盖页面上方主标题区。\n"
    "4. 若某个角色标注了放置位置，请尽量放在该位置；仅当该位置会遮挡关键文字或与其它元素冲突时才可调整。\n"
    "5. 请确保 IP 形象与页面其它视觉元素和谐共存，整体保持专业、美观的排版。\n"
    "</IPCharacterRequirements>"
)
MAX_IP_PROMPT_TEMPLATE_CHARS = 8000

POSITION_LABELS: dict = {
    None: "不限制，由整体画面构图自然决定",
    "left_top": "画面左上角",
    "left_bottom": "画面左下角",
    "right_top": "画面右上角",
    "right_bottom": "画面右下角",
    "center": "画面中央",
}
VALID_POSITIONS = set(POSITION_LABELS.keys())


def _run_dir(project):
    return Path(str(project.run_dir)).resolve()


def _manifest_path(project):
    return _run_dir(project) / "planning" / IP_CHARACTERS_MANIFEST


def _characters_dir(project):
    return _run_dir(project) / "planning" / IP_CHARACTERS_DIRNAME


def _read_json(path, fallback):
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return fallback


def _write_json(path, value):
    write_json_atomic(path, value)


def _safe_text(value, limit=4000):
    return str(value or "").strip()[:limit]


def _empty_manifest():
    return {
        "version": MANIFEST_VERSION,
        "enabled": False,
        "page_scope": "all",
        "selected_slide_ids": [],
        "prompt_template": DEFAULT_IP_PROMPT_TEMPLATE,
        "characters": [],
    }


def _normalize_manifest(raw):
    if not isinstance(raw, dict):
        return _empty_manifest()
    characters = raw.get("characters", [])
    if not isinstance(characters, list):
        characters = []
    normalized_characters = []
    for item in characters:
        if not isinstance(item, dict):
            continue
        position = item.get("position", None)
        if position not in VALID_POSITIONS:
            position = None
        normalized_characters.append(
            {
                "id": _safe_text(item.get("id"), 64) or uuid.uuid4().hex[:12],
                "name": _safe_text(item.get("name"), 100),
                "description": _safe_text(item.get("description"), 4000),
                "position": position,
                "image_filename": _safe_text(item.get("image_filename"), 200) or None,
                "prompt_text": _safe_text(item.get("prompt_text"), 2000),
                "created_at": _safe_text(item.get("created_at"), 40),
                "updated_at": _safe_text(item.get("updated_at"), 40),
            }
        )
    page_scope = raw.get("page_scope", "all")
    if page_scope not in ("all", "selected"):
        page_scope = "all"
    selected = raw.get("selected_slide_ids", [])
    if not isinstance(selected, list):
        selected = []
    return {
        "version": MANIFEST_VERSION,
        "enabled": bool(raw.get("enabled", False)),
        "page_scope": page_scope,
        "selected_slide_ids": [_safe_text(sid, 120) for sid in selected if sid],
        "prompt_template": (
            _safe_text(raw.get("prompt_template"), MAX_IP_PROMPT_TEMPLATE_CHARS)
            or DEFAULT_IP_PROMPT_TEMPLATE
        ),
        "characters": normalized_characters[:MAX_IP_CHARACTERS],
    }


def _load_manifest(project):
    raw = _read_json(_manifest_path(project), None)
    if raw is None:
        return _empty_manifest()
    return _normalize_manifest(raw)


def _save_manifest(project, manifest):
    _write_json(_manifest_path(project), manifest)


def _now_iso():
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _project_or_404(db, project_id):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


def _character_image_path(project, filename):
    if not filename:
        return None
    name = Path(_safe_text(filename, 200)).name
    if not name:
        return None
    base = _characters_dir(project)
    candidate = (base / name).resolve()
    try:
        candidate.relative_to(base.resolve())
    except ValueError:
        return None
    return candidate


def _public_manifest(manifest, project_id):
    characters = []
    for char in manifest.get("characters", []):
        item = dict(char)
        if item.get("image_filename"):
            item["image_url"] = (
                f"/api/projects/{project_id}/ip-characters/{item['id']}/image"
            )
        characters.append(item)
    return {
        "version": manifest.get("version", MANIFEST_VERSION),
        "enabled": manifest.get("enabled", False),
        "page_scope": manifest.get("page_scope", "all"),
        "selected_slide_ids": manifest.get("selected_slide_ids", []),
        "prompt_template": (
            manifest.get("prompt_template") or DEFAULT_IP_PROMPT_TEMPLATE
        ),
        "characters": characters,
        "max_characters": MAX_IP_CHARACTERS,
        "positions": [
            {"value": None, "label": "不限制"},
            {"value": "left_top", "label": "左上角"},
            {"value": "left_bottom", "label": "左下角"},
            {"value": "right_top", "label": "右上角"},
            {"value": "right_bottom", "label": "右下角"},
            {"value": "center", "label": "居中"},
        ],
    }


def get_ip_characters(project_id, db):
    project = _project_or_404(db, project_id)
    manifest = _load_manifest(project)
    return {"success": True, "data": _public_manifest(manifest, project_id)}


def _save_uploaded_image(project, file, prefix):
    content = file.file.read(MAX_IMAGE_UPLOAD_BYTES + 1)
    if len(content) > MAX_IMAGE_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"IP 形象图片超过 {MAX_IMAGE_UPLOAD_BYTES // (1024 * 1024)} MB 限制",
        )
    ext = ".png"
    original = _safe_text(file.filename, 200)
    if original:
        lowered = original.lower()
        for candidate_ext in (".png", ".jpg", ".jpeg", ".webp"):
            if lowered.endswith(candidate_ext):
                ext = candidate_ext
                break
    characters_dir = _characters_dir(project)
    os.makedirs(str(characters_dir), exist_ok=True)
    filename = f"{prefix}_{uuid.uuid4().hex[:10]}{ext}"
    target = characters_dir / filename
    with open(str(target), "wb") as f:
        f.write(content)
    return filename


def upsert_ip_character(project_id, payload, file, db):
    project = _project_or_404(db, project_id)
    manifest = _load_manifest(project)
    characters = manifest["characters"]

    character_id = _safe_text(payload.get("id"), 64)
    existing_index = None
    if character_id:
        for index, char in enumerate(characters):
            if char.get("id") == character_id:
                existing_index = index
                break

    if existing_index is None and len(characters) >= MAX_IP_CHARACTERS:
        raise HTTPException(
            status_code=400,
            detail=f"每个项目最多支持 {MAX_IP_CHARACTERS} 个 IP 形象角色",
        )

    position = payload.get("position", None)
    if position not in VALID_POSITIONS:
        position = None

    now = _now_iso()
    if existing_index is not None:
        current = dict(characters[existing_index])
        current["name"] = _safe_text(payload.get("name"), 100) or current["name"]
        current["description"] = _safe_text(payload.get("description"), 4000)
        if "position" in payload:
            current["position"] = position
        if "prompt_text" in payload:
            current["prompt_text"] = _safe_text(payload.get("prompt_text"), 2000)
        current["updated_at"] = now
    else:
        current = {
            "id": character_id or uuid.uuid4().hex[:12],
            "name": _safe_text(payload.get("name"), 100) or "未命名角色",
            "description": _safe_text(payload.get("description"), 4000),
            "position": position,
            "prompt_text": _safe_text(payload.get("prompt_text"), 2000),
            "image_filename": None,
            "created_at": now,
            "updated_at": now,
        }

    if file is not None and file.filename:
        if current.get("image_filename"):
            old_path = _character_image_path(project, current["image_filename"])
            if old_path and old_path.exists():
                try:
                    old_path.unlink()
                except OSError:
                    logger.warning("Failed to remove old IP image %s", old_path)
        current["image_filename"] = _save_uploaded_image(
            project, file, prefix=f"ip_char_{current['id']}"
        )
        current["updated_at"] = now

    if existing_index is not None:
        characters[existing_index] = current
    else:
        characters.append(current)
    manifest["characters"] = characters
    _save_manifest(project, manifest)

    logger.info(
        "IP character upserted for project %s: id=%s name=%s",
        project_id,
        current["id"],
        current["name"],
    )
    return {"success": True, "data": _public_manifest(manifest, project_id)}


def update_ip_character_config(project_id, payload, db):
    project = _project_or_404(db, project_id)
    manifest = _load_manifest(project)

    if "enabled" in payload:
        manifest["enabled"] = bool(payload.get("enabled"))
    if "prompt_template" in payload:
        manifest["prompt_template"] = (
            _safe_text(payload.get("prompt_template"), MAX_IP_PROMPT_TEMPLATE_CHARS)
            or DEFAULT_IP_PROMPT_TEMPLATE
        )
    if "page_scope" in payload:
        scope = payload.get("page_scope")
        manifest["page_scope"] = scope if scope in ("all", "selected") else "all"
    if "selected_slide_ids" in payload:
        selected = payload.get("selected_slide_ids")
        if isinstance(selected, list):
            manifest["selected_slide_ids"] = [
                _safe_text(sid, 120) for sid in selected if sid
            ]
        else:
            manifest["selected_slide_ids"] = []

    _save_manifest(project, manifest)
    return {"success": True, "data": _public_manifest(manifest, project_id)}


def delete_ip_character(project_id, character_id, db):
    project = _project_or_404(db, project_id)
    manifest = _load_manifest(project)
    characters = manifest["characters"]
    remaining = []
    removed = None
    for char in characters:
        if char.get("id") == character_id:
            removed = char
            continue
        remaining.append(char)
    if removed is None:
        raise HTTPException(status_code=404, detail="IP 形象角色不存在")
    if removed.get("image_filename"):
        old_path = _character_image_path(project, removed["image_filename"])
        if old_path and old_path.exists():
            try:
                old_path.unlink()
            except OSError:
                logger.warning("Failed to remove IP image %s", old_path)
    manifest["characters"] = remaining
    _save_manifest(project, manifest)
    logger.info("IP character deleted for project %s: id=%s", project_id, character_id)
    return {"success": True, "data": _public_manifest(manifest, project_id)}


def get_character_image_path(project_id, character_id, db):
    project = _project_or_404(db, project_id)
    manifest = _load_manifest(project)
    for char in manifest["characters"]:
        if char.get("id") == character_id:
            path = _character_image_path(project, char.get("image_filename"))
            if path is None or not path.exists():
                raise HTTPException(status_code=404, detail="IP 形象图片不存在")
            return path
    raise HTTPException(status_code=404, detail="IP 形象角色不存在")


def _slide_in_scope(manifest, slide_id):
    if not manifest.get("enabled", False):
        return False
    characters = manifest.get("characters", [])
    if not characters:
        return False
    if manifest.get("page_scope", "all") == "all":
        return True
    selected = manifest.get("selected_slide_ids", []) or []
    if slide_id is None:
        return False
    return slide_id in selected


def render_ip_character_prompt(project, slide_id=None):
    """按项目模板渲染 IP 形象融入提示词段，未启用/无角色时返回空串。

    每个角色优先使用自定义 prompt_text；留空时自动用
    「名称 + 描述 + 位置预设」生成。返回内容带 <IPCharacterRequirements> 标记，
    供生图链路做去重。
    """
    manifest = _load_manifest(project)
    if not _slide_in_scope(manifest, slide_id):
        return ""
    characters = manifest.get("characters", [])
    active = [c for c in characters if c.get("name") or c.get("description")]
    if not active:
        return ""
    entries = []
    for index, char in enumerate(active, start=1):
        name = char.get("name") or "未命名角色"
        position_label = POSITION_LABELS.get(
            char.get("position"), POSITION_LABELS[None]
        )
        # IP 形象以参考图为主要载体，文字描述固定为指引性文案。
        # 不再读取 description / prompt_text 字段（字段保留以兼容旧数据）。
        entry = f"{index}. {name}：参考我上传的人物 IP 图。建议位置：{position_label}。"
        entries.append(entry)
    template = _safe_text(
        manifest.get("prompt_template"), MAX_IP_PROMPT_TEMPLATE_CHARS
    ) or DEFAULT_IP_PROMPT_TEMPLATE
    canvas = get_project_canvas(project)
    safe_top = int((canvas.get("subtitle_safe_zone") or {}).get("top") or 930)
    rendered = template.replace("{characters}", "\n".join(entries))
    rendered = rendered.replace("{subtitle_safe_top}", str(safe_top))
    if canvas.get("orientation") == "portrait" and "y<930" in rendered:
        rendered = rendered.replace("y<930", f"y<{safe_top}")
    return rendered


def build_ip_character_prompt_segment(project, slide_id=None):
    """向后兼容别名：渲染带标记的 IP 形象融入提示词段。"""
    return render_ip_character_prompt(project, slide_id)


def ip_character_reference_paths(project, slide_id=None):
    manifest = _load_manifest(project)
    if not _slide_in_scope(manifest, slide_id):
        return []
    paths = []
    for char in manifest.get("characters", []):
        path = _character_image_path(project, char.get("image_filename"))
        if path is not None and path.exists() and path.is_file():
            paths.append(str(path))
    return paths
