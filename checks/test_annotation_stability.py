"""Cancellation, retries and immutable raster cache regression checks."""
from dataclasses import replace
from types import SimpleNamespace
import threading

import pytest

import annotation_ink as ink
import annotation_jobs as jobs
from annotation_contracts import AnnotationPage
from annotation_ocr_baidu import BaiduOcrError


def _manager(recognize):
    events = []
    store = SimpleNamespace(**{name: (lambda *args, name=name, **kw: events.append((name, args))) for name in (
        "update_progress", "mark_running", "mark_cancelled", "mark_failed", "mark_succeeded")})
    manager = jobs.AnnotationJobManager(jobs.AnnotationJobDependencies(
        job_store=store, session_factory=lambda: None, text_layout_builder=None, recognize=recognize,
    ))
    return manager, events


@pytest.mark.parametrize("retryable,expected_calls", [(True, 3), (False, 1)])
def test_ocr_retry_is_bounded_and_respects_error_class(monkeypatch, retryable, expected_calls):
    calls = []
    def recognize(*args):
        calls.append(args)
        raise BaiduOcrError("18", "limited", "rate_limit", retryable)
    manager, events = _manager(recognize)
    monkeypatch.setattr(jobs, "_OCR_RETRY_DELAYS", (0, 0))
    with pytest.raises(BaiduOcrError):
        manager._recognize_with_retry("j", threading.Event(), b"image", None)
    assert len(calls) == expected_calls
    assert sum(name == "update_progress" for name, _ in events) == expected_calls - 1


def test_ocr_retry_recovers_and_cancellation_interrupts_backoff(monkeypatch):
    event = threading.Event()
    calls = []
    def recognize(*args):
        calls.append(args)
        if len(calls) == 1:
            raise BaiduOcrError("18", "limited", "rate_limit", True)
        return "recognized"
    manager, _ = _manager(recognize)
    monkeypatch.setattr(jobs, "_OCR_RETRY_DELAYS", (0, 0))
    assert manager._recognize_with_retry("j", event, b"image", None) == "recognized"
    calls.clear()
    monkeypatch.setattr(event, "wait", lambda _delay: event.set() or True)
    with pytest.raises(ValueError, match="cancelled"):
        manager._recognize_with_retry("j", event, b"image", None)
    assert len(calls) == 1


@pytest.mark.parametrize("cancel", [False, True])
def test_empty_plan_is_noop_and_cancelled_plan_never_publishes(monkeypatch, cancel):
    manager, events = _manager(lambda *_: None)
    event = threading.Event()
    writes = []
    page = AnnotationPage(slide_id="s", revision=7, items=(), updated_at="before", ai_suggestion_snapshot=None)
    def plan(*args, **kwargs):
        if cancel:
            event.set()
        return [object()] if cancel else [], {}, []
    manager._deps = replace(manager._deps,
        text_layout_builder=SimpleNamespace(load=lambda *_: {}),
        annotation_store=SimpleNamespace(read_page=lambda *a, **kw: page,
            read_settings=lambda *_: None, write_page=lambda *a: writes.append(a)),
        planner=SimpleNamespace(plan_slide=plan))
    monkeypatch.setattr(manager, "_project", lambda *_: SimpleNamespace(canvas_profile=None))
    monkeypatch.setattr(manager, "_run_dir", lambda *_: "unused")
    monkeypatch.setattr(manager, "_read_image", lambda *_: b"image")
    monkeypatch.setattr(manager, "_file_hash", lambda *_: "hash")
    monkeypatch.setattr(manager, "_read_beats", lambda *_: [])
    manager._run_plan("j", "p", ["s"], event)
    assert not writes
    assert events[-1][0] == ("mark_cancelled" if cancel else "mark_succeeded")


def _request():
    return ink.InkRequest(points=((10, 10), (40, 20)), width_profile=(1, 1), canvas=(64, 32), texture=False)


def test_truncated_ink_is_rejected_and_rebuilt(tmp_path):
    ink.render_and_write(_request(), tmp_path, draw_duration_sec=.1)
    assert ink.cached_ink_metadata(tmp_path, (64, 32), .1, 30)
    (tmp_path / "frame_001.png").write_bytes(b"\x89PNG\r\n")
    assert ink.cached_ink_metadata(tmp_path, (64, 32), .1, 30) is None
    ink.render_and_write(_request(), tmp_path, draw_duration_sec=.1)
    assert ink.cached_ink_metadata(tmp_path, (64, 32), .1, 30)


def test_failed_atomic_replace_preserves_old_png_and_no_complete_marker(tmp_path, monkeypatch):
    ink.render_and_write(_request(), tmp_path, draw_duration_sec=.1)
    before = (tmp_path / "full.png").read_bytes()
    def fail(*_args):
        raise OSError("simulated interrupted replace")
    monkeypatch.setattr(ink.os, "replace", fail)
    with pytest.raises(OSError):
        ink.render_and_write(_request(), tmp_path, draw_duration_sec=.1)
    assert (tmp_path / "full.png").read_bytes() == before
    assert not (tmp_path / "meta.json").exists()
    assert not list(tmp_path.glob(".ink-*.tmp"))


def test_production_text_strokes_limit_expansion_toward_neighbors():
    from annotation_build import item_strokes

    def token(identifier, left, right):
        return {"token_id": identifier, "char": identifier,
                "polygon": [[left, 100], [right, 100], [right, 130], [left, 130]]}
    middle = token("mid", 100, 200)
    layout = {"layout_revision": 1, "lines": [{"line_id": "l", "tokens": [
        token("left", 0, 80), middle, token("right", 220, 300),
    ]}]}
    item = SimpleNamespace(
        target=SimpleNamespace(kind="text", path_strokes=(), path_points=(), token_ids=("mid",), layout_revision=1),
        style=SimpleNamespace(type="ellipse", width=5, padding=8, seed=1))
    points = item_strokes(item, layout)[0]["points"]
    assert min(point[0] for point in points) >= 86
    assert max(point[0] for point in points) <= 214
    layout["lines"][0]["tokens"] = [middle]
    unconstrained = item_strokes(item, layout)[0]["points"]
    assert max(point[0] for point in unconstrained) > 214
