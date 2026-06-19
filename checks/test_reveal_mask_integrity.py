import json
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.build_reveal_scene import (
    MASKED_COMPOSITION_METHOD,
    PIPELINE_VERSION,
    compose_slide,
    fill_enclosed_mask_holes,
    manual_mask_alpha,
    manual_mask_has_eraser,
)
from scripts.validate_reveal_scene import validate_scene as validate_reveal_output


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def make_master(path: Path) -> Image.Image:
    image = Image.new("RGB", (320, 180), "#fffdf7")
    draw = ImageDraw.Draw(image)
    draw.rectangle((30, 45, 120, 125), fill="#8fd3c7")
    draw.rectangle((105, 35, 220, 135), fill="#f3cf76")
    draw.rectangle((225, 50, 295, 130), fill="#a7c8ef")
    image.save(path)
    return image


hole_mask = Image.new("L", (40, 30), 0)
hole_draw = ImageDraw.Draw(hole_mask)
hole_draw.rectangle((5, 5, 34, 24), fill=255)
hole_draw.rectangle((15, 10, 24, 19), fill=0)
filled_mask, filled_count = fill_enclosed_mask_holes(hole_mask)
assert filled_count == 100
assert filled_mask.getpixel((20, 15)) == 255
assert manual_mask_has_eraser({"strokes": [{"mode": "erase", "points": []}]})
assert not manual_mask_has_eraser({"strokes": [{"mode": "paint", "points": []}]})


def painted_group(group_id: str, x: int, y: int, width: int = 46) -> dict:
    return {
        "id": group_id,
        "role": "content_body",
        "box": {"x": max(0, x - 30), "y": max(0, y - 30), "w": 100, "h": 100},
        "manual_mask": {
            "strokes": [{
                "mode": "paint",
                "size": width,
                "points": [{"x": x, "y": y}, {"x": x + 55, "y": y + 10}],
            }]
        },
        "reveal": {"type": "crop_fade_up"},
    }


with tempfile.TemporaryDirectory() as temp_dir_value:
    root = Path(temp_dir_value)
    master_path = root / "master.png"
    master = make_master(master_path)

    no_mask_dir = root / "slides" / "slide_001"
    no_mask_dir.mkdir(parents=True)
    compose_slide(
        {
            "slide_id": "slide_001",
            "slide_dir": str(no_mask_dir),
            "master": str(master_path),
            "canvas": {"width": 320, "height": 180, "background": "#fffdf7", "subtitle_safe_y": 180},
            "groups": [{"id": "unpainted", "role": "content_body", "box": {"x": 20, "y": 20, "w": 100, "h": 100}}],
        },
        root,
        root,
        {"width": 320, "height": 180, "background": "#fffdf7", "subtitle_safe_y": 180},
    )
    no_mask_scene = read_json(no_mask_dir / "scene.json")
    no_mask_timeline = read_json(no_mask_dir / "animation_timeline.json")
    no_mask_report = read_json(no_mask_dir / "reveal_report.json")
    assert len(no_mask_scene["layers"]) == 1
    assert no_mask_scene["layers"][0]["role"] == "full_slide"
    assert no_mask_timeline["events"] == []
    assert no_mask_report["fallback_full_slide"] is True
    validate_reveal_output(no_mask_dir, root, 320, 180, require_no_blocking=False)

    painted_dir = root / "slides" / "slide_002"
    (painted_dir / "assets").mkdir(parents=True)
    (painted_dir / "assets" / "stale-old-algorithm.png").write_bytes(b"stale")
    painted_groups = [
        painted_group("left", 60, 75),
        painted_group("overlap", 115, 75),
    ]
    compose_slide(
        {
            "slide_id": "slide_002",
            "slide_dir": str(painted_dir),
            "master": str(master_path),
            "canvas": {"width": 320, "height": 180, "background": "#fffdf7", "subtitle_safe_y": 180},
            "groups": painted_groups,
        },
        root,
        root,
        {"width": 320, "height": 180, "background": "#fffdf7", "subtitle_safe_y": 180},
    )
    painted_scene = read_json(painted_dir / "scene.json")
    painted_report = read_json(painted_dir / "reveal_report.json")
    assert [layer["role"] for layer in painted_scene["layers"]] == ["background", "reveal_crop", "reveal_crop"]
    assert painted_scene["composition"]["method"] == MASKED_COMPOSITION_METHOD
    assert painted_scene["composition"]["pipeline_version"] == PIPELINE_VERSION
    assert painted_scene["composition"]["source_image_used_for_background"] is False
    assert painted_report["pipeline_version"] == PIPELINE_VERSION
    assert painted_report["background_normalization"]["method"] == "outer_connected_near_white_only"
    assert not (painted_dir / "assets" / "stale-old-algorithm.png").exists()
    validate_reveal_output(painted_dir, root, 320, 180, require_no_blocking=False)

    reconstructed = Image.open(painted_dir / painted_scene["layers"][0]["asset"]).convert("RGBA")
    base_rgb = reconstructed.convert("RGB")
    assert base_rgb.getpixel((60, 75)) == (255, 253, 247)
    assert base_rgb.getpixel((145, 85)) == (255, 253, 247)
    for layer in painted_scene["layers"][1:]:
        reconstructed.alpha_composite(Image.open(painted_dir / layer["asset"]).convert("RGBA"))

    union = Image.new("L", master.size, 0)
    for group in painted_groups:
        exact_mask = manual_mask_alpha(group["manual_mask"], master.width, master.height)
        assert exact_mask is not None
        saved_mask = Image.open(painted_dir / "assets" / "masks" / f"{group['id']}.png").convert("L")
        assert saved_mask.tobytes() == exact_mask.tobytes()
        union = ImageChops.lighter(union, exact_mask)
    expected = Image.composite(master, Image.new("RGB", master.size, "#fffdf7"), union)
    assert reconstructed.convert("RGB").tobytes() == expected.tobytes()
    exact_preview = Image.open(painted_dir / "assets" / "manual_mask_composite.png").convert("RGB")
    assert exact_preview.tobytes() == expected.tobytes()
    assert reconstructed.convert("RGB").getpixel((290, 90)) == (255, 253, 247)
    uncovered_preview = Image.open(painted_dir / "assets" / "manual_mask_uncovered.png").convert("RGB")
    red_pixel = uncovered_preview.getpixel((290, 90))
    assert red_pixel[0] > 240 and red_pixel[1] < 100 and red_pixel[2] < 100
    assert painted_report["foreground_diagnostics"]["required_coverage_ratio"] == 0.999

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
        master.width,
        master.height,
    )
    assert edge_mask is not None
    assert edge_mask.getpixel((0, 90)) == 0
    assert edge_mask.getpixel((10, 90)) == 255

print("reveal mask integrity checks passed")
