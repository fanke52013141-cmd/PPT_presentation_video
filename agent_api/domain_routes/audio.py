"""Agent audio adapters: narration, TTS and media settings (visible Step 5)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from agent_contract.domains.audio import (
    MediaSettingsUpdateRequest,
    NarrationResultUpdateRequest,
    OptionalFreeFormRequest,
    TtsAudioConfirmRequest,
)
from agent_contract.domains.freeform import FreeFormRequest
from database import get_db

import narration_service as narration
import tts_service as tts
from visual_settings_service import get_visual_settings_service

router = APIRouter()


@router.post("/projects/{project_id}/narration/init")
def agent_narration_init(project_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return narration.init_step6_narration(project_id, db)


@router.get("/projects/{project_id}/narration")
def agent_get_narration_result(project_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return narration.get_step6_result(project_id, db)


@router.put("/projects/{project_id}/narration")
def agent_update_narration_result(
    project_id: str,
    payload: NarrationResultUpdateRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return narration.update_step6_result(project_id, payload.payload, db)


@router.post("/projects/{project_id}/narration/repair")
def agent_repair_narration_result(project_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return narration.repair_step6_result(project_id, db)


@router.get("/narration-annotation/settings")
def agent_get_narration_annotation_settings() -> dict[str, Any]:
    return narration.get_narration_annotation_settings()


@router.put("/narration-annotation/settings")
def agent_update_narration_annotation_settings(payload: FreeFormRequest) -> dict[str, Any]:
    return narration.update_narration_annotation_settings(payload.payload)


@router.post("/projects/{project_id}/narration/annotate")
def agent_annotate_narration(
    project_id: str,
    payload: OptionalFreeFormRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return narration.annotate_step6_narration(project_id, db=db, payload=payload.payload)


@router.post("/projects/{project_id}/tts/sync")
def agent_tts_sync_synthesize(project_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return tts.synthesize_tts_resumable(project_id, db)


@router.get("/projects/{project_id}/tts/audio-status")
def agent_get_tts_audio_status(project_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return tts.get_tts_audio_status(project_id, db)


@router.post("/projects/{project_id}/tts/confirm")
def agent_confirm_tts_audio(
    project_id: str,
    payload: TtsAudioConfirmRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return tts.confirm_tts_audio(project_id, db=db, payload=payload.payload)


@router.get("/projects/{project_id}/media/background")
def agent_get_media_background(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    service = get_visual_settings_service()
    return service.get(project_id, db)


@router.put("/projects/{project_id}/media/background")
def agent_update_media_background(
    project_id: str,
    payload: MediaSettingsUpdateRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    service = get_visual_settings_service()
    return service.update_background(project_id, payload.payload, db)


@router.get("/projects/{project_id}/media/subtitles")
def agent_get_media_subtitles(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    service = get_visual_settings_service()
    return service.get_subtitles(project_id, db)


@router.put("/projects/{project_id}/media/subtitles")
def agent_update_media_subtitles(
    project_id: str,
    payload: MediaSettingsUpdateRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    service = get_visual_settings_service()
    return service.update_subtitles(project_id, payload.payload, db)
