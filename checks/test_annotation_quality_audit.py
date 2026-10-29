import json

from PIL import Image

from scripts.audit_annotation_quality import audit


def test_quality_audit_flags_unknown_text_unbound_marks_and_low_contrast_without_writes(tmp_path):
    from checks.test_annotation_routes import MANUAL_REGION_ITEM

    (tmp_path / "planning").mkdir()
    directory = tmp_path / "slides/slide_001"
    directory.mkdir(parents=True)
    (tmp_path / "planning/visual_contract.json").write_text(json.dumps({"slides": [{"slide_id": "slide_001"}]}), encoding="utf-8")
    Image.new("RGB", (1920, 1080), "#FFE58A").save(directory / "visual_draft.png")
    (directory / "text_layout.json").write_text(json.dumps({"lines": [{"line_id": "l", "text": "▣", "polygon": [[0,0],[10,0],[10,10],[0,10]]}]}), encoding="utf-8")
    item = json.loads(json.dumps(MANUAL_REGION_ITEM))
    item.update(annotation_id="ann_001", status={"content": "draft"})
    item["style"].update(type="highlighter", color="#F6CE46", opacity=.28)
    (directory / "annotations.json").write_text(json.dumps({"items": [item]}), encoding="utf-8")
    (directory / "annotation_timeline.json").write_text(json.dumps({"events": [{"start_sec": 1, "draw_end_sec": 2, "exit_end_sec": 3}]}), encoding="utf-8")
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.rglob("*") if p.is_file()}
    report = audit(tmp_path)
    assert {issue["code"] for issue in report["issues"]} == {
        "ocr_unknown_glyph", "unbound_region_needs_visual_review", "unconfirmed", "marker_background_conflict"}
    assert report["status"] == "needs_review"
    assert 1 in report["slides"][0]["sample_slide_relative_seconds"]
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before} == before


def test_selected_layout_hash_ignores_unrelated_text_but_binds_selected_text_and_geometry(tmp_path):
    from types import SimpleNamespace
    from annotation_build import selected_layout_hash

    layout = {"layout_revision": 1, "lines": [{"line_id": "line", "text": "甲乙", "tokens": [
        {"token_id": "a", "char": "甲", "polygon": [[0,0],[10,0],[10,20],[0,20]]},
        {"token_id": "b", "char": "乙", "polygon": [[12,0],[22,0],[22,20],[12,20]]},
    ]}]}
    target = tmp_path / "text_layout.json"
    target.write_text(json.dumps(layout), encoding="utf-8")
    item = SimpleNamespace(status=SimpleNamespace(content="confirmed"), target=SimpleNamespace(kind="text", token_ids=["a"]))
    baseline = selected_layout_hash(tmp_path, [item])
    layout["corrections"] = {"b": {"text": "丙", "chars_changed": False}}
    target.write_text(json.dumps(layout), encoding="utf-8")
    assert selected_layout_hash(tmp_path, [item]) == baseline
    layout["corrections"]["a"] = {"text": "丁", "chars_changed": False}
    target.write_text(json.dumps(layout), encoding="utf-8")
    assert selected_layout_hash(tmp_path, [item]) != baseline
    layout["corrections"].pop("a")
    layout["lines"][0]["tokens"][1]["polygon"][0][0] = 11
    target.write_text(json.dumps(layout), encoding="utf-8")
    assert selected_layout_hash(tmp_path, [item]) != baseline
