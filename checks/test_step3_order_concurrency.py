import json
import sys
import tempfile
from pathlib import Path

from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server  # noqa: E402
from visual_provenance import visual_provenance_status, write_visual_provenance  # noqa: E402


class FakeProject:
    id = "order-project"

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = str(run_dir)
        self.current_step = 8
        self._statuses = {str(step): "completed" for step in range(1, 9)}

    def get_step_status(self, step=None):
        return dict(self._statuses) if step is None else self._statuses.get(str(step), "pending")

    def set_step_status(self, statuses):
        self._statuses = dict(statuses)


class FakeDb:
    def __init__(self, project: FakeProject) -> None:
        self.project = project
        self.commits = 0

    def query(self, *_args):
        return self

    def filter(self, *_args):
        return self

    def first(self):
        return self.project

    def commit(self):
        self.commits += 1


def _write_image_with_provenance(run_dir: Path, slide_id: str, content: bytes) -> None:
    image_path = run_dir / "slides" / slide_id / "visual_draft.png"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(content)
    write_visual_provenance(
        run_dir,
        slide_id,
        image_path=image_path,
        provider="manual_upload",
        source_type="local_upload",
        source_bytes=content,
        source_filename=f"{slide_id}.png",
    )


def test_dragging_moves_images_without_reordering_storyboard() -> None:
    with tempfile.TemporaryDirectory() as value:
        run_dir = Path(value)
        planning = run_dir / "planning"
        planning.mkdir(parents=True)
        contract_path = planning / "visual_contract.json"
        original_contract = {
            "slides": [
                {"slide_id": "a", "main_title": "标题 A"},
                {"slide_id": "b", "main_title": "标题 B"},
                {"slide_id": "c", "main_title": "标题 C"},
            ]
        }
        contract_path.write_text(json.dumps(original_contract, ensure_ascii=False), encoding="utf-8")
        narration_path = planning / "narration_beats.json"
        original_narration = {
            "slides": [
                {"slide_id": "a", "narration": "旁白 A"},
                {"slide_id": "b", "narration": "旁白 B"},
                {"slide_id": "c", "narration": "旁白 C"},
            ]
        }
        narration_path.write_text(json.dumps(original_narration, ensure_ascii=False), encoding="utf-8")
        manifest_path = run_dir / "reveal_manifest.json"
        manifest_path.write_text(
            json.dumps({
                "slides": [
                    {"slide_id": slide_id, "status": "completed", "groups": [{"group_id": slide_id}]}
                    for slide_id in ("a", "b", "c")
                ]
            }),
            encoding="utf-8",
        )
        for slide_id, content in (("a", b"image-a"), ("b", b"image-b"), ("c", b"image-c")):
            _write_image_with_provenance(run_dir, slide_id, content)

        (run_dir / "remotion_props.json").write_text("{}", encoding="utf-8")
        (planning / "audio_confirmed.json").write_text("{}", encoding="utf-8")
        project = FakeProject(run_dir)
        db = FakeDb(project)
        slide_ids = ["a", "b", "c"]
        version = server.step3_image_assignment_version(str(run_dir), slide_ids)

        response = server.update_step3_image_order(
            project.id,
            {"from_index": 2, "to_index": 0, "order_version": version},
            db,
        )

        assert json.loads(contract_path.read_text(encoding="utf-8")) == original_contract
        assert json.loads(narration_path.read_text(encoding="utf-8")) == original_narration
        assert response["slide_ids"] == slide_ids
        assert (run_dir / "slides" / "a" / "visual_draft.png").read_bytes() == b"image-c"
        assert (run_dir / "slides" / "b" / "visual_draft.png").read_bytes() == b"image-a"
        assert (run_dir / "slides" / "c" / "visual_draft.png").read_bytes() == b"image-b"
        assert all(visual_provenance_status(run_dir, slide_id)["valid"] for slide_id in slide_ids)
        assert not (run_dir / "remotion_props.json").exists()
        assert not (planning / "audio_confirmed.json").exists()
        assert project.get_step_status(4) == "pending_reconfirmation"
        assert project.get_step_status(8) == "pending_reconfirmation"
        assert db.commits == 1

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert [slide["slide_id"] for slide in manifest["slides"]] == slide_ids
        assert all(slide["groups"] == [] and slide["status"] == "pending" for slide in manifest["slides"])

        try:
            server.update_step3_image_order(
                project.id,
                {"from_index": 0, "to_index": 1, "order_version": version},
                db,
            )
        except HTTPException as exc:
            assert exc.status_code == 409
        else:
            raise AssertionError("stale image-assignment version unexpectedly succeeded")


def test_bulk_delete_images_clears_all_slide_derivatives() -> None:
    with tempfile.TemporaryDirectory() as value:
        run_dir = Path(value)
        planning = run_dir / "planning"
        planning.mkdir(parents=True)
        (planning / "visual_contract.json").write_text(
            json.dumps({"slides": [{"slide_id": "a"}, {"slide_id": "b"}]}),
            encoding="utf-8",
        )
        (planning / "audio_confirmed.json").write_text("{}", encoding="utf-8")
        (run_dir / "remotion_props.json").write_text("{}", encoding="utf-8")
        for slide_id, content in (("a", b"image-a"), ("b", b"image-b")):
            _write_image_with_provenance(run_dir, slide_id, content)
            slide_dir = run_dir / "slides" / slide_id
            (slide_dir / "visual_candidate.png").write_bytes(b"candidate")
            (slide_dir / "assets").mkdir()
            (slide_dir / "assets" / "layer.png").write_bytes(b"layer")

        project = FakeProject(run_dir)
        db = FakeDb(project)
        response = server.delete_all_slide_images(project.id, db)

        assert response["deleted_count"] == 2
        assert response["slide_ids"] == ["a", "b"]
        for slide_id in ("a", "b"):
            slide_dir = run_dir / "slides" / slide_id
            assert not (slide_dir / "visual_draft.png").exists()
            assert not (slide_dir / "visual_candidate.png").exists()
            assert not (slide_dir / "assets").exists()
        assert not (planning / "audio_confirmed.json").exists()
        assert not (run_dir / "remotion_props.json").exists()
        assert project.current_step == 3
        assert project.get_step_status(3) == "in_progress"
        assert project.get_step_status(4) == "pending_reconfirmation"
        assert db.commits == 1
