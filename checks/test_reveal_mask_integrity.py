import json
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.build_reveal_scene import (
    MASKED_COMPOSITION_METHOD,
    PIPELINE_VERSION,
    compose_slide,
    manual_mask_alpha,
)
from scripts.validate_reveal_scene import validate_scene as validate_reveal_output


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def make_master(path: Path) -> Image.Image:
    image = Image.new("RGB", (320, 180), "#ffffff")
    draw = ImageDraw.Draw(image)
    draw.rectangle((35, 40, 135, 135), fill="#ffffff", outline="#111111", width=5)
    draw.ellipse((72, 70, 98, 96), fill="#f3cf76", outline="#111111", width=3)
    draw.rectangle((185, 50, 290, 130), fill="#a7c8ef", outline="#111111", width=5)
    image.save(path)
    return image


def painted_group(group_id: str, points: list[tuple[int, int]], width: int) -> dict:
    return {
        "id": group_id,
        "role": "content_body",
        "manual_mask": {
            "strokes": [{
                "mode": "paint",
                "size": width,
                "points": [{"x": x, "y": y} for x, y in points],
            }]
        },
        "reveal": {"type": "crop_fade_up"},
    }


with tempfile.TemporaryDirectory() as temp_dir_value:
    root = Path(temp_dir_value)
    master_path = root / "master.png"
    make_master(master_path)
    canvas = {
        "width": 320,
        "height": 180,
        "background": "#fefdf9",
        "subtitle_safe_y": 180,
    }

    no_mask_dir = root / "slides" / "slide_001"
    no_mask_dir.mkdir(parents=True)
    compose_slide(
        {
            "slide_id": "slide_001",
            "slide_dir": str(no_mask_dir),
            "master": str(master_path),
            "canvas": canvas,
            "groups": [{"id": "unpainted", "role": "content_body"}],
        },
        root,
        root,
        canvas,
    )
    no_mask_scene = read_json(no_mask_dir / "scene.json")
    no_mask_report = read_json(no_mask_dir / "reveal_report.json")
    assert [layer["role"] for layer in no_mask_scene["layers"]] == ["full_slide"]
    assert no_mask_report["fallback_full_slide"] is True
    assert set(path.name for path in (no_mask_dir / "assets").iterdir()) == {"full_slide.png"}
    validate_reveal_output(no_mask_dir, root, 320, 180, require_no_blocking=False)

    painted_dir = root / "slides" / "slide_002"
    (painted_dir / "assets").mkdir(parents=True)
    (painted_dir / "assets" / "manual_mask_composite.png").write_bytes(b"legacy")
    (painted_dir / "assets" / "manual_mask_uncovered.png").write_bytes(b"legacy")
    groups = [
        painted_group("left", [(40, 88), (130, 88)], 100),
        painted_group("right", [(185, 90), (290, 90)], 100),
    ]
    compose_slide(
        {
            "slide_id": "slide_002",
            "slide_dir": str(painted_dir),
            "master": str(master_path),
            "canvas": canvas,
            "groups": groups,
        },
        root,
        root,
        canvas,
    )

    scene = read_json(painted_dir / "scene.json")
    report = read_json(painted_dir / "reveal_report.json")
    assert [layer["role"] for layer in scene["layers"]] == [
        "background",
        "reveal_crop",
        "reveal_crop",
    ]
    assert scene["composition"]["method"] == MASKED_COMPOSITION_METHOD
    assert scene["composition"]["pipeline_version"] == PIPELINE_VERSION
    assert scene["composition"]["cutout_method"] == "mask_boundary_connected_white_soft_alpha"
    assert scene["composition"]["source_image_used_for_background"] is False
    assert report["cutout"]["enclosed_white_preserved"] is True
    assert report["cutout"]["white_decontamination"] is True
    assert not (painted_dir / "assets" / "manual_mask_composite.png").exists()
    assert not (painted_dir / "assets" / "manual_mask_uncovered.png").exists()
    assert not (painted_dir / "assets" / "full_slide.png").exists()
    assert {
        path.relative_to(painted_dir / "assets").as_posix()
        for path in (painted_dir / "assets").rglob("*")
        if path.is_file()
    } == {
        "base_slide.png",
        "crops/left.png",
        "crops/right.png",
    }
    validate_reveal_output(painted_dir, root, 320, 180, require_no_blocking=False)

    reconstructed = Image.open(painted_dir / "assets" / "base_slide.png").convert("RGBA")
    for layer in sorted(scene["layers"][1:], key=lambda item: item["z_index"]):
        reconstructed.alpha_composite(Image.open(painted_dir / layer["asset"]).convert("RGBA"))

    # Mask-covered white outside the objects is removed to the configured video background.
    assert reconstructed.convert("RGB").getpixel((20, 20)) == (254, 253, 249)
    assert reconstructed.convert("RGB").getpixel((155, 90)) == (254, 253, 249)
    # Non-white content is retained.
    assert reconstructed.convert("RGB").getpixel((35, 80)) == (17, 17, 17)
    assert reconstructed.convert("RGB").getpixel((220, 90)) == (167, 200, 239)
    # White enclosed by the black border remains white instead of being hollowed out.
    assert reconstructed.convert("RGB").getpixel((60, 80)) == (255, 255, 255)

    edge_mask = manual_mask_alpha(
        {
            "strokes": [
                {
                    "mode": "paint",
                    "size": 80,
                    "points": [{"x": -20, "y": 90}],
                },
                {
                    "mode": "erase",
                    "eraser": True,
                    "size": 30,
                    "points": [{"x": -10, "y": 90}],
                },
            ]
        },
        320,
        180,
    )
    assert edge_mask is not None
    assert edge_mask.getpixel((0, 90)) == 0
    assert edge_mask.getpixel((10, 90)) == 255

print("reveal mask integrity checks passed")
