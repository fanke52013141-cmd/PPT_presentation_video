"""Client conditional discovery must revalidate and preserve caller revisions."""

import json
from io import BytesIO
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

import pytest

from agent_client.client import AgentClient, AgentClientError


def response(payload, etag='"first"'):
    result = MagicMock()
    result.__enter__.return_value = result
    result.read.return_value = json.dumps(payload).encode()
    result.headers = {"ETag": etag} if etag else {}
    return result


def unchanged():
    return HTTPError("http://test", 304, "Not Modified", {}, BytesIO())


def test_describe_revalidates_and_returns_isolated_values():
    client = AgentClient("http://test", app_token="first-user")
    with patch("agent_client.client.urlopen", side_effect=[
        response({"contract_revision": "one"}), unchanged(),
        response({"contract_revision": "two"}, '"second"'),
    ]) as transport:
        first = client.describe("project.create")
        first["contract_revision"] = "caller mutation"
        assert client.describe("project.create")["contract_revision"] == "one"
        assert transport.call_args.args[0].get_header("If-none-match") == '"first"'
        assert client.describe("project.create")["contract_revision"] == "two"


def test_cache_separates_identity_url_queries_and_can_be_cleared():
    client = AgentClient("http://test", app_token="first-user")
    with patch("agent_client.client.urlopen", side_effect=lambda *a, **k: response({"items": []})) as transport:
        client.discover(domain="project")
        client.discover(domain="source")
        assert transport.call_args.args[0].get_header("If-none-match") is None
        client.app_token = "second-user"
        client.discover(domain="project")
        assert transport.call_args.args[0].get_header("If-none-match") is None
        client.base_url = "http://other"
        client.discover(domain="project")
        assert transport.call_args.args[0].get_header("If-none-match") is None
        client.clear_discovery_cache()
        client.discover(domain="project")
        assert transport.call_args.args[0].get_header("If-none-match") is None


def test_changed_contract_error_does_not_retry_write_or_refresh_revision():
    client = AgentClient("http://test", app_token="")
    error = HTTPError("http://test", 409, "Conflict", {}, BytesIO(json.dumps({
        "error": {"code": "CONTRACT_CHANGED", "message": "Changed", "details": {"executed": False}}
    }).encode()))
    with patch("agent_client.client.urlopen", side_effect=error) as transport:
        with pytest.raises(AgentClientError) as caught:
            client.invoke("project.create", {"name": "example"}, expected_contract_revision="old")
        assert caught.value.code == "CONTRACT_CHANGED"
        assert transport.call_count == 1
        assert json.loads(transport.call_args.args[0].data)["expected_contract_revision"] == "old"


def test_server_without_etag_discards_cached_representation():
    client = AgentClient("http://test", app_token="")
    with patch("agent_client.client.urlopen", side_effect=[
        response({"items": []}), response({"items": []}, None), response({"items": []}),
    ]) as transport:
        client.discover()
        client.discover()
        client.discover()
        assert transport.call_args.args[0].get_header("If-none-match") is None
