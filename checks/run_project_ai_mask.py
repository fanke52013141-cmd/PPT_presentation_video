#!/usr/bin/env python3
"""Run the production AI Mask pipeline for one existing local project."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PPT_STUDIO_DISABLE_ONE_CLICK_ORCHESTRATOR", "1")

import server  # noqa: E402
from ai_mask_service import get_ai_mask_task_service  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_id")
    args = parser.parse_args()
    db = next(server.get_db())
    try:
        project = db.query(server.Project).filter(server.Project.id == args.project_id).first()
        if project is None:
            raise SystemExit(f"Project not found: {args.project_id}")
        result = get_ai_mask_task_service().annotate_project(project)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
