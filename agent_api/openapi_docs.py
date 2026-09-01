"""Standard OpenAPI 3.0 specification builder for the Agent API.

Generates a machine-readable OpenAPI document from the capabilities
registry so that Agent integrators can use standard Swagger UI / OpenAPI
tooling to discover available endpoints.

The spec is served at:
- ``/api/agent/v1/openapi.json`` — raw OpenAPI 3.0 JSON
- ``/api/agent/v1/docs``       — embedded Swagger UI HTML
"""

from __future__ import annotations

from typing import Any

from agent_contract.versions import AGENT_API_VERSION
from agent_contract.capabilities import (
    CAPABILITIES,
    CapabilityStatus,
    get_stable_capabilities,
)
from agent_contract.schema import (
    capability_input_schema,
    capability_output_schema,
    path_parameters_schema,
)


_BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})


def _without_path_properties(schema: dict[str, Any], path_names: set[str]) -> dict[str, Any]:
    """Return a request schema with URL path fields removed from its body."""
    result = dict(schema)
    properties = dict(result.get("properties", {}))
    for name in path_names:
        properties.pop(name, None)
    result["properties"] = properties
    if "required" in result:
        required = [name for name in result["required"] if name not in path_names]
        if required:
            result["required"] = required
        else:
            result.pop("required")
    return result


def _http_method_spec(cap: Any) -> dict[str, Any]:
    """Build a single operation object for an OpenAPI path item."""
    tags: list[str] = []
    capability_id = cap.id
    if "." in capability_id:
        tags.append(capability_id.split(".")[0])

    input_schema = capability_input_schema(cap)
    output_schema = capability_output_schema(cap)
    path_schema = path_parameters_schema(cap)
    path_names = set(path_schema["properties"])
    method = cap.agent_api_method.upper()
    parameters: list[dict[str, Any]] = [
        {
            "name": name,
            "in": "path",
            "required": True,
            "description": schema.get("description", ""),
            "schema": {"type": schema.get("type", "string")},
        }
        for name, schema in path_schema["properties"].items()
    ]
    if method not in _BODY_METHODS:
        for name, schema in input_schema.get("properties", {}).items():
            if name not in path_names:
                parameters.append({
                    "name": name,
                    "in": "query",
                    "required": name in input_schema.get("required", []),
                    "description": schema.get("description", ""),
                    "schema": schema,
                })

    operation: dict[str, Any] = {
        "tags": tags,
        "summary": cap.description,
        "operationId": capability_id.replace(".", "_"),
        "deprecated": cap.status == CapabilityStatus.deprecated,
        "responses": {
            "200": {
                "description": "Successful response",
                "content": {"application/json": {"schema": output_schema}},
            },
            "400": {"description": "Validation error"},
            "401": {"description": "Authentication required"},
            "404": {"description": "Resource not found"},
            "429": {"description": "Rate limit exceeded"},
        },
    }
    if parameters:
        operation["parameters"] = parameters
    if method in _BODY_METHODS:
        body_schema = _without_path_properties(input_schema, path_names)
        if body_schema.get("properties") or body_schema.get("additionalProperties"):
            operation["requestBody"] = {
                # FastAPI declares the request model itself as a required body
                # parameter even when all of that model's fields have defaults.
                "required": True,
                "content": {"application/json": {"schema": body_schema}},
            }
    return operation


def build_agent_openapi_spec(stable_only: bool = True) -> dict[str, Any]:
    """Build an OpenAPI 3.0 specification dict from the capability registry.

    Each capability contributes one path item keyed by its
    ``agent_api_path`` with the HTTP method from ``agent_api_method``.
    """
    source = get_stable_capabilities() if stable_only else list(CAPABILITIES)

    paths: dict[str, dict[str, Any]] = {}
    for cap in source:
        path_key = cap.agent_api_path
        method = cap.agent_api_method.lower()

        if path_key not in paths:
            paths[path_key] = {}

        paths[path_key][method] = _http_method_spec(cap)

    return {
        "openapi": "3.0.3",
        "info": {
            "title": "PPT Studio Agent API",
            "version": AGENT_API_VERSION,
            "description": (
                "Stable, versioned HTTP API for automated Agent integration "
                "with the PPT-to-Video production pipeline. "
                "All endpoints are prefixed with ``/api/agent/v1``. "
                "Authentication via ``PPT_AGENT_API_KEY`` environment variable."
            ),
        },
        "servers": [
            # Capability paths already include /api/agent/v1. A root server
            # avoids Swagger composing the prefix twice.
            {"url": "/", "description": "Local development"},
        ],
        "paths": paths,
        "components": {
            "securitySchemes": {
                "BearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "Set PPT_AGENT_API_KEY env var; pass as Bearer token.",
                },
                "ApiKeyAuth": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-API-Key",
                },
            }
        },
        "security": [{"BearerAuth": []}, {"ApiKeyAuth": []}],
    }


_SWAGGER_UI_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>PPT Studio Agent API — Swagger UI</title>
  <link rel="stylesheet" type="text/css"
        href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    window.onload = function() {{
      SwaggerUIBundle({{
        url: "{spec_url}",
        dom_id: "#swagger-ui",
        docExpansion: "list",
        deepLinking: true,
      }});
    }};
  </script>
</body>
</html>
"""


def render_swagger_ui(spec_path: str = "/api/agent/v1/openapi.json") -> str:
    """Return the Swagger UI HTML page pointing at the OpenAPI JSON endpoint."""
    return _SWAGGER_UI_HTML.format(spec_url=spec_path)
