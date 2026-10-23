"""Fixed discovery tools remain useful when the local business registry is stale."""

import json

from agent_client.client import AgentClientError


DEFINITIONS = [
    {"name": "ppt_capabilities_search", "description": "Search the running service's current capabilities.",
     "inputSchema": {"type": "object", "properties": {
         "q": {"type": "string"}, "domain": {"type": "string"},
         "offset": {"type": "integer", "minimum": 0},
         "limit": {"type": "integer", "minimum": 1, "maximum": 200}}, "additionalProperties": False}},
    {"name": "ppt_capability_describe", "description": "Read current schemas and contract_revision before invoking.",
     "inputSchema": {"type": "object", "properties": {"capability_id": {"type": "string"}},
                     "required": ["capability_id"], "additionalProperties": False}},
    {"name": "ppt_capability_invoke", "description": "Invoke a discovered JSON capability using its exact contract revision. A changed contract requires re-reading and re-planning; do not blindly retry writes.",
     "inputSchema": {"type": "object", "properties": {
         "capability_id": {"type": "string"}, "expected_contract_revision": {"type": "string", "minLength": 1},
         "arguments": {"type": "object"}},
         "required": ["capability_id", "expected_contract_revision", "arguments"], "additionalProperties": False}},
]
NAMES = frozenset(item["name"] for item in DEFINITIONS)


def call(name, arguments, client):
    try:
        allowed = next(item["inputSchema"]["properties"] for item in DEFINITIONS if item["name"] == name)
        if not isinstance(arguments, dict) or set(arguments) - set(allowed):
            raise ValueError("Invalid bootstrap arguments")
        if name == "ppt_capabilities_search":
            result = client.discover(**arguments)
        elif name == "ppt_capability_describe":
            result = client.describe(arguments["capability_id"])
        else:
            revision = arguments["expected_contract_revision"]
            if not isinstance(revision, str) or not revision:
                raise ValueError("expected_contract_revision is required")
            result = client.invoke(arguments["capability_id"], arguments["arguments"],
                                   expected_contract_revision=revision)
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}], "isError": False}
    except (AgentClientError, ValueError, KeyError, TypeError) as exc:
        error = {"code": getattr(exc, "code", "VALIDATION_ERROR"), "message": str(exc),
                 "details": getattr(exc, "details", {})}
        return {"content": [{"type": "text", "text": json.dumps({"error": error}, ensure_ascii=False)}], "isError": True}
