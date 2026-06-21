#!/usr/bin/env python3
"""Regression checks for configurable storyboard roles and Mask animations."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_reveal_scene import build_event
from scripts.pipeline_profiles import allowed_reveal_actions, read_pipeline_profile, role_catalog


def main() -> None:
    profile = read_pipeline_profile()
    roles = role_catalog(profile)
    assert roles["title"]["required"] is True
    assert roles["subtitle"]["required"] is False
    assert roles["summary"]["required"] is False
    assert {"quote", "data_point", "process_step", "callout"} <= set(roles)

    required_actions = {
        "wipe_left_to_right",
        "scratch_reveal",
        "brush_wipe_left_to_right",
        "sticker_pop",
        "stamp_in",
        "paper_drop",
    }
    assert required_actions <= allowed_reveal_actions(profile)

    event = build_event(
        "slide_001",
        {
            "id": "callout_group",
            "reveal": {
                "type": "sticker_pop",
                "duration": 0.7,
                "rotation": -4,
            },
        },
        "layer_callout",
        0.2,
    )
    assert event["action"] == "sticker_pop"
    assert event["duration"] == 0.7
    assert event["params"]["rotation"] == -4

    for schema_name in ("reveal_manifest.schema.json", "animation_timeline.schema.json"):
        schema = json.loads((ROOT / "schemas" / schema_name).read_text(encoding="utf-8-sig"))
        schema_text = json.dumps(schema, ensure_ascii=False)
        for action in required_actions:
            assert action in schema_text, f"{action} missing from {schema_name}"

    print("generalized storyboard and animation checks passed")


if __name__ == "__main__":
    main()
