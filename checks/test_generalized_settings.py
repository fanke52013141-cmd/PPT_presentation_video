#!/usr/bin/env python3
"""Regression checks for guided storyboard/style settings and unified animation UI."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_reveal_scene import build_event  # noqa: E402
from scripts.pipeline_profiles import normalize_reveal_action, role_catalog  # noqa: E402
from server import (  # noqa: E402
    apply_storyboard_profile_patch,
    merge_image_style_update,
    parse_storyboard_profile_text,
    read_style_tokens_data,
    storyboard_profile_editor_data,
)

def main() -> None:
    profile_text = (ROOT / "config" / "pipeline_profiles.yaml").read_text(encoding="utf-8-sig")
    profile = parse_storyboard_profile_text(profile_text)
    editor = storyboard_profile_editor_data(profile)
    assert editor["roles"]["subtitle"]["speak_policy"] == "display_only"
    assert "visual_groups[].content_unit_id" in editor["protected_fields"]

    patched = apply_storyboard_profile_patch(
        profile,
        {
            "slide_count": {"short_article": "5-7"},
            "roles": {
                "subtitle": {
                    "enabled": False,
                    "required": False,
                    "speak_policy": "speak",
                }
            },
        },
    )
    assert patched["storyboard"]["slide_count"]["short_article"] == "5-7"
    assert "subtitle" not in role_catalog(patched)
    assert storyboard_profile_editor_data(patched)["roles"]["subtitle"]["enabled"] is False
    assert normalize_reveal_action("scratch_reveal", profile, for_renderer=True) == "scratch_reveal"
    assert normalize_reveal_action("brush_wipe_left_to_right", profile, for_renderer=True) == "brush_wipe_left_to_right"
    scratch_event = build_event(
        "slide_001",
        {"id": "group_01", "reveal": {"type": "scratch_reveal", "duration": 0.9}},
        "group_01_layer",
        0.5,
    )
    assert scratch_event["action"] == "scratch_reveal"

    style = read_style_tokens_data()
    merged = merge_image_style_update(
        style,
        {
            "brand": {"style_keywords": ["中国水墨", "留白"]},
            "visual_assets": {
                "image_style": "chinese_ink",
                "layout_rules": ["每个语块独立留白"],
                "avoid": ["复杂背景"],
            },
        },
    )
    assert merged["brand"]["name"] == style["brand"]["name"]
    assert merged["brand"]["style_keywords"] == ["中国水墨", "留白"]
    assert merged["visual_assets"]["reveal_friendly_layout"] == ["每个语块独立留白"]
    assert merged["canvas"]["background"] == "#FFFFFF"

    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert 'id="step5-btn-animation-settings"' in html
    assert 'id="modal-animation-settings"' in html
    assert 'id="subtitle-font-weight"' in html
    assert "mask-animation-card" not in app_js
    assert "previewGlobalAnimationSettings" in app_js

    print("generalized settings checks passed")


if __name__ == "__main__":
    main()
