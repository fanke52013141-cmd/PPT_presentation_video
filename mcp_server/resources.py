"""MCP Resources — expose project state and artifacts as addressable resources.

Resource URI scheme: ppt://

Supported URIs:
    ppt://projects/{id}/summary       — project summary
    ppt://projects/{id}/slides        — all slides overview
    ppt://projects/{id}/slides/{sid}/image   — slide image
    ppt://projects/{id}/slides/{sid}/audio   — slide audio
    ppt://projects/{id}/videos/latest — latest rendered video
    ppt://projects/{id}/artifacts     — all artifacts
    ppt://projects/{id}/contract      — visual contract JSON

Resources are read-only and fetched via AgentClient.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from agent_client.client import AgentClient


# URI patterns (order matters — most specific first)
_URI_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^ppt://projects/([^/]+)/summary$"), "summary"),
    (re.compile(r"^ppt://projects/([^/]+)/slides$"), "slides"),
    (re.compile(r"^ppt://projects/([^/]+)/slides/([^/]+)/image$"), "slide_image"),
    (re.compile(r"^ppt://projects/([^/]+)/slides/([^/]+)/audio$"), "slide_audio"),
    (re.compile(r"^ppt://projects/([^/]+)/videos/latest$"), "video_latest"),
    (re.compile(r"^ppt://projects/([^/]+)/artifacts$"), "artifacts"),
    (re.compile(r"^ppt://projects/([^/]+)/contract$"), "contract"),
]


def parse_resource_uri(uri: str) -> Optional[tuple[str, str, dict[str, str]]]:
    """Parse a ppt:// URI into (project_id, resource_type, params).

    Returns None if the URI doesn't match any known pattern.
    """
    for pattern, rtype in _URI_PATTERNS:
        m = pattern.match(uri)
        if m:
            groups = m.groups()
            params: dict[str, str] = {}
            if rtype in ("slide_image", "slide_audio"):
                params["project_id"] = groups[0]
                params["slide_id"] = groups[1]
            else:
                params["project_id"] = groups[0]
            return (groups[0], rtype, params)
    return None


def list_resource_templates() -> list[dict[str, Any]]:
    """Return MCP resource template definitions for discovery."""
    return [
        {
            "uriTemplate": "ppt://projects/{project_id}/summary",
            "name": "Project Summary",
            "description": "Get project name, canvas, AI mode, and current step.",
            "mimeType": "application/json",
        },
        {
            "uriTemplate": "ppt://projects/{project_id}/slides",
            "name": "Slides Overview",
            "description": "List all slides with image and narration status.",
            "mimeType": "application/json",
        },
        {
            "uriTemplate": "ppt://projects/{project_id}/slides/{slide_id}/image",
            "name": "Slide Image",
            "description": "Get the generated image for a specific slide.",
            "mimeType": "image/png",
        },
        {
            "uriTemplate": "ppt://projects/{project_id}/slides/{slide_id}/audio",
            "name": "Slide Audio",
            "description": "Get the TTS audio for a specific slide.",
            "mimeType": "audio/mpeg",
        },
        {
            "uriTemplate": "ppt://projects/{project_id}/videos/latest",
            "name": "Latest Video",
            "description": "Get the most recently rendered video.",
            "mimeType": "video/mp4",
        },
        {
            "uriTemplate": "ppt://projects/{project_id}/artifacts",
            "name": "All Artifacts",
            "description": "List all artifacts (images, audio, video, pptx).",
            "mimeType": "application/json",
        },
        {
            "uriTemplate": "ppt://projects/{project_id}/contract",
            "name": "Visual Contract",
            "description": "Get the visual contract JSON for the project.",
            "mimeType": "application/json",
        },
    ]


def read_resource(uri: str, client: AgentClient) -> dict[str, Any]:
    """Read a resource by URI and return MCP-formatted content.

    Returns:
        {"contents": [{"uri": ..., "mimeType": ..., "text": ...}]}
    """
    parsed = parse_resource_uri(uri)
    if parsed is None:
        return {
            "contents": [{
                "uri": uri,
                "mimeType": "text/plain",
                "text": f"Unknown resource URI pattern: {uri}",
            }]
        }

    project_id, rtype, params = parsed

    if rtype == "summary":
        data = client.get_project(project_id)
        return {
            "contents": [{
                "uri": uri,
                "mimeType": "application/json",
                "text": _to_json_text(data),
            }]
        }

    elif rtype == "slides":
        data = client.get_project(project_id)
        return {
            "contents": [{
                "uri": uri,
                "mimeType": "application/json",
                "text": _to_json_text(data),
            }]
        }

    elif rtype == "slide_image":
        artifacts = client.list_artifacts(project_id, artifact_type="image", slide_id=params.get("slide_id"))
        return {
            "contents": [{
                "uri": uri,
                "mimeType": "application/json",
                "text": _to_json_text(artifacts),
            }]
        }

    elif rtype == "slide_audio":
        artifacts = client.list_artifacts(project_id, artifact_type="audio", slide_id=params.get("slide_id"))
        return {
            "contents": [{
                "uri": uri,
                "mimeType": "application/json",
                "text": _to_json_text(artifacts),
            }]
        }

    elif rtype == "video_latest":
        artifacts = client.list_artifacts(project_id, artifact_type="video")
        return {
            "contents": [{
                "uri": uri,
                "mimeType": "application/json",
                "text": _to_json_text(artifacts),
            }]
        }

    elif rtype == "artifacts":
        data = client.list_artifacts(project_id)
        return {
            "contents": [{
                "uri": uri,
                "mimeType": "application/json",
                "text": _to_json_text(data),
            }]
        }

    elif rtype == "contract":
        data = client.get_stage(project_id, "storyboard")
        return {
            "contents": [{
                "uri": uri,
                "mimeType": "application/json",
                "text": _to_json_text(data),
            }]
        }

    return {
        "contents": [{
            "uri": uri,
            "mimeType": "text/plain",
            "text": f"Unsupported resource type: {rtype}",
        }]
    }


def _to_json_text(data: Any) -> str:
    import json
    return json.dumps(data, indent=2, ensure_ascii=False, default=str)
