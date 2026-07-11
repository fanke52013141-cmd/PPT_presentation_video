"""Step 3 image-style reverse engineering from uploaded references.

Allows users to upload 1-3 reference images and turn them into a structured
Step 3 image style profile. The output is style text/rules only: final video
backgrounds and complex image backgrounds must not be baked into visual_draft.png.

The legacy /project-profile/image-style/reverse route is kept for compatibility.
New UI should use /steps/3/image-style/reverse, which stores state in
planning/step3_image_style.json.
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any

PATCH_MARKER = "__ppt_image_style_reverse_patch__"
INPUT_DIRNAME = "reverse_style_inputs"
INPUT_MANIFEST = "reverse_style_inputs.json"


def _safe_text(value: Any, limit: int = 8000) -> str:
    return str(value or "").strip()[:limit]


def _read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return fallback


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _run_dir(project: Any) -> Path:
    return Path(str(project.run_dir)).resolve()


def _profile_path(project: Any) -> Path:
    return _run_dir(project) / "planning" / "project_profile.json"


def _inputs_dir(project: Any) -> Path:
    return _run_dir(project) / "planning" / INPUT_DIRNAME


def _inputs_manifest_path(project: Any) -> Path:
    return _run_dir(project) / "planning" / INPUT_MANIFEST


def _clean_json_markdown(text: str) -> str:
    value = str(text or "").strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.I).strip()
        value = re.sub(r"\s*```$", "", value).strip()
    start = value.find("{")
    end = value.rfind("}")
    if start >= 0 and end > start:
        return value[start : end + 1]
    return value


def _mime_type(filename: str, fallback: str = "image/png") -> str:
    ext = Path(filename).suffix.lower()
    if ext in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if ext == ".webp":
        return "image/webp"
    return fallback


def _image_data_url(path: Path, mime_type: str) -> str:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{data}"


def _normalize_uploaded_image(server_module: ModuleType, data: bytes, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        Image = server_module.Image
        with Image.open(io.BytesIO(data)) as img:
            img = img.convert("RGBA")
            img.thumbnail((1536, 1536))
            background = Image.new("RGBA", img.size, (255, 255, 255, 255))
            background.alpha_composite(img)
            background.convert("RGB").save(path, "PNG")
    except Exception:
        path.write_bytes(data)


def _save_uploaded_references(server_module: ModuleType, project: Any, files: list[Any]) -> list[dict[str, Any]]:
    if not files:
        raise server_module.HTTPException(status_code=400, detail="请上传 1-3 张参考图")
    if len(files) > 3:
        raise server_module.HTTPException(status_code=400, detail="最多只能上传 3 张参考图")
    inputs_dir = _inputs_dir(project)
    inputs_dir.mkdir(parents=True, exist_ok=True)
    saved: list[dict[str, Any]] = []
    for index, file in enumerate(files, start=1):
        filename = _safe_text(getattr(file, "filename", "") or f"reference_{index}.png", 200)
        content_type = _safe_text(getattr(file, "content_type", "") or _mime_type(filename), 100)
        if not content_type.startswith("image/"):
            raise server_module.HTTPException(status_code=400, detail=f"{filename} 不是图片文件")
        data = file.file.read()
        if not data:
            raise server_module.HTTPException(status_code=400, detail=f"{filename} 是空文件")
        if len(data) > 12 * 1024 * 1024:
            raise server_module.HTTPException(status_code=400, detail=f"{filename} 超过 12MB")
        out_name = f"reverse_reference_{index:02d}.png"
        out_path = inputs_dir / out_name
        _normalize_uploaded_image(server_module, data, out_path)
        saved.append({
            "index": index,
            "filename": out_name,
            "original_filename": filename,
            "content_type": "image/png",
            "uploaded_at": datetime.now().isoformat(timespec="seconds"),
        })
    manifest = {
        "version": "reverse_style_inputs_v1",
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "images": saved,
    }
    _write_json(_inputs_manifest_path(project), manifest)
    return saved


def _reverse_prompt(requirement: str, output_schema: dict[str, Any]) -> str:
    return json.dumps(
        {
            "task": "Analyze the uploaded reference images and extract a reusable Step 3 image style profile for a PPT video generation system.",
            "user_requirement": requirement,
            "hard_production_invariants": [
                "Generated slide images must keep a flat pure-white #FFFFFF outer canvas.",
                "Do not bake final-video background colors, background images, paper textures, gradients, or complex backgrounds into visual_draft.png.",
                "Visual elements must remain separated by clear white gaps for AI Mask and manual Mask reveal.",
                "Do not copy exact copyrighted characters, logos, watermarks, brand marks, or identifiable compositions from the references.",
                "Extract reusable visual language only: line, shape, palette, density, typography, layout, icon style, and negative rules.",
            ],
            "fixed_output_schema": output_schema,
        },
        ensure_ascii=False,
        indent=2,
    )


def _call_vision_model(server_module: ModuleType, saved: list[dict[str, Any]], project: Any, requirement: str) -> dict[str, Any]:
    get_setting = getattr(server_module, "get_setting", None)
    if not callable(get_setting):
        raise server_module.HTTPException(status_code=500, detail="当前服务无法读取模型设置")
    api_key = _safe_text(get_setting("llm_api_key"), 4000)
    base_url = _safe_text(get_setting("llm_base_url"), 1000) or None
    model = _safe_text(get_setting("vision_model") or get_setting("llm_model"), 200)
    if not api_key or not model:
        raise server_module.HTTPException(status_code=400, detail="请先在系统设置中配置文本/视觉模型 API Key 和模型名称")

    output_schema = {
        "style_name": "中文风格名称",
        "style_summary": "一句话说明该风格的视觉观感、适合内容和受众",
        "system_content": "给生图模型使用的英文风格 system content，必须包含 pure-white outer canvas、separated elements、no overlap、no texture background 等约束",
        "visual_language": {
            "line_style": "线条风格",
            "shape_language": "形状语言",
            "color_palette": ["#FFFFFF", "#..."],
            "texture": "纹理/材质要求；若参考图有复杂背景，说明只抽取元素质感，不复制背景",
            "lighting": "光影规则",
            "layout_density": "布局密度",
            "typography": "标题和短标签风格",
            "composition": "构图规则",
            "iconography": "图标/插画语言",
        },
        "maskability_rules": ["方便 Mask reveal 的正向规则"],
        "negative_prompt_rules": ["必须避免的内容"],
        "sample_reference_image_prompts": ["可用于生成 Step 3 图片风格参考图的英文 prompt，最多 3 条"],
        "source_notes": "说明从参考图抽取了什么、舍弃了什么",
        "warnings": ["可能影响稳定生成或 Mask 的风险"],
    }
    content: list[dict[str, Any]] = [
        {"type": "text", "text": _reverse_prompt(requirement, output_schema)}
    ]
    for item in saved:
        path = _inputs_dir(project) / item["filename"]
        content.append({
            "type": "image_url",
            "image_url": {"url": _image_data_url(path, "image/png")},
        })

    system_prompt = """
