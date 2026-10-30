import json
from pathlib import Path
import subprocess
import wave

import pytest

import digital_human_audio_service as service
from scripts.media_tools import probe_media_duration_sec, resolve_media_tool


def setup_audio(root):
    ids = ["slide_001", "slide_002"]
    planning = root / "planning"
    planning.mkdir()
    (planning / "visual_contract.json").write_text(json.dumps({"slides": [{"slide_id": sid} for sid in ids]}))
    files = []
    for sid in ids:
        path = root / "slides" / sid / "voice.mp3"
        path.parent.mkdir(parents=True)
        with wave.open(str(path), "wb") as audio:
            audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            audio.writeframes(b"\x00\x00" * 16000)
        files.append(path)
    return ids, files, root / "planning/digital_human/audio_full.mp3"


def export(root, ids, files, output, gap=0, runner=subprocess.run):
    return service.export_full_audio(root, ids, files, output, gap=gap,
        ffmpeg=resolve_media_tool("ffmpeg"), run_command=runner, probe=probe_media_duration_sec)


def test_zero_gap_complete_export_reuses_current_audio_and_rejects_missing_pages(tmp_path):
    ids, files, output = setup_audio(tmp_path)
    result = export(tmp_path, ids, files, output)
    assert result["slides"] == 2 and result["gap_sec"] == 0
    assert abs(result["duration_sec"] - 2) < .15
    assert service.full_audio_current(tmp_path)
    before = output.read_bytes(), output.stat().st_mtime_ns
    assert export(tmp_path, ids, files, output, runner=lambda *_a, **_k: pytest.fail("no-op export reran FFmpeg"))["reused"]
    assert (output.read_bytes(), output.stat().st_mtime_ns) == before
    files[1].unlink()
    assert not service.full_audio_current(tmp_path)
    with pytest.raises(ValueError, match="slide_002"):
        export(tmp_path, ids, files, output)
    assert output.read_bytes() == before[0]


def test_changed_input_during_export_cannot_replace_previous_audio(tmp_path):
    ids, files, output = setup_audio(tmp_path)
    export(tmp_path, ids, files, output)
    before = output.read_bytes()
    def runner(command, **kwargs):
        result = subprocess.run(command, **kwargs)
        if Path(command[-1]).name == "full.mp3":
            files[0].write_bytes(b"changed input")
        return result
    with pytest.raises(service.FullAudioConflict):
        export(tmp_path, ids, files, output, gap=.6, runner=runner)
    assert output.read_bytes() == before
    assert not list(output.parent.glob("audio-export-*"))


def test_metadata_failure_restores_previous_audio(tmp_path, monkeypatch):
    ids, files, output = setup_audio(tmp_path)
    export(tmp_path, ids, files, output)
    record = output.with_suffix(".source.json")
    before = output.read_bytes(), record.read_bytes()
    original = service.write_json_atomic
    calls = []
    def writer(path, payload):
        calls.append(path)
        if len(calls) == 1:
            raise OSError("controlled metadata failure")
        original(path, payload)
    monkeypatch.setattr(service, "write_json_atomic", writer)
    with pytest.raises(OSError):
        export(tmp_path, ids, files, output, gap=.6)
    assert (output.read_bytes(), record.read_bytes()) == before
    assert not list(output.parent.glob("*.rollback"))
