from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

import credential_store as service


class MemoryStore:
    def __init__(self) -> None:
        self.value: dict[str, Any] = {
            "version": service.STORE_VERSION,
            "credentials": {},
        }

    def read(self) -> dict[str, Any]:
        return deepcopy(self.value)

    def write(self, value: dict[str, Any]) -> None:
        self.value = deepcopy(value)


@pytest.fixture()
def configured() -> MemoryStore:
    store = MemoryStore()
    previous = service._dependencies
    service.configure_credential_dependencies(
        service.CredentialDependencies(
            read_store=store.read,
            write_store=store.write,
            now=lambda: "2026-09-04T00:00:00+00:00",
            new_id=lambda: "team-a",
        )
    )
    try:
        yield store
    finally:
        service._dependencies = previous


def test_credential_metadata_never_contains_secret(configured: MemoryStore) -> None:
    metadata = service.create_credential(
        provider="minimax",
        label="账号 A",
        secret_values={"api_key": "private-key", "secret_key": "private-secret"},
    )
    assert metadata["credential_ref"] == "credential://team-a"
    assert metadata["configured"] is True
    assert "private-key" not in repr(metadata)
    assert "private-secret" not in repr(service.list_credentials())
    assert service.get_credential(metadata["credential_ref"]) == {
        "api_key": "private-key",
        "secret_key": "private-secret",
    }


def test_update_and_disable_preserve_reference(configured: MemoryStore) -> None:
    created = service.create_credential(
        provider="openai",
        label="文本",
        secret_values={"api_key": "key-v1"},
    )
    updated = service.update_credential(
        created["credential_ref"],
        label="文本新 Key",
        secret_values={"api_key": "key-v2"},
    )
    assert updated["credential_ref"] == created["credential_ref"]
    assert service.get_credential(created["credential_ref"])["api_key"] == "key-v2"
    service.update_credential(created["credential_ref"], state="disabled")
    with pytest.raises(service.CredentialUnavailable):
        service.get_credential(created["credential_ref"])
    assert service.list_credentials() == []
    assert service.list_credentials(include_disabled=True)[0]["state"] == "disabled"


def test_invalid_secret_shape_does_not_persist(configured: MemoryStore) -> None:
    with pytest.raises(service.CredentialError):
        service.create_credential(
            provider="x",
            label="bad",
            secret_values={"api_key": ""},
        )
    assert configured.value["credentials"] == {}
