#!/usr/bin/env python3
"""Rebuild reveal assets and bind them ahead of narration for one project."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PPT_STUDIO_DISABLE_ONE_CLICK_ORCHESTRATOR", "1")

import server  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_id")
    args = parser.parse_args()
    db = next(server.get_db())
    try:
        project = db.query(server.Project).filter(server.Project.id == args.project_id).first()
        if project is None:
            raise SystemExit(f"Project not found: {args.project_id}")
        server.build_current_reveal_assets(project)
        bind_script = ROOT / "scripts" / "bind_reveal_timeline.py"
        result = subprocess.run(
            [
                sys.executable,
                str(bind_script),
                "--run-dir",
                project.run_dir,
                "--lead-sec",
                str(server.REVEAL_VISUAL_LEAD_SEC),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=server.STEP7_BIND_TIMEOUT_SEC,
        )
        if result.returncode != 0:
            raise SystemExit(result.stderr or result.stdout)
        print(json.dumps({"success": True, "project_id": project.id, "run_dir": project.run_dir}, ensure_ascii=False))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
