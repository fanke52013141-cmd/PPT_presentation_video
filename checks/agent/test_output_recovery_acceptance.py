import json
from pathlib import Path
import subprocess
import time
import uuid

from checks.agent.test_full_workflow_mocked import api, invoke, workflow  # noqa: F401


def test_failed_pptx_job_retries_into_a_real_downloadable_export(workflow, api):
    from database import LocalJob, SessionLocal

    pid = workflow["project_id"]
    previous = "retry-acceptance-" + uuid.uuid4().hex
    with SessionLocal() as db:
        db.add(LocalJob(id=previous, project_id=pid, job_type="pptx_export", status="failed", progress=0,
            stage="failed", error="Controlled prior failure", payload_json=json.dumps({"mode": "image_only"})))
        db.commit()
    retried = invoke(api, "pptx.jobs.retry", {"project_id": pid, "job_id": previous})
    assert retried.status_code == 200, retried.text
    jid = retried.json()["job"]["id"]
    assert jid != previous
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        result = invoke(api, "pptx.jobs.get", {"project_id": pid, "job_id": jid})
        assert result.status_code == 200, result.text
        job = result.json()["job"]
        if job["status"] in {"succeeded", "failed", "interrupted"}:
            assert job["status"] == "succeeded" and not job.get("error"), result.text
            break
        time.sleep(.1)
    else:
        raise AssertionError("retry never reached a terminal state")
    exports = invoke(api, "pptx.exports.list", {"project_id": pid})
    assert exports.status_code == 200, exports.text
    assert exports.json().get("exports") or exports.json().get("artifacts")


def test_real_speed_variant_retains_metadata_registry_and_deletes_cleanly(api):
    from database import ArtifactRecord, Project, SessionLocal
    from project_storage import videos_dir
    from scripts.media_tools import resolve_media_tool

    pid = invoke(api, "project.create", {"name": "Speed acceptance"}).json()["project"]["project_id"]
    with SessionLocal() as db:
        root = Path(db.get(Project, pid).run_dir)
    directory = videos_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / "source.mp4"
    ffmpeg, ffprobe = (resolve_media_tool(tool) for tool in ("ffmpeg", "ffprobe"))
    assert ffmpeg and ffprobe
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=white:s=320x180:r=30:d=2",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:v", "libx264", "-c:a", "aac", "-shortest", str(source)],
        check=True, capture_output=True, timeout=30)
    (directory / "source.mp4.render.json").write_text(json.dumps({
        "reveal_pipeline_version": "exact_rle_mask_with_manual_corrections_v6"}), encoding="utf-8")
    changed = invoke(api, "video.speed", {"project_id": pid, "filename": "source.mp4", "payload": {"speed": 2}})
    assert changed.status_code == 200, changed.text
    name = changed.json()["video"]["filename"]
    variant = directory / name
    assert name != source.name and variant.exists()
    probe = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(variant)],
        check=True, capture_output=True, text=True, timeout=10)
    assert .8 <= float(json.loads(probe.stdout)["format"]["duration"]) <= 1.3
    assert Path(str(variant) + ".render.json").exists()
    with SessionLocal() as db:
        assert db.query(ArtifactRecord).filter_by(project_id=pid, artifact_type="video").count() == 1
    deleted = invoke(api, "video.delete", {"project_id": pid, "filename": name})
    assert deleted.status_code == 200, deleted.text
    assert not variant.exists() and not Path(str(variant) + ".render.json").exists()
    assert source.exists()
    with SessionLocal() as db:
        assert db.query(ArtifactRecord).filter_by(project_id=pid, artifact_type="video").count() == 0
