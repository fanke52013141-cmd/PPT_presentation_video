import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database import Project
from server import (
    audio_confirmation_path,
    handle_step_navigation,
    mark_step_in_progress,
    project_audio_confirmed,
)
from tts_artifacts import (
    CONFIRMATION_HASH_KEYS,
    artifact_paths,
    build_confirmation_payload,
)


class DummyDb:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1


with tempfile.TemporaryDirectory() as run_dir:
    os.makedirs(os.path.join(run_dir, "planning"), exist_ok=True)
    project = Project(id="test", name="test", run_dir=run_dir, current_step=6)
    project.set_step_status({str(i): "pending" for i in range(1, 9)})
    db = DummyDb()

    mark_step_in_progress(project, 7, db)
    assert project.get_step_status()["7"] == "in_progress"

    paths = artifact_paths(run_dir, "slide_001")
    for key in ("text", "audio", "metadata", "srt", "timeline"):
        paths[key].parent.mkdir(parents=True, exist_ok=True)
        paths[key].write_text(f"{key}-content", encoding="utf-8")
    project.set_step_status({str(i): "pending" for i in range(1, 9)})
    (Path(run_dir) / "planning" / "visual_contract.json").write_text(
        json.dumps({"slides": [{"slide_id": "slide_001"}]}),
        encoding="utf-8",
    )
    with open(audio_confirmation_path(project), "w", encoding="utf-8") as f:
        json.dump(
            build_confirmation_payload(run_dir, ["slide_001"], confirmation_mode="user_reviewed"),
            f,
        )
    assert project_audio_confirmed(project)

    paths["text"].write_text("changed narration", encoding="utf-8")
    assert not project_audio_confirmed(project)
    with open(audio_confirmation_path(project), "w", encoding="utf-8") as f:
        json.dump(
            build_confirmation_payload(run_dir, ["slide_001"], confirmation_mode="user_reviewed"),
            f,
        )

    handle_step_navigation(project, 6, db)
    assert not project_audio_confirmed(project)
    assert project.get_step_status()["7"] == "pending"


# --- voice fingerprint: a later TTS config change invalidates confirmation ---
import tts_artifacts
from tts_artifacts import confirmation_status

VOICE_RUNTIME = {
    "endpoint": "https://tts.example/v1",
    "model": "speech-2.8-hd",
    "voice_id": "voice-a",
    "clone_voice_id": "",
    "speed": "1.2",
    "volume": "1.0",
    "pitch": "0",
}

with tempfile.TemporaryDirectory() as runtime_dir:
    os.makedirs(os.path.join(runtime_dir, "planning"), exist_ok=True)
    runtime_paths = artifact_paths(runtime_dir, "slide_001")
    for key in CONFIRMATION_HASH_KEYS:
        runtime_paths[key].parent.mkdir(parents=True, exist_ok=True)
        runtime_paths[key].write_text(f"{key}-content", encoding="utf-8")
    with open(os.path.join(runtime_dir, "planning", "audio_confirmed.json"), "w", encoding="utf-8") as f:
        json.dump(
            build_confirmation_payload(
                runtime_dir,
                ["slide_001"],
                confirmation_mode="user_reviewed",
                tts_runtime=VOICE_RUNTIME,
            ),
            f,
        )

    # Resolver unavailable (unconfigured process) must keep the old behavior.
    tts_artifacts.set_confirmation_runtime_resolver(None)
    assert confirmation_status(runtime_dir, ["slide_001"])["confirmed"]

    # Identical live fingerprint stays confirmed.
    tts_artifacts.set_confirmation_runtime_resolver(lambda _rd: dict(VOICE_RUNTIME))
    assert confirmation_status(runtime_dir, ["slide_001"])["confirmed"]

    # A changed voice flips the confirmation and names the changed key.
    def _changed_voice(_rd):
        changed = dict(VOICE_RUNTIME)
        changed["voice_id"] = "voice-b"
        return changed

    tts_artifacts.set_confirmation_runtime_resolver(_changed_voice)
    status = confirmation_status(runtime_dir, ["slide_001"])
    assert not status["confirmed"]
    assert status["reason"] == "config_changed"
    assert status["changed_keys"] == ["voice_id"]
    tts_artifacts.set_confirmation_runtime_resolver(None)

# Pre-v2 confirmation files without a stored fingerprint are rejected as legacy.
with tempfile.TemporaryDirectory() as legacy_dir:
    os.makedirs(os.path.join(legacy_dir, "planning"), exist_ok=True)
    legacy_paths = artifact_paths(legacy_dir, "slide_001")
    for key in CONFIRMATION_HASH_KEYS:
        legacy_paths[key].parent.mkdir(parents=True, exist_ok=True)
        legacy_paths[key].write_text("content", encoding="utf-8")
    payload = build_confirmation_payload(
        legacy_dir, ["slide_001"], confirmation_mode="user_reviewed", tts_runtime=VOICE_RUNTIME
    )
    payload["schema_version"] = 2
    with open(os.path.join(legacy_dir, "planning", "audio_confirmed.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f)
    assert confirmation_status(legacy_dir, ["slide_001"])["reason"] == "legacy_confirmation"

print("audio confirmation checks passed")
