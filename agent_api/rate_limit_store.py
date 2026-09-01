"""SQLite-backed persistence store for the Agent API rate limiter.

When configured, the middleware delegates timestamp tracking to this store
so that rate-limit state survives process restarts. The store uses a
dedicated SQLite database (default ``data/agent_rate_limit.db``) with a
single table ``rate_limit_hits (client_key TEXT, ts REAL)``.

The hot path (record + check) is a single SQLite read-write transaction.
Expired entries are pruned on every access to keep the table small.
"""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from threading import Lock
from typing import Optional


_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS rate_limit_hits (
    client_key TEXT NOT NULL,
    ts         REAL NOT NULL
)
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_rate_limit_ts ON rate_limit_hits(ts)
"""


class RateLimitStore:
    """SQLite-backed sliding-window rate limit counter."""

    def __init__(self, db_path: str | os.PathLike[str] = "data/agent_rate_limit.db") -> None:
        self._db_path = str(db_path)
        self._lock = Lock()
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Create the table and index if they don't exist."""
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute(_CREATE_TABLE_SQL)
            conn.execute(_CREATE_INDEX_SQL)
            conn.commit()
        finally:
            conn.close()

    def record_and_check(
        self,
        client_key: str,
        max_requests: int,
        window_seconds: int,
    ) -> tuple[bool, int, int]:
        """Record a timestamp and check if the client is within limits.

        Returns ``(allowed, remaining, retry_after_seconds)``.
        """
        now = time.time()
        cutoff = now - window_seconds

        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                # Prune expired entries globally (cheap with index on ts).
                conn.execute("DELETE FROM rate_limit_hits WHERE ts < ?", (cutoff,))

                # Count current window hits for this client.
                cursor = conn.execute(
                    "SELECT ts FROM rate_limit_hits WHERE client_key = ? ORDER BY ts ASC",
                    (client_key,),
                )
                rows = cursor.fetchall()

                if len(rows) >= max_requests:
                    oldest = rows[0][0]
                    retry_after = int(oldest + window_seconds - now) + 1
                    conn.commit()
                    return False, 0, max(retry_after, 1)

                conn.execute(
                    "INSERT INTO rate_limit_hits (client_key, ts) VALUES (?, ?)",
                    (client_key, now),
                )
                conn.commit()
                remaining = max_requests - len(rows) - 1
                return True, remaining, 0
            finally:
                conn.close()

    def cleanup(self, window_seconds: int = 3600) -> int:
        """Remove entries older than *window_seconds*. Returns deleted count."""
        cutoff = time.time() - window_seconds
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                cursor = conn.execute(
                    "DELETE FROM rate_limit_hits WHERE ts < ?",
                    (cutoff,),
                )
                conn.commit()
                return cursor.rowcount
            finally:
                conn.close()

    def get_client_count(self, client_key: str, window_seconds: int) -> int:
        """Return the current hit count for a client within the window."""
        cutoff = time.time() - window_seconds
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM rate_limit_hits WHERE client_key = ? AND ts >= ?",
                    (client_key, cutoff),
                )
                return cursor.fetchone()[0]
            finally:
                conn.close()

    def reset(self) -> None:
        """Clear all stored hits (for testing)."""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute("DELETE FROM rate_limit_hits")
                conn.commit()
            finally:
                conn.close()


# Module-level singleton, lazily initialized.
_store: Optional[RateLimitStore] = None


def get_rate_limit_store(
    db_path: str | os.PathLike[str] = "data/agent_rate_limit.db",
) -> RateLimitStore:
    """Return the shared RateLimitStore singleton."""
    global _store
    if _store is None:
        _store = RateLimitStore(db_path)
    return _store


def reset_rate_limit_store_singleton() -> None:
    """Reset the module singleton (for testing)."""
    global _store
    _store = None
