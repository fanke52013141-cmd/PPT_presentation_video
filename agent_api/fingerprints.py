"""Bind write replay to the current semantics and exact target resource."""

from agent_contract.capabilities import get_capability
from agent_contract.discovery import describe_capability
from agent_idempotency_service import compute_fingerprint


def request_fingerprint(capability_id: str, payload: dict, **resource_identity) -> str:
    return compute_fingerprint({
        "payload": {key: value for key, value in payload.items() if key != "idempotency_key"},
        "resource_identity": resource_identity,
        "contract_revision": describe_capability(get_capability(capability_id))["contract_revision"],
    })
