"""Per-run one-click status paths and identity-checked reads; no app imports."""

from __future__ import annotations

import json
import re
from pathlib import Path


def run_path(project, run_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", run_id):
        raise ValueError("Invalid pipeline run ID")
    return Path(project.run_dir) / "planning" / "one_click_runs" / (run_id + ".json")


def read_run(project, run_id: str) -> dict | None:
    path = run_path(project, run_id)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or data.get("run_id") != run_id or data.get("project_id") != str(project.id):
        raise ValueError("Pipeline run identity mismatch")
    return data


def list_run_ids(project) -> list[str]:
    folder = Path(project.run_dir) / "planning" / "one_click_runs"
    return sorted(path.stem for path in folder.glob("*.json")) if folder.is_dir() else []
