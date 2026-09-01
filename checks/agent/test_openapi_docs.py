"""Tests for OpenAPI/Swagger documentation generation.

Covers:
- build_agent_openapi_spec structure (openapi version, info, paths)
- Each stable capability appears as a path item
- HTTP methods are correctly mapped
- Security schemes are defined
- Swagger UI HTML contains expected elements
- operationId generation
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


# ---------------------------------------------------------------------------
# OpenAPI spec building
# ---------------------------------------------------------------------------

def test_openapi_spec_basic_structure():
    """The spec must have the core OpenAPI 3.0 keys."""
    from agent_api.openapi_docs import build_agent_openapi_spec

    spec = build_agent_openapi_spec()

    assert spec["openapi"].startswith("3.0")
    assert "info" in spec
    assert "paths" in spec
    assert "servers" in spec
    assert isinstance(spec["paths"], dict)
    assert len(spec["paths"]) > 0


def test_openapi_info_metadata():
    """The info section must have title and version."""
    from agent_api.openapi_docs import build_agent_openapi_spec

    info = build_agent_openapi_spec()["info"]
    assert "title" in info
    assert "version" in info
    assert "PPT" in info["title"] or "Agent" in info["title"]


def test_openapi_all_stable_capabilities_present():
    """Every stable capability must appear in the paths."""
    from agent_api.openapi_docs import build_agent_openapi_spec
    from agent_contract.capabilities import get_stable_capabilities

    spec = build_agent_openapi_spec()
    paths = spec["paths"]

    for cap in get_stable_capabilities():
        assert cap.agent_api_path in paths, f"Missing path for {cap.id}: {cap.agent_api_path}"


def test_openapi_http_methods_correct():
    """Each path item must use the correct HTTP method from the capability."""
    from agent_api.openapi_docs import build_agent_openapi_spec
    from agent_contract.capabilities import get_stable_capabilities

    spec = build_agent_openapi_spec()
    paths = spec["paths"]

    for cap in get_stable_capabilities():
        method = cap.agent_api_method.lower()
        path_item = paths[cap.agent_api_path]
        assert method in path_item, (
            f"Method {method} missing for {cap.id} at {cap.agent_api_path}"
        )


def test_openapi_operation_ids():
    """operationId must be the capability ID with dots replaced by underscores."""
    from agent_api.openapi_docs import build_agent_openapi_spec
    from agent_contract.capabilities import get_stable_capabilities

    spec = build_agent_openapi_spec()

    # Check at least one known capability
    create_cap = next(c for c in get_stable_capabilities() if c.id == "project.create")
    method = create_cap.agent_api_method.lower()
    path_item = spec["paths"][create_cap.agent_api_path][method]
    assert path_item["operationId"] == "project_create"


def test_openapi_security_schemes():
    """Security schemes must include Bearer and API key."""
    from agent_api.openapi_docs import build_agent_openapi_spec

    spec = build_agent_openapi_spec()
    schemes = spec.get("components", {}).get("securitySchemes", {})

    assert "BearerAuth" in schemes
    assert "ApiKeyAuth" in schemes
    assert schemes["BearerAuth"]["type"] == "http"
    assert schemes["ApiKeyAuth"]["type"] == "apiKey"


def test_openapi_servers():
    """Servers must include at least one entry."""
    from agent_api.openapi_docs import build_agent_openapi_spec

    servers = build_agent_openapi_spec()["servers"]
    assert len(servers) >= 1
    assert any("/api/agent" in s.get("url", "") for s in servers)


def test_openapi_response_codes():
    """Each operation must include standard response codes."""
    from agent_api.openapi_docs import build_agent_openapi_spec
    from agent_contract.capabilities import get_stable_capabilities

    spec = build_agent_openapi_spec()
    first_cap = get_stable_capabilities()[0]
    method = first_cap.agent_api_method.lower()
    path_item = spec["paths"][first_cap.agent_api_path][method]
    responses = path_item.get("responses", {})

    assert "200" in responses
    assert "400" in responses
    assert "404" in responses


def test_openapi_tags_from_capability_ids():
    """Tags must be derived from the capability ID prefix."""
    from agent_api.openapi_docs import build_agent_openapi_spec
    from agent_contract.capabilities import get_stable_capabilities

    spec = build_agent_openapi_spec()
    create_cap = next(c for c in get_stable_capabilities() if c.id == "project.create")
    method = create_cap.agent_api_method.lower()
    path_item = spec["paths"][create_cap.agent_api_path][method]
    assert "project" in path_item.get("tags", [])


# ---------------------------------------------------------------------------
# Swagger UI
# ---------------------------------------------------------------------------

def test_swagger_ui_html_structure():
    """Swagger UI HTML must contain the expected elements."""
    from agent_api.openapi_docs import render_swagger_ui

    html = render_swagger_ui("/api/agent/v1/openapi.json")
    assert isinstance(html, str)
    assert "<!DOCTYPE html>" in html
    assert "swagger-ui" in html.lower()
    assert "SwaggerUIBundle" in html
    assert "/api/agent/v1/openapi.json" in html


def test_swagger_ui_custom_spec_url():
    """Swagger UI must accept a custom spec URL."""
    from agent_api.openapi_docs import render_swagger_ui

    html = render_swagger_ui("/custom/spec.json")
    assert "/custom/spec.json" in html
