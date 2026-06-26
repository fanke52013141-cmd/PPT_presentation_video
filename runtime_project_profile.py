"""Project Profile v1 runtime bridge.

Adds project-level production profile storage and lightweight APIs without
rewriting the existing large server.py. The profile is intentionally additive:
project creation still uses the existing /api/projects endpoint, then the front
end saves planning/project_profile.json through these routes.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from typing import Any

PATCH_MARKER = "__ppt_project_profile_runtime_patch__"
INJECT_MARKER = "__ppt_project_profile_inject_patch__"
PROFILE_FILENAME = "project_profile.json"
PROFILE_VERSION = "project_profile_v1"

BUILT_IN_STORYBOARD_TEMPLATES = [
    {
        "id": "science_explainer",
        "name": "科普解释型",
        "description": "适合把复杂概念拆成定义、机制、例子和总结。旁白偏解释，视觉以流程、对比和概念图为主。",
        "methodology": "每页只讲一个核心点；优先用概念定义、因果链路、流程拆解和类比解释；旁白保持清晰递进。",
    },
    {
        "id": "business_report",
        "name": "商业汇报型",
        "description": "适合策略、增长、产品和管理类内容。强调结论先行、结构清晰、关键指标和框架表达。",
        "methodology": "先给结论，再解释原因和行动建议；多用框架图、对比矩阵、路径图和关键数字。",
    },
    {
        "id": "course_training",
        "name": "课程讲解型",
        "description": "适合培训课、知识课和教程。强调学习目标、步骤拆解、复盘和可执行动作。",
        "methodology": "按学习路径组织页面：目标、概念、步骤、练习、总结；每页保留明确教学意图。",
    },
    {
        "id": "storytelling",
        "name": "故事叙事型",
        "description": "适合历史、人物、案例和品牌故事。强调起承转合、场景感和情绪推进。",
        "methodology": "用场景引入问题，再呈现冲突、转折和结论；视觉更重情境和主线线索。",
    },
    {
        "id": "comparison_analysis",
        "name": "对比分析型",
        "description": "适合观点辨析、方案比较和前后变化。强调横向对比、优缺点和判断依据。",
        "methodology": "围绕对比维度拆页：现状、差异、证据、结论；优先使用双栏、象限和对照结构。",
    },
]

BUILT_IN_IMAGE_STYLE_TEMPLATES = [
    {
        "id": "handdrawn_ppt_sticker",
        "name": "手绘 PPT 贴纸风",
        "description": "黑色手绘线条、柔和色块、贴纸式元素，适合知识讲解和 Mask reveal。",
        "system_content": "Use clean hand-drawn PPT sticker style: black sketch outlines, soft pastel fills, separated objects, pure-white outer canvas, no texture background, no element sticking.",
    },
    {
        "id": "flat_infographic",
        "name": "扁平信息图风",
        "description": "干净几何图形、清晰层级、图标和标签分离，适合商业和科普。",
        "system_content": "Use flat infographic style: clean geometric shapes, clear hierarchy, concise labels, separated icons, pure-white outer canvas, no overlap.",
    },
    {
        "id": "minimal_whiteboard",
        "name": "极简白板风",
        "description": "少色彩、强调线条和箭头，适合解释复杂流程和技术概念。",
        "system_content": "Use minimal whiteboard style: sparse composition, black line diagrams, small accent colors, large white spacing, pure-white outer canvas.",
    },
    {
        "id": "consulting_slide",
        "name": "咨询汇报风",
        "description": "专业、克制、结构化，适合企业培训、战略分析和商业报告。",
        "system_content": "Use consulting slide illustration style: structured composition, muted professional palette, clean icons, concise labels, pure-white outer canvas.",
    },
]

DEFAULT_PROFILE: dict[str, Any] = {
    "version": PROFILE_VERSION,
    "automation_mode": "manual_review",
    "storyboard_profile": {
        "source": "template",
        "template_id": "science_explainer",
        "template_name": "科普解释型",
        "custom_requirement": "",
        "methodology": "每页只讲一个核心点；优先把复杂内容拆成清晰的概念、流程、对比或案例。",
    },
    "image_style_profile": {
        "source": "template",
        "template_id": "handdrawn_ppt_sticker",
        "template_name": "手绘 PPT 贴纸风",
        "custom_requirement": "",
        "system_content": "Use clean hand-drawn PPT sticker style. Keep visual_draft.png on pure-white #FFFFFF outer canvas. Keep all visual elements separated for Mask reveal.",
        "reference_image_count_target": 0,
    },
    "background_profile": {
        "mode": "solid",
        "solid_color": "#FFFFFF",
        "image_asset": "",
        "generation_policy": "visual_draft_must_remain_pure_white",
    },
    "quality_gates": {
        "pause_on_storyboard_validation_error": True,
        "pause_on_image_generation_failure": True,
        "pause_on_ai_mask_low_confidence": True,
        "pause_on_tts_failure": True,
        "pause_on_render_failure": True,
    },
}


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        return deepcopy(fallback or {})
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return deepcopy(fallback or {})
    return value if isinstance(value, dict) else deepcopy(fallback or {})


def _run_dir(project: Any) -> Path:
    return Path(str(project.run_dir)).resolve()


def _profile_path(project: Any) -> Path:
    return _run_dir(project) / "planning" / PROFILE_FILENAME


def _normalize_hex(value: Any, fallback: str = "#FFFFFF") -> str:
    text = str(value or "").strip().upper()
    return text if re.fullmatch(r"#[0-9A-F]{6}", text) else fallback


def _template_by_id(items: list[dict[str, Any]], template_id: str) -> dict[str, Any] | None:
    for item in items:
        if item.get("id") == template_id:
            return item
    return None


def _safe_text(value: Any, limit: int = 12000) -> str:
    text = str(value or "").strip()
    return text[:limit]


def normalize_profile(payload: Any) -> dict[str, Any]:
    source = payload.get("profile") if isinstance(payload, dict) and isinstance(payload.get("profile"), dict) else payload
    if not isinstance(source, dict):
        source = {}
    profile = deepcopy(DEFAULT_PROFILE)
    profile["version"] = PROFILE_VERSION

    automation_mode = str(source.get("automation_mode") or profile["automation_mode"]).strip()
    profile["automation_mode"] = "auto" if automation_mode == "auto" else "manual_review"

    storyboard = source.get("storyboard_profile") if isinstance(source.get("storyboard_profile"), dict) else {}
    storyboard_template_id = str(storyboard.get("template_id") or profile["storyboard_profile"]["template_id"]).strip()
    storyboard_template = _template_by_id(BUILT_IN_STORYBOARD_TEMPLATES, storyboard_template_id) or BUILT_IN_STORYBOARD_TEMPLATES[0]
    profile["storyboard_profile"] = {
        "source": str(storyboard.get("source") or "template")[:40],
        "template_id": storyboard_template["id"],
        "template_name": storyboard_template["name"],
        "description": storyboard_template.get("description", ""),
        "custom_requirement": _safe_text(storyboard.get("custom_requirement"), 4000),
        "methodology": _safe_text(storyboard.get("methodology") or storyboard_template.get("methodology"), 8000),
    }

    image_style = source.get("image_style_profile") if isinstance(source.get("image_style_profile"), dict) else {}
    image_template_id = str(image_style.get("template_id") or profile["image_style_profile"]["template_id"]).strip()
    image_template = _template_by_id(BUILT_IN_IMAGE_STYLE_TEMPLATES, image_template_id) or BUILT_IN_IMAGE_STYLE_TEMPLATES[0]
    profile["image_style_profile"] = {
        "source": str(image_style.get("source") or "template")[:60],
        "template_id": image_template["id"],
        "template_name": image_template["name"],
        "description": image_template.get("description", ""),
        "custom_requirement": _safe_text(image_style.get("custom_requirement"), 4000),
        "system_content": _safe_text(image_style.get("system_content") or image_template.get("system_content"), 12000),
        "reference_image_count_target": max(0, min(3, int(image_style.get("reference_image_count_target") or 0))),
    }

    background = source.get("background_profile") if isinstance(source.get("background_profile"), dict) else {}
    mode = "image" if str(background.get("mode") or "solid").strip().lower() == "image" else "solid"
    profile["background_profile"] = {
        "mode": mode,
        "solid_color": _normalize_hex(background.get("solid_color"), "#FFFFFF"),
        "image_asset": _safe_text(background.get("image_asset"), 500),
        "generation_policy": "visual_draft_must_remain_pure_white",
    }

    gates = source.get("quality_gates") if isinstance(source.get("quality_gates"), dict) else {}
    profile["quality_gates"] = {
        key: bool(gates.get(key, DEFAULT_PROFILE["quality_gates"][key]))
        for key in DEFAULT_PROFILE["quality_gates"]
    }
    return profile


def _apply_background_companion(project: Any, profile: dict[str, Any]) -> None:
    run_dir = _run_dir(project)
    background = profile.get("background_profile") if isinstance(profile.get("background_profile"), dict) else {}
    companion = {
        "mode": background.get("mode") or "solid",
        "solid_color": _normalize_hex(background.get("solid_color"), "#FFFFFF"),
        "image_fit": "cover",
        "generation_policy": "keep_visual_draft_white_for_mask",
    }
    _write_json(run_dir / "planning" / "storyboard_background.json", companion)


def _apply_prompt_companion(project: Any, profile: dict[str, Any]) -> None:
    run_dir = _run_dir(project)
    companion = {
        "version": "project_profile_prompt_companion_v1",
        "storyboard_methodology": profile.get("storyboard_profile", {}).get("methodology", ""),
        "image_style_system_content": profile.get("image_style_profile", {}).get("system_content", ""),
        "image_style_custom_requirement": profile.get("image_style_profile", {}).get("custom_requirement", ""),
        "production_invariants": [
            "visual_draft.png must keep a pure-white #FFFFFF outer canvas for AI Mask and manual Mask.",
            "Final video background is configured separately and must not be baked into generated slide images.",
            "Visual elements should not touch, overlap, or stick together; leave clear white gaps for Mask reveal.",
        ],
    }
    _write_json(run_dir / "planning" / "project_profile_prompt_companion.json", companion)


def save_profile(project: Any, payload: Any) -> dict[str, Any]:
    profile = normalize_profile(payload)
    _write_json(_profile_path(project), profile)
    _apply_background_companion(project, profile)
    _apply_prompt_companion(project, profile)
    return profile


def read_profile(project: Any) -> dict[str, Any]:
    return normalize_profile(_read_json(_profile_path(project), DEFAULT_PROFILE))


def _install_injection(app: Any) -> None:
    if getattr(app.state, INJECT_MARKER, False):
        return

    @app.middleware("http")
    async def project_profile_asset_injection(request: Any, call_next: Any) -> Any:
        response = await call_next(request)
        if "text/html" not in response.headers.get("content-type", "").lower():
            return response
        try:
            body = b"".join([chunk async for chunk in response.body_iterator]).decode("utf-8")
        except Exception:
            return response
        if "project_profile_extension.js" not in body and "</body>" in body:
            body = body.replace("</body>", '  <script src="project_profile_extension.js?v=1.0.0"></script>\n</body>')
        from starlette.responses import Response
        headers = dict(response.headers)
        headers.pop("content-length", None)
        return Response(body, status_code=response.status_code, headers=headers, media_type="text/html")

    setattr(app.state, INJECT_MARKER, True)


def _register(server_module: ModuleType) -> bool:
    if getattr(server_module, PATCH_MARKER, False):
        return True
    required = ("app", "Project", "HTTPException", "Depends", "get_db")
    if not all(hasattr(server_module, name) for name in required):
        return False
    app = server_module.app

    def get_templates() -> dict[str, Any]:
        return {
            "success": True,
            "storyboard_templates": BUILT_IN_STORYBOARD_TEMPLATES,
            "image_style_templates": BUILT_IN_IMAGE_STYLE_TEMPLATES,
            "automation_modes": [
                {"id": "manual_review", "name": "手动审核模式", "description": "每一步都由用户确认，适合首版、客户项目和高质量交付。"},
                {"id": "auto", "name": "全自动模式", "description": "正常路径自动跑完整链路；失败或质量门不通过时暂停给用户处理。"},
            ],
        }

    def get_profile(project_id: str, db: Any = server_module.Depends(server_module.get_db)) -> dict[str, Any]:
        project = db.query(server_module.Project).filter(server_module.Project.id == project_id).first()
        if not project:
            raise server_module.HTTPException(status_code=404, detail="项目不存在")
        return {"success": True, "profile": read_profile(project)}

    def put_profile(project_id: str, payload: dict[str, Any], db: Any = server_module.Depends(server_module.get_db)) -> dict[str, Any]:
        project = db.query(server_module.Project).filter(server_module.Project.id == project_id).first()
        if not project:
            raise server_module.HTTPException(status_code=404, detail="项目不存在")
        profile = save_profile(project, payload if isinstance(payload, dict) else {})
        try:
            server_module.write_project_log(project, "project_profile_saved", profile=profile)
        except Exception:
            pass
        return {"success": True, "profile": profile}

    app.add_api_route("/api/project-profile/templates", get_templates, methods=["GET"])
    app.add_api_route("/api/projects/{project_id}/project-profile", get_profile, methods=["GET"])
    app.add_api_route("/api/projects/{project_id}/project-profile", put_profile, methods=["PUT", "POST"])
    try:
        _install_injection(app)
    except Exception:
        pass
    setattr(server_module, PATCH_MARKER, True)
    return True


def _candidate_modules() -> list[ModuleType]:
    return [module for module in list(sys.modules.values()) if isinstance(module, ModuleType) and hasattr(module, "app") and hasattr(module, "Project")]


def _install_when_ready() -> None:
    def worker() -> None:
        while not os.environ.get("PPT_STUDIO_DISABLE_PROJECT_PROFILE"):
            for module in _candidate_modules():
                try:
                    if _register(module):
                        return
                except Exception:
                    return
            time.sleep(0.1)
    threading.Thread(target=worker, name="ppt-project-profile-runtime", daemon=True).start()


_install_when_ready()
