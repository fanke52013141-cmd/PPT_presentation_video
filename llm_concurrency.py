"""Process-wide gate for concurrent outbound LLM chat-completion requests."""

from __future__ import annotations

import functools
import threading
from contextlib import contextmanager
from typing import Callable, Iterator, Optional

DEFAULT_LLM_MAX_CONCURRENCY = 2
LLM_MAX_CONCURRENCY_BOUNDS = (1, 4)

_setting_reader: Optional[Callable[[str, int, int, int], int]] = None


def configure_llm_concurrency(setting_reader: Callable[[str, int, int, int], int]) -> None:
    """Inject ``get_bounded_int_setting``-compatible reader (kept out of imports for tests)."""
    global _setting_reader
    _setting_reader = setting_reader


def _resolve_limit() -> int:
    if _setting_reader is not None:
        return _setting_reader("llm_max_concurrency", DEFAULT_LLM_MAX_CONCURRENCY, *LLM_MAX_CONCURRENCY_BOUNDS)
    from config_store import get_bounded_int_setting

    return get_bounded_int_setting(
        "llm_max_concurrency", DEFAULT_LLM_MAX_CONCURRENCY, *LLM_MAX_CONCURRENCY_BOUNDS
    )


class _LlmConcurrencyGate:
    """Condition-based slot counter so the configured limit can change at runtime."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._active = 0

    @contextmanager
    def slot(self) -> Iterator[None]:
        limit = max(1, _resolve_limit())
        with self._condition:
            while self._active >= limit:
                self._condition.wait()
            self._active += 1
        try:
            yield
        finally:
            with self._condition:
                self._active -= 1
                self._condition.notify_all()


_GATE = _LlmConcurrencyGate()


@contextmanager
def llm_request_slot() -> Iterator[None]:
    """Hold one shared LLM request slot; callers queue while the gate is full."""
    with _GATE.slot():
        yield


def with_llm_request_slot(func):
    """Decorate an entry-point request builder so the whole call holds one slot.

    Only outer entry points may use this: nested gated calls would deadlock at
    a limit of 1 because the gate is not re-entrant.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with llm_request_slot():
            return func(*args, **kwargs)

    return wrapper
