"""Tests for structured trace context and correlated logging.

Covers:
- TraceContext context manager lifecycle
- get/set/clear trace_id
- TraceLoggingFilter injection into log records
- generate_trace_id format
- bind_trace_logger dedup
- Integration with request tracing middleware
"""

from __future__ import annotations

import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


# ---------------------------------------------------------------------------
# Trace ID generation and accessors
# ---------------------------------------------------------------------------

def test_generate_trace_id_length():
    """generate_trace_id must return a 16-char hex string."""
    from agent_api.trace_context import generate_trace_id

    tid = generate_trace_id()
    assert isinstance(tid, str)
    assert len(tid) == 16
    # Must be hex
    int(tid, 16)


def test_generate_trace_id_unique():
    """Two calls must produce different IDs."""
    from agent_api.trace_context import generate_trace_id

    ids = {generate_trace_id() for _ in range(100)}
    assert len(ids) == 100


def test_get_trace_id_default_none():
    """get_trace_id must return None when no context is active."""
    from agent_api.trace_context import get_trace_id

    assert get_trace_id() is None


def test_set_and_clear_trace_id():
    """set_trace_id and clear_trace_id must work as a pair."""
    from agent_api.trace_context import set_trace_id, get_trace_id, clear_trace_id

    token = set_trace_id("test-tid-001")
    assert get_trace_id() == "test-tid-001"

    clear_trace_id(token)
    assert get_trace_id() is None


# ---------------------------------------------------------------------------
# TraceContext context manager
# ---------------------------------------------------------------------------

def test_trace_context_sets_and_clears():
    """TraceContext must set the trace_id on entry and clear on exit."""
    from agent_api.trace_context import TraceContext, get_trace_id

    assert get_trace_id() is None

    with TraceContext("ctx-tid-001") as tid:
        assert tid == "ctx-tid-001"
        assert get_trace_id() == "ctx-tid-001"

    assert get_trace_id() is None


def test_trace_context_auto_generates_id():
    """TraceContext must auto-generate when no ID is provided."""
    from agent_api.trace_context import TraceContext, get_trace_id

    with TraceContext() as tid:
        assert tid is not None
        assert len(tid) == 16
        assert get_trace_id() == tid

    assert get_trace_id() is None


def test_trace_context_clears_on_exception():
    """TraceContext must clear the trace_id even if the block raises."""
    from agent_api.trace_context import TraceContext, get_trace_id

    with pytest.raises(RuntimeError):
        with TraceContext("err-tid"):
            raise RuntimeError("test")

    assert get_trace_id() is None


def test_trace_context_nesting():
    """Nested TraceContext must restore the parent's trace_id on exit."""
    from agent_api.trace_context import TraceContext, get_trace_id

    with TraceContext("outer"):
        assert get_trace_id() == "outer"
        with TraceContext("inner"):
            assert get_trace_id() == "inner"
        assert get_trace_id() == "outer"

    assert get_trace_id() is None


# ---------------------------------------------------------------------------
# TraceLoggingFilter
# ---------------------------------------------------------------------------

def test_trace_logging_filter_injects_trace_id():
    """TraceLoggingFilter must add trace_id to log records."""
    from agent_api.trace_context import TraceLoggingFilter, TraceContext

    filt = TraceLoggingFilter()
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__,
        lineno=1, msg="test message", args=(), exc_info=None,
    )

    # Without context, trace_id should be "-"
    assert filt.filter(record) is True
    assert record.trace_id == "-"

    # With context, trace_id should be the active ID
    with TraceContext("log-tid-123"):
        record2 = logging.LogRecord(
            name="test", level=logging.INFO, pathname=__file__,
            lineno=1, msg="test message", args=(), exc_info=None,
        )
        assert filt.filter(record2) is True
        assert record2.trace_id == "log-tid-123"


def test_bind_trace_logger_attaches_filter():
    """bind_trace_logger must attach TraceLoggingFilter exactly once."""
    from agent_api.trace_context import bind_trace_logger, TraceLoggingFilter

    logger = bind_trace_logger("PPTStudio.TestTrace")
    filters = [f for f in logger.filters if isinstance(f, TraceLoggingFilter)]
    assert len(filters) >= 1

    # Calling again must not duplicate
    bind_trace_logger("PPTStudio.TestTrace")
    filters2 = [f for f in logger.filters if isinstance(f, TraceLoggingFilter)]
    assert len(filters2) == 1


def test_trace_filter_return_true():
    """TraceLoggingFilter.filter must always return True (allow logging)."""
    from agent_api.trace_context import TraceLoggingFilter

    filt = TraceLoggingFilter()
    record = logging.LogRecord(
        name="x", level=logging.DEBUG, pathname="", lineno=0,
        msg="", args=(), exc_info=None,
    )
    assert filt.filter(record) is True


# ---------------------------------------------------------------------------
# Integration: log records within TraceContext
# ---------------------------------------------------------------------------

def test_log_within_trace_context_has_id():
    """A logger with TraceLoggingFilter must include trace_id in records."""
    from agent_api.trace_context import TraceContext, TraceLoggingFilter

    lg = logging.getLogger("PPTStudio.TestIntegration")
    lg.addFilter(TraceLoggingFilter())

    records: list[logging.LogRecord] = []

    class CaptureHandler(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = CaptureHandler()
    lg.addHandler(handler)
    lg.setLevel(logging.DEBUG)

    with TraceContext("integration-tid"):
        lg.info("Processing request within trace")

    assert len(records) == 1
    assert hasattr(records[0], "trace_id")
    assert records[0].trace_id == "integration-tid"

    # Cleanup
    lg.removeHandler(handler)
