"""Operation polling utility for long-running Agent tasks.

Usage:
    result = poll_operation(
        client,
        project_id="abc123",
        poll_fn=client.get_pipeline_status,
        config=PollConfig(timeout=300, interval=5),
    )
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from agent_client.client import AgentClient, AgentClientError


@dataclass(frozen=True)
class PollConfig:
    """Configuration for operation polling."""
    timeout: int = 300  # max seconds to wait
    interval: int = 5   # seconds between polls
    terminal_statuses: frozenset = frozenset({
        "succeeded", "failed", "cancelled", "interrupted", "waiting_for_review",
    })


def poll_operation(
    client: AgentClient,
    project_id: str,
    poll_fn: Callable[[str], dict[str, Any]],
    config: Optional[PollConfig] = None,
) -> dict[str, Any]:
    """Poll an operation until it reaches a terminal state or times out.

    Args:
        client: The AgentClient instance.
        project_id: The project to poll.
        poll_fn: A function that takes project_id and returns a status dict.
        config: Polling configuration.

    Returns:
        The final status dict.

    Raises:
        TimeoutError: If the operation doesn't complete within config.timeout.
    """
    cfg = config or PollConfig()
    start = time.monotonic()

    while True:
        result = poll_fn(project_id)
        status = result.get("status", "unknown")

        if status in cfg.terminal_statuses:
            return result

        elapsed = time.monotonic() - start
        if elapsed >= cfg.timeout:
            raise TimeoutError(
                f"Operation timed out after {cfg.timeout}s. "
                f"Last status: {status}, stage: {result.get('current_stage', 'unknown')}"
            )

        time.sleep(cfg.interval)
