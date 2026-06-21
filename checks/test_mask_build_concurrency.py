import json
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.build_reveal_scene import build_manifest
from server import reveal_lock_for, write_json_atomic


with tempfile.TemporaryDirectory() as temp_dir_value:
    root = Path(temp_dir_value)

    # Concurrent manifest saves must always leave one complete JSON document.
    manifest_path = root / "reveal_manifest.json"
    writers = [
        threading.Thread(
            target=write_json_atomic,
            args=(str(manifest_path), {"writer": index, "slides": [{"slide_id": "slide_001"}]}),
        )
        for index in range(20)
    ]
    for writer in writers:
        writer.start()
    for writer in writers:
        writer.join()
    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert saved["writer"] in range(20)
    assert saved["slides"][0]["slide_id"] == "slide_001"

    # Every server operation for one run must share the same re-entrant lock.
    project = SimpleNamespace(run_dir=str(root))
    assert reveal_lock_for(project) is reveal_lock_for(project)

    # Even direct concurrent builders publish complete files from staging.
    slide_dir = root / "slides" / "slide_001"
    slide_dir.mkdir(parents=True)
    Image.new("RGB", (240, 135), (255, 255, 255)).save(slide_dir / "visual_draft.png")
    manifest = {
        "version": "reveal_v1",
        "canvas": {
            "width": 240,
            "height": 135,
            "background": "#FEFDF9",
            "subtitle_safe_y": 116,
        },
        "slides": [
            {
                "slide_id": "slide_001",
                "slide_dir": str(slide_dir),
                "master": "visual_draft.png",
                "default_duration_sec": 1,
                "groups": [],
            }
        ],
    }
    errors = []

    def run_build() -> None:
        try:
            with reveal_lock_for(project):
                build_manifest(manifest, manifest_path, root)
        except Exception as exc:  # pragma: no cover - assertion reports details
            errors.append(exc)

    builders = [threading.Thread(target=run_build) for _ in range(4)]
    for builder in builders:
        builder.start()
    for builder in builders:
        builder.join()
    assert not errors, errors

    scene = json.loads((slide_dir / "scene.json").read_text(encoding="utf-8"))
    report = json.loads((slide_dir / "reveal_report.json").read_text(encoding="utf-8"))
    assert scene["layers"][0]["asset"] == "assets/full_slide.png"
    assert report["fallback_full_slide"] is True
    assert (slide_dir / "assets" / "full_slide.png").exists()
    assert not list(slide_dir.glob(".reveal-build-*"))

print("mask build concurrency checks passed")
