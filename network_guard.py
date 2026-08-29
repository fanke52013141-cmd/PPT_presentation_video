"""Network binding safety checks.

Standalone, side-effect-free module so that test discovery can import these
helpers without pulling in the application composition root (AGENTS.md:
end-to-end entrypoints must not import ``server`` at module import time).
"""

from __future__ import annotations

import ipaddress
import os


def is_loopback_host(host: str) -> bool:
    normalized = host.strip().lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def validate_network_security(host: str) -> None:
    if is_loopback_host(host):
        return
    if os.environ.get("PPT_STUDIO_ACCESS_TOKEN", "").strip():
        return
    if os.environ.get("PPT_STUDIO_ALLOW_INSECURE_NETWORK", "").strip().lower() in {"1", "true", "yes"}:
        return
    raise SystemExit(
        "Refusing to listen on a non-loopback address without PPT_STUDIO_ACCESS_TOKEN. "
        "Set a token, use PPT_STUDIO_HOST=127.0.0.1, or explicitly opt in with "
        "PPT_STUDIO_ALLOW_INSECURE_NETWORK=1."
    )
