"""Composition helper for credential, model, and creation-config routes."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


def configure_reusable_config_routes(
    app: Any,
    *,
    model_connections_path: Path | str,
    creation_configs_path: Path | str,
    credentials_path: Path | str,
    read_json_file: Callable[[Path | str], Any],
    write_json_atomic: Callable[[Path | str, Any], Any],
) -> None:
    """Configure injected stores and mount all reusable-config routers."""
    from creation_config_routes import router as creation_config_router
    from creation_config_service import (
        CreationConfigDependencies,
        JsonCreationConfigStore,
        configure_creation_config_dependencies,
        new_creation_config_id,
        utc_timestamp,
    )
    from credential_routes import router as credential_router
    from credential_store import (
        STORE_VERSION as CREDENTIAL_STORE_VERSION,
        CredentialDependencies,
        configure_credential_dependencies,
    )
    from model_connection_routes import router as model_connection_router
    from model_connection_service import ModelConnectionDependencies, configure_model_connection_dependencies

    configure_model_connection_dependencies(ModelConnectionDependencies(
        read_registry=lambda: read_json_file(model_connections_path, {}),
        write_registry=lambda value: write_json_atomic(model_connections_path, value),
    ))
    configure_creation_config_dependencies(CreationConfigDependencies(
        store=JsonCreationConfigStore(creation_configs_path, write_json_atomic=write_json_atomic),
        now=utc_timestamp,
        new_id=new_creation_config_id,
    ))
    configure_credential_dependencies(CredentialDependencies(
        # A new installation has no credentials file yet.  The credential
        # service expects its versioned envelope even for an empty store;
        # returning a bare object here makes every credentials read fail with
        # "凭据存储格式不正确" before the first credential can be created.
        read_store=lambda: read_json_file(
            credentials_path,
            {"version": CREDENTIAL_STORE_VERSION, "credentials": {}},
        ),
        write_store=lambda value: write_json_atomic(credentials_path, value),
    ))
    app.include_router(model_connection_router)
    app.include_router(creation_config_router)
    app.include_router(credential_router)
