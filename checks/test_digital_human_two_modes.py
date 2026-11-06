"""Cross-entry source storage, no-op writes and stale-result protection."""
from __future__ import annotations

import asyncio
import io
from types import SimpleNamespace

from fastapi import HTTPException, UploadFile
import pytest
from starlette.datastructures import Headers

import digital_human_routes as routes
import digital_human_source_service as sources
from checks.test_digital_human_impact import FakeProject, FakeSession


def upload(content):
    return UploadFile(filename="motion.mp4", file=io.BytesIO(content),
                      headers=Headers({"content-type": "video/mp4"}))


def test_web_and_agent_motion_upload_share_noop_and_preserve_work(tmp_path, monkeypatch):
    from agent_api.domain_routes.digital_human_ext import agent_dh_upload_motion
    monkeypatch.setattr(sources, "probe_video_metadata", lambda path: {"duration_sec": 25} if path.read_bytes() else None)
    project, db = FakeProject(tmp_path), FakeSession()
    monkeypatch.setattr(routes, "_project_or_404", lambda session, project_id: project)
    routes.update_digital_human_config(project, {"enabled": True, "mode": "portrait", "avatar_id": "av_photo"})
    old_result = tmp_path / "planning/digital_human/digi_full.mp4"
    old_result.parent.mkdir(parents=True, exist_ok=True)
    old_result.write_bytes(b"previous-success")
    first = asyncio.run(routes.upload_dh_motion(project.id, file=upload(b"motion-a"), db=db))
    assert first["changed"] and db.commits == 1
    path = sources.motion_path(tmp_path, "custom")
    config = tmp_path / "planning/digital_human.json"
    times = path.stat().st_mtime_ns, config.stat().st_mtime_ns
    second = asyncio.run(agent_dh_upload_motion(project.id, file=upload(b"motion-a"), db=db))
    assert not second["changed"] and db.commits == 1
    assert times == (path.stat().st_mtime_ns, config.stat().st_mtime_ns)
    assert old_result.read_bytes() == b"previous-success"


def test_invalid_motion_replacement_keeps_previous_source(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "probe_video_metadata", lambda path: None)
    path = sources.motion_path(tmp_path, "custom")
    path.parent.mkdir(parents=True)
    path.write_bytes(b"previous-motion")
    with pytest.raises(ValueError, match="无法解码"):
        sources.save_motion_video(tmp_path, b"not-video")
    assert path.read_bytes() == b"previous-motion"


def test_changed_photo_rejects_old_completed_job_before_download(tmp_path, monkeypatch):
    project, db = FakeProject(tmp_path), FakeSession()
    monkeypatch.setattr(routes, "_project_or_404", lambda session, project_id: project)
    cfg = routes.update_digital_human_config(project, {"mode": "portrait", "avatar_id": "av_original"})
    old_source = sources.generation_source_fingerprint(tmp_path, cfg)
    cfg.update(avatar_id="av_replacement", slides={"full": {
        "job_id": "old-job", "status": "processing", "source_sha256": old_source,
    }})
    routes._save_config(project, cfg)
    def download(*args):
        pytest.fail("a completed old source must never be downloaded over the current result")
    monkeypatch.setattr(routes, "get_digital_human_client", lambda: SimpleNamespace(
        get_job=lambda job_id: {"status": "done", "slide_id": "full"}, download_result=download))
    assert routes.get_dh_job(project.id, "old-job", db)["job"]["stale"]


@pytest.mark.parametrize("payload", [{"motion_source": "../other"}, {"upload_start_sec": float("nan")},
                                    {"upload_start_sec": -1}, {"upload_short_video_policy": "stretch"}])
def test_invalid_source_configuration_has_no_side_effects(tmp_path, payload):
    with pytest.raises(HTTPException) as error:
        routes.update_digital_human_config(FakeProject(tmp_path), payload)
    assert error.value.status_code == 400
    assert not (tmp_path / "planning/digital_human.json").exists()
