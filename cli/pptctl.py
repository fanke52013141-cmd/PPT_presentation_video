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

    try:
        result = client.set_source(args.project, content=content, topic=args.topic)
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
            stop_at=args.stop_at,
            mode=args.mode,
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


def cmd_run_resume(args: argparse.Namespace) -> None:
    client = AgentClient(base_url=args.base_url, app_token=args.token)
    try:
        result = client.resume_pipeline(args.project, stop_at=args.stop_at)
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
        result = client.approve_checkpoint(args.project, args.checkpoint, approved=not args.reject)
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
        result = client.regenerate_image(args.project, args.slide, args.instruction)
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
        result = client.update_narration(args.project, args.slide, args.text)
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
        result = client.synthesize_tts(args.project)
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
        result = client.render_video(args.project)
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
    p_update.set_defaults(func=cmd_project_update)

    # source
    src_parser = subparsers.add_parser("source", help="Set project source")
    src_sub = src_parser.add_subparsers(dest="subcommand", required=True)

    s_set = src_sub.add_parser("set", help="Set article content or topic")
    s_set.add_argument("--project", required=True)
    s_set.add_argument("--file", default=None, help="Path to article file (Markdown)")
    s_set.add_argument("--content", default=None, help="Direct article text")
    s_set.add_argument("--topic", default=None, help="Topic for AI generation")
    s_set.set_defaults(func=cmd_source_set)

    # run
    run_parser = subparsers.add_parser("run", help="Pipeline operations")
    run_sub = run_parser.add_subparsers(dest="subcommand", required=True)

    r_start = run_sub.add_parser("start", help="Start pipeline")
    r_start.add_argument("--project", required=True)
    r_start.add_argument("--stop-at", default=None)
    r_start.add_argument("--mode", default="resume")
    r_start.set_defaults(func=cmd_run_start)

    r_status = run_sub.add_parser("status", help="Get pipeline status")
    r_status.add_argument("--project", required=True)
    r_status.set_defaults(func=cmd_run_status)

    r_resume = run_sub.add_parser("resume", help="Resume pipeline")
    r_resume.add_argument("--project", required=True)
    r_resume.add_argument("--stop-at", default=None)
    r_resume.set_defaults(func=cmd_run_resume)

    # approve
    ap_parser = subparsers.add_parser("approve", help="Approve/reject checkpoint")
    ap_parser.add_argument("--project", required=True)
    ap_parser.add_argument("--checkpoint", required=True)
    ap_parser.add_argument("--reject", action="store_true")
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
    i_regen.set_defaults(func=cmd_image_regenerate)

    # narration
    nar_parser = subparsers.add_parser("narration", help="Narration operations")
    nar_sub = nar_parser.add_subparsers(dest="subcommand", required=True)

    n_update = nar_sub.add_parser("update", help="Update narration text")
    n_update.add_argument("--project", required=True)
    n_update.add_argument("--slide", required=True)
    n_update.add_argument("--text", required=True)
    n_update.set_defaults(func=cmd_narration_update)

    # tts
    tts_parser = subparsers.add_parser("tts", help="TTS operations")
    tts_sub = tts_parser.add_subparsers(dest="subcommand", required=True)

    t_synth = tts_sub.add_parser("synthesize", help="Synthesize audio")
    t_synth.add_argument("--project", required=True)
    t_synth.set_defaults(func=cmd_tts_synthesize)

    # video
    vid_parser = subparsers.add_parser("video", help="Video operations")
    vid_sub = vid_parser.add_subparsers(dest="subcommand", required=True)

    v_render = vid_sub.add_parser("render", help="Render video")
    v_render.add_argument("--project", required=True)
    v_render.set_defaults(func=cmd_video_render)

    # artifacts
    art_parser = subparsers.add_parser("artifacts", help="Artifact operations")
    art_sub = art_parser.add_subparsers(dest="subcommand", required=True)

    a_list = art_sub.add_parser("list", help="List artifacts")
    a_list.add_argument("--project", required=True)
    a_list.add_argument("--type", default=None)
    a_list.add_argument("--slide", default=None)
    a_list.set_defaults(func=cmd_artifacts_list)

    # diagnostics
    diag_parser = subparsers.add_parser("diagnostics", help="System diagnostics")
    diag_parser.set_defaults(func=cmd_diagnostics)

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
