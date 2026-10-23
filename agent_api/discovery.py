"""Small stable bootstrap surface for current-contract discovery and execution."""

import hashlib
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from database import get_db
from agent_api.dispatch import invoke_capability
from agent_api.errors import AgentAPIError
from agent_contract.capabilities import CAPABILITIES, get_capability
from agent_contract.discovery import describe_capability
from agent_contract.versions import get_contract_hash


router = APIRouter(tags=["Agent discovery"])


def _discovery_response(request: Request, payload: dict[str, Any]) -> Response:
    """Validate private discovery representations on every conditional read."""
    response = JSONResponse(payload)
    etag = '"' + hashlib.sha256(response.body).hexdigest() + '"'
    headers = {"ETag": etag, "Cache-Control": "private, no-cache",
               "Vary": "Authorization, X-API-Key, X-Agent-Token, X-PPT-Account-ID, Cookie"}
    candidates = request.headers.get("if-none-match", "").split(",")
    if any(value.strip().removeprefix("W/") in {etag, "*"} for value in candidates):
        return Response(status_code=304, headers=headers)
    response.headers.update(headers)
    return response


class InvokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    capability_id: str = Field(min_length=1, max_length=128)
    expected_contract_revision: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any] = Field(default_factory=dict)


@router.get("/capabilities")
def list_capabilities(
    request: Request, q: str = Query("", max_length=200),
    domain: str = Query("", max_length=128), offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    scopes = getattr(request.state, "agent_scopes", set())
    authenticated = getattr(request.state, "agent_authenticated", False)
    items = []
    for cap in CAPABILITIES:
        if cap.status.value == "removed":
            continue
        detail = describe_capability(cap)
        if domain and detail["domain"] != domain:
            continue
        if q and q.casefold() not in (cap.id + " " + cap.description).casefold():
            continue
        detail["authorized"] = not authenticated or not scopes or set(detail["required_scopes"]).issubset(scopes)
        # Summary only: describe retrieves the full schema.
        items.append({key: detail[key] for key in (
            "id", "domain", "description", "contract_revision", "response_kind", "invocable", "authorized",
        )})
    return _discovery_response(request, {"contract_hash": get_contract_hash(), "items": items[offset:offset + limit],
            "total": len(items), "offset": offset,
            "next_offset": offset + limit if offset + limit < len(items) else None})


@router.get("/capabilities/{capability_id}")
def get_capability_detail(capability_id: str, request: Request):
    try:
        cap = get_capability(capability_id)
    except ValueError as exc:
        raise AgentAPIError("CAPABILITY_NOT_FOUND", "Unknown capability", 404) from exc
    if cap.status.value == "removed":
        raise AgentAPIError("CAPABILITY_NOT_FOUND", "Unknown capability", 404)
    return _discovery_response(request, describe_capability(cap))


@router.post("/invoke")
def invoke(payload: InvokeRequest, request: Request, db: Session = Depends(get_db)):
    return invoke_capability(payload.capability_id, payload.expected_contract_revision,
                             payload.arguments, request, db)
