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
import re
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any

PATCH_MARKER = "__ppt_image_style_reverse_patch__"
INPUT_DIRNAME = "reverse_style_inputs"
INPUT_MANIFEST = "reverse_style_inputs.json"
REVERSE_SYSTEM_CONTENT_KEY = "image_style_reverse_system_content"
REVERSE_OUTPUT_EXAMPLE_KEY = "image_style_reverse_output_example"
DEFAULT_REVERSE_SYSTEM_CONTENT = """<PromptVersion>image_style_reverse_v2_minimal</PromptVersion>

<Role>
You are a visual-style analyst for a PPT video production system. Your only task is to extract reusable visual language from the attached reference images; do not copy their subject matter or composition.
</Role>

<SystemBackground>
The returned profile will be converted deterministically into editable Step 3 image-generation System Content. Production code adds canvas, white-background, spacing, Mask, and copyright safety rules later, so do not repeat those universal rules in style fields or sample prompts.
</SystemBackground>

<InputContract>
- One to three attached images, in upload order. They are the primary evidence.
- An optional JSON text object `{\"requirement\": \"...\"}` containing only the user's extra preference. If absent, infer style only from the images.
</InputContract>

<AnalysisRules>
1. Extract only reusable choices: line and shape language, palette, element texture, lighting, density, typography, composition, and icon/illustration language.
2. Treat repeated evidence across images as stronger than a feature seen once. If references conflict, describe the common denominator and put the conflict in `warnings`.
3. The optional requirement may refine emphasis but cannot override what the images visibly support or introduce unrelated content.
4. Do not copy logos, watermarks, named characters, exact layouts, identifiable compositions, text content, or page-specific objects.
5. `sample_reference_image_prompts` must be short, content-neutral English scene briefs that demonstrate the extracted style. Do not repeat the full style profile or production rules in them.
</AnalysisRules>

<OutputContract>
Return one JSON object with exactly these fields:
- `style_name`: concise Chinese name.
- `style_summary`: one Chinese sentence describing the visual feel and suitable use.
- `visual_language`: object containing `line_style`, `shape_language`, `color_palette`, `texture`, `lighting`, `layout_density`, `typography`, `composition`, and `iconography`.
- `negative_prompt_rules`: zero or more style-specific things to avoid; do not repeat universal white-canvas or Mask rules.
- `sample_reference_image_prompts`: one to three short English scene briefs.
- `warnings`: only evidence conflicts or uncertainties; otherwise an empty array.

Do not output `system_content`, `maskability_rules`, source-image descriptions, Markdown, or explanations outside the JSON object.
</OutputContract>

<SelfCheck>
- Every style claim is supported by the images or optional requirement.
- No copied page content, brand identity, or exact composition appears in the output.
- The output contains only the declared fields and is valid JSON.
</SelfCheck>"""
DEFAULT_REVERSE_OUTPUT_EXAMPLE = """{
  "style_name": "柔和蓝紫线性信息图",
  "style_summary": "适合知识讲解的轻盈扁平风格，以柔和蓝紫配色、圆角几何和清晰线性图标建立层级。",
  "visual_language": {
    "line_style": "clean medium-weight rounded outlines",
    "shape_language": "soft rounded geometric panels and simple callouts",
    "color_palette": ["#6C63FF", "#9B8AFB", "#DCE7FF", "#26324A"],
    "texture": "flat fills with very light local shading",
    "lighting": "soft and even, no dramatic highlights",
    "layout_density": "moderate with generous whitespace",
    "typography": "bold concise headings and short readable labels",
    "composition": "one clear focal structure with supporting elements",
    "iconography": "consistent rounded line icons"
  },
  "negative_prompt_rules": ["avoid photorealistic rendering", "avoid ornate decorative frames"],
  "sample_reference_image_prompts": [
    "A concise cause-and-effect explainer with one central concept and three supporting icons.",
    "A clean three-step process using simple line icons and short labels."
  ],
  "warnings": []
}"""


def compose_reverse_style_prompt(system_content: str, output_example: str) -> str:
    return (
        str(system_content or "").strip()
        + "\n\n<OutputExample>\n"
        + str(output_example or "").strip()
        + "\n</OutputExample>"
    )