你是 PPT 视频生成系统的 Step 3 图片风格反推专家。
你会从用户上传的 1-3 张参考图中抽取可复用风格，而不是复制具体图片内容。
必须特别保护生产约束：visual_draft.png 外背景永远纯白 #FFFFFF；最终视频背景单独合成；元素必须分离、不能粘连，方便 AI Mask 和手动 Mask。
只输出 JSON，不要输出解释文字。
""".strip()

    try:
        client = server_module.get_openai_client(api_key=api_key, base_url=base_url, timeout=120.0, max_retries=1)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ],
            temperature=0.25,
            max_tokens=3000,
            timeout=120,
        )
        raw = str(response.choices[0].message.content or "").strip()
        parsed = json.loads(_clean_json_markdown(raw))
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError as exc:
        raise server_module.HTTPException(status_code=500, detail=f"视觉模型返回的 JSON 解析失败: {exc}") from exc
    except server_module.HTTPException:
        raise
    except Exception as exc:
        raise server_module.HTTPException(status_code=500, detail=f"反推图片风格失败: {exc}") from exc


def _style_with_required_rules(style: dict[str, Any], saved: list[dict[str, Any]], requirement: str) -> dict[str, Any]:
    required_mask_rules = [
        "Generated slide images must use a flat pure-white #FFFFFF outer background.",
        "Keep all semantic visual groups separated by clear white gaps for Mask reveal.",
        "Do not bake final-video background color, image, paper texture, or complex reference backgrounds into visual_draft.png.",
    ]
    negative_required = [
        "no copied logos, watermarks, copyrighted characters, or exact reference-image compositions",
        "no complex background, gradient canvas, paper texture, or off-white outer canvas",
        "no crowded collage, tiny dense text, overlapping labels, or sticking objects",
    ]
    mask_rules = style.get("maskability_rules") if isinstance(style.get("maskability_rules"), list) else []
    neg_rules = style.get("negative_prompt_rules") if isinstance(style.get("negative_prompt_rules"), list) else []
    sample_prompts = style.get("sample_reference_image_prompts") if isinstance(style.get("sample_reference_image_prompts"), list) else []
    visual_language = style.get("visual_language") if isinstance(style.get("visual_language"), dict) else {}
    system_content = _safe_text(style.get("system_content"), 12000)
    if not system_content:
        system_content = "\n".join([
            f"Use the reusable visual style named {style.get('style_name') or 'reverse-engineered PPT style'}.",
            "Keep the generated slide image outer canvas pure-white #FFFFFF.",
            "Keep semantic visual groups separated by clear white gaps for Mask reveal.",
            "Do not copy the reference images; use their visual language only.",
        ])
    return {
        "source": "image_reverse_engineered",
        "template_id": "image_reverse_engineered",
        "template_name": _safe_text(style.get("style_name") or "参考图反推风格", 120),
        "style_name": _safe_text(style.get("style_name") or "参考图反推风格", 120),
        "style_summary": _safe_text(style.get("style_summary") or style.get("source_notes") or requirement, 1000),
        "custom_requirement": requirement,
        "system_content": system_content,
        "visual_language": visual_language,
        "maskability_rules": [str(x).strip() for x in [*mask_rules, *required_mask_rules] if str(x).strip()],
        "negative_prompt_rules": [str(x).strip() for x in [*neg_rules, *negative_required] if str(x).strip()],
        "sample_reference_image_prompts": [str(x).strip() for x in sample_prompts[:3] if str(x).strip()],
        "reference_image_count_target": min(3, max(1, len(sample_prompts) or len(saved))),
        "reverse_engineered_from": saved,
        "source_notes": _safe_text(style.get("source_notes"), 2000),
        "warnings": style.get("warnings") if isinstance(style.get("warnings"), list) else [],
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


def _apply_style_to_project(project: Any, style: dict[str, Any]) -> dict[str, Any]:
    """Legacy compatibility writer for the old project-profile route."""

    profile = _read_json(_profile_path(project), {})
    if not isinstance(profile, dict):
        profile = {}
    profile.setdefault("version", "project_profile_v1")
    profile["image_style_profile"] = style
    _write_json(_profile_path(project), profile)
    companion_path = _run_dir(project) / "planning" / "project_profile_prompt_companion.json"
    companion = _read_json(companion_path, {})
    if not isinstance(companion, dict):
        companion = {}
    companion.update({
        "version": "project_profile_prompt_companion_v1",
        "legacy_compatibility_only": True,
        "preferred_state_file": "planning/step3_image_style.json",
        "image_style_system_content": style.get("system_content", ""),
        "image_style_custom_requirement": style.get("custom_requirement", ""),
        "image_style_profile": style,
        "production_invariants": [
            "visual_draft.png must keep a pure-white #FFFFFF outer canvas for AI Mask and manual Mask.",
            "Final video background is configured separately and must not be baked into generated slide images.",
            "Visual elements should not touch, overlap, or stick together; leave clear white gaps for Mask reveal.",
        ],
    })
    _write_json(companion_path, companion)
    return profile


def _register(server_module: ModuleType) -> bool:
    if getattr(server_module, PATCH_MARKER, False):
        return True
    required = ("app", "Project", "HTTPException", "Depends", "get_db", "File", "Form", "Image")
    if not all(hasattr(server_module, name) for name in required):
        return False
    app = server_module.app

    async def reverse_image_style(
        project_id: str,
        files: list[Any] = server_module.File(...),
        requirement: str = server_module.Form(""),
        apply: bool = server_module.Form(True),
        db: Any = server_module.Depends(server_module.get_db),
    ) -> dict[str, Any]:
        project = db.query(server_module.Project).filter(server_module.Project.id == project_id).first()
        if not project:
            raise server_module.HTTPException(status_code=404, detail="项目不存在")
        saved = _save_uploaded_references(server_module, project, files)
        raw_style = _call_vision_model(server_module, saved, project, _safe_text(requirement, 4000))
        style = _style_with_required_rules(raw_style, saved, _safe_text(requirement, 4000))
        legacy_profile = _apply_style_to_project(project, style) if apply else None
        try:
            server_module.write_project_log(
                project,
                "legacy_image_style_reverse_engineered",
                reference_count=len(saved),
                applied=bool(apply),
                style_name=style.get("style_name"),
                preferred_route=f"/api/projects/{project_id}/steps/3/image-style/reverse",
            )
        except Exception:
            pass
        return {
            "success": True,
            "style": style,
            "style_state": None,
            "legacy_profile": legacy_profile,
            "profile": legacy_profile,
            "inputs": saved,
            "deprecated_route": True,
            "preferred_route": f"/api/projects/{project_id}/steps/3/image-style/reverse",
        }

    app.add_api_route("/api/projects/{project_id}/project-profile/image-style/reverse", reverse_image_style, methods=["POST"])
    setattr(server_module, PATCH_MARKER, True)
    return True


def _candidate_modules() -> list[ModuleType]:
    return [module for module in list(sys.modules.values()) if isinstance(module, ModuleType) and hasattr(module, "app") and hasattr(module, "Project")]


def _install_when_ready() -> None:
    def worker() -> None:
        while not os.environ.get("PPT_STUDIO_DISABLE_IMAGE_STYLE_REVERSE"):
            for module in _candidate_modules():
                try:
                    if _register(module):
                        return
                except Exception:
                    return
            time.sleep(0.1)
    threading.Thread(name="ppt-image-style-reverse-runtime", target=worker, daemon=True).start()
