#!/usr/bin/env python3
"""Ensure production rendering cannot fall back to historical reveal algorithms."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    server = (ROOT / "server.py").read_text(encoding="utf-8")
    builder = (ROOT / "scripts" / "build_reveal_scene.py").read_text(encoding="utf-8")
    preflight = (ROOT / "scripts" / "run_reveal_preflight.ps1").read_text(encoding="utf-8")

    assert 'REVEAL_PIPELINE_VERSION = "manual_mask_outer_white_v3"' in server
    assert "build_current_reveal_assets(project)" in server
    assert '"--image-format=png"' in server
    assert '"--pixel-format=yuv420p"' in server
    assert '"--color-space=bt709"' in server
    assert "validate_render_color.py" in server
    assert "auto_fit_reveal_boxes.py" not in server
    assert "decompose_slide_layers.py" not in server
    assert "split_master_layers.py" not in server
    assert "auto_fit_reveal_boxes.py" not in preflight

    forbidden_builder_symbols = (
        "erase_later_groups_from_crop",
        "connected_components(",
        "nearest_owner",
        "reveal_padding_px",
        "foreground_mask_crop",
    )
    for symbol in forbidden_builder_symbols:
        assert symbol not in builder, symbol

    assert 'PIPELINE_VERSION = "manual_mask_outer_white_v3"' in builder
    assert '"source_image_used_for_background": False' in builder
    print("reveal pipeline isolation checks passed")


if __name__ == "__main__":
    main()