def _read_reverse_style_prompts(server_module: ModuleType) -> tuple[str, str]:
    get_setting = getattr(server_module, "get_setting", None)
    if not callable(get_setting):
        return DEFAULT_REVERSE_SYSTEM_CONTENT, DEFAULT_REVERSE_OUTPUT_EXAMPLE
    system_content = _safe_text(get_setting(REVERSE_SYSTEM_CONTENT_KEY, DEFAULT_REVERSE_SYSTEM_CONTENT), 30000)
    output_example = _safe_text(get_setting(REVERSE_OUTPUT_EXAMPLE_KEY, DEFAULT_REVERSE_OUTPUT_EXAMPLE), 20000)
    return (
        system_content or DEFAULT_REVERSE_SYSTEM_CONTENT,
        output_example or DEFAULT_REVERSE_OUTPUT_EXAMPLE,
    )


def build_reverse_style_user_text(requirement: str) -> str:
    value = _safe_text(requirement, 4000)
    return json.dumps({"requirement": value}, ensure_ascii=False) if value else ""


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


REVERSE_VISUAL_LANGUAGE_FIELDS = {
    "line_style",
    "shape_language",
    "color_palette",
    "texture",
    "lighting",
    "layout_density",
    "typography",
    "composition",
    "iconography",
}
REVERSE_OUTPUT_FIELDS = {
    "style_name",
    "style_summary",
    "visual_language",
    "negative_prompt_rules",
    "sample_reference_image_prompts",
    "warnings",
}


