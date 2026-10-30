"""Digital-human edits keep existing videos and only flag real render changes."""

from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path

from fastapi import UploadFile
from starlette.datastructures import Headers

import digital_human_routes as routes
from project_impact_service import list_impacts


class FakeProject:
    def __init__(self, run_dir: Path) -> None:
        self.id = "digital-impact"
        self.run_dir = str(run_dir)
        self.current_step = 8
        self._statuses = {str(step): "completed" for step in range(1, 9)}

    def get_step_status(self) -> dict[str, str]:
        return dict(self._statuses)

    def set_step_status(self, statuses: dict[str, str]) -> None:
        self._statuses = dict(statuses)


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


def _video_upload(content: bytes) -> UploadFile:
    return UploadFile(
        filename="presenter.mp4",
        file=io.BytesIO(content),
        headers=Headers({"content-type": "video/mp4"}),
    )


def test_config_change_marks_only_output_and_identical_save_is_noop(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = FakeProject(tmp_path)
    db = FakeSession()
    (tmp_path / "videos").mkdir()
    old_video = tmp_path / "videos" / "existing.mp4"
    old_video.write_bytes(b"previous-output")
    (tmp_path / "remotion_props.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(routes, "_project_or_404", lambda _db, _id: project)

    result = routes.put_dh_config(
        project.id,
        {"enabled": True, "mode": "upload", "circle": {"cx": 0.7}},
        db,
    )

    assert result["success"] is True
    assert project.get_step_status()["8"] == "pending_reconfirmation"
    assert db.commits == 1
    assert old_video.read_bytes() == b"previous-output"
    assert not (tmp_path / "remotion_props.json").exists()
    assert [item["id"] for item in list_impacts(tmp_path)] == [
        "digital_human_changed:project"
    ]

    saves: list[dict[str, object]] = []
    original_save = routes._save_config
    monkeypatch.setattr(routes, "_save_config", lambda _project, cfg: saves.append(cfg))
    routes.put_dh_config(
        project.id,
        {"enabled": True, "mode": "upload", "circle": {"cx": 0.7}},
        db,
    )

    assert saves == []
    assert db.commits == 1
    monkeypatch.setattr(routes, "_save_config", original_save)


def test_avatar_or_sync_setting_while_disabled_does_not_stale_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = FakeProject(tmp_path)
    db = FakeSession()
    monkeypatch.setattr(routes, "_project_or_404", lambda _db, _id: project)

    routes.put_dh_config(
        project.id,
        {"enabled": False, "avatar_id": "av_new", "sync_mode": "fast"},
        db,
    )

    assert project.get_step_status()["8"] == "completed"
    assert db.commits == 0
    assert list_impacts(tmp_path) == []


def test_identical_uploaded_presenter_is_noop_and_replacement_keeps_old_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(routes, "probe_video_metadata", lambda *_args, **_kwargs: {"duration_sec": 1})
    project = FakeProject(tmp_path)
    db = FakeSession()
    monkeypatch.setattr(routes, "_project_or_404", lambda _db, _id: project)
    digi_dir = tmp_path / "planning" / "digital_human"
    digi_dir.mkdir(parents=True)
    source = digi_dir / "digi_upload.mp4"
    source.write_bytes(b"old-presenter")
    (tmp_path / "planning" / "digital_human.json").write_text(
        json.dumps({"enabled": True, "mode": "upload"}), encoding="utf-8"
    )
    (tmp_path / "videos").mkdir()
    old_output = tmp_path / "videos" / "existing.mp4"
    old_output.write_bytes(b"previous-output")

    asyncio.run(routes.upload_dh_video(project.id, _video_upload(b"old-presenter"), db))
    assert db.commits == 0
    assert project.get_step_status()["8"] == "completed"

    asyncio.run(routes.upload_dh_video(project.id, _video_upload(b"new-presenter"), db))
    assert source.read_bytes() == b"new-presenter"
    assert db.commits == 1
    assert project.get_step_status()["8"] == "pending_reconfirmation"
    assert old_output.read_bytes() == b"previous-output"
