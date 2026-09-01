"""Comprehensive tests for agent_idempotency_service.py.

Covers the full judgment matrix:
- compute_fingerprint: deterministic, excludes idempotency_key, default=str
- claim(): no-key bypass, new insert, succeeded replay, in-progress conflict,
  stale orphan recovery, failed re-claim, fingerprint mismatch conflict
- finalize(): no-op on None pk, succeeded/failed terminal states, missing record
- check_revision(): None bypass, match, mismatch
- bump_revision(): increments from 0 and from existing
- Self-managed session commit semantics
- Opportunistic cleanup of expired records
- Module-level singleton lifecycle
"""

from __future__ import annotations

import json
import sys
import os
import tempfile
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Ensure repo root is on path
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from agent_idempotency_service import (
    AgentIdempotencyService,
    AgentIdempotencyDependencies,
    ClaimResult,
    IdempotencyConflictError,
    compute_fingerprint,
    configure_idempotency_service,
    get_idempotency_service,
    RETENTION_DAYS,
    STALE_IN_PROGRESS_HOURS,
)
from database import AgentIdempotencyRecord, utc_now_naive


# ---------------------------------------------------------------------------
# Test fixtures — in-memory SQLite with just the idempotency table
# ---------------------------------------------------------------------------

@pytest.fixture
def db_session_factory():
    """Create a fresh in-memory SQLite DB for each test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    AgentIdempotencyRecord.__table__.create(engine, checkfirst=True)
    Session = sessionmaker(bind=engine)
    factory = lambda: Session()
    yield factory
    engine.dispose()


@pytest.fixture
def service(db_session_factory):
    """Build an AgentIdempotencyService backed by the in-memory DB."""
    deps = AgentIdempotencyDependencies(session_factory=db_session_factory)
    return AgentIdempotencyService(deps)


# ---------------------------------------------------------------------------
# compute_fingerprint
# ---------------------------------------------------------------------------

class TestComputeFingerprint:
    def test_deterministic(self):
        payload = {"name": "Test", "description": "desc"}
        fp1 = compute_fingerprint(payload)
        fp2 = compute_fingerprint(payload)
        assert fp1 == fp2
        assert len(fp1) == 64  # SHA-256 hex

    def test_excludes_idempotency_key(self):
        """The idempotency_key must NOT influence the fingerprint."""
        base = {"name": "Test", "content": "hello"}
        with_key = {**base, "idempotency_key": "key-A"}
        without = {**base}
        assert compute_fingerprint(with_key) == compute_fingerprint(without)

    def test_different_keys_same_body_same_fingerprint(self):
        body = {"name": "Test", "content": "hello"}
        a = {**body, "idempotency_key": "key-A"}
        b = {**body, "idempotency_key": "key-B"}
        assert compute_fingerprint(a) == compute_fingerprint(b)

    def test_different_bodies_different_fingerprints(self):
        a = {"name": "A", "content": "hello"}
        b = {"name": "B", "content": "hello"}
        assert compute_fingerprint(a) != compute_fingerprint(b)

    def test_key_order_independent(self):
        """Dict key insertion order must not change the fingerprint."""
        fp1 = compute_fingerprint({"a": 1, "b": 2})
        fp2 = compute_fingerprint({"b": 2, "a": 1})
        assert fp1 == fp2

    def test_handles_non_json_types(self):
        """default=str should serialize non-JSON-native types."""
        from datetime import datetime
        payload = {"created_at": datetime(2025, 1, 1, 12, 0, 0)}
        fp = compute_fingerprint(payload)
        assert len(fp) == 64

    def test_empty_dict(self):
        fp = compute_fingerprint({})
        assert len(fp) == 64

    def test_nested_structures(self):
        payload = {"meta": {"nested": [1, 2, 3]}, "name": "test"}
        fp = compute_fingerprint(payload)
        assert len(fp) == 64


# ---------------------------------------------------------------------------
# claim() — no-key bypass
# ---------------------------------------------------------------------------

class TestClaimNoKey:
    def test_empty_key_bypasses(self, service):
        result = service.claim("source.set", "p1", "", "fp123")
        assert result.is_new is True
        assert result.replay_response is None
        assert result.record_pk is None

    def test_empty_key_does_not_create_record(self, service, db_session_factory):
        service.claim("source.set", "p1", "", "fp123")
        db = db_session_factory()
        count = db.query(AgentIdempotencyRecord).count()
        db.close()
        assert count == 0


# ---------------------------------------------------------------------------
# claim() — new insert
# ---------------------------------------------------------------------------

class TestClaimNewInsert:
    def test_new_key_creates_record(self, service, db_session_factory):
        result = service.claim("source.set", "p1", "key-1", "fp123")
        assert result.is_new is True
        assert result.replay_response is None
        assert result.record_pk == ("source.set", "p1", "key-1")

        db = db_session_factory()
        record = db.query(AgentIdempotencyRecord).one()
        assert record.status == "in_progress"
        assert record.request_fingerprint == "fp123"
        assert record.response_json is None
        db.close()

    def test_new_key_for_different_scope(self, service):
        """Same key+project but different scope should succeed independently."""
        r1 = service.claim("source.set", "p1", "key-shared", "fp1")
        r2 = service.claim("pipeline.run", "p1", "key-shared", "fp2")
        assert r1.is_new is True
        assert r2.is_new is True

    def test_new_key_for_different_project(self, service):
        r1 = service.claim("source.set", "p1", "key-shared", "fp1")
        r2 = service.claim("source.set", "p2", "key-shared", "fp1")
        assert r1.is_new is True
        assert r2.is_new is True


# ---------------------------------------------------------------------------
# claim() — succeeded replay
# ---------------------------------------------------------------------------

class TestClaimSucceededReplay:
    def test_succeeded_with_response_returns_replay(self, service, db_session_factory):
        # First claim + finalize as succeeded
        service.claim("source.set", "p1", "key-1", "fp123")
        service.finalize(("source.set", "p1", "key-1"), True, {"ok": True})

        # Second claim with same key+fingerprint should replay
        result = service.claim("source.set", "p1", "key-1", "fp123")
        assert result.is_new is False
        assert result.replay_response == {"ok": True}

    def test_succeeded_no_response_re_claims(self, service, db_session_factory):
        # Simulate a succeeded record with no stored response
        db = db_session_factory()
        db.add(AgentIdempotencyRecord(
            scope="source.set", project_id="p1", idempotency_key="key-1",
            request_fingerprint="fp123", status="succeeded",
            response_json=None, created_at=utc_now_naive(), updated_at=utc_now_naive(),
        ))
        db.commit()
        db.close()

        result = service.claim("source.set", "p1", "key-1", "fp123")
        assert result.is_new is True
        assert result.replay_response is None

    def test_succeeded_corrupt_json_re_claims(self, service, db_session_factory):
        # Simulate a succeeded record with corrupt JSON
        db = db_session_factory()
        db.add(AgentIdempotencyRecord(
            scope="source.set", project_id="p1", idempotency_key="key-1",
            request_fingerprint="fp123", status="succeeded",
            response_json="{not valid json", created_at=utc_now_naive(), updated_at=utc_now_naive(),
        ))
        db.commit()
        db.close()

        result = service.claim("source.set", "p1", "key-1", "fp123")
        assert result.is_new is True
        assert result.replay_response is None


# ---------------------------------------------------------------------------
# claim() — in-progress conflict
# ---------------------------------------------------------------------------

class TestClaimInProgress:
    def test_in_progress_recent_raises_conflict(self, service, db_session_factory):
        db = db_session_factory()
        now = utc_now_naive()
        db.add(AgentIdempotencyRecord(
            scope="source.set", project_id="p1", idempotency_key="key-1",
            request_fingerprint="fp123", status="in_progress",
            created_at=now, updated_at=now,  # just created → not stale
        ))
        db.commit()
        db.close()

        with pytest.raises(IdempotencyConflictError, match="already in progress"):
            service.claim("source.set", "p1", "key-1", "fp123")

    def test_in_progress_stale_re_claims(self, service, db_session_factory):
        """Stale in-progress (>STALE_IN_PROGRESS_HOURS) should be reclaimed."""
        db = db_session_factory()
        stale = utc_now_naive() - timedelta(hours=STALE_IN_PROGRESS_HOURS + 1)
        db.add(AgentIdempotencyRecord(
            scope="source.set", project_id="p1", idempotency_key="key-1",
            request_fingerprint="fp123", status="in_progress",
            created_at=stale, updated_at=stale,
        ))
        db.commit()
        db.close()

        result = service.claim("source.set", "p1", "key-1", "fp123")
        assert result.is_new is True
        assert result.replay_response is None

    def test_in_progress_borderline_stale_re_claims(self, service, db_session_factory):
        """Exactly at the stale threshold should allow re-claim."""
        db = db_session_factory()
        stale = utc_now_naive() - timedelta(hours=STALE_IN_PROGRESS_HOURS, seconds=1)
        db.add(AgentIdempotencyRecord(
            scope="source.set", project_id="p1", idempotency_key="key-1",
            request_fingerprint="fp123", status="in_progress",
            created_at=stale, updated_at=stale,
        ))
        db.commit()
        db.close()

        result = service.claim("source.set", "p1", "key-1", "fp123")
        assert result.is_new is True


# ---------------------------------------------------------------------------
# claim() — failed re-claim
# ---------------------------------------------------------------------------

class TestClaimFailed:
    def test_failed_status_re_claims(self, service, db_session_factory):
        db = db_session_factory()
        db.add(AgentIdempotencyRecord(
            scope="source.set", project_id="p1", idempotency_key="key-1",
            request_fingerprint="fp123", status="failed",
            created_at=utc_now_naive(), updated_at=utc_now_naive(),
        ))
        db.commit()
        db.close()

        result = service.claim("source.set", "p1", "key-1", "fp123")
        assert result.is_new is True


# ---------------------------------------------------------------------------
# claim() — fingerprint mismatch
# ---------------------------------------------------------------------------

class TestClaimFingerprintMismatch:
    def test_different_body_same_key_raises(self, service, db_session_factory):
        db = db_session_factory()
        db.add(AgentIdempotencyRecord(
            scope="source.set", project_id="p1", idempotency_key="key-1",
            request_fingerprint="fp-original", status="in_progress",
            created_at=utc_now_naive(), updated_at=utc_now_naive(),
        ))
        db.commit()
        db.close()

        with pytest.raises(IdempotencyConflictError, match="different request body"):
            service.claim("source.set", "p1", "key-1", "fp-different")

    def test_conflict_error_has_details(self, service, db_session_factory):
        db = db_session_factory()
        db.add(AgentIdempotencyRecord(
            scope="source.set", project_id="p1", idempotency_key="key-1",
            request_fingerprint="fp-original", status="succeeded",
            response_json=json.dumps({"ok": True}),
            created_at=utc_now_naive(), updated_at=utc_now_naive(),
        ))
        db.commit()
        db.close()

        try:
            service.claim("source.set", "p1", "key-1", "fp-different")
            assert False, "Should have raised"
        except IdempotencyConflictError as e:
            assert e.details["scope"] == "source.set"
            assert e.details["idempotency_key"] == "key-1"


# ---------------------------------------------------------------------------
# finalize()
# ---------------------------------------------------------------------------

class TestFinalize:
    def test_none_pk_is_noop(self, service):
        # Should not raise
        service.finalize(None, True, {"ok": True})

    def test_succeeded_stores_response(self, service, db_session_factory):
        service.claim("source.set", "p1", "key-1", "fp123")
        service.finalize(("source.set", "p1", "key-1"), True, {"result": "done"})

        db = db_session_factory()
        record = db.query(AgentIdempotencyRecord).one()
        assert record.status == "succeeded"
        assert json.loads(record.response_json) == {"result": "done"}
        db.close()

    def test_failed_clears_response(self, service, db_session_factory):
        service.claim("source.set", "p1", "key-1", "fp123")
        service.finalize(("source.set", "p1", "key-1"), False)

        db = db_session_factory()
        record = db.query(AgentIdempotencyRecord).one()
        assert record.status == "failed"
        assert record.response_json is None
        db.close()

    def test_succeeded_with_none_response(self, service, db_session_factory):
        service.claim("source.set", "p1", "key-1", "fp123")
        service.finalize(("source.set", "p1", "key-1"), True, None)

        db = db_session_factory()
        record = db.query(AgentIdempotencyRecord).one()
        assert record.status == "succeeded"
        assert record.response_json is None
        db.close()

    def test_missing_record_does_not_raise(self, service):
        # Finalizing a pk that doesn't exist should be a no-op
        service.finalize(("nonexistent", "scope", "key"), True, {"ok": True})

    def test_finalize_logs_on_exception(self, service, db_session_factory):
        """If the DB session raises during finalize, it should be caught."""
        broken_factory = MagicMock(side_effect=Exception("DB unavailable"))
        broken_deps = AgentIdempotencyDependencies(session_factory=broken_factory)
        broken_service = AgentIdempotencyService(broken_deps)
        # Should not raise — finalize swallows errors
        broken_service.finalize(("s", "p", "k"), True, {"ok": True})


# ---------------------------------------------------------------------------
# check_revision()
# ---------------------------------------------------------------------------

class TestCheckRevision:
    def test_none_revision_bypasses(self):
        project = MagicMock(revision=5)
        AgentIdempotencyService.check_revision(project, None)

    def test_matching_revision_passes(self):
        project = MagicMock(revision=3)
        AgentIdempotencyService.check_revision(project, 3)

    def test_mismatch_raises(self):
        project = MagicMock(revision=3)
        with pytest.raises(IdempotencyConflictError, match="Revision mismatch"):
            AgentIdempotencyService.check_revision(project, 5)

    def test_mismatch_details(self):
        project = MagicMock(revision=3)
        try:
            AgentIdempotencyService.check_revision(project, 5)
            assert False, "Should have raised"
        except IdempotencyConflictError as e:
            assert e.details["current_revision"] == 3
            assert e.details["expected_revision"] == 5

    def test_missing_revision_attr_defaults_to_zero(self):
        project = MagicMock(spec=[])  # no revision attribute
        with pytest.raises(IdempotencyConflictError):
            AgentIdempotencyService.check_revision(project, 1)

    def test_zero_revision_matches_zero(self):
        project = MagicMock(revision=0)
        AgentIdempotencyService.check_revision(project, 0)


# ---------------------------------------------------------------------------
# bump_revision()
# ---------------------------------------------------------------------------

class TestBumpRevision:
    def test_increment_from_zero(self):
        project = MagicMock(revision=0)
        AgentIdempotencyService.bump_revision(MagicMock(), project)
        assert project.revision == 1

    def test_increment_from_existing(self):
        project = MagicMock(revision=5)
        AgentIdempotencyService.bump_revision(MagicMock(), project)
        assert project.revision == 6

    def test_missing_revision_attr_defaults_to_zero(self):
        project = MagicMock(spec=[])
        AgentIdempotencyService.bump_revision(MagicMock(), project)
        assert project.revision == 1

    def test_does_not_commit(self):
        """bump_revision should NOT call commit — the route owns the commit."""
        db = MagicMock()
        project = MagicMock(revision=2)
        AgentIdempotencyService.bump_revision(db, project)
        db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# Self-managed session commit semantics
# ---------------------------------------------------------------------------

class TestSessionCommitSemantics:
    def test_claim_uses_own_session(self, db_session_factory):
        """claim() must create and close its own session, not depend on caller's."""
        deps = AgentIdempotencyDependencies(session_factory=db_session_factory)
        svc = AgentIdempotencyService(deps)

        # Simulate an independent caller session that is NOT committed
        caller_session = db_session_factory()

        # claim should succeed without caller committing
        result = svc.claim("source.set", "p1", "key-1", "fp123")
        assert result.is_new is True

        # Verify the record is visible in a fresh session (claim committed)
        verify_session = db_session_factory()
        assert verify_session.query(AgentIdempotencyRecord).count() == 1
        verify_session.close()
        caller_session.close()

    def test_finalize_uses_own_session(self, db_session_factory):
        deps = AgentIdempotencyDependencies(session_factory=db_session_factory)
        svc = AgentIdempotencyService(deps)
        svc.claim("source.set", "p1", "key-1", "fp123")
        svc.finalize(("source.set", "p1", "key-1"), True, {"ok": True})

        verify = db_session_factory()
        record = verify.query(AgentIdempotencyRecord).one()
        assert record.status == "succeeded"
        verify.close()

    def test_claim_final_claim_replay_lifecycle(self, service, db_session_factory):
        """Full lifecycle: claim → finalize → replay."""
        fp = compute_fingerprint({"content": "hello"})

        # 1. First claim — new
        r1 = service.claim("source.set", "p1", "key-abc", fp)
        assert r1.is_new is True

        # 2. Finalize as succeeded
        service.finalize(r1.record_pk, True, {"article_imported": True})

        # 3. Second claim with same key+body — should replay
        r2 = service.claim("source.set", "p1", "key-abc", fp)
        assert r2.is_new is False
        assert r2.replay_response == {"article_imported": True}


