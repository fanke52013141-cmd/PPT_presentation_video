from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy.exc import OperationalError

from video_job_store import VideoJobPersistenceError, VideoJobStore


def _operational_error(message: str) -> OperationalError:
    return OperationalError(
        "INSERT INTO local_jobs ...",
        {"project_id": "must-not-appear-in-diagnostics"},
        sqlite3.OperationalError(message),
    )


class _Session:
    def __init__(self, commit_result: Exception | None = None) -> None:
        self.commit_result = commit_result
        self.added = []
        self.rollback_calls = 0
        self.close_calls = 0
        self.refreshed = []
        self.expunged = []

    def add(self, value) -> None:
        self.added.append(value)

    def commit(self) -> None:
        if self.commit_result:
            raise self.commit_result

    def rollback(self) -> None:
        self.rollback_calls += 1

    def close(self) -> None:
        self.close_calls += 1

    def refresh(self, value) -> None:
        self.refreshed.append(value)

    def expunge(self, value) -> None:
        self.expunged.append(value)


def _store_for(sessions: list[_Session], delays: list[float]) -> VideoJobStore:
    def factory():
        return sessions.pop(0)

    return VideoJobStore(factory, sleep=delays.append)


def test_create_retries_sqlite_locked_with_fresh_sessions() -> None:
    first = _Session(_operational_error("database is locked"))
    second = _Session()
    sessions = [first, second]
    delays: list[float] = []

    created = _store_for(sessions, delays).create(
        "project-001",
        job_id="job-001",
        stage="validating",
        payload={},
    )

    assert created.id == "job-001"
    assert first.rollback_calls == first.close_calls == 1
    assert second.rollback_calls == second.close_calls == 1
    assert delays == [0.15]
    assert sessions == []


def test_create_stops_after_bounded_sqlite_locked_retries() -> None:
    created_sessions = [
        _Session(_operational_error("database is locked"))
        for _ in range(3)
    ]
    sessions = list(created_sessions)
    delays: list[float] = []

    with pytest.raises(VideoJobPersistenceError) as raised:
        _store_for(sessions, delays).create(
            "project-001",
            job_id="job-001",
            stage="validating",
            payload={},
        )

    error = raised.value
    assert error.category == "sqlite_write_locked"
    assert error.exception_type == "OperationalError"
    assert error.attempt_count == 3
    assert error.retryable is True
    assert error.public_message == "本地任务数据库正忙，请稍后重试。"
    assert delays == [0.15, 0.5]
    assert sessions == []
    assert all(item.rollback_calls == item.close_calls == 1 for item in created_sessions)


def test_create_does_not_retry_non_lock_operational_errors() -> None:
    failed = _Session(_operational_error("disk I/O error"))
    sessions = [failed]
    delays: list[float] = []

    with pytest.raises(VideoJobPersistenceError) as raised:
        _store_for(sessions, delays).create(
            "project-001",
            job_id="job-001",
            stage="validating",
            payload={},
        )

    error = raised.value
    assert error.category == "database_operational_error"
    assert error.attempt_count == 1
    assert error.retryable is False
    assert delays == []
    assert sessions == []
    assert failed.rollback_calls == failed.close_calls == 1
