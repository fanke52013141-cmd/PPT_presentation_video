"""Explicit adapters to source-owned Agent endpoints; no dynamic imports from input."""

from __future__ import annotations

import inspect
import json
from typing import Any

from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ValidationError
from starlette.responses import JSONResponse

from agent_api.errors import AgentAPIError
from agent_contract.capabilities import get_capability
from agent_contract.discovery import describe_capability, input_model, path_names, required_scope


# These are Python adapter names, never supplied or resolved by the caller.
# Both named HTTP routes and invoke execute these same functions.
HANDLERS = {
    "operation.get": "agent_get_operation",
    "operation.list": "agent_list_operations",
    "operation.cancel": "agent_cancel_operation",
    "identity.get": "get_agent_identity",
    "diagnostics": "get_diagnostics",
    "project.create": "agent_create_project",
    "project.list": "agent_list_projects",
    "project.get": "agent_get_project",
    "project.update": "agent_update_project",
    "project.delete": "agent_delete_project",
    "source.set": "agent_set_source",
    "pipeline.run": "agent_start_pipeline",
    "pipeline.status": "agent_pipeline_status",
    "pipeline.resume": "agent_resume_pipeline",
    "checkpoint.list": "agent_list_checkpoints",
    "checkpoint.approve": "agent_approve_checkpoint",
    "stage.get": "agent_get_stage",
    "image.regenerate": "agent_regenerate_image",
    "narration.update": "agent_update_narration",
    "tts.synthesize": "agent_tts_synthesize",
    "video.render": "agent_video_render",
    "artifacts.list": "agent_list_artifacts",
    "artifact.get": "agent_get_artifact",
    "digital_human.config.get": "agent_get_digital_human_config",
    "digital_human.config.update": "agent_update_digital_human_config",
    "digital_human.health": "agent_digital_human_health",
    "digital_human.generate": "agent_digital_human_generate_full",
    "generation.status": "agent_generation_status",
    "generation.stop": "agent_generation_stop",
}


def invoke_capability(capability_id: str, revision: str, arguments: dict[str, Any], request, db):
    try:
        cap = get_capability(capability_id)
    except ValueError as exc:
        raise AgentAPIError("CAPABILITY_NOT_FOUND", "Unknown capability", 404) from exc
    if cap.status.value == "removed":
        raise AgentAPIError("CAPABILITY_NOT_FOUND", "Unknown capability", 404)
    detail = describe_capability(cap)
    if not detail["invocable"] or capability_id not in HANDLERS:
        raise AgentAPIError("UNSUPPORTED_TRANSPORT", "Use the declared resource transport", 422,
                            details={"method": cap.agent_api_method, "path": cap.agent_api_path})
    scopes = getattr(request.state, "agent_scopes", set())
    if getattr(request.state, "agent_authenticated", False) and scopes and required_scope(cap) not in scopes:
        raise AgentAPIError("FORBIDDEN", f"Missing scope: {required_scope(cap)}", 403)
    if revision != detail["contract_revision"]:
        raise AgentAPIError("CONTRACT_CHANGED", "Refresh the capability before calling it", 409,
                            details={"capability_id": cap.id, "contract_revision": detail["contract_revision"],
                                     "executed": False, "repair_actions": [{"action": "describe", "capability_id": cap.id}]})
    try:
        parsed = input_model(cap).model_validate(arguments)
    except ValidationError as exc:
        raise AgentAPIError("VALIDATION_ERROR", "Invalid capability arguments", 422,
                            details={"errors": exc.errors(include_input=False, include_context=False)}) from exc
    values = parsed.model_dump(mode="python")
    names = path_names(cap)
    if any(not values[name] or "/" in values[name] or "\\" in values[name] for name in names):
        raise AgentAPIError("VALIDATION_ERROR", "Invalid resource identifier", 422)

    from agent_api import routes
    endpoint = getattr(routes, HANDLERS[capability_id])
    kwargs: dict[str, Any] = {}
    for name, parameter in inspect.signature(endpoint).parameters.items():
        if name == "db":
            kwargs[name] = db
        elif name == "request":
            kwargs[name] = request
        elif name == "payload":
            # Preserve fields_set (pipeline start/resume distinguishes omitted defaults).
            kwargs[name] = cap.request_model.model_validate({
                key: value for key, value in arguments.items() if key in cap.request_model.model_fields
            })
        elif name == "status_filter":
            kwargs[name] = values.get("status")
        elif name in values:
            kwargs[name] = values[name]
        elif parameter.default is inspect.Parameter.empty:
            raise RuntimeError(f"Missing adapter binding: {cap.id}.{name}")
    result = endpoint(**kwargs)
    if isinstance(result, JSONResponse):
        if result.status_code >= 400:
            return result
        data = json.loads(result.body)
    else:
        data = jsonable_encoder(result)
    if cap.response_model is not BaseModel:
        try:
            cap.response_model.model_validate(data)
        except ValidationError as exc:
            raise AgentAPIError("OUTPUT_CONTRACT_ERROR", "Service result does not match its contract", 500,
                                details={"execution_may_have_completed": True,
                                         "repair_actions": [{"action": "inspect_operation_before_retry"}]}) from exc
    return result if isinstance(result, JSONResponse) else data
