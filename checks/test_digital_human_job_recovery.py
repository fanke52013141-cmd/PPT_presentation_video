import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import comfyui_backend as backend
import digital_human_service as service


@pytest.fixture()
def isolated_jobs(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "JOB_DIR", tmp_path)
    monkeypatch.setattr(service, "_jobs", {})
    monkeypatch.setattr(service, "_recovering_jobs", set())
    return tmp_path


def test_restart_retains_exact_engine_prompt_and_retrieves_without_submission(isolated_jobs, monkeypatch):
    job = {"job_id": "job_test", "status": "processing", "engine_prompt_id": "exact-prompt",
           "output_path": str(isolated_jobs / "result.mp4"), "error": "old error", "slide_id": "full"}
    (isolated_jobs / "job_test.json").write_text(json.dumps(job))
    service._load_persisted_jobs()
    assert service._jobs["job_test"]["status"] == "waiting_external"
    calls = []
    def recover(prompt, output, workflow):
        calls.append(prompt)
        Path(output).write_bytes(b"downloaded verified video")
        return True
    monkeypatch.setattr(backend, "recover_comfyui_result", recover)
    monkeypatch.setattr(backend, "_submit_prompt", lambda *_: pytest.fail("recovery submitted a new generation"))
    public = service.get_job("job_test")
    assert public["status"] == "done" and public["progress"] == 100 and public["error"] is None
    assert calls == ["exact-prompt"]
    service.get_job("job_test")
    assert calls == ["exact-prompt"]
    assert json.loads((isolated_jobs / "job_test.json").read_text())["error"] is None


def test_temporary_recovery_error_keeps_external_job_pending(isolated_jobs, monkeypatch):
    service._jobs["job_test"] = {"job_id": "job_test", "status": "waiting_external", "engine_prompt_id": "original",
        "output_path": str(isolated_jobs / "result.mp4")}
    def offline(*_):
        raise ConnectionError("temporarily unavailable")
    monkeypatch.setattr(backend, "recover_comfyui_result", offline)
    result = service.get_job("job_test")
    assert result["status"] == "waiting_external" and result["recoverable"]
    assert not service._recovering_jobs


def test_engine_error_is_not_misclassified_as_success_when_completed_flag_is_set(monkeypatch):
    response = SimpleNamespace(status_code=200, json=lambda: {"exact": {
        "status": {"completed": True, "status_str": "error", "messages": "failed"}}})
    client = SimpleNamespace(get=lambda _: response)
    with pytest.raises(backend.ComfyUIExecutionError):
        backend._poll_history(client, "exact", timeout=1)


def test_engine_acknowledgement_is_persisted_before_polling(isolated_jobs, monkeypatch):
    job = {"job_id": "job_ack", "status": "processing"}
    service._jobs["job_ack"] = job
    workflow = {"1": {"class_type": "VHS_VideoCombine", "inputs": {}}}
    job["workflow_template"] = workflow
    monkeypatch.setattr(backend, "check_health", lambda: True)
    monkeypatch.setattr(backend, "inspect_video_preflight", lambda _: {"success": True})
    def inference(**kwargs):
        kwargs["on_submitted"]("acknowledged-prompt")
        persisted = json.loads((isolated_jobs / "job_ack.json").read_text())
        assert persisted["engine_prompt_id"] == "acknowledged-prompt"
        raise backend.ComfyUIWaitTimeout("still waiting")
    monkeypatch.setattr(backend, "run_comfyui_inference", inference)
    with pytest.raises(backend.ComfyUIWaitTimeout):
        service._run_comfyui_inference(job, Path("avatar.png"), Path("audio.mp3"), isolated_jobs / "output.mp4")
