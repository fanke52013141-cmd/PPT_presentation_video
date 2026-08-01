import json
import subprocess
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server
from video_artifact_service import VideoArtifactService


class FakeDb:
    def __init__(self, project):
        self.project = project

    def query(self, *_args):
        return self

    def filter(self, *_args):
        return self

    def first(self):
        return self.project

    def commit(self):
        return None


with tempfile.TemporaryDirectory() as temp_dir:
    runs_dir = Path(temp_dir) / "runs"
    run_dir = runs_dir / "project_test"
    videos_dir = run_dir / "videos"
    videos_dir.mkdir(parents=True)
    source = videos_dir / "render_test.mp4"
    source.write_bytes(b"source-video")
    (videos_dir / "render_test.mp4.render.json").write_text(
        json.dumps(
            {
                "reveal_pipeline_version": server.REVEAL_PIPELINE_VERSION,
                "video_background": "#FEFDF9",
                "subtitle_style": server.DEFAULT_SUBTITLE_STYLE,
            }
        ),
        encoding="utf-8",
    )
    project = SimpleNamespace(id="project_test", run_dir=str(run_dir))
    captured = {}

    def fake_run(command, **_kwargs):
        captured["command"] = command
        Path(command[-1]).write_bytes(b"speed-video")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    dependencies = replace(
        server.video_render_service.artifacts.dependencies,
        resolve_media_tool=lambda _name: "ffmpeg",
        runs_root=runs_dir,
    )
    service = VideoArtifactService(dependencies)
    with patch(
        "video_artifact_service.subprocess.run",
        side_effect=fake_run,
    ), patch("video_artifact_service.record_artifact"):
        result = service.create_speed_adjusted_video(
            FakeDb(project),
            "project_test",
            "render_test.mp4",
            {"speed": 1.25},
        )

    command = captured["command"]
    assert "setpts=PTS/1.25" in command
    assert "atempo=1.25" in command
    adjusted = videos_dir / "render_test_speed_1_25x.mp4"
    assert adjusted.read_bytes() == b"speed-video"
    metadata = json.loads(Path(str(adjusted) + ".render.json").read_text(encoding="utf-8"))
    assert metadata["playback_rate"] == 1.25
    assert metadata["source_filename"] == "render_test.mp4"
    assert result["video"]["is_speed_variant"] is True
    assert result["video"]["playback_rate"] == 1.25

output_render_js = (ROOT / "static" / "output_render.js").read_text(encoding="utf-8")
assert "应用语速并生成 MP4" in output_render_js
assert "generateStep8SpeedVideo" in output_render_js

print("video speed checks passed")
