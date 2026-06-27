"""Step 3 visual draft quality API.

This runtime bridge exposes a read-only project endpoint that runs the same
Mask-friendly white-background checks as ``scripts/check_visual_draft_quality.py``.
It helps users find problematic Step 3 images before entering Step 5 Mask work.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from types import ModuleType
from typing import Any

PATCH_MARKER = "__ppt_visual_draft_quality_patch__"
INSTALL_TIMEOUT_SEC = 120.0
POLL_INTERVAL_SEC = 0.1


def _project_run_dir(project: Any) -> Path:
    run_dir = getattr(project, "run_dir", "") or ""
    if not run_dir:
        raise ValueError("Project run_dir is empty")
    return Path(run_dir)


def _register(server_module: ModuleType) -> bool:
    app = getattr(server_module, "app", None)
    Project = getattr(server_module, "Project", None)
    HTTPException = getattr(server_module, "HTTPException", None)
    Depends = getattr(server_module, "Depends", None)
    get_db = getattr(server_module, "get_db", None)
    if any(value is None for value in (app, Project, HTTPException, Depends, get_db)):
        return False
    if getattr(server_module, PATCH_MARKER, False):
        return True

    def check_step3_visual_draft_quality(project_id: str, db: Any = Depends(get_db)) -> dict[str, Any]:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        try:
            from scripts.check_visual_draft_quality import check_run_dir

            report = check_run_dir(_project_run_dir(project))
        except Exception as exc:
            return {
                "success": False,
                "project_id": project_id,
                "error": f"{type(exc).__name__}: {exc}",
                "checked_count": 0,
                "failed_count": 0,
                "results": [],
            }
        report["project_id"] = project_id
        return report

    app.add_api_route(
        "/api/projects/{project_id}/steps/3/visual-draft-quality",
        check_step3_visual_draft_quality,
        methods=["GET"],
    )
    setattr(server_module, PATCH_MARKER, True)
    return True


def _candidate_modules() -> list[ModuleType]:
    return [module for module in list(sys.modules.values()) if isinstance(module, ModuleType) and hasattr(module, "app")]


def _install_when_ready() -> None:
    def worker() -> None:
        started_at = time.monotonic()
        while not os.environ.get("PPT_STUDIO_DISABLE_VISUAL_DRAFT_QUALITY"):
            for module in _candidate_modules():
                try:
                    if _register(module):
                        return
                except Exception:
                    return
            if time.monotonic() - started_at > INSTALL_TIMEOUT_SEC:
                return
            time.sleep(POLL_INTERVAL_SEC)

    threading.Thread(name="ppt-visual-draft-quality", target=worker, daemon=True).start()


_install_when_ready()
