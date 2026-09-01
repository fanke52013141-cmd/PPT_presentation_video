"""Structured trace context for correlated logging across Agent API requests.

Uses ``contextvars`` (ASGI-safe, thread-safe) to propagate a ``trace_id``
throughout a request's call stack without threading it explicitly through
every function signature.

Components:
- :class:`TraceContext` — context manager that sets/clears the trace_id.
- :func:`get_trace_id` / :func:`set_trace_id` — direct accessors.
- :class:`TraceLoggingFilter` — ``logging.Filter`` that injects
  ``trace_id`` into every log record emitted within the context.

Integration point: ``AgentRequestTracingMiddleware`` calls
``set_trace_id(request_id)`` at the start of each Agent API request and
``clear_trace_id()`` after the response is returned.
"""

from __future__ import annotations

import contextlib
import logging
import uuid
from contextvars import ContextVar
from typing import Iterator, Optional

# ContextVar is safe for async contexts (ASGI) and survives task copies.
_trace_id_var: ContextVar[Optional[str]] = ContextVar("agent_trace_id", default=None)

_DEFAULT_TRACE_ID_LENGTH = 16


def generate_trace_id() -> str:
    """Generate a new short trace ID."""
    return uuid.uuid4().hex[:_DEFAULT_TRACE_ID_LENGTH]


def get_trace_id() -> Optional[str]:
    """Return the current trace ID or ``None`` if not set."""
    return _trace_id_var.get()


def set_trace_id(trace_id: Optional[str]) -> contextlib.Token[Optional[str]]:
    """Set the current trace ID. Returns a token for restoration."""
    return _trace_id_var.set(trace_id)


def clear_trace_id(token: contextlib.Token[Optional[str]]) -> None:
    """Reset the trace ID using the token from :func:`set_trace_id`."""
    _trace_id_var.reset(token)


@contextlib.contextmanager
def TraceContext(trace_id: Optional[str] = None) -> Iterator[str]:
    """Context manager that activates a trace ID for the duration of the block.

    If *trace_id* is ``None`` a new one is generated.

    Usage::

        with TraceContext("req-123") as tid:
            logger.info("Processing request")  # filter adds trace_id
    """
    tid = trace_id or generate_trace_id()
    token = set_trace_id(tid)
    try:
        yield tid
    finally:
        clear_trace_id(token)


class TraceLoggingFilter(logging.Filter):
    """Logging filter that injects ``trace_id`` into each log record.

    Attach to a logger to automatically include the current trace context
    in every emitted record::

        filt = TraceLoggingFilter()
        logging.getLogger("myapp").addFilter(filt)
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = get_trace_id() or "-"
        return True


def bind_trace_logger(logger_name: str = "PPTStudio.AgentAPI") -> logging.Logger:
    """Create a logger pre-bound with :class:`TraceLoggingFilter`.

    This is a convenience for modules that want structured trace logging
    without manually managing filter attachment.
    """
    lg = logging.getLogger(logger_name)
    # Avoid duplicate filter attachment.
    if not any(isinstance(f, TraceLoggingFilter) for f in lg.filters):
        lg.addFilter(TraceLoggingFilter())
    return lg
