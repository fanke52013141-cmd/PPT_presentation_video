"""Agent system adapters: global settings, config packages, credentials,
model connections and diagnostics."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Query, UploadFile
from fastapi.responses import Response

from agent_contract.domains.freeform import FreeFormRequest
from agent_contract.domains.system import (
    CredentialUpdateRequest,
)
from model_connection_models import (
    ModelConnectionCopy,
    ModelConnectionCreate,
    ModelConnectionStateUpdate,
    ModelConnectionUpdate,
)

import credential_store as credential_service
import diagnostics_routes
import model_connection_service as connection_service
import settings_service as settings_service
from config_portability_service import (
    export_full_config_with_secrets as _export_with_secrets,
    export_full_config_with_secrets_zip as _export_with_secrets_zip,
    import_config_bundle_bytes as _import_bundle_bytes,
    import_full_config as _import_full_config,
)
from settings_routes import (
    _config_import_limit,
    _config_zip_response,
    export_full_config,
    export_full_config_zip,
)
from app_security import verify_access_token

router = APIRouter()


def _require_secret_confirmation(payload: dict[str, Any], request) -> None:
    from fastapi import HTTPException

    if not verify_access_token(request):
        raise HTTPException(status_code=401, detail="导出密钥需要有效的 PPT Studio access token。")
    if str((payload or {}).get("confirmation") or "") != "EXPORT_SECRETS":
        raise HTTPException(status_code=400, detail="Explicit secret-export confirmation is required.")


@router.get("/settings")
def agent_get_settings() -> dict[str, Any]:
    return settings_service.get_settings()


@router.put("/settings")
def agent_update_settings(payload: FreeFormRequest) -> dict[str, Any]:
    from settings_service import SettingsUpdate

    return settings_service.update_system_settings(SettingsUpdate(settings=payload.payload))


@router.get("/config/export")
def agent_export_config() -> dict[str, Any]:
    return export_full_config()


@router.get("/config/export-zip")
def agent_export_config_zip() -> Response:
    return export_full_config_zip()


@router.post("/config/export-with-secrets")
def agent_export_config_secrets(payload: FreeFormRequest, request) -> dict[str, Any]:
    _require_secret_confirmation(payload.payload, request)
    return _export_with_secrets()


@router.post("/config/export-with-secrets-zip")
def agent_export_config_secrets_zip(payload: FreeFormRequest, request) -> Response:
    _require_secret_confirmation(payload.payload, request)
    return _config_zip_response(_export_with_secrets_zip())


@router.post("/config/import")
def agent_import_config(payload: FreeFormRequest) -> dict[str, Any]:
    _config_import_limit()
    try:
        return _import_full_config(payload.payload)
    except ValueError as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/config/import-zip")
async def agent_import_config_zip(file: UploadFile = File(...)) -> dict[str, Any]:
    _config_import_limit()
    data = await file.read()
    if not data:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="上传的配置包为空")
    try:
        return _import_bundle_bytes(data)
    except ValueError as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/settings/test-llm")
def agent_test_llm_connection(payload: FreeFormRequest) -> dict[str, Any]:
    return settings_service.test_llm_connection(payload.payload)


@router.post("/settings/test-image")
def agent_test_image_connection(payload: FreeFormRequest) -> dict[str, Any]:
    return settings_service.test_image_connection(payload.payload)


@router.post("/settings/test-tts")
def agent_test_tts_connection(payload: FreeFormRequest) -> dict[str, Any]:
    return settings_service.test_tts_connection(payload.payload)


@router.get("/settings/comfyui-tts-workflow")
def agent_get_comfyui_tts_workflow() -> dict[str, Any]:
    import settings_routes as settings_module

    return settings_module.get_comfyui_tts_workflow()


@router.post("/settings/comfyui-tts-workflow")
async def agent_upload_comfyui_tts_workflow(file: UploadFile = File(...)) -> dict[str, Any]:
    import settings_routes as settings_module

    return await settings_module.upload_comfyui_tts_workflow(file=file)


@router.get("/credentials")
def agent_list_credentials(include_disabled: bool = Query(False)) -> dict[str, Any]:
    from credential_routes import _run

    return _run(
        lambda: {"credentials": credential_service.list_credentials(include_disabled=include_disabled)}
    )


@router.post("/credentials")
def agent_create_credential(payload: FreeFormRequest) -> dict[str, Any]:
    from credential_routes import CredentialCreate, _run

    body = CredentialCreate.model_validate(payload.payload)
    return _run(lambda: {"credential": credential_service.create_credential(**body.model_dump())})


@router.put("/credentials")
def agent_update_credential(payload: CredentialUpdateRequest) -> dict[str, Any]:
    from credential_routes import CredentialUpdate, _run

    body = CredentialUpdate.model_validate(payload.payload)
    return _run(
        lambda: {
            "credential": credential_service.update_credential(
                payload.credential_ref, **body.model_dump(exclude_unset=True)
            )
        }
    )


@router.get("/model-connections")
def agent_list_model_connections(
    kind: str | None = Query(None),
    include_archived: bool = Query(False),
) -> dict[str, Any]:
    from model_connection_routes import _raise_http_error

    try:
        return connection_service.list_model_connections(
            kind=kind, include_archived=include_archived
        )
    except Exception as exc:
        _raise_http_error(exc)


@router.post("/model-connections")
def agent_create_model_connection(payload: FreeFormRequest) -> dict[str, Any]:
    from model_connection_routes import _raise_http_error

    body = ModelConnectionCreate.model_validate(payload.payload)
    try:
        return connection_service.create_model_connection(body)
    except Exception as exc:
        _raise_http_error(exc)


@router.get("/model-connections/{connection_id}")
def agent_get_model_connection(connection_id: str) -> dict[str, Any]:
    from model_connection_routes import _raise_http_error

    try:
        return connection_service.get_model_connection(connection_id)
    except Exception as exc:
        _raise_http_error(exc)


@router.put("/model-connections/{connection_id}")
def agent_update_model_connection(
    connection_id: str,
    payload: FreeFormRequest,
) -> dict[str, Any]:
    from model_connection_routes import _raise_http_error

    body = ModelConnectionUpdate.model_validate(payload.payload)
    try:
        return connection_service.update_model_connection(connection_id, body)
    except Exception as exc:
        _raise_http_error(exc)


@router.post("/model-connections/{connection_id}/reference-audio")
async def agent_upload_model_reference_audio(
    connection_id: str,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    from model_connection_routes import upload_model_reference_audio

    return await upload_model_reference_audio(connection_id=connection_id, file=file)


@router.post("/model-connections/{connection_id}/copy")
def agent_copy_model_connection(connection_id: str, payload: FreeFormRequest) -> dict[str, Any]:
    from model_connection_routes import _raise_http_error

    body = ModelConnectionCopy.model_validate(payload.payload)
    try:
        return connection_service.copy_model_connection(connection_id, body)
    except Exception as exc:
        _raise_http_error(exc)


@router.post("/model-connections/{connection_id}/test")
def agent_test_model_connection(connection_id: str) -> dict[str, Any]:
    from model_connection_routes import _raise_http_error

    try:
        return connection_service.test_saved_model_connection(connection_id)
    except Exception as exc:
        _raise_http_error(exc)


@router.put("/model-connections/{connection_id}/state")
def agent_update_model_connection_state(
    connection_id: str,
    payload: FreeFormRequest,
) -> dict[str, Any]:
    from model_connection_routes import _raise_http_error

    body = ModelConnectionStateUpdate.model_validate(payload.payload)
    try:
        return connection_service.set_model_connection_state(connection_id, body)
    except Exception as exc:
        _raise_http_error(exc)


@router.delete("/model-connections/{connection_id}")
def agent_delete_model_connection(connection_id: str) -> dict[str, Any]:
    from model_connection_routes import _raise_http_error

    try:
        return connection_service.delete_model_connection(connection_id)
    except Exception as exc:
        _raise_http_error(exc)


@router.get("/runtime/diagnostics")
def agent_runtime_diagnostics(request) -> dict[str, Any]:
    return diagnostics_routes.runtime_diagnostics(request)


@router.get("/diagnostics/generation-governor")
def agent_governor_snapshot() -> dict[str, Any]:
    return diagnostics_routes.generation_governor_snapshot()


@router.get("/error-log")
def agent_get_error_log(limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    return diagnostics_routes.get_error_log(limit=limit)


@router.get("/error-log/latest")
def agent_get_latest_error_log() -> Response:
    from diagnostics_routes import get_latest_error_log

    return get_latest_error_log()
