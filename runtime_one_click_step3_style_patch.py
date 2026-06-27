"""One-click compatibility patch for Step 3 image style ownership.

Project creation no longer owns image style. This patch keeps the existing
orchestrator but changes its style-related decisions so image regeneration reacts
to ``planning/step3_image_style.json`` and One-click no longer auto-generates
reference images from Project Profile defaults. It also normalizes the user-facing
One-click style-reference stage wording to Step 3 image style semantics.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from types import ModuleType
from typing import Any

PATCH_MARKER = "__ppt_one_click_step3_style_patch__"

STAGE_TITLE_OVERRIDES = {
    "style_references": "检查 Step 3 图片风格参考图",
}

MESSAGE_REPLACEMENTS = [
    ("生成风格参考图", "检查 Step 3 图片风格参考图"),
    ("检查项目级风格参考图", "检查 Step 3 图片风格参考图"),
    ("项目级风格参考图", "Step 3 图片风格参考图"),
    ("Project style references", "Step 3 image style references"),
    ("风格参考图生成失败，继续使用文本风格", "Step 3 图片风格参考图生成失败，继续使用 Step 3 文本图片风格"),
    ("风格参考图已就绪或当前项目不需要自动生成", "Step 3 图片风格参考图已就绪；自动流程不会从项目创建配置生成参考图"),
    ("风格参考图", "Step 3 图片风格参考图"),
]


def _step3_message(value: Any) -> str:
    text = str(value or "")
    for old, new in MESSAGE_REPLACEMENTS:
        text = text.replace(old, new)
    return text


def _normalize_status_titles(status: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(status, dict):
        return status
    for item in status.get("stages", []) or []:
        if not isinstance(item, dict):
            continue
        stage_id = str(item.get("id") or "")
        if stage_id in STAGE_TITLE_OVERRIDES:
            item["title"] = STAGE_TITLE_OVERRIDES[stage_id]
        if item.get("message"):
            item["message"] = _step3_message(item.get("message"))
        if isinstance(item.get("warnings"), list):
            item["warnings"] = [_step3_message(warning) for warning in item["warnings"]]
        if isinstance(item.get("blocking_errors"), list):
            item["blocking_errors"] = [_step3_message(error) for error in item["blocking_errors"]]
    return status


def _patch_stages(module: ModuleType) -> None:
    stages = getattr(module, "STAGES", None)
    if not isinstance(stages, list):
        return
    patched = []
    for stage_id, title in stages:
        patched.append((stage_id, STAGE_TITLE_OVERRIDES.get(stage_id, _step3_message(title))))
    module.STAGES = patched


def _patch_status_helpers(module: ModuleType) -> None:
    if not all(hasattr(module, item) for item in ("_initial_status", "_status_for_project", "_start_stage", "_finish_stage", "_warn_stage", "_fail_stage")):
        return

    original_initial_status = module._initial_status
    original_status_for_project = module._status_for_project
    original_start_stage = module._start_stage
    original_finish_stage = module._finish_stage
    original_warn_stage = module._warn_stage
    original_fail_stage = module._fail_stage

    def step3_initial_status(project_id: str, run_id: str) -> dict[str, Any]:
        return _normalize_status_titles(original_initial_status(project_id, run_id))

    def step3_status_for_project(project: Any, project_id: str) -> dict[str, Any]:
        return _normalize_status_titles(original_status_for_project(project, project_id))

    def step3_start_stage(project: Any, status: dict[str, Any], stage_id: str, message: str = "") -> None:
        return original_start_stage(project, status, stage_id, _step3_message(message))

    def step3_finish_stage(project: Any, status: dict[str, Any], stage_id: str, message: str = "", progress: float = 1.0) -> None:
        return original_finish_stage(project, status, stage_id, _step3_message(message), progress)

    def step3_warn_stage(project: Any, status: dict[str, Any], stage_id: str, warning: str) -> None:
        return original_warn_stage(project, status, stage_id, _step3_message(warning))

    def step3_fail_stage(project: Any, status: dict[str, Any], stage_id: str, error: str) -> None:
        return original_fail_stage(project, status, stage_id, _step3_message(error))

    module._initial_status = step3_initial_status
    module._status_for_project = step3_status_for_project
    module._start_stage = step3_start_stage
    module._finish_stage = step3_finish_stage
    module._warn_stage = step3_warn_stage
    module._fail_stage = step3_fail_stage


def _patch_orchestrator(module: ModuleType) -> bool:
    if getattr(module, PATCH_MARKER, False):
        return True
    required = ("_run_dir",)
    if not all(hasattr(module, item) for item in required):
        return False

    def step3_upstream_image_inputs(project: Any, slide_id: str) -> list[Path]:
        run_dir = module._run_dir(project)
        return [
            run_dir / "planning" / "visual_contract.json",
            run_dir / "planning" / "step3_image_style.json",
            run_dir / "planning" / "project_style_references.json",
            run_dir / "planning" / "storyboard_background.json",
            run_dir / "slides" / slide_id / "visual_prompt.md",
        ]

    def no_project_profile_style_refs(project: Any) -> bool:
        return False

    _patch_stages(module)
    _patch_status_helpers(module)
    module._upstream_image_inputs = step3_upstream_image_inputs
    module._profile_wants_style_refs = no_project_profile_style_refs
    setattr(module, PATCH_MARKER, True)
    return True


def _candidate_modules() -> list[ModuleType]:
    return [
        module
        for module in list(sys.modules.values())
        if isinstance(module, ModuleType) and getattr(module, "__name__", "") == "runtime_one_click_orchestrator"
    ]


def _install_when_ready() -> None:
    def worker() -> None:
        while not os.environ.get("PPT_STUDIO_DISABLE_ONE_CLICK_STEP3_STYLE_PATCH"):
            for module in _candidate_modules():
                try:
                    if _patch_orchestrator(module):
                        return
                except Exception:
                    return
            try:
                import runtime_one_click_orchestrator as orchestrator
                if _patch_orchestrator(orchestrator):
                    return
            except Exception:
                pass
            time.sleep(0.1)
    threading.Thread(name="ppt-one-click-step3-style-patch", target=worker, daemon=True).start()


_install_when_ready()
