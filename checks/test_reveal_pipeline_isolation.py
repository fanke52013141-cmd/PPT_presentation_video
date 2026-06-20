#!/usr/bin/env python3
"""Ensure production rendering cannot fall back to historical reveal algorithms."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    server = (ROOT / "server.py").read_text(encoding="utf-8")
    builder = (ROOT / "scripts" / "build_reveal_scene.py").read_text(encoding="utf-8")
    run_validator = (ROOT / "scripts" / "validate_run_assets.py").read_text(encoding="utf-8")
    preflight = (ROOT / "scripts" / "run_reveal_preflight.ps1").read_text(encoding="utf-8")

    assert 'REVEAL_PIPELINE_VERSION = "manual_mask_boundary_white_v4"' in server
    assert "build_current_reveal_assets(project)" in server
    assert '"--image-format=png"' in server
    assert '"--pixel-format=yuv420p"' in server
    assert '"--color-space=bt709"' in server
    assert "validate_render_color.py" in server
    assert "auto_fit_reveal_boxes.py" not in server
    assert "decompose_slide_layers.py" not in server
    assert "split_master_layers.py" not in server
    assert "auto_fit_reveal_boxes.py" not in preflight
    assert 'MASKED_COMPOSITION_METHOD = "solid_background_mask_boundary_white_cutout"' in builder

    removed_paths = (
        "scripts/auto_fit_reveal_boxes.py",
        "scripts/split_master_layers.py",
        "scripts/decompose_slide_layers.py",
        "scripts/compose_manifest_layers.py",
        "scripts/prepare_full_slide_scenes.py",
        "scripts/validate_layer_recomposition.py",
        "scripts/render_remotion.ps1",
        "scripts/ffmpeg_finalize.ps1",
        "schemas/master_split_manifest.schema.json",
        "schemas/layer_manifest.schema.json",
        "templates/manifests/master_split_manifest.template.json",
        "references/master_split_workflow.md",
    )
    for relative_path in removed_paths:
        assert not (ROOT / relative_path).exists(), relative_path

    operational_docs = (
        ROOT / "README.md",
        ROOT / "AGENTS.md",
        ROOT / "checks" / "preflight_checklist.md",
        ROOT / "checks" / "validate_scene.md",
        ROOT / "templates" / "prompts" / "scene_reconstruction.prompt.md",
    )
    for path in operational_docs:
        text = path.read_text(encoding="utf-8")
        assert "manual_mask_exact_v2" not in text, path
        assert "solid_background_manual_mask_exact" not in text, path
        assert "manual_mask_outer_white_v3" not in text, path
        assert "solid_background_outer_white_manual_mask" not in text, path
        assert "compose_manifest_layers.py" not in text, path

    forbidden_builder_symbols = (
        "erase_later_groups_from_crop",
        "connected_components(",
        "nearest_owner",
        "reveal_padding_px",
        "foreground_mask_crop",
        "fill_enclosed_mask_holes",
        "foreground_diagnostics",
        "selection_ratio",
    )
    for symbol in forbidden_builder_symbols:
        assert symbol not in builder, symbol

    assert 'PIPELINE_VERSION = "manual_mask_boundary_white_v4"' in builder
    assert '"cutout_method": "mask_boundary_connected_white_soft_alpha"' in builder
    assert '"source_image_used_for_background": False' in builder
    assert 'slide_dir / "assets" / "full_slide.png"' not in run_validator
    print("reveal pipeline isolation checks passed")


if __name__ == "__main__":
    main()
