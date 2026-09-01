"""Agent API idempotency persistence and optimistic-locking service.

This module owns:
- Request fingerprint computation (sha256 of normalized request body)
- Idempotency claim/finalize lifecycle (self-managed sessions with immediate
  commit, matching the VideoJobStore pattern)
- Optimistic revision locking (uses the caller's request-scoped session — no
  commit; the route owns the single database commit)
- Opportunity-based cleanup of expired records (no background thread)

Dependencies are injected as a frozen record; this module never imports the
application module, FastAPI wiring, or database session helpers directly.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Callable, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import AgentIdempotencyRecord, utc_now_naive

logger = logging.getLogger("PPTStudio.AgentIdempotency")

RETENTION_DAYS = 7
STALE_IN_PROGRESS_HOURS = 1


@dataclass(frozen=True)
class AgentIdempotencyDependencies:
    """Frozen dependency record for the idempotency service."""
    session_factory: Callable[[], Session]


@dataclass
class ClaimResult:
    """Result of an idempotency claim.

    When ``is_new`` is True the caller should proceed with execution and then
    call ``finalize``.  When ``replay_response`` is not None the caller should
    return the stored response immediately (with a replay header).
    """
    is_new: bool
    replay_response: Optional[dict[str, Any]] = None
    record_pk: Optional[tuple[str, str, str]] = None


class IdempotencyConflictError(Exception):
    """Raised when a claim conflicts with an existing record.

    ``details`` dict is forwarded to the API layer for the error response body.
    """

    def __init__(self, message: str, details: Optional[dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.details = details or {}


def compute_fingerprint(payload: dict[str, Any]) -> str:
    """Compute a deterministic SHA-256 fingerprint of the request payload.

    ``idempotency_key`` is excluded so it does not influence the fingerprint.
    ``default=str`` ensures non-JSON-native types (UUID, datetime) are stable.
    """
    normalized = {k: v for k, v in payload.items() if k != "idempotency_key"}
    canonical = json.dumps(normalized, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class AgentIdempotencyService:
    """Manages idempotency records and optimistic revision locking."""

    def __init__(self, deps: AgentIdempotencyDependencies) -> None:
        self._session_factory = deps.session_factory

    # ------------------------------------------------------------------
    # Idempotency claim / finalize
    # ------------------------------------------------------------------

    def claim(
        self,
        scope: str,
        project_id: str,
        idempotency_key: str,
        fingerprint: str,
    ) -> ClaimResult:
        """Attempt to claim an idempotency slot.

        Returns a ``ClaimResult`` instructing the caller whether to proceed
        with execution (``is_new=True``) or replay a cached response.

        Raises ``IdempotencyConflictError`` on key reuse with a different
        request body, or when an operation is already in progress.
        """
        if not idempotency_key:
            # No key provided — bypass idempotency entirely.
            return ClaimResult(is_new=True, replay_response=None, record_pk=None)

        # Opportunity-based cleanup of expired records.
        self._cleanup_expired(scope)

        pk = (scope, project_id, idempotency_key)
        now = utc_now_naive()

        db = self._session_factory()
        try:
            record = AgentIdempotencyRecord(
                scope=scope,
                project_id=project_id,
                idempotency_key=idempotency_key,
                request_fingerprint=fingerprint,
                status="in_progress",
                created_at=now,
                updated_at=now,
            )
            db.add(record)
            db.commit()
            return ClaimResult(is_new=True, replay_response=None, record_pk=pk)
        except IntegrityError:
            db.rollback()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

        # PK conflict — an existing record was found.  Resolve by status.
        return self._resolve_existing(scope, project_id, idempotency_key, fingerprint, pk)

    def _resolve_existing(
        self,
        scope: str,
        project_id: str,
        idempotency_key: str,
        fingerprint: str,
        pk: tuple[str, str, str],
    ) -> ClaimResult:
        """Handle the case where a record with the same PK already exists."""
        now = utc_now_naive()
        db = self._session_factory()
        try:
            existing = (
                db.query(AgentIdempotencyRecord)
                .filter(
                    AgentIdempotencyRecord.scope == scope,
                    AgentIdempotencyRecord.project_id == project_id,
                    AgentIdempotencyRecord.idempotency_key == idempotency_key,
                )
                .first()
            )
            if existing is None:
                # Race between INSERT failure and read — treat as new.
                existing = AgentIdempotencyRecord(
                    scope=scope,
                    project_id=project_id,
                    idempotency_key=idempotency_key,
                    request_fingerprint=fingerprint,
                    status="in_progress",
                    created_at=now,
                    updated_at=now,
                )
                db.add(existing)
                db.commit()
                return ClaimResult(is_new=True, replay_response=None, record_pk=pk)

            # Fingerprint mismatch → key reuse with different body.
            if existing.request_fingerprint != fingerprint:
                raise IdempotencyConflictError(
                    "Idempotency key already used with a different request body",
                    details={"scope": scope, "idempotency_key": idempotency_key},
                )

            # Same fingerprint — dispatch by existing status.
            if existing.status == "succeeded":
                replay = None
                if existing.response_json:
                    try:
                        replay = json.loads(existing.response_json)
                    except (json.JSONDecodeError, TypeError):
                        replay = None
                if replay is not None:
                    return ClaimResult(is_new=False, replay_response=replay, record_pk=pk)
                # Succeeded but no stored response — fall through to re-execute.

            if existing.status == "in_progress":
                stale_threshold = now - timedelta(hours=STALE_IN_PROGRESS_HOURS)
                is_stale = existing.updated_at and existing.updated_at < stale_threshold
                if not is_stale:
                    raise IdempotencyConflictError(
                        "Operation is already in progress; poll for status "
                        "instead of retrying with the same idempotency key",
                        details={"scope": scope, "idempotency_key": idempotency_key},
                    )
                # Orphan — fall through to re-claim.

            # Re-claim: reset to in_progress (covers failed + stale + succeeded-no-response).
            existing.status = "in_progress"
            existing.request_fingerprint = fingerprint
            existing.response_json = None
            existing.updated_at = now
            db.commit()
            return ClaimResult(is_new=True, replay_response=None, record_pk=pk)
        except IdempotencyConflictError:
            raise
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def finalize(
        self,
        record_pk: Optional[tuple[str, str, str]],
        succeeded: bool,
        response: Optional[dict[str, Any]] = None,
    ) -> None:
        """Write the terminal state for an idempotency record."""
        if record_pk is None:
            return

        scope, project_id, key = record_pk
        now = utc_now_naive()

        db = None
        try:
            db = self._session_factory()
            record = (
                db.query(AgentIdempotencyRecord)
                .filter(
                    AgentIdempotencyRecord.scope == scope,
                    AgentIdempotencyRecord.project_id == project_id,
                    AgentIdempotencyRecord.idempotency_key == key,
                )
                .first()
            )
            if record:
                record.status = "succeeded" if succeeded else "failed"
                record.response_json = (
                    json.dumps(response, ensure_ascii=False)
                    if succeeded and response is not None
                    else None
                )
                record.updated_at = now
                db.commit()
        except Exception:
            if db is not None:
                db.rollback()
            logger.warning(
                "Failed to finalize idempotency record %s", record_pk, exc_info=True
            )
        finally:
            if db is not None:
                db.close()

    # ------------------------------------------------------------------
    # Optimistic revision locking
    # ------------------------------------------------------------------

    @staticmethod
    def check_revision(project: Any, expected_revision: Optional[int]) -> None:
        """Validate optimistic lock; raise on mismatch.

        Uses ``project`` as a detached ORM object — does not touch the session.
        """
        if expected_revision is None:
            return
        current = getattr(project, "revision", 0) or 0
        if current != expected_revision:
            raise IdempotencyConflictError(
                f"Revision mismatch: expected {expected_revision}, got {current}",
                details={
                    "current_revision": current,
                    "expected_revision": expected_revision,
                },
            )

    @staticmethod
    def bump_revision(db: Session, project: Any) -> None:
        """Increment the project revision.

        The caller's request-scoped session owns the commit (per
        "API callers own one database commit" policy).
        """
        current = getattr(project, "revision", 0) or 0
        project.revision = current + 1

    # ------------------------------------------------------------------
    # Opportunity-based cleanup
    # ------------------------------------------------------------------

    def _cleanup_expired(self, scope: str) -> None:
        """Delete records older than ``RETENTION_DAYS`` for this scope."""
        cutoff = utc_now_naive() - timedelta(days=RETENTION_DAYS)
        db = self._session_factory()
        try:
            (
                db.query(AgentIdempotencyRecord)
                .filter(
                    AgentIdempotencyRecord.scope == scope,
                    AgentIdempotencyRecord.created_at < cutoff,
                )
                .delete(synchronize_session=False)
            )
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()


# ---------------------------------------------------------------------------
# Module-level singleton (configured once by the application root)
# ---------------------------------------------------------------------------

_service: Optional[AgentIdempotencyService] = None


def configure_idempotency_service(deps: AgentIdempotencyDependencies) -> AgentIdempotencyService:
    """Create and cache the singleton idempotency service."""
    global _service
    _service = AgentIdempotencyService(deps)
    return _service


def get_idempotency_service() -> AgentIdempotencyService:
    """Return the configured idempotency service or raise."""
    if _service is None:
        raise RuntimeError(
            "AgentIdempotencyService is not configured; "
            "call configure_idempotency_service() at startup."
        )
    return _service
