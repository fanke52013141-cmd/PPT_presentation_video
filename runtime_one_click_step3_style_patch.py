"""One-click compatibility patch for Step 3 image style ownership.

Project creation no longer owns image style. This patch keeps the existing
orchestrator but changes its style-related decisions so image regeneration reacts
to ``planning/step3_image_style.json`` and One-click no longer auto-generates
reference images from Project Profile defaults.
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
