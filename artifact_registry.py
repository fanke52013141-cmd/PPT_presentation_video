"""Database registry helpers for generated project files."""

from __future__ import annotations

from pathlib import Path
import json
import uuid
from typing import Any

from database import ArtifactRecord


def record_artifact(
    db,
    *,
    project_id: str,
    artifact_type: str,
    path: str | Path,
    relative_path: str,
    mime_type: str,
    source_fingerprint: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> ArtifactRecord:
    target = Path(path)
    existing = db.query(ArtifactRecord).filter(
        ArtifactRecord.project_id == project_id,
        ArtifactRecord.artifact_type == artifact_type,
        ArtifactRecord.filename == target.name,
    ).first()
    artifact = existing or ArtifactRecord(
        id=uuid.uuid4().hex,
        project_id=project_id,
        artifact_type=artifact_type,
        filename=target.name,
        relative_path=relative_path,
        mime_type=mime_type,
    )
    artifact.size_bytes = target.stat().st_size
    artifact.source_fingerprint = json.dumps(
        source_fingerprint or {},
        ensure_ascii=False,
        sort_keys=True,
    )
    artifact.metadata_json = json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True)
    if not existing:
        db.add(artifact)
    db.flush()
    return artifact


def remove_artifact_record(
    db,
    *,
    project_id: str,
    artifact_type: str,
    filename: str,
) -> int:
    return db.query(ArtifactRecord).filter(
        ArtifactRecord.project_id == project_id,
        ArtifactRecord.artifact_type == artifact_type,
        ArtifactRecord.filename == filename,
    ).delete(synchronize_session=False)

