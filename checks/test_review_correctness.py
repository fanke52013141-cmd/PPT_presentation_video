"""Regression checks for the remaining workflow correctness findings."""
from __future__ import annotations

import json
import os
from types import SimpleNamespace

from fastapi import HTTPException
import pytest

import one_click_resume_policy as resume
import step3_image_style_service as styles
import tts_service as tts


@pytest.mark.parametrize("runtime", [{"provider": "minimax", "voice_id": "new"}, None])
def test_confirm_rejects_stale_or_unresolvable_voice_before_mutation(tmp_path, monkeypatch, runtime):
    project = SimpleNamespace(id="p", run_dir=str(tmp_path))
    metadata = tmp_path / "tts_metadata.json"
    metadata.write_text(json.dumps({"provider": "minimax", "request": {"voice_id": "old"}}))
    confirmation = tmp_path / "planning" / "audio_confirmed.json"
    confirmation.parent.mkdir()
    confirmation.write_text("old confirmation")
    monkeypatch.setattr(tts, "project_or_404", lambda *_: project)
    monkeypatch.setattr(tts, "read_current_slide_ids_or_404", lambda *_: ["s1"])
    monkeypatch.setattr(tts, "slide_tts_artifact_status", lambda *_: {"complete": True})
    monkeypatch.setattr(tts, "slide_tts_artifact_paths", lambda *_: {"metadata": str(metadata)})
    monkeypatch.setattr(tts, "current_tts_cache_key", lambda *_: runtime)
    monkeypatch.setattr(tts, "_load_beats_by_slide", lambda *_: pytest.fail("must reject before timeline writes"))
    with pytest.raises(HTTPException) as exc:
        tts.confirm_tts_audio("p", None)
    assert exc.value.status_code == 409
    assert confirmation.read_text() == "old confirmation"


@pytest.mark.parametrize("change_during_bind", [False, True])
def test_confirm_uses_verified_runtime_and_rechecks_after_binding(tmp_path, monkeypatch, change_during_bind):
    project = SimpleNamespace(id="p", run_dir=str(tmp_path))
    runtime = {"provider": "minimax", "voice_id": "old"}
    metadata = tmp_path / "tts_metadata.json"
    metadata.write_text(json.dumps({"provider": "minimax", "request": {"voice_id": "old"}}))
    confirmation = tmp_path / "planning" / "audio_confirmed.json"
    navigations = []
    monkeypatch.setattr(tts, "project_or_404", lambda *_: project)
    monkeypatch.setattr(tts, "read_current_slide_ids_or_404", lambda *_: ["s1"])
    monkeypatch.setattr(tts, "slide_tts_artifact_status", lambda *_: {"complete": True})
    monkeypatch.setattr(tts, "slide_tts_artifact_paths", lambda *_: {"metadata": str(metadata)})
    monkeypatch.setattr(tts, "current_tts_cache_key", lambda *_: dict(runtime))
    monkeypatch.setattr(tts, "_load_beats_by_slide", lambda *_: {})
    monkeypatch.setattr(tts, "rewrite_audio_timeline_by_beats", lambda *_: None)

    def bind(_project):
        if change_during_bind:
            runtime["voice_id"] = "new"
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(tts, "_run_bind_reveal_timeline", bind)
    monkeypatch.setattr(tts, "audio_confirmation_path", lambda *_: str(confirmation))
    monkeypatch.setattr(tts, "build_audio_confirmation_payload", lambda *a, **kw: {"runtime": kw["tts_runtime"]})
    monkeypatch.setattr(tts, "handle_step_navigation", lambda *a: navigations.append(a[1]))
    monkeypatch.setattr(tts, "tts_artifact_paths", lambda *_: {})
    if change_during_bind:
        with pytest.raises(HTTPException) as exc:
            tts.confirm_tts_audio("p", None)
        assert exc.value.status_code == 409
        assert not confirmation.exists()
        assert not navigations
    else:
        assert tts.confirm_tts_audio("p", None)["audio_confirmed"]
        assert json.loads(confirmation.read_text())["runtime"] == runtime
        assert navigations == [7]


def test_style_edits_and_reference_metadata_do_not_regenerate_existing_images(tmp_path):
    project = SimpleNamespace(run_dir=str(tmp_path))
    planning = tmp_path / "planning"
    slide = tmp_path / "slides" / "s1"
    planning.mkdir()
    slide.mkdir(parents=True)
    contract = planning / "visual_contract.json"
    contract.write_text(json.dumps({"slides": [{"slide_id": "s1"}, {"slide_id": "s2"}]}))
    image = slide / "visual_draft.png"
    image.write_bytes(b"approved image")
    os.utime(contract, (100, 100))
    os.utime(image, (200, 200))
    styles.save_step3_style(project, {"system_content": "new style"}, "manual")
    (planning / "project_style_references.json").write_text('{"images":[]}')
    refs = planning / "style_references"
    refs.mkdir()
    (refs / "style_reference_01.png").write_bytes(b"new reference")
    assert resume.slides_requiring_images(project) == ["s2"]
    assert image.read_bytes() == b"approved image"
    os.utime(contract, (300, 300))
    assert resume.slides_requiring_images(project) == ["s1", "s2"]


def test_same_style_from_another_entry_point_is_noop(tmp_path):
    project = SimpleNamespace(run_dir=str(tmp_path))
    style = {"system_content": "same"}
    styles.save_step3_style(project, style, "template")
    path = styles.state_path(project)
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    styles.save_step3_style(project, style, "manual")
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
