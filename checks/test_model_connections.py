"""Contract tests for the versioned, credential-reference-only registry."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import model_connection_routes as routes  # noqa: E402
import model_connection_service as service  # noqa: E402
from model_connection_models import (  # noqa: E402
    ModelConnectionCopy,
    ModelConnectionCreate,
    ModelConnectionStateUpdate,
    ModelConnectionUpdate,
)


@pytest.fixture()
def registry() -> dict[str, Any]:
    stored: dict[str, Any] = {}
    identifiers = iter(("text-1", "text-2", "tts-1"))
    previous = service._dependencies
    service.configure_model_connection_dependencies(
        service.ModelConnectionDependencies(
            read_registry=lambda: stored.get("value"),
            write_registry=lambda value: stored.__setitem__("value", value),
            now=lambda: datetime(2026, 9, 4, 9, 30, 0),
            new_id=lambda: next(identifiers),
        )
    )
    try:
        yield stored
    finally:
        service._dependencies = previous


def _text_connection(**changes: Any) -> ModelConnectionCreate:
    data = {
        "name": "文章模型",
        "kind": "text",
        "provider": "openai_compatible",
        "model": "writing-v1",
        "endpoint": "https://models.example.test/v1",
        "credential_ref": "credential://team-a/text-primary",
        "public_config": {"temperature": 0.4, "region": "cn"},
    }
    data.update(changes)
    return ModelConnectionCreate(**data)


def test_create_response_never_exposes_credential_reference_or_secret(
    registry: dict[str, Any],
) -> None:
    result = service.create_model_connection(_text_connection())

    assert result["id"] == "text-1"
    assert result["revision"]["credential_configured"] is True
    assert "credential_ref" not in repr(result)
    assert "team-a/text-primary" not in repr(result)
    assert "credential_ref" in repr(registry["value"])

    with pytest.raises(ValueError, match="credential_ref"):
        service.create_model_connection(
            _text_connection(public_config={"api_key": "do-not-store"})
        )


def test_edit_creates_immutable_revision_and_old_revision_resolves(
    registry: dict[str, Any],
) -> None:
    created = service.create_model_connection(_text_connection())
    updated = service.update_model_connection(
        created["id"],
        ModelConnectionUpdate(model="writing-v2", public_config={"temperature": 0.8}),
    )

    assert updated["current_revision"] == 2
    assert updated["revision"]["model"] == "writing-v2"
    historic = service.resolve_model_connection(created["id"], revision=1)
    latest = service.resolve_model_connection(created["id"])
    assert historic.model == "writing-v1"
    assert historic.credential_ref == "credential://team-a/text-primary"
    assert latest.revision == 2
    assert latest.model == "writing-v2"
    assert registry["value"]["connections"][created["id"]]["revisions"][0]["model"] == "writing-v1"


def test_copy_has_a_distinct_connection_and_first_revision(
    registry: dict[str, Any],
) -> None:
    created = service.create_model_connection(_text_connection())
    copied = service.copy_model_connection(
        created["id"], ModelConnectionCopy(name="文章模型副本")
    )

    assert copied["id"] == "text-2"
    assert copied["current_revision"] == 1
    assert copied["revision"]["model"] == created["revision"]["model"]
    assert service.resolve_model_connection(copied["id"]).credential_ref == "credential://team-a/text-primary"


def test_disabled_and_archived_connections_cannot_be_newly_bound_but_existing_snapshot_resolves(
    registry: dict[str, Any],
) -> None:
    created = service.create_model_connection(_text_connection())
    disabled = service.set_model_connection_state(
        created["id"], ModelConnectionStateUpdate(state="disabled")
    )
    assert disabled["state"] == "disabled"
    with pytest.raises(service.ModelConnectionUnavailableError):
        service.bind_model_connection(created["id"])
    assert service.resolve_model_connection(created["id"]).model == "writing-v1"

    archived = service.set_model_connection_state(
        created["id"], ModelConnectionStateUpdate(state="archived")
    )
    assert archived["archived_at"]
    assert service.list_model_connections() == []
    assert service.list_model_connections(include_archived=True)[0]["id"] == created["id"]
    with pytest.raises(service.ModelConnectionUnavailableError):
        service.bind_model_connection(created["id"])
    with pytest.raises(service.ModelConnectionUnavailableError):
        service.copy_model_connection(created["id"], ModelConnectionCopy(name="不允许"))


def test_legacy_sensitive_values_are_redacted_from_public_response(
    registry: dict[str, Any],
) -> None:
    registry["value"] = {
        "version": "model_connections_v1",
        "connections": {
            "legacy": {
                "id": "legacy",
                "name": "旧连接",
                "kind": "tts",
                "state": "active",
                "current_revision": 1,
                "created_at": "2026-09-04T09:30:00",
                "updated_at": "2026-09-04T09:30:00",
                "archived_at": None,
                "revisions": [{
                    "revision": 1,
                    "provider": "minimax",
                    "model": "speech-2.8",
                    "endpoint": "https://example.test/tts?api_key=bad",
                    "credential_ref": "credential://private",
                    "public_config": {"secret_key": "bad", "region": "cn"},
                    "created_at": "2026-09-04T09:30:00",
                }],
            }
        },
    }
    public = service.get_model_connection("legacy")

    assert public["revision"]["endpoint"] is None
    assert public["revision"]["public_config"] == {"secret_key": "__REDACTED__", "region": "cn"}
    assert "credential://private" not in repr(public)
    assert "bad" not in repr(public)


def test_routes_translate_archive_conflict_without_exposing_secret(
    registry: dict[str, Any],
) -> None:
    created = routes.create_model_connection(_text_connection())
    routes.update_model_connection_state(
        created["id"], ModelConnectionStateUpdate(state="archived")
    )
    with pytest.raises(routes.HTTPException) as exc_info:
        routes.update_model_connection(
            created["id"], ModelConnectionUpdate(model="should-not-write")
        )
    assert exc_info.value.status_code == 409
    assert "credential" not in str(exc_info.value.detail).lower()

