"""Bounded, atomic binary downloads from the configured Agent origin."""

from __future__ import annotations

import hashlib
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import tempfile
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from agent_client.client import AgentClientError

DEFAULT_MAX_DOWNLOAD_BYTES = 1024 * 1024 * 1024
CHUNK_BYTES = 64 * 1024


def _is_agent_path(path: str) -> bool:
    decoded = unquote(path)
    return (decoded.startswith("/api/agent/v1/") and "\\" not in decoded
            and not any(part in {".", ".."} for part in decoded.split("/")))


def _origin(url: str) -> tuple:
    parsed = urlsplit(url)
    return parsed.scheme.lower(), parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)


class _SameOriginRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlsplit(newurl)
        if (_origin(req.full_url) != _origin(newurl) or parsed.fragment or parsed.username
                or not _is_agent_path(parsed.path)):
            raise AgentClientError("Resource redirect left the controlled Agent surface", code="UNSAFE_RESOURCE_URL")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_file(client, path: str, destination: str | Path, *,
                  max_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES,
                  expected_sha256: str | None = None) -> dict:
    """Publish only a complete verified file; do not buffer media in memory."""
    parsed = urlsplit(path)
    if (parsed.scheme or parsed.netloc or parsed.fragment
            or not _is_agent_path(parsed.path)):
        raise ValueError("Resource path must stay within /api/agent/v1/")
    base = urlsplit(client.base_url)
    if base.scheme not in {"http", "https"} or not base.hostname or base.query or base.fragment or base.username:
        raise ValueError("Agent base URL must be an HTTP(S) server without embedded credentials")
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
        raise ValueError("max_bytes must be a positive integer")
    if expected_sha256 is not None and not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256):
        raise ValueError("expected_sha256 must contain 64 hex characters")
    headers = {"Accept": "*/*", "Accept-Encoding": "identity"}
    if client.app_token:
        headers["Authorization"] = "Bearer " + client.app_token
    request = Request(client.base_url + path, method="GET", headers=headers)
    target = Path(destination)
    temporary = None
    try:
        with build_opener(_SameOriginRedirect()).open(request, timeout=client.timeout) as response:
            if response.status != 200:
                raise AgentClientError("Resource response was not a complete file", code="RESOURCE_INCOMPLETE")
            length_header = response.headers.get("Content-Length")
            length = int(length_header) if length_header is not None else None
            if length is not None and (length < 0 or length > max_bytes):
                raise AgentClientError("Resource exceeds the download size limit", code="RESOURCE_TOO_LARGE")
            target.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            size = 0
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".ppt-download-", delete=False) as output:
                temporary = Path(output.name)
                while chunk := response.read(CHUNK_BYTES):
                    size += len(chunk)
                    if size > max_bytes:
                        raise AgentClientError("Resource exceeds the download size limit", code="RESOURCE_TOO_LARGE")
                    digest.update(chunk)
                    output.write(chunk)
            if length is not None and size != length:
                raise AgentClientError("Resource download was incomplete", code="RESOURCE_INCOMPLETE")
            actual_hash = digest.hexdigest()
            if expected_sha256 and actual_hash != expected_sha256.lower():
                raise AgentClientError("Resource hash does not match", code="RESOURCE_HASH_MISMATCH")
            content_type = response.headers.get_content_type()
        os.replace(temporary, target)
        return {"saved_to": str(target), "bytes": size, "sha256": actual_hash,
                "content_type": content_type}
    except HTTPError as exc:
        raw = exc.read(CHUNK_BYTES).decode("utf-8", errors="replace")
        try:
            error = json.loads(raw).get("error", {})
            raise AgentClientError(error.get("message", "Resource request failed"), exc.code,
                                   error.get("details", {}), error.get("code", "")) from exc
        except (ValueError, AttributeError):
            raise AgentClientError("Resource request failed", exc.code) from exc
    except (URLError, OSError, HTTPException, ValueError) as exc:
        raise AgentClientError("Resource transfer failed: " + str(exc), code="RESOURCE_TRANSFER_FAILED") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def upload_file(client, path: str, file_path: str | Path, *,
                field: str = "file",
                form_fields: dict | None = None,
                content_type: str | None = None,
                max_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES) -> dict:
    """Bounded multipart upload to a declared /api/agent/v1/ file transport.

    The file size is validated before any byte is read; the server's JSON
    reply is returned verbatim and structured errors propagate like downloads.
    """
    parsed = urlsplit(path)
    if (parsed.scheme or parsed.netloc or parsed.fragment
            or not _is_agent_path(parsed.path)):
        raise ValueError("Resource path must stay within /api/agent/v1/")
    base = urlsplit(client.base_url)
    if base.scheme not in {"http", "https"} or not base.hostname or base.query or base.fragment or base.username:
        raise ValueError("Agent base URL must be an HTTP(S) server without embedded credentials")
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
        raise ValueError("max_bytes must be a positive integer")
    source = Path(file_path)
    if not source.is_file():
        raise AgentClientError("Upload source file does not exist", code="UPLOAD_SOURCE_MISSING")
    size = source.stat().st_size
    if size > max_bytes:
        raise AgentClientError("Upload exceeds the size limit", code="RESOURCE_TOO_LARGE")
    if form_fields is not None and not isinstance(form_fields, dict):
        raise ValueError("form_fields must be a dict of strings")
    fields = {str(k): str(v) for k, v in (form_fields or {}).items()}

    boundary = "ppt-agent-upload-" + uuid.uuid4().hex
    body = bytearray()
    for name, value in fields.items():
        body += (f"--{boundary}\r\n"
                 f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                 f"{value}\r\n").encode("utf-8")
    upload_name = source.name.replace('"', "")
    declared_type = content_type or "application/octet-stream"
    body += (f"--{boundary}\r\n"
             f'Content-Disposition: form-data; name="{field}"; filename="{upload_name}"\r\n'
             f"Content-Type: {declared_type}\r\n\r\n").encode("utf-8")
    with open(source, "rb") as handle:
        while chunk := handle.read(CHUNK_BYTES):
            body += chunk
    body += f"\r\n--{boundary}--\r\n".encode("utf-8")

    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body)),
    }
    if client.app_token:
        headers["Authorization"] = "Bearer " + client.app_token
    request = Request(client.base_url + path, data=bytes(body), method="POST", headers=headers)
    try:
        with build_opener().open(request, timeout=client.timeout) as response:
            payload = json.loads(response.read(CHUNK_BYTES * 64).decode("utf-8"))
        return payload
    except HTTPError as exc:
        raw = exc.read(CHUNK_BYTES).decode("utf-8", errors="replace")
        try:
            error = json.loads(raw).get("error", {})
            raise AgentClientError(error.get("message", "Upload request failed"), exc.code,
                                   error.get("details", {}), error.get("code", "")) from exc
        except (ValueError, AttributeError):
            raise AgentClientError("Upload request failed", exc.code) from exc
    except (URLError, OSError, HTTPException, ValueError) as exc:
        raise AgentClientError("Resource transfer failed: " + str(exc), code="RESOURCE_TRANSFER_FAILED") from exc
