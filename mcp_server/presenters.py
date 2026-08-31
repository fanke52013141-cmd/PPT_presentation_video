"""Media presenters — format artifacts for MCP tool responses.

MCP tool responses can include text, image, and audio content blocks.
This module converts API artifact data into MCP-friendly content blocks.
"""

from __future__ import annotations

import base64
from typing import Any, Optional


def present_artifact_as_text(artifact: dict[str, Any]) -> dict[str, Any]:
    """Format an artifact dict as a text content block with key info."""
    lines = [
        f"Artifact ID: {artifact.get('artifact_id', 'N/A')}",
        f"Type: {artifact.get('artifact_type', 'N/A')}",
        f"Filename: {artifact.get('filename', 'N/A')}",
        f"MIME: {artifact.get('mime_type', 'N/A')}",
        f"Size: {artifact.get('size_bytes', 0)} bytes",
        f"Resource URI: {artifact.get('resource_uri', 'N/A')}",
    ]
    if artifact.get("slide_id"):
        lines.append(f"Slide: {artifact['slide_id']}")
    if artifact.get("revision"):
        lines.append(f"Revision: {artifact['revision']}")
    if artifact.get("download_url"):
        lines.append(f"Download: {artifact['download_url']}")
    return {"type": "text", "text": "\n".join(lines)}


def present_artifact_list_as_text(
    project_id: str,
    artifacts: list[dict[str, Any]],
    title: str = "Artifacts",
) -> dict[str, Any]:
    """Format a list of artifacts as a summary text block."""
    lines = [f"## {title} ({len(artifacts)} items)", ""]
    for a in artifacts:
        sid = a.get("slide_id", "-")
        lines.append(
            f"- [{a.get('artifact_type', '?')}] {a.get('filename', '?')} "
            f"(slide={sid}, id={a.get('artifact_id', '?')[:12]}...)"
        )
    return {"type": "text", "text": "\n".join(lines)}


def present_operation_status(op: dict[str, Any]) -> dict[str, Any]:
    """Format an operation status dict as a readable text block."""
    lines = [
        f"Operation: {op.get('operation_id', 'N/A')}",
        f"Type: {op.get('operation_type', 'N/A')}",
        f"Status: {op.get('status', 'N/A')}",
    ]
    if op.get("stage"):
        lines.append(f"Stage: {op['stage']}")
    if op.get("progress") is not None:
        lines.append(f"Progress: {op['progress']}%")
    if op.get("message"):
        lines.append(f"Message: {op['message']}")
    if op.get("blocking_errors"):
        lines.append(f"Blocking Errors: {op['blocking_errors']}")
    if op.get("warnings"):
        lines.append(f"Warnings: {op['warnings']}")
    return {"type": "text", "text": "\n".join(lines)}


def present_project_summary(project: dict[str, Any]) -> dict[str, Any]:
    """Format a project dict as a readable text block."""
    lines = [
        f"Project: {project.get('name', 'N/A')}",
        f"ID: {project.get('project_id', 'N/A')}",
        f"Canvas: {project.get('canvas_profile', 'N/A')}",
        f"AI Mode: {project.get('ai_mode', 'N/A')}",
    ]
    if project.get("description"):
        lines.append(f"Description: {project['description']}")
    if project.get("current_step"):
        lines.append(f"Current Step: {project['current_step']}")
    if project.get("slide_ids"):
        lines.append(f"Slides: {len(project['slide_ids'])} ({', '.join(project['slide_ids'][:5])}...)")
    return {"type": "text", "text": "\n".join(lines)}


def present_checkpoint_list(
    project_id: str,
    checkpoints: list[dict[str, Any]],
) -> dict[str, Any]:
    """Format a checkpoint list for Agent review."""
    lines = [f"## Checkpoints for project {project_id}", ""]
    for cp in checkpoints:
        status_icon = "✓" if cp.get("approved") else "○"
        lines.append(
            f"{status_icon} {cp.get('checkpoint', '?')} — {cp.get('label', '')} "
            f"[{cp.get('status', 'unknown')}]"
        )
    lines.append("")
    lines.append("Use ppt_checkpoint_approve to approve or reject a checkpoint.")
    return {"type": "text", "text": "\n".join(lines)}


def present_image_for_agent(
    artifact: dict[str, Any],
    image_base64: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Build content blocks for an image artifact.

    If image_base64 is provided, includes an image content block.
    Otherwise, returns text with resource URI for lazy loading.
    """
    blocks: list[dict[str, Any]] = []
    blocks.append(present_artifact_as_text(artifact))
    if image_base64:
        blocks.append({
            "type": "image",
            "data": image_base64,
            "mimeType": artifact.get("mime_type", "image/png"),
        })
    return blocks


def present_contact_sheet(
    project_id: str,
    slides: list[dict[str, Any]],
) -> dict[str, Any]:
    """Format a contact sheet (thumbnail review table) for Agent display."""
    lines = [f"## Contact Sheet — {project_id}", ""]
    lines.append("| # | Slide ID | Image Status | Narration |")
    lines.append("|---|----------|-------------|-----------|")
    for i, s in enumerate(slides, 1):
        img_status = "✓" if s.get("has_image") else "✗"
        has_narration = "✓" if s.get("has_narration") else "✗"
        lines.append(f"| {i} | {s.get('slide_id', '?')} | {img_status} | {has_narration} |")
    lines.append("")
    lines.append("Say which slides need changes (e.g., 'slides 2, 5, 7 need regeneration').")
    return {"type": "text", "text": "\n".join(lines)}
