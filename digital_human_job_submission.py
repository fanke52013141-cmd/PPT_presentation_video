"""Snapshot presenter inputs and reserve exact requests without replacing published media."""
from __future__ import annotations

from dataclasses import dataclass
import copy
from pathlib import Path
import shutil
from typing import Callable
import uuid

from artifact_fingerprint import sha256_file
from digital_human_source_service import generation_source_fingerprint
from pipeline_lifecycle import project_artifact_lock


@dataclass(frozen=True)
class PresenterSubmissionDependencies:
    read_config: Callable[[], dict]
    write_config: Callable[[dict], None]
    build_payload: Callable[[dict], dict]
    create_job: Callable[[dict], dict]
    impact_snapshot: Callable[[], list]


def submit_presenter_job(run_dir: str | Path, slide_id: str,
                         dependencies: PresenterSubmissionDependencies) -> dict:
    root = Path(run_dir).resolve()
    with project_artifact_lock(root):
        config = copy.deepcopy(dependencies.read_config())
        payload = dependencies.build_payload(config)
        audio_hash = sha256_file(payload["audio_path"])
        driving_hash = sha256_file(payload["driving_path"]) if payload.get("backend") == "portrait" else None
        source_hash = generation_source_fingerprint(root, config, motion_sha256=driving_hash)
        if not audio_hash:
            raise ValueError("旁白音频不存在")
        entry = config.setdefault("slides", {}).setdefault(slide_id, {})
        pending = entry.get("pending_request") or {}
        # A timed-out submission is retried with the same exact request and
        # immutable snapshots. It must never allocate a fresh generation key.
        same_options = all(payload.get(key) == pending.get(key) for key in (
            "avatar_id", "backend", "sync_mode", "workflow_template",
        ))
        retry = (entry.get("status") in {"submitting", "submission_unknown", "queued", "processing", "publishing", "waiting_external"}
                 and entry.get("audio_sha256") == audio_hash
                 and entry.get("source_sha256") == source_hash and pending and same_options)
        if retry:
            payload = copy.deepcopy(pending)
            if not Path(payload["audio_path"]).is_file():
                raise ValueError("待确认任务的输入快照缺失，请先核对原任务状态")
        else:
            token = uuid.uuid4().hex
            directory = root / "planning/digital_human/inputs" / token
            directory.mkdir(parents=True)
            audio = directory / "voice.mp3"
            shutil.copyfile(payload["audio_path"], audio)
            if sha256_file(audio) != audio_hash:
                raise ValueError("旁白在快照期间变化，请重新提交")
            payload["audio_path"] = str(audio)
            if payload.get("backend") == "portrait":
                original = Path(payload["driving_path"])
                driving = directory / "driving.mp4"
                shutil.copyfile(original, driving)
                if sha256_file(driving) != driving_hash:
                    raise ValueError("动作视频在快照期间变化，请重新提交")
                payload["driving_path"] = str(driving)
            payload["request_id"] = token
            # Preserve the published envelope even while another job is pending.
            entry.update(job_id="job_" + token, status="submitting",
                         audio_sha256=audio_hash, source_sha256=source_hash,
                         pending_request=copy.deepcopy(payload),
                         impact_snapshot=dependencies.impact_snapshot())
            dependencies.write_config(config)
        token = payload["request_id"]
    try:
        result = dependencies.create_job(payload)
    except Exception:
        with project_artifact_lock(root):
            latest = dependencies.read_config()
            current = (latest.get("slides") or {}).get(slide_id) or {}
            if (current.get("pending_request") or {}).get("request_id") == token:
                current["status"] = "submission_unknown"
                dependencies.write_config(latest)
        raise
    with project_artifact_lock(root):
        latest = dependencies.read_config()
        current = (latest.get("slides") or {}).get(slide_id) or {}
        if (current.get("pending_request") or {}).get("request_id") == token:
            current.update(job_id=result["job_id"], status=result.get("status", "queued"))
            dependencies.write_config(latest)
    return result
