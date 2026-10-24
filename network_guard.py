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


_TRUE_VALUES = {"1", "true", "yes"}


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUE_VALUES


def validate_network_security(host: str) -> None:
    if is_loopback_host(host):
        return
    if not os.environ.get("PPT_STUDIO_ACCESS_TOKEN", "").strip():
        if _env_flag("PPT_STUDIO_ALLOW_INSECURE_NETWORK"):
            # 显式豁免 Web 面检查；Agent 面使用独立凭据，仍需单独确认。
            _validate_agent_surface()
            return
        raise SystemExit(
            "Refusing to listen on a non-loopback address without PPT_STUDIO_ACCESS_TOKEN. "
            "Set a token, use PPT_STUDIO_HOST=127.0.0.1, or explicitly opt in with "
            "PPT_STUDIO_ALLOW_INSECURE_NETWORK=1."
        )
    _validate_agent_surface()


def _validate_agent_surface() -> None:
    """Agent API 使用独立凭据（PPT_AGENT_API_KEY），不能由 Web 令牌代替保护。

    273 个能力包含删除项目与写入供应商凭据，未认证暴露在非回环地址上等于
    把整台工作站的管理面开放给局域网（历史缺陷：Web 守卫放行的局域网部署
    中 Agent 面仍处于匿名开放状态）。
    """
    if os.environ.get("PPT_AGENT_API_KEY", "").strip():
        return
    if _env_flag("PPT_AGENT_ALLOW_INSECURE_AGENT_API"):
        return
    raise SystemExit(
        "Refusing to expose the Agent API on a non-loopback address without "
        "PPT_AGENT_API_KEY. Set PPT_AGENT_API_KEY, bind PPT_STUDIO_HOST=127.0.0.1, "
        "or explicitly opt in with PPT_AGENT_ALLOW_INSECURE_AGENT_API=1."
    )
