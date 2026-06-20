import json
import tempfile
from pathlib import Path

import sys

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.bind_reveal_timeline import bind_slide
from scripts.build_reveal_scene import compose_slide
from scripts.pipeline_profiles import (
    allowed_reveal_actions,
    default_reveal_for_role,
    image_prompt_profile_text,
    read_pipeline_profile,
    speak_policy_for_role,
    storyboard_profile_prompt,
)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def make_master(path: Path) -> None:
    image = Image.new("RGB", (320, 180), "#fffdf7")
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 50, 150, 120), fill="#f3cf76")
    image.save(path)


def test_profile_exposes_generalized_structure() -> None:
    profile = read_pipeline_profile()
    prompt = storyboard_profile_prompt("短文章", profile)
    assert "不要固定套用" in prompt
    assert "subtitle" in prompt
    assert speak_policy_for_role("subtitle", profile) == "display_only"
    assert speak_policy_for_role("quote", profile) == "speak"
    assert "scratch_reveal" in allowed_reveal_actions(profile)
    assert default_reveal_for_role("diagram", profile)["type"] == "scratch_reveal"
    assert "完整 PPT/讲解页静态主图" in image_prompt_profile_text(profile)


def test_reveal_builder_preserves_configured_effect_and_duration() -> None:
    with tempfile.TemporaryDirectory() as temp_dir_value:
        root = Path(temp_dir_value)
        master_path = root / "master.png"
        make_master(master_path)
        slide_dir = root / "slides" / "slide_001"
        slide_dir.mkdir(parents=True)
        compose_slide(
            {
                "slide_id": "slide_001",
                "slide_dir": str(slide_dir),
                "master": str(master_path),
                "canvas": {"width": 320, "height": 180, "background": "#fffdf7", "subtitle_safe_y": 180},
                "groups": [
                    {
                        "id": "g1",
                        "role": "quote",
                        "box": {"x": 20, "y": 20, "w": 140, "h": 100},
                        "manual_mask": {
                            "strokes": [
                                {
                                    "mode": "paint",
                                    "size": 48,
                                    "points": [{"x": 70, "y": 80}, {"x": 125, "y": 90}],
                                }
                            ]
                        },
                        "reveal": {"type": "wipe_right_to_left", "duration": 0.82},
                    }
                ],
            },
            root,
            root,
            {"width": 320, "height": 180, "background": "#fffdf7", "subtitle_safe_y": 180},
        )
        timeline = read_json(slide_dir / "animation_timeline.json")
        assert timeline["events"][0]["action"] == "wipe_right_to_left"
        assert timeline["events"][0]["duration"] == 0.82


def test_timeline_binding_keeps_reveal_duration() -> None:
    with tempfile.TemporaryDirectory() as temp_dir_value:
        slide_dir = Path(temp_dir_value)
        (slide_dir / "animation_timeline.json").write_text(
            json.dumps(
                {
                    "slide_id": "slide_001",
                    "duration_sec": 3,
                    "events": [
                        {
                            "id": "e1",
                            "target": "reveal_crop_g1",
                            "action": "scratch_reveal",
                            "at": 0.2,
                            "duration": 0.9,
                            "narration_beat_id": "beat_01",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (slide_dir / "audio_timeline.json").write_text(
            json.dumps(
                {
                    "slide_id": "slide_001",
                    "duration_sec": 2,
                    "segments": [{"id": "seg_01", "start": 0.4, "end": 1.6, "text": "hello"}],
                }
            ),
            encoding="utf-8",
        )
        (slide_dir / "narration_beats.json").write_text(
            json.dumps({"slide_id": "slide_001", "beats": [{"id": "beat_01", "linked_segment_id": "seg_01"}]}),
            encoding="utf-8",
        )
        assert bind_slide(slide_dir, lead_sec=0, preserve_existing_at=False) is True
        timeline = read_json(slide_dir / "animation_timeline.json")
        assert timeline["events"][0]["at"] == 0.4
        assert timeline["events"][0]["duration"] == 0.9


if __name__ == "__main__":
    test_profile_exposes_generalized_structure()
    test_reveal_builder_preserves_configured_effect_and_duration()
    test_timeline_binding_keeps_reveal_duration()
    print("generalized pipeline config checks passed")
