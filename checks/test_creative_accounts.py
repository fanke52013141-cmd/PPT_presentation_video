from __future__ import annotations

import json
from pathlib import Path
from copy import deepcopy
import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from account_context import account_scope
from account_service import (
    create_account,
    create_agent_token,
    get_default_creation_config,
    authenticate_agent_token,
    set_default_creation_config,
)
from database import Account, Base, Project
from project_service import ProjectCreate, ProjectDependencies, ProjectService
import creation_config_service
import credential_store
import model_connection_service
from model_connection_models import ModelConnectionCreate
import account_routes


def _session(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'accounts.db'}")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)


def test_accounts_issue_scoped_agent_tokens_and_defaults(tmp_path: Path) -> None:
    engine, session_factory = _session(tmp_path)
    db = session_factory()
    try:
        default = Account(id="default", name="默认", status="active")
        db.add(default)
        db.commit()
        account = create_account(db, name="培训账号")
        updated = set_default_creation_config(
            db, account["id"], "training", 2
        )
        assert updated["default_creation_config"] == {"package_id": "training", "version": 2}
        assert get_default_creation_config(account["id"], db) == {"package_id": "training", "version": 2}
        issued = create_agent_token(db, account["id"], name="MCP", scopes=["project:read"])
        assert issued["token"].startswith("ppt_")
        assert authenticate_agent_token(db, issued["token"]).account_id == account["id"]
        assert authenticate_agent_token(db, "ppt_invalid") is None
    finally:
        db.close()
        engine.dispose()


def test_projects_are_isolated_by_request_account(tmp_path: Path) -> None:
    engine, session_factory = _session(tmp_path)
    db = session_factory()
    try:
        db.add_all([
            Account(id="default", name="默认", status="active"),
            Account(id="acct_b", name="B", status="active"),
        ])
        db.commit()
        service = ProjectService(ProjectDependencies(
            runs_root=tmp_path / "runs",
            project_audio_confirmed=lambda _project: False,
        ))
        with account_scope("default"):
            project_a = service.create(ProjectCreate(name="A"), db)["project"]["id"]
            assert [p["id"] for p in service.list(db)] == [project_a]
        with account_scope("acct_b"):
            project_b = service.create(ProjectCreate(name="B"), db)["project"]["id"]
            assert [p["id"] for p in service.list(db)] == [project_b]
            with pytest.raises(Exception) as exc:
                service.get(project_a, db)
            assert getattr(exc.value, "status_code", None) == 404
    finally:
        db.close()
        engine.dispose()


def test_account_scopes_isolate_creation_configs_connections_and_credentials() -> None:
    class Store:
        def __init__(self, value):
            self.value = value

        def read(self):
            return deepcopy(self.value)

        def write(self, value):
            self.value = deepcopy(value)

    config_store = Store({"version": creation_config_service.STORE_VERSION, "packages": {}})
    credential_store_data = Store({"version": credential_store.STORE_VERSION, "credentials": {}})
    connection_store = Store({"version": model_connection_service.REGISTRY_VERSION, "connections": {}})
    old_config = creation_config_service._dependencies
    old_credentials = credential_store._dependencies
    old_connections = model_connection_service._dependencies
    creation_config_service.configure_creation_config_dependencies(
        creation_config_service.CreationConfigDependencies(
            store=config_store,
            now=lambda: "2026-09-04T00:00:00+00:00",
            new_id=lambda: "pkg_account_a",
        )
    )
    credential_store.configure_credential_dependencies(
        credential_store.CredentialDependencies(
            read_store=credential_store_data.read,
            write_store=credential_store_data.write,
            now=lambda: "2026-09-04T00:00:00+00:00",
            new_id=lambda: "secret-a",
        )
    )
    model_connection_service.configure_model_connection_dependencies(
        model_connection_service.ModelConnectionDependencies(
            read_registry=connection_store.read,
            write_registry=connection_store.write,
            now=lambda: __import__("datetime").datetime(2026, 9, 4),
            new_id=lambda: "connection-a",
        )
    )
    try:
        package_payload = {"prompts": {"article_generation": {"system_content": "A"}}}
        with account_scope("acct_a"):
            package = creation_config_service.create_creation_config(
                name="A 配置", payload=package_payload
            )
            connection = model_connection_service.create_model_connection(
                ModelConnectionCreate(
                    name="A 文本",
                    kind="text",
                    provider="openai_compatible",
                    model="model-a",
                    credential_ref="credential://secret-a",
                )
            )
            credential = credential_store.create_credential(
                provider="openai", label="A 密钥", secret_values={"api_key": "private-a"}
            )
            assert package["account_id"] == "acct_a"
            assert connection["id"] == "connection-a"
            assert credential["account_id"] == "acct_a"

        with account_scope("acct_b"):
            assert creation_config_service.list_creation_configs() == []
            assert model_connection_service.list_model_connections() == []
            assert credential_store.list_credentials() == []
            with pytest.raises(creation_config_service.CreationConfigNotFound):
                creation_config_service.get_creation_config(package["id"])
            with pytest.raises(model_connection_service.ModelConnectionNotFoundError):
                model_connection_service.get_model_connection(connection["id"])
            with pytest.raises(credential_store.CredentialNotFound):
                credential_store.get_credential(credential["credential_ref"])
    finally:
        creation_config_service._dependencies = old_config
        credential_store._dependencies = old_credentials
        model_connection_service._dependencies = old_connections


def test_account_routes_reject_unbound_initial_default_and_invalid_target_package(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(account_routes.HTTPException) as initial_error:
        account_routes.account_create(
            account_routes.AccountCreateRequest(
                name="新账号", default_package_id="package-from-another-account"
            ),
            db=None,
        )
    assert initial_error.value.status_code == 422

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("package belongs to another account")

    monkeypatch.setattr(
        account_routes.creation_config_service,
        "resolve_creation_config",
        unavailable,
        raising=False,
    )
    with pytest.raises(account_routes.HTTPException) as config_error:
        account_routes.account_default_config(
            "acct_target",
            account_routes.AccountDefaultConfigRequest(package_id="foreign-package"),
            db=None,
        )
    assert config_error.value.status_code == 422
