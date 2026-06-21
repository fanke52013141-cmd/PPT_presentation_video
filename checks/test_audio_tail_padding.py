import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.build_remotion_props import (
    DEFAULT_AUDIO_TAIL_PADDING_SEC,
    align_audio_timeline_to_voice,
    slide_duration,
)


audio = {
    "duration_sec": 3.0,
    "segments": [{"id": "s1", "start": 0.0, "end": 3.0, "text": "测试"}],
}
animation = {
    "duration_sec": 2.8,
    "events": [{"id": "e1", "target": "layer", "action": "fade_in", "at": 1.0, "duration": 0.5}],
}
assert slide_duration(audio, animation, Path("slide_001")) == round(3.0 + DEFAULT_AUDIO_TAIL_PADDING_SEC, 3)

long_animation = {
    "duration_sec": 4.5,
    "events": [],
}
assert slide_duration(audio, long_animation, Path("slide_001")) == 4.5

short_timeline = {
    "duration_sec": 3.0,
    "segments": [
        {"id": "s1", "start": 0.0, "end": 1.5, "text": "前半句"},
        {"id": "s2", "start": 1.5, "end": 3.0, "text": "后半句"},
    ],
}
with patch("scripts.build_remotion_props.probe_audio_duration_sec", return_value=4.0):
    aligned = align_audio_timeline_to_voice(short_timeline, Path("voice.mp3"))

assert aligned["duration_sec"] == 4.0
assert aligned["audio_content_duration_sec"] == 4.0
assert aligned["duration_source"] == "local_audio_ffprobe"
assert aligned["previous_timeline_content_duration_sec"] == 3.0
assert aligned["segments"][-1]["end"] == 4.0
assert slide_duration(aligned, animation, Path("slide_001")) == round(4.0 + DEFAULT_AUDIO_TAIL_PADDING_SEC, 3)

print("audio tail padding checks passed")
