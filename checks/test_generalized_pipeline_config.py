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
    read_pipeline_profile,
)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def make_master(path: Path) -> None:
    image = Image.new("RGB", (320, 180), "#fffdf7")
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 50, 150, 120), fill="#f3cf76")
    image.save(path)


def test_step2_prompt_contracts_are_minimal() -> None:
    profile = read_pipeline_profile()
    script_system = (ROOT / "templates" / "prompts" / "step2_script_system.md").read_text(encoding="utf-8")
    script_example = json.loads((ROOT / "templates" / "prompts" / "step2_script_output_example.json").read_text(encoding="utf-8"))
    visual_system = (ROOT / "templates" / "prompts" / "step2_visual_system.md").read_text(encoding="utf-8")
    visual_example = json.loads((ROOT / "templates" / "prompts" / "step2_visual_output_example.json").read_text(encoding="utf-8"))

    assert "slide_title" in script_example["slides"][0]
    assert "narration" in script_example["slides"][0]
    first_script_slide = script_example["slides"][0]
    assert set(first_script_slide) == {"slide_id", "slide_title", "slide_subtitle", "narration"}
    assert "输出字段只能是" in script_system
    assert "完整演讲稿" in script_system
    assert "visual_groups" not in script_example["slides"][0]
    assert "按语义把整页 `narration` 切成" in visual_system
    assert "role" in visual_system and "visual_type" in visual_system
    assert "完整还原本页原始演讲稿" in visual_system
    assert "最小的 Mask/Reveal 原子" in visual_system
    assert "多个独立卡片" in visual_system
    assert "每个需要独立 Mask/Reveal 的正文元素都必须绑定一段非空旁白" in visual_system
    first_visual_element = visual_example["slides"][0]["visual_elements"][0]
    assert set(first_visual_element) == {"element_id", "role", "visual_type", "visual_description", "narration"}
    assert "不输出 `body_points`" in visual_system
    assert "source_segment_id" not in json.dumps(visual_example, ensure_ascii=False)
    assert "speak_policy" not in script_system + visual_system
    assert "scratch_reveal" in allowed_reveal_actions(profile)
    diagram_reveal = default_reveal_for_role("diagram", profile)
    assert diagram_reveal["type"] in allowed_reveal_actions(profile)
    assert diagram_reveal["duration"] > 0


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
    test_step2_prompt_contracts_are_minimal()
    test_reveal_builder_preserves_configured_effect_and_duration()
    test_timeline_binding_keeps_reveal_duration()
    print("generalized pipeline config checks passed")