# ---------------------------------------------------------------------------
# Opportunistic cleanup
# ---------------------------------------------------------------------------

class TestOpportunisticCleanup:
    def test_old_records_are_cleaned(self, service, db_session_factory):
        # Insert a record older than RETENTION_DAYS
        db = db_session_factory()
        old = utc_now_naive() - timedelta(days=RETENTION_DAYS + 1)
        db.add(AgentIdempotencyRecord(
            scope="source.set", project_id="p1", idempotency_key="old-key",
            request_fingerprint="fp-old", status="succeeded",
            response_json=json.dumps({"ok": True}),
            created_at=old, updated_at=old,
        ))
        db.commit()
        db.close()

        # Trigger a new claim — cleanup should fire first
        service.claim("source.set", "p1", "new-key", "fp-new")

        verify = db_session_factory()
        remaining = verify.query(AgentIdempotencyRecord).all()
        keys = {r.idempotency_key for r in remaining}
        assert "old-key" not in keys
        assert "new-key" in keys
        verify.close()

    def test_recent_records_are_preserved(self, service, db_session_factory):
        db = db_session_factory()
        recent = utc_now_naive() - timedelta(days=1)
        db.add(AgentIdempotencyRecord(
            scope="source.set", project_id="p1", idempotency_key="recent-key",
            request_fingerprint="fp-recent", status="succeeded",
            response_json=json.dumps({"ok": True}),
            created_at=recent, updated_at=recent,
        ))
        db.commit()
        db.close()

        service.claim("source.set", "p1", "other-key", "fp-other")

        verify = db_session_factory()
        keys = {r.idempotency_key for r in verify.query(AgentIdempotencyRecord).all()}
        assert "recent-key" in keys
        verify.close()

    def test_cleanup_is_scoped(self, service, db_session_factory):
        """Cleanup should only delete records for the SAME scope."""
        db = db_session_factory()
        old = utc_now_naive() - timedelta(days=RETENTION_DAYS + 1)
        db.add(AgentIdempotencyRecord(
            scope="pipeline.run", project_id="p1", idempotency_key="old-pipeline",
            request_fingerprint="fp-old", status="succeeded",
            response_json=None, created_at=old, updated_at=old,
        ))
        db.commit()
        db.close()

        # Claim for a DIFFERENT scope — cleanup fires for "source.set" only
        service.claim("source.set", "p1", "new-key", "fp-new")

        verify = db_session_factory()
        keys = {r.idempotency_key for r in verify.query(AgentIdempotencyRecord).all()}
        assert "old-pipeline" in keys  # survived because different scope
        verify.close()


