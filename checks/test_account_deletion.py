"""Account removal stays isolated from owned work and keeps a usable account."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import database
from account_context import AccountContextMiddleware
from account_routes import router
from account_service import (
    authenticate_agent_token, create_agent_token, delete_account, list_accounts,
)
from database import Account, Base, Project


@pytest.fixture
def accounts_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'deletion.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add_all([Account(id="default", name="默认"), Account(id="other", name="其他")])
        db.commit()
    monkeypatch.setattr(database, "SessionLocal", factory)
    yield factory
    engine.dispose()


def test_delete_preserves_projects_and_rejects_old_tokens_and_last_account(accounts_db):
    with accounts_db() as db:
        db.add(Project(id="work", name="作品", run_dir="retained", account_id="default"))
        db.commit()
        token = create_agent_token(db, "default")
        delete_account(db, "default")
        assert [a["id"] for a in list_accounts(db)] == ["other"]
        assert db.get(Project, "work").account_id == "default"
        assert authenticate_agent_token(db, token["token"]) is None
        with pytest.raises(HTTPException) as last:
            delete_account(db, "other")
        assert last.value.status_code == 409
        with pytest.raises(HTTPException) as missing:
            delete_account(db, "default")
        assert missing.value.status_code == 404


def test_concurrent_deletion_retains_one_account(accounts_db):
    barrier = Barrier(2)

    def remove(account_id):
        with accounts_db() as db:
            barrier.wait()
            try:
                delete_account(db, account_id)
                return 200
            except HTTPException as exc:
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(remove, ["default", "other"])) == [200, 409]
    with accounts_db() as db:
        assert len(list_accounts(db)) == 1


def test_current_deletion_cookie_recovery_and_explicit_header_isolation(accounts_db):
    app = FastAPI()
    app.add_middleware(AccountContextMiddleware)
    app.include_router(router)

    def get_test_db():
        with accounts_db() as db:
            yield db

    app.dependency_overrides[database.get_db] = get_test_db
    with TestClient(app) as client:
        response = client.delete('/api/accounts/default')
        assert response.status_code == 200
        assert client.cookies.get('ppt_studio_account_id') == 'other'
        assert client.get('/api/accounts/current').json()['account']['id'] == 'other'
        client.cookies.set('ppt_studio_account_id', 'default')
        assert client.get('/api/accounts/current').json()['account']['id'] == 'other'
        client.cookies.clear()
        assert client.get('/api/accounts/current').json()['account']['id'] == 'other'
        assert client.get('/api/accounts/current', headers={'x-ppt-account-id': 'default'}).status_code == 404
        assert client.delete('/api/accounts/other').status_code == 409
