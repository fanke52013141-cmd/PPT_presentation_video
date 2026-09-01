"""Tests for the SQLite-backed rate limit persistence store.

Covers:
- RateLimitStore basic allow/block behavior
- State persistence across store instances (simulating process restart)
- Cleanup of expired entries
- Middleware integration with persistent_store
- get_client_count accuracy
"""

from __future__ import annotations

import os
import sys
import tempfile
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


# ---------------------------------------------------------------------------
# Store creation helper
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_store():
    """Create a RateLimitStore backed by a temporary file."""
    from agent_api.rate_limit_store import RateLimitStore

    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, "test_rate_limit.db")
    store = RateLimitStore(db_path)
    yield store
    # Cleanup
    try:
        os.remove(db_path)
    except OSError:
        pass
    os.rmdir(tmpdir)


# ---------------------------------------------------------------------------
# Store behavior
# ---------------------------------------------------------------------------

def test_store_allows_under_limit(temp_store):
    """Store must allow requests under the limit."""
    allowed, remaining, retry = temp_store.record_and_check("client-1", max_requests=5, window_seconds=60)
    assert allowed is True
    assert remaining == 4
    assert retry == 0


def test_store_blocks_over_limit(temp_store):
    """Store must block when the limit is exceeded."""
    for _ in range(3):
        temp_store.record_and_check("client-2", max_requests=3, window_seconds=60)

    allowed, remaining, retry = temp_store.record_and_check("client-2", max_requests=3, window_seconds=60)
    assert allowed is False
    assert remaining == 0
    assert retry >= 1


def test_store_independent_clients(temp_store):
    """Each client key must have its own independent counter."""
    temp_store.record_and_check("client-a", max_requests=2, window_seconds=60)
    temp_store.record_and_check("client-a", max_requests=2, window_seconds=60)

    # Client A should be blocked now
    allowed_a, _, _ = temp_store.record_and_check("client-a", max_requests=2, window_seconds=60)
    assert allowed_a is False

    # Client B should still be allowed
    allowed_b, remaining_b, _ = temp_store.record_and_check("client-b", max_requests=2, window_seconds=60)
    assert allowed_b is True
    assert remaining_b == 1


def test_store_persistence_across_instances(temp_store):
    """Rate limit state must persist across store instances (process restart simulation)."""
    db_path = temp_store._db_path

    # Use up some of the limit
    for _ in range(4):
        temp_store.record_and_check("persist-client", max_requests=5, window_seconds=600)

    # Create a new store pointing at the same DB file
    from agent_api.rate_limit_store import RateLimitStore
    new_store = RateLimitStore(db_path)

    # The new store should see the previous 4 hits
    allowed, remaining, _ = new_store.record_and_check("persist-client", max_requests=5, window_seconds=600)
    assert allowed is True
    assert remaining == 0  # 5th hit fills the limit

    # 6th hit should be blocked
    allowed2, _, _ = new_store.record_and_check("persist-client", max_requests=5, window_seconds=600)
    assert allowed2 is False


def test_store_cleanup_removes_expired(temp_store):
    """Cleanup must remove entries older than the given window."""
    # Record a hit with a very short window
    temp_store.record_and_check("expiring-client", max_requests=10, window_seconds=1)

    # Wait for it to expire
    time.sleep(1.5)

    # Cleanup with a 1-second window should remove the expired entry
    deleted = temp_store.cleanup(window_seconds=1)
    assert deleted >= 1

    # After cleanup, the client should be allowed again
    allowed, remaining, _ = temp_store.record_and_check("expiring-client", max_requests=10, window_seconds=60)
    assert allowed is True
    assert remaining == 9


def test_store_get_client_count(temp_store):
    """get_client_count must accurately report hits within the window."""
    for _ in range(3):
        temp_store.record_and_check("count-client", max_requests=10, window_seconds=60)

    count = temp_store.get_client_count("count-client", window_seconds=60)
    assert count == 3

    # Different client should have 0
    count_other = temp_store.get_client_count("other-client", window_seconds=60)
    assert count_other == 0


def test_store_reset_clears_all(temp_store):
    """reset must clear all stored hits."""
    for _ in range(5):
        temp_store.record_and_check("reset-client", max_requests=10, window_seconds=60)

    assert temp_store.get_client_count("reset-client", window_seconds=60) == 5

    temp_store.reset()

    assert temp_store.get_client_count("reset-client", window_seconds=60) == 0


# ---------------------------------------------------------------------------
# Middleware integration with persistent store
# ---------------------------------------------------------------------------

def test_middleware_uses_persistent_store():
    """Middleware must delegate to the persistent store when provided."""
    from agent_api.rate_limit import AgentRateLimitMiddleware

    class MockStore:
        def __init__(self):
            self.called = 0
            self.args = None

        def record_and_check(self, key, max_req, window):
            self.called += 1
            self.args = (key, max_req, window)
            return True, 10, 0

    mock_store = MockStore()

    async def dummy_app(request):
        from starlette.responses import PlainTextResponse
        return PlainTextResponse("ok")

    middleware = AgentRateLimitMiddleware(
        dummy_app,
        max_requests=5,
        window_seconds=30,
        persistent_store=mock_store,
    )

    # The in-memory hits dict should not be used when a store is set
    assert middleware._store is mock_store
    assert middleware._store is not None

    # Simulate a check
    allowed, remaining, retry = middleware._check_and_record("test-key")
    assert mock_store.called == 1
    assert mock_store.args == ("test-key", 5, 30)
    assert allowed is True
    assert remaining == 10


def test_store_singleton_is_none_by_default():
    """The module-level singleton must be None until first access."""
    from agent_api.rate_limit_store import _store, reset_rate_limit_store_singleton

    # Reset to ensure clean state
    reset_rate_limit_store_singleton()
    from agent_api.rate_limit_store import _store as current
    assert current is None


def test_store_singleton_returns_same_instance(tmp_path):
    """get_rate_limit_store must return the same instance on repeated calls."""
    from agent_api.rate_limit_store import get_rate_limit_store, reset_rate_limit_store_singleton

    reset_rate_limit_store_singleton()
    db_path = str(tmp_path / "singleton_test.db")
    store1 = get_rate_limit_store(db_path)
    store2 = get_rate_limit_store(db_path)
    assert store1 is store2
    reset_rate_limit_store_singleton()
