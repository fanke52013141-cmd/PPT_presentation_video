import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.build_remotion_props import DEFAULT_AUDIO_TAIL_PADDING_SEC, slide_duration


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

print("audio tail padding checks passed")
