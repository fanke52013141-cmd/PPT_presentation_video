"""Exercise real bounded HTTP downloads without starting the production app."""

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from unittest.mock import MagicMock

import pytest

from agent_client.client import AgentClient, AgentClientError
from agent_client.transfers import CHUNK_BYTES


PAYLOAD = b"resource-content" * 10000


@pytest.fixture(scope="module")
def download_server():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path.endswith("redirect"):
                self.send_response(302)
                destination = "http://example.invalid/steal" if self.path.endswith("external-redirect") else "/api/agent/v1/good"
                if self.path.endswith("outside-redirect"):
                    destination = "/elsewhere"
                self.send_header("Location", destination)
                self.end_headers()
                return
            if self.path.endswith("error"):
                self.send_response(404)
                body = json.dumps({"error": {"code": "ARTIFACT_UNAVAILABLE", "message": "Unavailable"}}).encode()
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            assert self.headers.get("Authorization") == "Bearer transfer-test"
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            if not self.path.endswith("unbounded"):
                extra = 5 if self.path.endswith("truncated") else 0
                self.send_header("Content-Length", str(len(PAYLOAD) + extra))
            self.end_headers()
            self.wfile.write(PAYLOAD)
            self.close_connection = True

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield AgentClient(f"http://127.0.0.1:{server.server_port}", app_token="transfer-test")
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


@pytest.mark.parametrize("path", ["good", "local-redirect"])
def test_download_streams_verified_bytes_and_publishes_atomically(download_server, tmp_path, path):
    target = tmp_path / "video.mp4"
    digest = hashlib.sha256(PAYLOAD).hexdigest()
    result = download_server.download_file("/api/agent/v1/" + path, target, expected_sha256=digest)
    assert target.read_bytes() == PAYLOAD
    assert result["sha256"] == digest
    assert result["bytes"] == len(PAYLOAD)
    assert result["content_type"] == "video/mp4"
    assert not list(tmp_path.glob(".ppt-download-*"))


@pytest.mark.parametrize("path,options,code", [
    ("good", {"max_bytes": 10}, "RESOURCE_TOO_LARGE"),
    ("unbounded", {"max_bytes": 10}, "RESOURCE_TOO_LARGE"),
    ("truncated", {}, "RESOURCE_INCOMPLETE"),
    ("good", {"expected_sha256": "0" * 64}, "RESOURCE_HASH_MISMATCH"),
    ("external-redirect", {}, "UNSAFE_RESOURCE_URL"),
    ("outside-redirect", {}, "UNSAFE_RESOURCE_URL"),
    ("error", {}, "ARTIFACT_UNAVAILABLE"),
])
def test_failed_transfer_preserves_existing_file(download_server, tmp_path, path, options, code):
    target = tmp_path / "video.mp4"
    target.write_bytes(b"keep-existing")
    with pytest.raises(AgentClientError) as caught:
        download_server.download_file("/api/agent/v1/" + path, target, **options)
    assert caught.value.code == code
    assert target.read_bytes() == b"keep-existing"
    assert not list(tmp_path.glob(".ppt-download-*"))


@pytest.mark.parametrize("path", ["https://other.test/file", "//other.test/file", "/elsewhere", "/api/agent/v1/../secret", "/api/agent/v1/%2e%2e/secret"])
def test_download_rejects_uncontrolled_resource_paths(tmp_path, path):
    with pytest.raises(ValueError):
        AgentClient("http://unused").download_file(path, tmp_path / "output")
    assert list(tmp_path.iterdir()) == []


def test_download_never_requests_an_unbounded_read(monkeypatch, tmp_path):
    response = MagicMock()
    response.__enter__.return_value = response
    response.status = 200
    response.headers.get.return_value = None
    response.headers.get_content_type.return_value = "application/octet-stream"
    response.read.side_effect = [b"a" * CHUNK_BYTES, b"b", b""]
    opener = MagicMock()
    opener.open.return_value = response
    monkeypatch.setattr("agent_client.transfers.build_opener", lambda *args: opener)
    AgentClient("http://test").download_file("/api/agent/v1/file", tmp_path / "out")
    assert [call.args for call in response.read.call_args_list] == [(CHUNK_BYTES,)] * 3


def test_cli_artifact_download_uses_metadata_hash_and_streaming(monkeypatch, capsys, tmp_path):
    from cli.pptctl import main
    client = MagicMock()
    digest = hashlib.sha256(PAYLOAD).hexdigest()
    client.get_artifact.return_value = {"artifact": {"sha256": digest}}
    client.download_file.return_value = {"saved_to": "output", "sha256": digest, "bytes": len(PAYLOAD)}
    monkeypatch.setattr("cli.pptctl.AgentClient", lambda **kwargs: client)
    target = tmp_path / "video.mp4"
    main(["artifact", "download", "--project", "p1", "--artifact", "a1", "--out", str(target), "--max-bytes", "1000000"])
    client.download_file.assert_called_once_with("/api/agent/v1/projects/p1/artifacts/a1/content", str(target),
                                                expected_sha256=digest, max_bytes=1000000)
    client.get_bytes.assert_not_called()
    assert json.loads(capsys.readouterr().out)["sha256"] == digest
