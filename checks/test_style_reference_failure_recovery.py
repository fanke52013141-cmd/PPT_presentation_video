import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image
from fastapi import HTTPException, UploadFile

import image_style_reverse_service as reverse
import project_style_reference_service as generation
import project_style_reference_store as store


def test_download_uses_published_unique_reference_filename(tmp_path, monkeypatch):
    import project_style_routes as routes

    project = SimpleNamespace(run_dir=str(tmp_path))
    directory = store.references_dir(project)
    directory.mkdir(parents=True)
    published = directory / "style_reference_01_unique.png"
    published.write_bytes(png())
    (directory / "style_reference_01.png").write_bytes(b"obsolete")
    store.manifest_path(project).write_text(json.dumps({"images": [
        {"index": 1, "filename": published.name}]}), encoding="utf-8")
    monkeypatch.setattr(routes, "_project_or_404", lambda *_: project)
    for handler in (routes.get_step3_reference_image, routes.get_legacy_reference_image):
        assert Path(handler("project", 1, None).path) == published.resolve()
    published.unlink()
    with pytest.raises(HTTPException) as error:
        routes.get_step3_reference_image("project", 1, None)
    assert error.value.status_code == 404


def png():
    output = io.BytesIO()
    Image.new("RGB", (80, 60), "blue").save(output, "PNG")
    return output.getvalue()


def test_invalid_second_reverse_image_keeps_previous_inputs(tmp_path):
    project = SimpleNamespace(run_dir=str(tmp_path))
    directory = reverse._inputs_dir(project)
    directory.mkdir(parents=True)
    old = directory / "reverse_reference_01.png"
    old.write_bytes(png())
    manifest = reverse._inputs_manifest_path(project)
    manifest.write_bytes(b'{"images": []}')
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    files = [UploadFile(filename="one.png", file=io.BytesIO(png()), headers={"content-type": "image/png"}),
             UploadFile(filename="two.png", file=io.BytesIO(b"broken"), headers={"content-type": "image/png"})]
    with pytest.raises(HTTPException) as error:
        reverse._save_uploaded_references(SimpleNamespace(image_class=Image, http_exception=HTTPException), project, files)
    assert error.value.status_code == 400
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("failure", ["generation", "metadata"])
def test_reference_generation_failure_preserves_prior_batch(tmp_path, monkeypatch, failure):
    project = SimpleNamespace(run_dir=str(tmp_path), canvas_profile="landscape_16_9")
    refs = generation._references_dir(project)
    refs.mkdir(parents=True)
    (refs / "style_reference_01.png").write_bytes(png())
    manifest = generation._manifest_path(project)
    manifest.write_bytes(b'{"images": [{"filename": "style_reference_01.png"}]}')
    state = tmp_path / "planning/step3_image_style.json"
    state.write_bytes(b'{"source":"original"}')
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    monkeypatch.setattr(generation, "_profile_image_style", lambda _: {"style_name": "original"})
    monkeypatch.setattr(generation, "_reference_prompts", lambda *_: ["one", "two"])
    monkeypatch.setattr(generation, "_read_reference_generation_system_content", lambda _: "stable rules")
    client = Mock()
    generate = Mock(side_effect=[png(), RuntimeError("upstream failed")] if failure == "generation" else [png(), png()])
    def update(*_):
        state.write_text(json.dumps({"source": "changed"}))
        raise OSError("metadata failed")
    if failure == "metadata":
        monkeypatch.setattr(generation, "_update_prompt_companion", update)
    deps = SimpleNamespace(get_setting=lambda key, default=None: {"image_api_key": "test", "image_size": "1024x1024"}.get(key, default),
        get_openai_client=lambda **_: client, generate_image_response=generate,
        extract_image_bytes_from_response=lambda value: value,
        process_and_save_image=lambda value, path, **_: Path(path).write_bytes(value),
        http_exception=HTTPException)
    with pytest.raises((RuntimeError, OSError)):
        generation._generate_reference_images(deps, project, "project", {"count": 2})
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before
    client.close.assert_called_once()
    assert generate.call_args.kwargs["api_key"] == "test"


def test_failed_vision_analysis_does_not_publish_uploaded_inputs(tmp_path, monkeypatch):
    project = SimpleNamespace(run_dir=str(tmp_path))
    directory = reverse._inputs_dir(project)
    directory.mkdir(parents=True)
    manifest = reverse._inputs_manifest_path(project)
    manifest.write_bytes(b'{"images": []}')
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    def reject(*_):
        raise RuntimeError("model returned invalid output")
    monkeypatch.setattr(reverse, "_call_vision_model", reject)
    file = UploadFile(filename="one.png", file=io.BytesIO(png()), headers={"content-type": "image/png"})
    with pytest.raises(RuntimeError):
        reverse.analyze_uploaded_references(SimpleNamespace(image_class=Image, http_exception=HTTPException), project, [file], "")
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before
