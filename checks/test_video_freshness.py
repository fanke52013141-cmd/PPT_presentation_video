import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server  # noqa: E402


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def test_video_state_tracks_complete_render_inputs() -> None:
    with tempfile.TemporaryDirectory() as value:
        run_dir = Path(value)
        project = SimpleNamespace(id="freshness", run_dir=str(run_dir))
        _write(
            run_dir / "planning" / "visual_contract.json",
            json.dumps({"slides": [{"slide_id": "slide_001"}]}),
        )
        for relative in (
            "planning/narration_beats.json",
            "reveal_manifest.json",
            "remotion_props.json",
            "slides/slide_001/scene.json",
            "slides/slide_001/animation_timeline.json",
            "slides/slide_001/tts_metadata.json",
            "slides/slide_001/audio_timeline.json",
        ):
            _write(run_dir / relative, "{}")
        for relative in (
            "slides/slide_001/visual_draft.png",
            "slides/slide_001/tts_text.txt",
            "slides/slide_001/voice.mp3",
            "slides/slide_001/subtitles.srt",
        ):
            _write(run_dir / relative, "source")

        video = run_dir / "videos" / "render.mp4"
        _write(video, "video")
        fingerprint = server.current_render_input_fingerprint(project)
        metadata = {
            "reveal_pipeline_version": server.REVEAL_PIPELINE_VERSION,
            "video_background": server.DEFAULT_VIDEO_BACKGROUND,
            "subtitle_style": server.DEFAULT_SUBTITLE_STYLE,
            "input_fingerprint": fingerprint,
        }
        _write(Path(str(video) + ".render.json"), json.dumps(metadata))
        assert server.video_item(project, str(video))["artifact_state"] == "current"

        _write(run_dir / "slides" / "slide_001" / "tts_text.txt", "changed narration")
        stale = server.video_item(project, str(video))
        assert stale["artifact_state"] == "stale"
        assert stale["is_stale"] is True

        legacy_video = run_dir / "videos" / "legacy.mp4"
        _write(legacy_video, "legacy")
        assert server.video_item(project, str(legacy_video))["artifact_state"] == "legacy"

        invalid_video = run_dir / "videos" / "invalid.mp4"
        _write(invalid_video, "invalid")
        _write(Path(str(invalid_video) + ".render.json"), "not-json")
        assert server.video_item(project, str(invalid_video))["artifact_state"] == "invalid"