def validate_reverse_style_model_output(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("参考图反推输出必须是 JSON 对象")
    missing = sorted(REVERSE_OUTPUT_FIELDS - set(value))
    unexpected = sorted(set(value) - REVERSE_OUTPUT_FIELDS)
    if missing:
        raise ValueError(f"参考图反推输出缺少字段: {', '.join(missing)}")
    if unexpected:
        raise ValueError(f"参考图反推输出包含未声明字段: {', '.join(unexpected)}")
    if not _safe_text(value.get("style_name"), 120) or not _safe_text(value.get("style_summary"), 1000):
        raise ValueError("style_name 和 style_summary 不能为空")
    visual_language = value.get("visual_language")
    if not isinstance(visual_language, dict):
        raise ValueError("visual_language 必须是对象")
    missing_visual = sorted(REVERSE_VISUAL_LANGUAGE_FIELDS - set(visual_language))
    unexpected_visual = sorted(set(visual_language) - REVERSE_VISUAL_LANGUAGE_FIELDS)
    if missing_visual:
        raise ValueError(f"visual_language 缺少字段: {', '.join(missing_visual)}")
    if unexpected_visual:
        raise ValueError(f"visual_language 包含未声明字段: {', '.join(unexpected_visual)}")
    for key in ("negative_prompt_rules", "sample_reference_image_prompts", "warnings"):
        if not isinstance(value.get(key), list):
            raise ValueError(f"{key} 必须是数组")
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


def _call_vision_model(server_module: ModuleType, saved: list[dict[str, Any]], project: Any, requirement: str) -> dict[str, Any]:
    get_setting = getattr(server_module, "get_setting", None)
    if not callable(get_setting):
        raise server_module.HTTPException(status_code=500, detail="当前服务无法读取模型设置")
    api_key = _safe_text(get_setting("llm_api_key"), 4000)
    base_url = _safe_text(get_setting("llm_base_url"), 1000) or None
    model = _safe_text(get_setting("vision_model") or get_setting("llm_model"), 200)
    if not api_key or not model:
        raise server_module.HTTPException(status_code=400, detail="请先在系统设置中配置文本/视觉模型 API Key 和模型名称")

    content: list[dict[str, Any]] = []
    user_text = build_reverse_style_user_text(requirement)
    if user_text:
        content.append({"type": "text", "text": user_text})
    for item in saved:
        path = _inputs_dir(project) / item["filename"]
        content.append({
            "type": "image_url",
            "image_url": {"url": _image_data_url(path, "image/png")},
        })

    system_content, output_example = _read_reverse_style_prompts(server_module)
    system_prompt = compose_reverse_style_prompt(system_content, output_example)

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
        return validate_reverse_style_model_output(parsed)
    except (json.JSONDecodeError, ValueError) as exc:
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
    neg_rules = style.get("negative_prompt_rules") if isinstance(style.get("negative_prompt_rules"), list) else []
    sample_prompts = style.get("sample_reference_image_prompts") if isinstance(style.get("sample_reference_image_prompts"), list) else []
    visual_language = style.get("visual_language") if isinstance(style.get("visual_language"), dict) else {}
    style_name = _safe_text(style.get("style_name") or "reverse-engineered PPT style", 120)
    style_summary = _safe_text(style.get("style_summary") or requirement, 1000)
    system_lines = [f"Reusable visual style: {style_name}."]
    if style_summary:
        system_lines.append(f"Style summary: {style_summary}")
    if visual_language:
        system_lines.append("Visual language:")
        system_lines.extend(f"- {key}: {value}" for key, value in visual_language.items())
    if neg_rules:
        system_lines.append("Style-specific negative rules:")
        system_lines.extend(f"- {str(rule).strip()}" for rule in neg_rules if str(rule).strip())
    system_content = "\n".join(system_lines)
    return {
        "source": "image_reverse_engineered",
        "template_id": "image_reverse_engineered",
        "template_name": _safe_text(style.get("style_name") or "参考图反推风格", 120),
        "style_name": _safe_text(style.get("style_name") or "参考图反推风格", 120),
        "style_summary": _safe_text(style.get("style_summary") or requirement, 1000),
        "custom_requirement": requirement,
        "system_content": system_content,
        "visual_language": visual_language,
        "maskability_rules": required_mask_rules,
        "negative_prompt_rules": [str(x).strip() for x in [*neg_rules, *negative_required] if str(x).strip()],
        "sample_reference_image_prompts": [str(x).strip() for x in sample_prompts[:3] if str(x).strip()],
        "reference_image_count_target": 3,
        "reverse_engineered_from": saved,
        "source_notes": "",
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

    def get_reverse_style_prompt_settings() -> dict[str, Any]:
        system_content, output_example = _read_reverse_style_prompts(server_module)
        return {
            "success": True,
            "prompts": {
                "system_content": system_content,
                "output_example": output_example,
                "full_prompt": compose_reverse_style_prompt(system_content, output_example),
            },
            "defaults": {
                "system_content": DEFAULT_REVERSE_SYSTEM_CONTENT,
                "output_example": DEFAULT_REVERSE_OUTPUT_EXAMPLE,
            },
        }

    def update_reverse_style_prompt_settings(payload: dict[str, Any]) -> dict[str, Any]:
        prompts = payload.get("prompts") if isinstance(payload.get("prompts"), dict) else payload
        system_content = _safe_text(prompts.get("system_content"), 30000)
        output_example = _safe_text(prompts.get("output_example"), 20000)
        if not system_content or not output_example:
            raise server_module.HTTPException(status_code=400, detail="图片风格反推的 System Content 和 Output Example 不能为空")
        update_settings = getattr(server_module, "update_settings", None)
        if not callable(update_settings):
            raise server_module.HTTPException(status_code=500, detail="当前服务无法保存图片风格反推 Prompt")
        update_settings({
            REVERSE_SYSTEM_CONTENT_KEY: system_content,
            REVERSE_OUTPUT_EXAMPLE_KEY: output_example,
        })
        return {
            "success": True,
            "prompts": {
                "system_content": system_content,
                "output_example": output_example,
                "full_prompt": compose_reverse_style_prompt(system_content, output_example),
            },
        }

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

    app.add_api_route("/api/settings/image-style-reverse", get_reverse_style_prompt_settings, methods=["GET"])
    app.add_api_route("/api/settings/image-style-reverse", update_reverse_style_prompt_settings, methods=["PUT"])
    app.add_api_route("/api/projects/{project_id}/project-profile/image-style/reverse", reverse_image_style, methods=["POST"])
    setattr(server_module, PATCH_MARKER, True)
    return True