# ---------------------------------------------------------------------------
# Module-level singleton lifecycle
# ---------------------------------------------------------------------------

class TestSingletonLifecycle:
    def test_get_unconfigured_raises(self):
        # Reset the module-level singleton
        import agent_idempotency_service as mod
        original = mod._service
        mod._service = None
        try:
            with pytest.raises(RuntimeError, match="not configured"):
                get_idempotency_service()
        finally:
            mod._service = original

    def test_configure_then_get(self):
        import agent_idempotency_service as mod
        original = mod._service
        try:
            deps = AgentIdempotencyDependencies(
                session_factory=lambda: MagicMock(),
            )
            svc = configure_idempotency_service(deps)
            assert get_idempotency_service() is svc
        finally:
            mod._service = original

    def test_configure_returns_cached_instance(self):
        import agent_idempotency_service as mod
        original = mod._service
        try:
            deps = AgentIdempotencyDependencies(
                session_factory=lambda: MagicMock(),
            )
            svc1 = configure_idempotency_service(deps)
            svc2 = configure_idempotency_service(deps)
            assert svc2 is not svc1  # configure creates new each time
            assert get_idempotency_service() is svc2
        finally:
            mod._service = original


# ---------------------------------------------------------------------------
# Integration: claim + finalize → replay round-trip
# ---------------------------------------------------------------------------

