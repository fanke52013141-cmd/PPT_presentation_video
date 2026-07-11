import json
import os
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tts_artifacts import artifact_paths, artifact_status, remove_outputs, timeline_duration_sec


def _write(path: Path, value: str = "data") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def test_paths_and_incomplete_status() -> None:
    with tempfile.TemporaryDirectory() as value:
        run_dir = Path(value)
        paths = artifact_paths(run_dir, "slide_001")
        assert paths["audio"] == (run_dir / "slides" / "slide_001" / "voice.mp3").resolve()
        _write(paths["audio"], "audio")
        status = artifact_status(run_dir, "slide_001")
        assert status["audio_exists"] is True
        assert status["complete"] is False
        assert status["audio_bytes"] == 5
        assert status["missing_artifacts"] == ["metadata", "srt", "timeline"]


def test_complete_and_stale_status() -> None:
    with tempfile.TemporaryDirectory() as value:
        run_dir = Path(value)
        paths = artifact_paths(run_dir, "slide_001")
        _write(paths["audio"], "audio")
        _write(paths["metadata"], "{}")
        _write(paths["srt"], "subtitle")
        _write(paths["timeline"], json.dumps({"audio_content_duration_sec": 2.5}))
        assert artifact_status(run_dir, "slide_001")["complete"] is True

        _write(paths["text"], "new narration")
        newest = max(path.stat().st_mtime for key, path in paths.items() if key not in {"slide_dir", "text"}) + 2
        os.utime(paths["text"], (newest, newest))
        status = artifact_status(run_dir, "slide_001")
        assert status["stale"] is True
        assert status["complete"] is False


def test_duration_prefers_content_and_preserves_zero() -> None:
    with tempfile.TemporaryDirectory() as value:
        timeline = Path(value) / "timeline.json"
        _write(timeline, json.dumps({"audio_content_duration_sec": 0, "duration_sec": 9}))
        assert timeline_duration_sec(timeline) == 0.0
        _write(timeline, json.dumps({"duration_sec": 3.25}))
        assert timeline_duration_sec(timeline) == 3.25
        _write(timeline, "not-json")
        assert timeline_duration_sec(timeline) is None


def test_remove_outputs_keeps_text_source() -> None:
    with tempfile.TemporaryDirectory() as value:
        paths = artifact_paths(value, "slide_001")
        for key, path in paths.items():
            if key != "slide_dir":
                _write(path)
        removed = remove_outputs(paths)
        assert len(removed) == 4
        assert paths["text"].exists()
        assert all(not paths[key].exists() for key in ("audio", "metadata", "srt", "timeline"))


if __name__ == "__main__":
    test_paths_and_incomplete_status()
    test_complete_and_stale_status()
    test_duration_prefers_content_and_preserves_zero()
    test_remove_outputs_keeps_text_source()
    print("TTS artifact checks passed")
