"""Run one real topic-to-video one-click job against the configured providers."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server
from fastapi.testclient import TestClient


def require(response, label: str) -> dict:
    try:
        payload = response.json()
    except Exception:
        payload = {}
    if response.status_code >= 400 or (isinstance(payload, dict) and payload.get("success") is False):
        detail = payload.get("detail") or payload.get("message") or response.text
        raise RuntimeError(f"{label} failed: {detail}")
    return payload if isinstance(payload, dict) else {"value": payload}


def write_preflight_report(run_dir: Path, project_id: str) -> None:
    checks = {
        "article": (run_dir / "inputs" / "article.md").exists(),
        "pipeline_profiles": (ROOT / "config" / "pipeline_profiles.yaml").exists(),
        "style_tokens": (ROOT / "config" / "style_tokens.yaml").exists(),
        "ffmpeg": bool(server.resolve_media_tool("ffmpeg")),
        "ffprobe": bool(server.resolve_media_tool("ffprobe")),
        "llm_credentials": bool(str(server.get_setting("llm_api_key") or "").strip()),
        "image_credentials": bool(str(server.get_setting("image_api_key") or "").strip()),
        "tts_credentials": bool(str(server.configured_tts_api_key(server.normalize_tts_provider(server.get_setting("tts_provider", "minimax"))) or "").strip()),
    }
    report = [
        "# One-click preflight report",
        "",
        f"- project_id: `{project_id}`",
        f"- status: `{'passed' if all(checks.values()) else 'blocked'}`",
        "- credentials: presence checked; values were not read into this report",
        "",
        "## Checks",
        "",
        *[f"- {'PASS' if passed else 'FAIL'}: {name}" for name, passed in checks.items()],
        "",
    ]
    path = run_dir / "logs" / "preflight_report.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(report), encoding="utf-8")
    if not all(checks.values()):
        failed = [name for name, passed in checks.items() if not passed]
        raise RuntimeError("preflight failed: " + ", ".join(failed))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", default="为什么睡眠能帮助大脑巩固记忆：从海马体到长期记忆的通俗解释")
    parser.add_argument("--name", default="一键生成优化验收-睡眠与记忆")
    parser.add_argument("--timeout-sec", type=int, default=3600)
    parser.add_argument("--resume-project", default="")
    args = parser.parse_args()

    with TestClient(server.app) as client:
        if args.resume_project:
            project_id = args.resume_project
            project = {}
        else:
            created = require(client.post("/api/projects", json={"name": args.name, "description": "Codex 一键生成优化真实全链路验收"}), "create project")
            project = created.get("project") or {}
            project_id = str(project.get("id") or "")
            if not project_id:
                raise RuntimeError("create project returned no id")
        detail = require(client.get(f"/api/projects/{project_id}"), "project detail")
        run_dir = Path(str(detail.get("run_dir") or project.get("run_dir") or ""))

        if not args.resume_project:
            generated = require(client.post(f"/api/projects/{project_id}/steps/1/generate-article", json={"topic": args.topic}), "generate article")
            article = str(generated.get("content") or "").strip()
            if not article:
                raise RuntimeError("generated article is empty")
            require(client.post(f"/api/projects/{project_id}/steps/1/import", data={"content": article}), "import article")
            write_preflight_report(run_dir, project_id)

        mode = "resume" if args.resume_project else "restart"
        require(client.post(f"/api/projects/{project_id}/one-click-generate", json={"mode": mode}), "start one-click")
        deadline = time.monotonic() + args.timeout_sec
        previous = ""
        while time.monotonic() < deadline:
            result = require(client.get(f"/api/projects/{project_id}/one-click-generate/status"), "one-click status")
            status = result.get("status") or {}
            marker = f"{status.get('status')}:{status.get('current_stage')}:{status.get('updated_at')}"
            if marker != previous:
                print(marker, flush=True)
                previous = marker
            if status.get("status") in {"completed", "paused"}:
                summary_path = run_dir / "logs" / "one_click_e2e_result.json"
                summary_path.parent.mkdir(parents=True, exist_ok=True)
                summary_path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                print(json.dumps({"project_id": project_id, "run_dir": str(run_dir), "status": status.get("status"), "result": str(summary_path)}, ensure_ascii=False))
                return 0 if status.get("status") == "completed" else 2
            time.sleep(2.5)
        raise TimeoutError(f"one-click job timed out after {args.timeout_sec}s: {project_id}")


if __name__ == "__main__":
    raise SystemExit(main())
