import copy

import pytest

from agent_client.client import AgentClientError
from scripts.batch_image_repairs import run_batch


class Client:
    base_url, app_token = "http://localhost:8000", "test-token"

    def __init__(self):
        self.calls = []
        self.fail = False

    def describe(self, _):
        return {"contract_revision": "frozen-revision"}

    def invoke(self, capability, arguments, **kwargs):
        self.calls.append((capability, copy.deepcopy(arguments), kwargs))
        if self.fail:
            raise AgentClientError("disconnected", 0)
        return {"success": True}


def manifest():
    return {"project_id": "project", "batch_id": "batch", "slides": [{"slide_id": "slide_001", "prompt": "explicit repair prompt"}]}


def test_unknown_generation_reuses_exact_key_arguments_and_revision(tmp_path):
    client, request = Client(), manifest()
    client.fail = True
    with pytest.raises(AgentClientError):
        run_batch(client, request, tmp_path / "report.json")
    client.fail = False
    run_batch(client, request, tmp_path / "report.json")
    assert client.calls[0] == client.calls[1]
    run_batch(client, request, tmp_path / "report.json")
    assert len(client.calls) == 2
    request["slides"][0]["prompt"] = "changed"
    with pytest.raises(ValueError, match="parameters changed"):
        run_batch(client, request, tmp_path / "report.json")
    assert len(client.calls) == 2


def test_unknown_application_is_never_retried_and_unreviewed_is_skipped(tmp_path):
    request, client = manifest(), Client()
    entry = request["slides"][0]
    entry.update(reviewed=False, regions=[[0, 0, 10, 10]], expected_image_sha256="a" * 64, expected_candidate_sha256="b" * 64)
    run_batch(client, request, tmp_path / "report.json", apply_reviewed=True)
    assert not client.calls
    entry["reviewed"], client.fail = True, True
    with pytest.raises(AgentClientError):
        run_batch(client, request, tmp_path / "report.json", apply_reviewed=True)
    with pytest.raises(ValueError, match="Unknown application"):
        run_batch(client, request, tmp_path / "report.json", apply_reviewed=True)
    assert len(client.calls) == 1
