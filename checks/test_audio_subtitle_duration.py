import os
import io
import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.media_tools import probe_media_duration_sec, resolve_media_tool
from scripts.minimax_tts import build_segments_from_provider_timestamps, extract_minimax_bundle
from server import rewrite_audio_timeline_by_beats


with tempfile.TemporaryDirectory() as temp_dir:
    temp = Path(temp_dir)
    media = temp / "voice.mp3"
    ffprobe = temp / ("ffprobe.exe" if os.name == "nt" else "ffprobe")
    media.write_bytes(b"audio")
    ffprobe.write_bytes(b"tool")

    with patch.dict(os.environ, {"FFPROBE_BINARY": str(ffprobe)}):
        assert resolve_media_tool("ffprobe", repo_root=ROOT) == str(ffprobe)
        with patch(
            "scripts.media_tools.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, stdout="12.345\n", stderr=""),
        ):
            assert probe_media_duration_sec(media, repo_root=ROOT) == 12.345

assert probe_media_duration_sec(ROOT / "missing.mp3", repo_root=ROOT) is None

with tempfile.TemporaryDirectory() as temp_dir:
    temp = Path(temp_dir)
    output = temp / "voice.mp3"
    bundle_buffer = io.BytesIO()
    titles = [{"text": "第一句字幕。", "time_begin": 100, "time_end": 2100}]
    with tarfile.open(fileobj=bundle_buffer, mode="w") as archive:
        for name, payload in (
            ("result/content.mp3", b"real-mp3-bytes"),
            ("result/content.titles", json.dumps(titles, ensure_ascii=False).encode("utf-8")),
            ("result/content.extra", b'{"audio_length":2200}'),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    extracted = extract_minimax_bundle(bundle_buffer.getvalue(), output)
    assert output.read_bytes() == b"real-mp3-bytes"
    assert extracted["subtitle_timestamps"] == titles
    assert extracted["extra_info"]["audio_length"] == 2200

segments = build_segments_from_provider_timestamps(titles, "slide_001", 26, 2.2)
assert len(segments) == 1
assert segments[0]["start"] == 0.1
assert segments[0]["end"] == 2.1
assert segments[0]["timing_source"] == "provider_sentence_timestamps"

jittery_titles = [
    {"text": "第一句", "time_begin": 0, "time_end": 1000},
    {"text": ".", "time_begin": 1000, "time_end": 1190},
    {"text": "第二句", "time_begin": 1200, "time_end": 2200},
]
jitter_free = build_segments_from_provider_timestamps(jittery_titles, "slide_002", 26, 2.2)
assert len(jitter_free) == 2
assert jitter_free[0]["text"] == "第一句."
assert jitter_free[0]["end"] == jitter_free[1]["start"] == 1.2
assert jitter_free[1]["text"] == "第二句"

video_tsx = (ROOT / "scripts" / "remotion" / "src" / "Video.tsx").read_text(encoding="utf-8")
assert "SUBTITLE_GAP_HOLD_SEC = 0.35" in video_tsx
assert "subtitleAtTime(segments, audioSeconds)" in video_tsx
assert "hasReadableSubtitleText" in video_tsx

with tempfile.TemporaryDirectory() as temp_dir:
    timeline_path = Path(temp_dir) / "audio_timeline.json"
    timeline_path.write_text(
        json.dumps(
            {
                "duration_sec": 4.0,
                "audio_content_duration_sec": 4.0,
                "timing_source": "provider_sentence_timestamps",
                "segments": [
                    {"id": "s1", "text": "第一段内容", "start": 0.0, "end": 1.8, "provider_sentence_index": 0},
                    {"id": "s2", "text": "第二段内容", "start": 2.0, "end": 3.8, "provider_sentence_index": 1},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    beats = [
        {"id": "beat_1", "spoken_text": "这是第一段内容。"},
        {"id": "beat_2", "spoken_text": "这是第二段内容。"},
    ]
    with patch("server.probe_media_duration_sec", return_value=4.0):
        rewrite_audio_timeline_by_beats(str(timeline_path), "slide_001", beats)
    rewritten = json.loads(timeline_path.read_text(encoding="utf-8"))
    assert [segment["beat_id"] for segment in rewritten["segments"]] == ["beat_1", "beat_2"]
    assert [segment["start"] for segment in rewritten["segments"]] == [0.0, 2.0]

app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
assert "const hasExistingAudio" in app_js
assert "const canLoadAudio = stepAllowsAudio || hasExistingAudio" in app_js

print("audio/subtitle duration checks passed")
