#!/usr/bin/env python3
"""Stable local launcher for PPT Visualization Studio.

`python server.py` still works, but it starts Uvicorn from the import string
`server:app`, which can import the large server module a second time in some
local environments. This launcher imports `server.app` once and passes the app
object directly to Uvicorn.

Usage:

    python start_server.py

Optional environment variables:

    PPT_STUDIO_HOST=127.0.0.1
    PPT_STUDIO_PORT=8000
"""

from __future__ import annotations

import os

import uvicorn

from server import app


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = int(str(raw).strip())
    except ValueError as exc:
        raise SystemExit(f"{name} must be an integer, got: {raw!r}") from exc
    if value < 1 or value > 65535:
        raise SystemExit(f"{name} must be between 1 and 65535, got: {value}")
    return value


def main() -> int:
    host = os.environ.get("PPT_STUDIO_HOST", "0.0.0.0").strip() or "0.0.0.0"
    port = _int_env("PPT_STUDIO_PORT", 8000)
    uvicorn.run(app, host=host, port=port, reload=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
