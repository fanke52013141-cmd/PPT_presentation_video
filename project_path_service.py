"""Validated project/slide artifact path helpers used by workflow services."""

from __future__ import annotations

import logging

from fastapi import HTTPException

from database import Project
from project_storage import (
    UnsafeProjectPath,
    project_run_dir as validated_project_run_dir,
    slide_file as storage_slide_file,
)
from repository_paths import RUNS_DIR
from visual_contract_service import read_contract_slide_ids


logger = logging.getLogger("PPTStudio.ProjectPaths")


def read_current_slide_ids_or_404(project: Project) -> list[str]:
    slide_ids = read_contract_slide_ids(project.run_dir)
    if not slide_ids:
        raise HTTPException(status_code=400, detail="分镜规划尚未生成，请先完成第二步")
    return slide_ids


def project_run_dir_or_500(project: Project) -> str:
    try:
        return str(validated_project_run_dir(RUNS_DIR, project.run_dir, project.id))
    except UnsafeProjectPath as exc:
        logger.error("Unsafe project run directory for %s: %s", project.id, exc)
        raise HTTPException(status_code=500, detail="项目运行目录安全校验失败") from exc


def current_slide_file_or_404(project: Project, slide_id: str, filename: str) -> str:
    run_dir = project_run_dir_or_500(project)
    if slide_id not in read_current_slide_ids_or_404(project):
        raise HTTPException(status_code=404, detail="Slide 不存在")
    try:
        return str(storage_slide_file(run_dir, slide_id, filename))
    except UnsafeProjectPath as exc:
        raise HTTPException(status_code=400, detail="Slide 路径无效") from exc
