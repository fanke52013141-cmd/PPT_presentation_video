import json
import os
import sys
import tempfile
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database import Project
from server import mark_slide_image_changed, prune_stale_mask_groups, sync_reveal_manifest_to_contract


class DummyDb:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1


with tempfile.TemporaryDirectory() as temp_value:
    run_dir = Path(temp_value)
    planning = run_dir / "planning"
    planning.mkdir()
    slides_root = run_dir / "slides"
    for slide_id in ("slide_001", "slide_002"):
        slide_dir = slides_root / slide_id
        (slide_dir / "assets").mkdir(parents=True)
        Image.new("RGB", (32, 18), "#fffdf7").save(slide_dir / "visual_draft.png")
        (slide_dir / "scene.json").write_text("{}", encoding="utf-8")
        (slide_dir / "animation_timeline.json").write_text("{}", encoding="utf-8")
        (slide_dir / "reveal_report.json").write_text("{}", encoding="utf-8")
        (slide_dir / "assets" / "old.png").write_bytes(b"old")

    (planning / "visual_contract.json").write_text(
        json.dumps({"slides": [{"slide_id": "slide_001"}, {"slide_id": "slide_002"}]}),
        encoding="utf-8",
    )
    (planning / "audio_confirmed.json").write_text("{}", encoding="utf-8")
    (run_dir / "remotion_props.json").write_text("{}", encoding="utf-8")
    (run_dir / "reveal_manifest.json").write_text(
        json.dumps({
            "slides": [
                {
                    "slide_id": "slide_001",
                    "status": "completed",
                    "groups": [{"id": "g1", "manual_mask": {"strokes": [{"points": [{"x": 1, "y": 1}]}]}}],
                    "semantic_blocks": [{"id": "g1"}],
                },
                {"slide_id": "slide_002", "groups": []},
            ]
        }),
        encoding="utf-8",
    )

    project = Project(id="test", name="test", run_dir=str(run_dir), current_step=8)
    project.set_step_status({str(i): "completed" for i in range(1, 9)})
    db = DummyDb()
    mark_slide_image_changed(project, "slide_001", db)

    manifest = json.loads((run_dir / "reveal_manifest.json").read_text(encoding="utf-8"))
    slide = manifest["slides"][0]
    assert slide["groups"] == []
    assert slide["semantic_blocks"] == []
    assert slide["status"] == "pending"
    assert not (slides_root / "slide_001" / "scene.json").exists()
    assert not (slides_root / "slide_001" / "assets").exists()
    assert not (run_dir / "remotion_props.json").exists()
    assert not (planning / "audio_confirmed.json").exists()
    assert project.get_step_status()["3"] == "completed"
    assert project.get_step_status()["5"] == "pending_reconfirmation"
    assert project.current_step == 3
    assert db.commits == 1

print("slide visual invalidation checks passed")


with tempfile.TemporaryDirectory() as temp_value:
    run_dir = Path(temp_value)
    planning = run_dir / "planning"
    planning.mkdir()
    (planning / "visual_contract.json").write_text(
        json.dumps({
            "slides": [{
                "slide_id": "slide_001",
                "visual_groups": [{"id": "body_group"}],
            }],
        }),
        encoding="utf-8",
    )
    project = Project(id="static-header", name="static-header", run_dir=str(run_dir), current_step=5)
    payload = {
        "slides": [{
            "slide_id": "slide_001",
            "groups": [
                {"id": "__static_title_header__", "is_static": True, "is_static_header": True, "source": "ai_static_header"},
                {"id": "body_group", "visual_group_id": "body_group"},
                {"id": "stale_group"},
            ],
            "semantic_blocks": [],
        }],
    }
    pruned = prune_stale_mask_groups(project, payload)
    ids = [group["id"] for group in pruned["slides"][0]["groups"]]
    assert ids == ["__static_title_header__", "body_group"]

print("static title header pruning checks passed")


with tempfile.TemporaryDirectory() as temp_value:
    run_dir = Path(temp_value)
    planning = run_dir / "planning"
    planning.mkdir()
    contract = {
        "version": "visual_contract_v1",
        "slides": [
            {
                "slide_id": slide_id,
                "visual_groups": [
                    {"id": f"{slide_id}_title", "role": "title", "visible_text": f"Title {index}"},
                    {"id": f"{slide_id}_body", "role": "content_body", "visible_text": f"Body {index}"},
                ],
                "narration_beats": [
                    {"id": f"{slide_id}_beat", "group_id": f"{slide_id}_body"},
                ],
            }
            for index, slide_id in enumerate(("slide_001", "slide_002"), start=1)
        ],
    }
    (planning / "visual_contract.json").write_text(
        json.dumps(contract, ensure_ascii=False),
        encoding="utf-8",
    )
    (run_dir / "reveal_manifest.json").write_text(
        json.dumps({
            "version": "reveal_v1",
            "slides": [],
            "ai_mask_annotation": {"status": "completed", "processed_slide_count": 9},
        }),
        encoding="utf-8",
    )
    project = Project(id="repair-empty", name="repair-empty", run_dir=str(run_dir), current_step=5)
    assert sync_reveal_manifest_to_contract(project) is True
    repaired = json.loads((run_dir / "reveal_manifest.json").read_text(encoding="utf-8"))
    assert [slide["slide_id"] for slide in repaired["slides"]] == ["slide_001", "slide_002"]
    assert repaired["slides"][0]["groups"][1]["id"] == "slide_001_body"
    assert "ai_mask_annotation" not in repaired

print("empty reveal manifest repair checks passed")
