"""Agent source adapters to source-owned business services."""

from __future__ import annotations

from typing import Any
from fastapi import Depends
from sqlalchemy.orm import Session
from database import get_db
from agent_contract.models import SourceSetRequest, SourceSetResult
from agent_api.errors import ValidationFailedError, ConflictError
from agent_api.fingerprints import request_fingerprint
from agent_idempotency_service import get_idempotency_service, IdempotencyConflictError
from fastapi import APIRouter

from agent_api.domain_routes.common import (
    _idempotency_replay_or_raise,
    _resolve_project,
    finalize_claim_failure,
)

router = APIRouter()


@router.post("/projects/{project_id}/source")
def agent_set_source(
    project_id: str,
    payload: SourceSetRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Set project source — direct content or topic-based generation."""
    project = _resolve_project(db, project_id)

    idempotency = get_idempotency_service()
    try:
        claim = idempotency.claim(
            "source.set",
            project_id,
            payload.idempotency_key or "",
            request_fingerprint(
                "source.set", payload.model_dump(mode="json"), project_id=project_id
            ),
        )
    except IdempotencyConflictError as e:
        raise ConflictError(str(e), details=e.details)
    replay = _idempotency_replay_or_raise(claim)
    if replay is not None:
        return replay

    try:
        import article_service as article_svc

        if payload.content:
            # Direct article import
            result = article_svc.import_article(project, payload.content, db)
            article_text = payload.content
        elif payload.topic:
            # Topic-based generation
            gen_payload = {"topic": payload.topic}
            result = article_svc.generate_article_from_topic(project, gen_payload)
            article_text = str(result.get("content") or "")
            # Topic generation only produces text.  Persist it through the same
            # source-owned import path used by the web UI before reporting success.
            article_svc.import_article(project, article_text, db)
        else:
            raise ValidationFailedError("Either 'content' or 'topic' must be provided")

        preview = article_text[:500] if article_text else ""
        word_count = len(article_text) if article_text else 0

        response = SourceSetResult(
            project_id=project_id,
            article_imported=True,
            article_preview=preview,
            word_count=word_count,
        ).model_dump()
        idempotency.finalize(claim.record_pk, True, response)
        return response
    except Exception as exc:
        finalize_claim_failure(claim, exc)
        raise