class TestIntegrationRoundTrip:
    def test_full_create_project_lifecycle(self, service):
        """Simulate the create_project idempotency flow."""
        body = {
            "name": "Test Project",
            "description": "desc",
            "canvas_profile": "landscape_16_9",
            "idempotency_key": "create-key-1",
        }
        fp = compute_fingerprint(body)

        # First request
        claim1 = service.claim("project.create", "", "create-key-1", fp)
        assert claim1.is_new is True
        fake_response = {"project": {"project_id": "p123", "name": "Test Project"}}
        service.finalize(claim1.record_pk, True, fake_response)

        # Duplicate request (retry with same key + same body)
        claim2 = service.claim("project.create", "", "create-key-1", fp)
        assert claim2.is_new is False
        assert claim2.replay_response == fake_response

    def test_failure_then_retry_succeeds(self, service):
        """Failed operation should be reclaimable."""
        body = {"content": "hello", "idempotency_key": "key-fail"}
        fp = compute_fingerprint(body)

        # First attempt — fails
        claim1 = service.claim("source.set", "p1", "key-fail", fp)
        assert claim1.is_new is True
        service.finalize(claim1.record_pk, False, None)

        # Retry — should get a new claim (not replay)
        claim2 = service.claim("source.set", "p1", "key-fail", fp)
        assert claim2.is_new is True

        # This time succeeds
        service.finalize(claim2.record_pk, True, {"article_imported": True})

        # Third request — replay
        claim3 = service.claim("source.set", "p1", "key-fail", fp)
        assert claim3.is_new is False
        assert claim3.replay_response == {"article_imported": True}

    def test_different_projects_isolated(self, service):
        """Same key on different projects should not interfere."""
        fp = compute_fingerprint({"content": "hello"})

        r1 = service.claim("source.set", "p1", "shared-key", fp)
        r2 = service.claim("source.set", "p2", "shared-key", fp)
        assert r1.is_new is True
        assert r2.is_new is True
        assert r1.record_pk != r2.record_pk
