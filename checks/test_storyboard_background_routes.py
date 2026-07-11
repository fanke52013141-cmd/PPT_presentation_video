import json
from pathlib import Path
import sys
import tempfile

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server
import storyboard_background
from storyboard_background_render import apply_storyboard_background


def test_routes_are_explicit_and_unique() -> None:
    expected = {
        ("/api/projects/{project_id}/storyboard-background", "GET"),
        ("/api/projects/{project_id}/storyboard-background", "PUT"),
        ("/api/projects/{project_id}/storyboard-background/image", "POST"),
        ("/api/projects/{project_id}/storyboard-background/image", "GET"),
    }
    actual = []
    for route in server.app.routes:
        for method in getattr(route, "methods", set()) or set():
            pair = (getattr(route, "path", ""), method)
            if pair in expected:
                actual.append(pair)
    assert set(actual) == expected
    assert len(actual) == len(expected)
    assert not hasattr(storyboard_background, "_install_when_ready")
    assert not hasattr(storyboard_background, "_candidate_modules")


def test_background_render_is_an_explicit_post_build_function() -> None:
    with tempfile.TemporaryDirectory() as value:
        run_dir = Path(value)
        planning = run_dir / "planning"
        slide_dir = run_dir / "slides" / "slide_001"
        assets = slide_dir / "assets"
        planning.mkdir()
        assets.mkdir(parents=True)
        (planning / "storyboard_background.json").write_text(
            json.dumps({"mode": "image", "image_fit": "cover"}), encoding="utf-8"
        )
        Image.new("RGB", (20, 20), "#336699").save(planning / "storyboard_background.png")
        Image.new("RGB", (40, 30), "white").save(assets / "base_slide.png")
        (slide_dir / "scene.json").write_text(
            json.dumps({"canvas": {"width": 40, "height": 30}}), encoding="utf-8"
        )
        manifest = run_dir / "reveal_manifest.json"
        manifest.write_text(
            json.dumps({"slides": [{"slide_id": "slide_001", "slide_dir": str(slide_dir)}]}),
            encoding="utf-8",
        )
        assert apply_storyboard_background(manifest) == 1
        scene = json.loads((slide_dir / "scene.json").read_text(encoding="utf-8"))
        assert scene["canvas"]["background_mode"] == "image"
        assert scene["composition"]["background_source"] == "planning/storyboard_background.png"


if __name__ == "__main__":
    test_routes_are_explicit_and_unique()
    test_background_render_is_an_explicit_post_build_function()
    print("storyboard background route checks passed")
