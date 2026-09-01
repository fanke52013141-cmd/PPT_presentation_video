#!/usr/bin/env python3
"""pptctl — PPT Studio CLI for Agent API operations.

This CLI is a thin wrapper around AgentClient. It does NOT access the
database or project files directly. Use it for:
- Local debugging and troubleshooting
- Batch automation scripts
- CI/CD integration
- Manual API testing

Examples:
    pptctl project create --name "测试" --canvas portrait_9_16
    pptctl project list --status active
    pptctl project show abc123_143022
    pptctl source set --project abc123 --file article.md
    pptctl source set --project abc123 --topic "人工智能的未来"
    pptctl run start --project abc123 --stop-at image_review
    pptctl run status --project abc123
    pptctl run resume --project abc123
    pptctl approve --project abc123 --checkpoint image_review
    pptctl stage get --project abc123 --stage storyboard
    pptctl image regenerate --project abc123 --slide slide_001 --instruction "更有冲击力"
    pptctl narration update --project abc123 --slide slide_001 --text "新旁白内容"
    pptctl tts synthesize --project abc123
    pptctl video render --project abc123
    pptctl artifacts list --project abc123 --type image
    pptctl artifact get --project abc123 --artifact artifact_id
    pptctl diagnostics
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Optional

# Add repo root to path for agent_client import
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from agent_client.client import AgentClient, AgentClientError, DEFAULT_BASE_URL


# This explicit map is intentionally test-visible.  A capability registered
# for Agent use must also be reachable from the CLI, and CI compares this map
# with the capability registry.
CLI_COMMANDS = {
    "project create",
    "project list",
    "project show",
    "project update",
    "source set",
    "run start",
    "run status",
    "run stream",
    "run resume",
    "approve",
    "stage get",
    "image regenerate",
    "narration update",
    "tts synthesize",
    "video render",
    "artifacts list",
    "artifact get",
    "diagnostics",
    "digital-human config",
    "digital-human config --set",
    "digital-human health",
    "digital-human generate",
    "batch status",
    "batch render",
    "batch cleanup",
}


def _print_json(data: Any) -> None:
    """Pretty-print JSON output."""
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _print_error(msg: str) -> None:
    """Print error message to stderr."""
    print(f"Error: {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Project commands
# ---------------------------------------------------------------------------

def cmd_project_create(args: argparse.Namespace) -> None:
    client = AgentClient(base_url=args.base_url, app_token=args.token)
    try:
        result = client.create_project(
            name=args.name,
            description=args.description or "",
            canvas_profile=args.canvas,
            automation_mode=args.mode,
            review_policy=args.review_policy,
            idempotency_key=args.idempotency_key,
        )
        _print_json(result)
    except AgentClientError as e:
        _print_error(str(e))
        sys.exit(1)


def cmd_project_list(args: argparse.Namespace) -> None:
    client = AgentClient(base_url=args.base_url, app_token=args.token)
    try:
        result = client.list_projects(status=args.status, limit=args.limit)
        _print_json(result)
    except AgentClientError as e:
        _print_error(str(e))
        sys.exit(1)


def cmd_project_show(args: argparse.Namespace) -> None:
    client = AgentClient(base_url=args.base_url, app_token=args.token)
    try:
        result = client.get_project(args.project)
        _print_json(result)
    except AgentClientError as e:
        _print_error(str(e))
        sys.exit(1)


def cmd_project_update(args: argparse.Namespace) -> None:
    client = AgentClient(base_url=args.base_url, app_token=args.token)
    try:
        result = client.update_project(
            args.project,
            name=args.name,
            description=args.description,
            ai_mode=args.ai_mode,
            expected_revision=args.expected_revision,
            idempotency_key=args.idempotency_key,
        )
        _print_json(result)
    except AgentClientError as e:
        _print_error(str(e))
        sys.exit(1)


# ---------------------------------------------------------------------------
# Source commands
# ---------------------------------------------------------------------------

def cmd_source_set(args: argparse.Namespace) -> None:
    client = AgentClient(base_url=args.base_url, app_token=args.token)
    content = None
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            content = f.read()
    elif args.content:
        content = args.content

    supplied = sum(bool(value) for value in (content, args.topic))
    if supplied != 1:
        _print_error("Provide exactly one of --file/--content or --topic")
        sys.exit(2)

    try:
        result = client.set_source(args.project, content=content, topic=args.topic, idempotency_key=args.idempotency_key)
        _print_json(result)
    except AgentClientError as e:
        _print_error(str(e))
        sys.exit(1)


# ---------------------------------------------------------------------------
# Pipeline run commands
# ---------------------------------------------------------------------------

def cmd_run_start(args: argparse.Namespace) -> None:
    client = AgentClient(base_url=args.base_url, app_token=args.token)
    try:
        result = client.start_pipeline(
            args.project,
            start_from=args.start_from,
            stop_at=args.stop_at,
            mode=args.mode,
            idempotency_key=args.idempotency_key,
        )
        _print_json(result)
    except AgentClientError as e:
        _print_error(str(e))
        sys.exit(1)


def cmd_run_status(args: argparse.Namespace) -> None:
    client = AgentClient(base_url=args.base_url, app_token=args.token)
    try:
        result = client.get_pipeline_status(args.project)
        _print_json(result)
    except AgentClientError as e:
        _print_error(str(e))
        sys.exit(1)


def cmd_run_stream(args: argparse.Namespace) -> None:
    """Poll pipeline status until terminal, printing each state change."""
    import time

    terminal_states = frozenset({
        "completed", "failed", "waiting_for_review", "idle", "paused",
    })
    interval = getattr(args, "interval", 1.0)
    max_polls = getattr(args, "max_polls", 1800)
    client = AgentClient(base_url=args.base_url, app_token=args.token)
    last_fingerprint: Optional[str] = None
    try:
        for _ in range(max_polls):
            result = client.get_pipeline_status(args.project)
            status = result.get("status", "unknown")
            stage = result.get("current_stage", "")
            run_id = result.get("run_id", "")
            fingerprint = f"{status}|{stage}|{run_id}"
            if fingerprint != last_fingerprint:
                _print_json(result)
                last_fingerprint = fingerprint
            if status in terminal_states:
                break
            time.sleep(interval)
        else:
            _print_error("Max polls reached; pipeline still running")
    except AgentClientError as e:
        _print_error(str(e))
        sys.exit(1)


def cmd_run_resume(args: argparse.Namespace) -> None:
    client = AgentClient(base_url=args.base_url, app_token=args.token)
    try:
        result = client.resume_pipeline(args.project, stop_at=args.stop_at, idempotency_key=args.idempotency_key)
        _print_json(result)
    except AgentClientError as e:
        _print_error(str(e))
        sys.exit(1)


# ---------------------------------------------------------------------------
# Checkpoint commands
# ---------------------------------------------------------------------------

def cmd_approve(args: argparse.Namespace) -> None:
    client = AgentClient(base_url=args.base_url, app_token=args.token)
    try:
        result = client.approve_checkpoint(args.project, args.checkpoint, approved=not args.reject, notes=args.notes, idempotency_key=args.idempotency_key)
        _print_json(result)
    except AgentClientError as e:
        _print_error(str(e))
        sys.exit(1)


# ---------------------------------------------------------------------------
# Stage commands
# ---------------------------------------------------------------------------

def cmd_stage_get(args: argparse.Namespace) -> None:
    client = AgentClient(base_url=args.base_url, app_token=args.token)
    try:
        result = client.get_stage(args.project, args.stage)
        _print_json(result)
    except AgentClientError as e:
        _print_error(str(e))
        sys.exit(1)


# ---------------------------------------------------------------------------
# Image commands
# ---------------------------------------------------------------------------

def cmd_image_regenerate(args: argparse.Namespace) -> None:
    client = AgentClient(base_url=args.base_url, app_token=args.token)
    try:
        result = client.regenerate_image(args.project, args.slide, args.instruction, idempotency_key=args.idempotency_key)
        _print_json(result)
    except AgentClientError as e:
        _print_error(str(e))
        sys.exit(1)


# ---------------------------------------------------------------------------
# Narration commands
# ---------------------------------------------------------------------------

def cmd_narration_update(args: argparse.Namespace) -> None:
    client = AgentClient(base_url=args.base_url, app_token=args.token)
    try:
        result = client.update_narration(args.project, args.slide, args.text, expected_revision=args.expected_revision, idempotency_key=args.idempotency_key)
        _print_json(result)
    except AgentClientError as e:
        _print_error(str(e))
        sys.exit(1)


# ---------------------------------------------------------------------------
# TTS commands
# ---------------------------------------------------------------------------

def cmd_tts_synthesize(args: argparse.Namespace) -> None:
    client = AgentClient(base_url=args.base_url, app_token=args.token)
    try:
        result = client.synthesize_tts(args.project, idempotency_key=args.idempotency_key)
        _print_json(result)
    except AgentClientError as e:
        _print_error(str(e))
        sys.exit(1)


# ---------------------------------------------------------------------------
# Video commands
# ---------------------------------------------------------------------------

def cmd_video_render(args: argparse.Namespace) -> None:
    client = AgentClient(base_url=args.base_url, app_token=args.token)
    try:
        result = client.render_video(args.project, idempotency_key=args.idempotency_key)
        _print_json(result)
    except AgentClientError as e:
        _print_error(str(e))
        sys.exit(1)


# ---------------------------------------------------------------------------
# Artifacts commands
# ---------------------------------------------------------------------------

def cmd_artifacts_list(args: argparse.Namespace) -> None:
    client = AgentClient(base_url=args.base_url, app_token=args.token)
    try:
        result = client.list_artifacts(args.project, artifact_type=args.type, slide_id=args.slide)
        _print_json(result)
    except AgentClientError as e:
        _print_error(str(e))
        sys.exit(1)


def cmd_artifact_get(args: argparse.Namespace) -> None:
    client = AgentClient(base_url=args.base_url, app_token=args.token)
    try:
        result = client.get_artifact(args.project, args.artifact)
        _print_json(result)
    except AgentClientError as e:
        _print_error(str(e))
        sys.exit(1)


# ---------------------------------------------------------------------------
# Diagnostics commands
# ---------------------------------------------------------------------------

def cmd_diagnostics(args: argparse.Namespace) -> None:
    client = AgentClient(base_url=args.base_url, app_token=args.token)
    try:
        result = client.get_diagnostics()
        _print_json(result)
    except AgentClientError as e:
        _print_error(str(e))
        sys.exit(1)


# ---------------------------------------------------------------------------
# Digital Human commands
# ---------------------------------------------------------------------------

def cmd_digital_human_config(args: argparse.Namespace) -> None:
    client = AgentClient(base_url=args.base_url, app_token=args.token)
    try:
        if getattr(args, "set", None):
            body = json.loads(args.set)
            result = client.update_digital_human_config(args.project, body)
        else:
            result = client.get_digital_human_config(args.project)
        _print_json(result)
    except AgentClientError as e:
        _print_error(str(e))
        sys.exit(1)


def cmd_digital_human_health(args: argparse.Namespace) -> None:
    client = AgentClient(base_url=args.base_url, app_token=args.token)
    try:
        result = client.check_digital_human_health(args.project)
        _print_json(result)
    except AgentClientError as e:
        _print_error(str(e))
        sys.exit(1)


def cmd_digital_human_generate(args: argparse.Namespace) -> None:
    client = AgentClient(base_url=args.base_url, app_token=args.token)
    try:
        result = client.generate_digital_human(args.project)
        _print_json(result)
    except AgentClientError as e:
        _print_error(str(e))
        sys.exit(1)


# ---------------------------------------------------------------------------
# Batch commands
# ---------------------------------------------------------------------------

def cmd_batch_status(args: argparse.Namespace) -> None:
    """Get pipeline status for all (or filtered) projects in one call."""
    client = AgentClient(base_url=args.base_url, app_token=args.token)
    try:
        projects = client.list_projects(status_filter=args.status)
        project_list = projects.get("projects", projects) if isinstance(projects, dict) else projects
        results = []
        errors = []
        for proj in project_list:
            pid = proj.get("project_id", proj.get("id", "")) if isinstance(proj, dict) else str(proj)
            if not pid:
                continue
            try:
                status = client.get_pipeline_status(pid)
                results.append({"project_id": pid, "status": status})
            except AgentClientError as e:
                errors.append({"project_id": pid, "error": str(e)})
        _print_json({"results": results, "errors": errors, "total": len(results)})
    except AgentClientError as e:
        _print_error(str(e))
        sys.exit(1)


def cmd_batch_render(args: argparse.Namespace) -> None:
    """Submit video render jobs for all ready projects."""
    client = AgentClient(base_url=args.base_url, app_token=args.token)
    try:
        projects = client.list_projects()
        project_list = projects.get("projects", projects) if isinstance(projects, dict) else projects
        results = []
        errors = []
        for proj in project_list:
            pid = proj.get("project_id", proj.get("id", "")) if isinstance(proj, dict) else str(proj)
            if not pid:
                continue
            try:
                result = client.render_video(pid, speed=args.speed)
                results.append({"project_id": pid, "result": result})
            except AgentClientError as e:
                errors.append({"project_id": pid, "error": str(e)})
        _print_json({"results": results, "errors": errors, "total": len(results)})
    except AgentClientError as e:
        _print_error(str(e))
        sys.exit(1)


def cmd_batch_cleanup(args: argparse.Namespace) -> None:
    """Delete completed or all projects (destructive)."""
    client = AgentClient(base_url=args.base_url, app_token=args.token)
    try:
        projects = client.list_projects(status_filter=args.status)
        project_list = projects.get("projects", projects) if isinstance(projects, dict) else projects
        results = []
        errors = []
        for proj in project_list:
            pid = proj.get("project_id", proj.get("id", "")) if isinstance(proj, dict) else str(proj)
            if not pid:
                continue
            try:
                result = client.delete_project(pid)
                results.append({"project_id": pid, "deleted": True})
            except AgentClientError as e:
                errors.append({"project_id": pid, "error": str(e)})
        _print_json({"deleted": results, "errors": errors, "total": len(results)})
    except AgentClientError as e:
        _print_error(str(e))
        sys.exit(1)


def cmd_meta(args: argparse.Namespace) -> None:
    client = AgentClient(base_url=args.base_url, app_token=args.token)
    try:
        result = client.get_meta()
        _print_json(result)
    except AgentClientError as e:
        _print_error(str(e))
        sys.exit(1)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pptctl",
        description="PPT Studio CLI — Agent API operations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Agent API base URL")
    parser.add_argument("--token", default=os.environ.get("PPT_APP_TOKEN", ""), help="App token")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # project
    proj_parser = subparsers.add_parser("project", help="Project management")
    proj_sub = proj_parser.add_subparsers(dest="subcommand", required=True)

    p_create = proj_sub.add_parser("create", help="Create a new project")
    p_create.add_argument("--name", required=True)
    p_create.add_argument("--description", default="")
    p_create.add_argument("--canvas", default="landscape_16_9", choices=["landscape_16_9", "portrait_9_16"])
    p_create.add_argument("--mode", default="auto", choices=["auto", "manual", "agent"])
    p_create.add_argument("--review-policy", default="none", choices=["none", "images_and_video", "all_stages"], help="Review policy for checkpoint approval")
    p_create.add_argument("--idempotency-key", default=None, help="Idempotency key to prevent duplicate creation")
    p_create.set_defaults(func=cmd_project_create)

    p_list = proj_sub.add_parser("list", help="List projects")
    p_list.add_argument("--status", default=None)
    p_list.add_argument("--limit", type=int, default=50)
    p_list.set_defaults(func=cmd_project_list)

    p_show = proj_sub.add_parser("show", help="Show project details")
    p_show.add_argument("--project", required=True)
    p_show.set_defaults(func=cmd_project_show)

    p_update = proj_sub.add_parser("update", help="Update project")
    p_update.add_argument("--project", required=True)
    p_update.add_argument("--name", default=None)
    p_update.add_argument("--description", default=None)
    p_update.add_argument("--ai-mode", default=None)
    p_update.add_argument("--expected-revision", type=int, default=None, help="Optimistic lock: expected project revision")
    p_update.add_argument("--idempotency-key", default=None, help="Idempotency key to prevent duplicate updates")
    p_update.set_defaults(func=cmd_project_update)

    # source
    src_parser = subparsers.add_parser("source", help="Set project source")
    src_sub = src_parser.add_subparsers(dest="subcommand", required=True)

    s_set = src_sub.add_parser("set", help="Set article content or topic")
    s_set.add_argument("--project", required=True)
    s_set.add_argument("--file", default=None, help="Path to article file (Markdown)")
    s_set.add_argument("--content", default=None, help="Direct article text")
    s_set.add_argument("--topic", default=None, help="Topic for AI generation")
    s_set.add_argument("--idempotency-key", default=None, help="Idempotency key to prevent duplicate operations")
    s_set.set_defaults(func=cmd_source_set)

    # run
    run_parser = subparsers.add_parser("run", help="Pipeline operations")
    run_sub = run_parser.add_subparsers(dest="subcommand", required=True)

    r_start = run_sub.add_parser("start", help="Start pipeline")
    r_start.add_argument("--project", required=True)
    r_start.add_argument("--start-from", default=None)
    r_start.add_argument("--stop-at", default=None)
    r_start.add_argument("--mode", default="resume")
    r_start.add_argument("--idempotency-key", default=None, help="Idempotency key to prevent duplicate pipeline starts")
    r_start.set_defaults(func=cmd_run_start)

    r_status = run_sub.add_parser("status", help="Get pipeline status")
    r_status.add_argument("--project", required=True)
    r_status.set_defaults(func=cmd_run_status)

    r_stream = run_sub.add_parser("stream", help="Stream pipeline progress via polling")
    r_stream.add_argument("--project", required=True)
    r_stream.add_argument("--interval", type=float, default=1.0, help="Polling interval in seconds")
    r_stream.add_argument("--max-polls", type=int, default=1800, help="Maximum number of polling iterations")
    r_stream.set_defaults(func=cmd_run_stream)

    r_resume = run_sub.add_parser("resume", help="Resume pipeline")
    r_resume.add_argument("--project", required=True)
    r_resume.add_argument("--stop-at", default=None)
    r_resume.add_argument("--idempotency-key", default=None, help="Idempotency key to prevent duplicate resumes")
    r_resume.set_defaults(func=cmd_run_resume)

    # approve
    ap_parser = subparsers.add_parser("approve", help="Approve/reject checkpoint")
    ap_parser.add_argument("--project", required=True)
    ap_parser.add_argument("--checkpoint", required=True)
    ap_parser.add_argument("--reject", action="store_true")
    ap_parser.add_argument("--notes", default="", help="Notes for rejection")
    ap_parser.add_argument("--idempotency-key", default=None, help="Idempotency key to prevent duplicate approvals")
    ap_parser.set_defaults(func=cmd_approve)

    # stage
    st_parser = subparsers.add_parser("stage", help="Get stage data")
    st_sub = st_parser.add_subparsers(dest="subcommand", required=True)

    st_get = st_sub.add_parser("get", help="Get stage details")
    st_get.add_argument("--project", required=True)
    st_get.add_argument("--stage", required=True)
    st_get.set_defaults(func=cmd_stage_get)

    # image
    img_parser = subparsers.add_parser("image", help="Image operations")
    img_sub = img_parser.add_subparsers(dest="subcommand", required=True)

    i_regen = img_sub.add_parser("regenerate", help="Regenerate slide image")
    i_regen.add_argument("--project", required=True)
    i_regen.add_argument("--slide", required=True)
    i_regen.add_argument("--instruction", default="")
    i_regen.add_argument("--idempotency-key", default=None, help="Idempotency key to prevent duplicate regeneration")
    i_regen.set_defaults(func=cmd_image_regenerate)

    # narration
    nar_parser = subparsers.add_parser("narration", help="Narration operations")
    nar_sub = nar_parser.add_subparsers(dest="subcommand", required=True)

    n_update = nar_sub.add_parser("update", help="Update narration text")
    n_update.add_argument("--project", required=True)
    n_update.add_argument("--slide", required=True)
    n_update.add_argument("--text", required=True)
    n_update.add_argument("--expected-revision", type=int, default=None, help="Optimistic lock: expected project revision")
    n_update.add_argument("--idempotency-key", default=None, help="Idempotency key to prevent duplicate updates")
    n_update.set_defaults(func=cmd_narration_update)

    # tts
    tts_parser = subparsers.add_parser("tts", help="TTS operations")
    tts_sub = tts_parser.add_subparsers(dest="subcommand", required=True)

    t_synth = tts_sub.add_parser("synthesize", help="Synthesize audio")
    t_synth.add_argument("--project", required=True)
    t_synth.add_argument("--idempotency-key", default=None, help="Idempotency key to prevent duplicate synthesis")
    t_synth.set_defaults(func=cmd_tts_synthesize)

    # video
    vid_parser = subparsers.add_parser("video", help="Video operations")
    vid_sub = vid_parser.add_subparsers(dest="subcommand", required=True)

    v_render = vid_sub.add_parser("render", help="Render video")
    v_render.add_argument("--project", required=True)
    v_render.add_argument("--idempotency-key", default=None, help="Idempotency key to prevent duplicate renders")
    v_render.set_defaults(func=cmd_video_render)

    # artifacts
    art_parser = subparsers.add_parser("artifacts", help="Artifact operations")
    art_sub = art_parser.add_subparsers(dest="subcommand", required=True)

    a_list = art_sub.add_parser("list", help="List artifacts")
    a_list.add_argument("--project", required=True)
    a_list.add_argument("--type", default=None)
    a_list.add_argument("--slide", default=None)
    a_list.set_defaults(func=cmd_artifacts_list)

    artifact_parser = subparsers.add_parser("artifact", help="Get a single artifact")
    artifact_sub = artifact_parser.add_subparsers(dest="subcommand", required=True)
    a_get = artifact_sub.add_parser("get", help="Get artifact details and download URL")
    a_get.add_argument("--project", required=True)
    a_get.add_argument("--artifact", required=True)
    a_get.set_defaults(func=cmd_artifact_get)

    # diagnostics
    diag_parser = subparsers.add_parser("diagnostics", help="System diagnostics")
    diag_parser.set_defaults(func=cmd_diagnostics)

    # digital-human
    dh_parser = subparsers.add_parser("digital-human", help="Digital human operations")
    dh_sub = dh_parser.add_subparsers(dest="dh_action")

    dh_config = dh_sub.add_parser("config", help="Get or update digital-human config")
    dh_config.add_argument("--project", required=True)
    dh_config.add_argument("--set", default=None, help="JSON string to update config (PATCH)")
    dh_config.set_defaults(func=cmd_digital_human_config)

    dh_health = dh_sub.add_parser("health", help="Check digital-human service health")
    dh_health.add_argument("--project", required=True)
    dh_health.set_defaults(func=cmd_digital_human_health)

    dh_gen = dh_sub.add_parser("generate", help="Generate digital-human videos for all slides")
    dh_gen.add_argument("--project", required=True)
    dh_gen.set_defaults(func=cmd_digital_human_generate)

    # batch
    batch_parser = subparsers.add_parser("batch", help="Batch operations across multiple projects")
    batch_sub = batch_parser.add_subparsers(dest="batch_action", required=True)

    b_status = batch_sub.add_parser("status", help="Get pipeline status for all projects")
    b_status.add_argument("--status", default=None, help="Filter by project status")
    b_status.set_defaults(func=cmd_batch_status)

    b_render = batch_sub.add_parser("render", help="Submit video render for all projects")
    b_render.add_argument("--speed", default="1.0", help="Playback speed (e.g. 1.0, 1.25)")
    b_render.set_defaults(func=cmd_batch_render)

    b_cleanup = batch_sub.add_parser("cleanup", help="Delete projects (destructive)")
    b_cleanup.add_argument("--status", default="completed", help="Filter projects to delete by status")
    b_cleanup.set_defaults(func=cmd_batch_cleanup)

    # meta
    meta_parser = subparsers.add_parser("meta", help="Agent API metadata")
    meta_parser.set_defaults(func=cmd_meta)

    return parser


def main(argv: Optional[list[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
