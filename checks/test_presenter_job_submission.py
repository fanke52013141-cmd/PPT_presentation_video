"""Pending requests cannot relabel published video or consume later edits."""
import copy
from pathlib import Path

import pytest

from artifact_fingerprint import sha256_file
from digital_human_job_submission import PresenterSubmissionDependencies, submit_presenter_job
from digital_human_source_service import generation_source_fingerprint, presenter_source_stale, presenter_audio_stale


def fixture_state(tmp_path):
    audio = tmp_path / "slides/s1/voice.mp3"
    motion = tmp_path / "planning/digital_human/motion_reference.mp4"
    for path, value in [(audio, b"new-audio"), (motion, b"new-motion")]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
    config = {"mode": "portrait", "motion_source": "custom", "avatar_id": "av_new",
              "circle": {"r": 0.12}, "slides": {"s1": {"published": {
                  "job_id": "previous", "source_sha256": "old-source", "audio_sha256": "old-audio",
              }}}}
    def read():
        return copy.deepcopy(config)
    def write(value):
        config.clear()
        config.update(copy.deepcopy(value))
    def build(value):
        return {"avatar_id": value["avatar_id"], "audio_path": str(audio),
                "backend": "portrait", "driving_path": str(motion), "slide_id": "s1"}
    return config, read, write, build, audio, motion


def test_pending_and_failed_replacement_do_not_relabel_previous_video(tmp_path):
    config, read, write, build, audio, motion = fixture_state(tmp_path)
    def create(payload):
        # Edits after submission cannot alter the immutable engine inputs.
        audio.write_bytes(b"later-audio")
        motion.write_bytes(b"later-motion")
        assert Path(payload["audio_path"]).read_bytes() == b"new-audio"
        assert Path(payload["driving_path"]).read_bytes() == b"new-motion"
        concurrent = read()
        concurrent["circle"]["r"] = 0.2
        write(concurrent)
        return {"job_id": "job_" + payload["request_id"], "status": "queued"}
    deps = PresenterSubmissionDependencies(read, write, build, create, lambda: [])
    submit_presenter_job(tmp_path, "s1", deps)
    entry = config["slides"]["s1"]
    assert config["circle"]["r"] == 0.2
    assert entry["published"]["job_id"] == "previous"
    assert entry["audio_sha256"] != sha256_file(audio)
    assert presenter_source_stale(tmp_path, config, entry)
    assert presenter_audio_stale(tmp_path, entry, "s1")
    entry["status"] = "failed"
    assert presenter_source_stale(tmp_path, config, entry)


def test_unknown_submission_reuses_exact_request_and_snapshots(tmp_path):
    config, read, write, build, audio, motion = fixture_state(tmp_path)
    attempts = []
    def create(payload):
        attempts.append(copy.deepcopy(payload))
        if len(attempts) == 1:
            raise TimeoutError("accepted, but response lost")
        return {"job_id": "job_" + payload["request_id"], "status": "processing"}
    deps = PresenterSubmissionDependencies(read, write, build, create, lambda: [])
    with pytest.raises(TimeoutError):
        submit_presenter_job(tmp_path, "s1", deps)
    assert config["slides"]["s1"]["status"] == "submission_unknown"
    submit_presenter_job(tmp_path, "s1", deps)
    assert attempts[0] == attempts[1]
    assert config["slides"]["s1"]["published"]["job_id"] == "previous"


def test_published_binding_becomes_stale_when_confirmed_audio_changes(tmp_path):
    config, _, _, _, audio, _ = fixture_state(tmp_path)
    entry = config["slides"]["s1"]
    entry["published"] = {"source_sha256": generation_source_fingerprint(tmp_path, config),
                          "audio_sha256": sha256_file(audio)}
    assert not presenter_source_stale(tmp_path, config, entry)
    assert not presenter_audio_stale(tmp_path, entry, "s1")
    audio.write_bytes(b"new-confirmed-narration")
    assert presenter_audio_stale(tmp_path, entry, "s1")


def test_engine_exact_request_replay_does_not_launch_second_worker(tmp_path, monkeypatch):
    from fastapi import HTTPException
    import digital_human_service as service
    avatar = tmp_path / "avatars"
    avatar.mkdir()
    (avatar / "av_test.png").write_bytes(b"portrait")
    audio = tmp_path / "voice.mp3"
    audio.write_bytes(b"narration")
    starts = []
    class Worker:
        def __init__(self, *args, **kwargs):
            pass
        def start(self):
            starts.append(True)
    monkeypatch.setattr(service, "AVATAR_DIR", avatar)
    monkeypatch.setattr(service, "JOB_DIR", tmp_path / "jobs")
    monkeypatch.setattr(service, "_jobs", {})
    monkeypatch.setattr(service.threading, "Thread", Worker)
    payload = {"avatar_id": "av_test", "audio_path": str(audio), "backend": "comfyui",
               "request_id": "a" * 32}
    first = service.create_job(payload)
    assert service.create_job(dict(payload)) == first
    assert len(starts) == 1
    with pytest.raises(HTTPException) as error:
        service.create_job({**payload, "slide_id": "another-slide"})
    assert error.value.status_code == 409
