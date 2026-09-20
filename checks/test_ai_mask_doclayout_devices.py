"""W5: DocLayout device probing, session reuse and CPU fallback.

These cases run against a fake ``onnxruntime``: a provider that is *listed* is
not a provider that can serve the model, and the only honest difference between
them is what happens when a session is created and a tensor is fed.  Every
assertion below therefore checks the reported device evidence, not a guess.
"""

from __future__ import annotations

import logging
import types
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

import ai_mask_doclayout
import ai_mask_engine
from ai_mask_doclayout import (
    CPU_PROVIDER,
    CUDA_PROVIDER,
    DocLayoutDetector,
    available_device_modes,
    normalize_device_mode,
)

BOX = np.array([[[100.0, 100.0, 500.0, 500.0, 0.9, 1.0]]], dtype=np.float32)
BOTH = [CUDA_PROVIDER, CPU_PROVIDER]


class _Logger:
    logger = logging.getLogger("ai-mask-doclayout-devices-test")


class _SessionOptions:
    """Mirror of ORT's SessionOptions: the arena is on until we say otherwise."""

    def __init__(self) -> None:
        self.enable_cpu_mem_arena = True


@pytest.fixture(autouse=True)
def _clear_doclayout_caches():
    ai_mask_doclayout.reset_doclayout_caches()
    yield
    ai_mask_doclayout.reset_doclayout_caches()


def _page(tmp_path: Path, name: str = "visual_draft.png") -> Path:
    path = tmp_path / name
    Image.new("RGB", (1000, 800), "white").save(path)
    return path


def _session(
    providers: list[str],
    *,
    bound: list[str] | None = None,
    pred=None,
    run_error: BaseException | None = None,
    probes: list[np.ndarray] | None = None,
) -> types.SimpleNamespace:
    """A session that reports the providers it was *created* with by default."""

    def run(_names, feed):
        if probes is not None:
            probes.append(next(iter(feed.values())))
        if run_error is not None:
            raise run_error
        return [pred if pred is not None else np.zeros((1, 0, 6), dtype=np.float32)]

    return types.SimpleNamespace(
        get_inputs=lambda: [types.SimpleNamespace(name="images", shape=[1, 3, 1024, 1024])],
        get_outputs=lambda: [types.SimpleNamespace(name="output0")],
        get_providers=lambda: list(bound if bound is not None else providers),
        get_modelmeta=lambda: types.SimpleNamespace(custom_metadata_map={}),
        run=run,
    )


def _fake_ort(
    monkeypatch,
    *,
    available: list[str],
    session_factory,
) -> list[list[str]]:
    """Install a fake ORT and record every provider list it was asked for."""
    creations: list[list[str]] = []

    def build(path, **kwargs):
        creations.append(list(kwargs["providers"]))
        return session_factory(kwargs["providers"])

    monkeypatch.setattr(ai_mask_doclayout.os.path, "exists", lambda _p: True)
    monkeypatch.setattr(ai_mask_doclayout, "onnxruntime", types.SimpleNamespace(
        get_available_providers=lambda: list(available),
        SessionOptions=_SessionOptions,
        InferenceSession=build,
    ))
    return creations


def test_device_mode_is_normalised_and_reports_the_real_capability(monkeypatch) -> None:
    assert normalize_device_mode("  CUDA ") == "cuda"
    assert normalize_device_mode("cpu") == "cpu"
    assert normalize_device_mode("") == "auto"
    assert normalize_device_mode("openvino") == "auto"
    assert ai_mask_engine.normalize_settings({})["doclayout_device_mode"] == "auto"
    assert ai_mask_engine.normalize_settings(
        {"doclayout_device_mode": "CUDA"}
    )["doclayout_device_mode"] == "cuda"

    monkeypatch.setattr(ai_mask_doclayout, "onnxruntime", types.SimpleNamespace(
        get_available_providers=lambda: [CPU_PROVIDER],
        InferenceSession=lambda *_a, **_k: None,
    ))
    report = available_device_modes()
    assert report["available_providers"] == [CPU_PROVIDER]
    assert report["onnxruntime_installed"] is True
    assert report["cuda_available"] is False
    monkeypatch.setattr(ai_mask_doclayout, "onnxruntime", None)
    assert available_device_modes() == {
        "onnxruntime_installed": False,
        "available_providers": [],
        "cuda_available": False,
    }


def test_device_mode_cpu_bypasses_gpu_without_probing_it(monkeypatch) -> None:
    creations = _fake_ort(
        monkeypatch, available=BOTH, session_factory=lambda p: _session(p, pred=BOX)
    )
    outcome = DocLayoutDetector("/fake/cpu.onnx", device_mode="cpu").detect_with_status(
        Image.new("RGB", (1000, 800), "white")
    )
    assert creations == [[CPU_PROVIDER]]
    assert outcome["device_mode"] == "cpu"
    assert outcome["requested_providers"] == [CPU_PROVIDER]
    assert outcome["actual_providers"] == [CPU_PROVIDER]
    assert outcome["device_reason"] == "device_mode=cpu"
    assert outcome["status"] == "ok"
    assert outcome["box_count"] == 1


def test_listed_cuda_provider_must_bind_or_cpu_serves_the_page(monkeypatch) -> None:
    # This build advertises CUDA but silently puts the graph on CPU; only the
    # bound provider list says so, so the record must not claim a GPU run.
    def session_factory(providers):
        wants_gpu = providers[0] == CUDA_PROVIDER
        return _session(
            providers,
            bound=[CPU_PROVIDER] if wants_gpu else list(providers),
            pred=BOX,
        )

    creations = _fake_ort(monkeypatch, available=BOTH, session_factory=session_factory)
    image = Image.new("RGB", (1000, 800), "white")
    first = DocLayoutDetector("/fake/binding.onnx").detect_with_status(image)
    assert first["status"] == "ok"
    assert first["box_count"] == 1
    # Both the request and the answer describe the session that served the page;
    # the discarded GPU attempt shows up in device_reason, not as a provider.
    assert first["requested_providers"] == [CPU_PROVIDER]
    assert first["actual_providers"] == [CPU_PROVIDER]
    assert first["device_reason"] == "cuda_provider_not_bound"
    assert first["session_reused"] is False

    # A broken GPU must not be rediscovered on every page of the same run.
    second = DocLayoutDetector("/fake/binding.onnx").detect_with_status(image)
    assert second["requested_providers"] == [CPU_PROVIDER]
    assert second["device_reason"] == "cuda_provider_not_bound"
    assert second["session_reused"] is True
    assert creations == [BOTH, [CPU_PROVIDER]]


def test_cuda_out_of_memory_falls_back_to_cpu_without_losing_boxes(monkeypatch) -> None:
    def session_factory(providers):
        wants_gpu = providers[0] == CUDA_PROVIDER
        return _session(
            providers,
            run_error=MemoryError("CUDA out of memory trying to allocate 2.1GiB")
            if wants_gpu
            else None,
            pred=BOX,
        )

    creations = _fake_ort(monkeypatch, available=BOTH, session_factory=session_factory)
    image = Image.new("RGB", (1000, 800), "white")
    outcome = DocLayoutDetector("/fake/oom.onnx").detect_with_status(image)
    assert outcome["status"] == "ok"
    assert outcome["box_count"] == 1
    assert outcome["actual_providers"] == [CPU_PROVIDER]
    assert outcome["device_reason"].startswith("cuda_smoke_failed:MemoryError")
    # The next page goes straight to CPU at full image quality.
    DocLayoutDetector("/fake/oom.onnx").detect_with_status(image)
    assert creations == [BOTH, [CPU_PROVIDER]]


def test_smoke_probe_is_a_tiny_zero_tensor_not_a_detection(monkeypatch) -> None:
    probes: list[np.ndarray] = []
    monkeypatch.setattr(ai_mask_doclayout.os.path, "exists", lambda _p: True)
    doc = DocLayoutDetector("/fake/probe.onnx")
    session = _session([CUDA_PROVIDER], pred=BOX, probes=probes)
    assert doc._verify_gpu_session(session) == ""
    assert probes[0].shape == (1, 3, 64, 64)
    assert not probes[0].any()


def test_verified_cuda_session_reports_the_gpu_as_the_actual_device(monkeypatch) -> None:
    creations = _fake_ort(
        monkeypatch, available=BOTH, session_factory=lambda p: _session(p, pred=BOX)
    )
    outcome = DocLayoutDetector("/fake/gpu.onnx").detect_with_status(
        Image.new("RGB", (1000, 800), "white")
    )
    assert creations == [BOTH]
    assert outcome["actual_providers"] == BOTH
    assert outcome["device_reason"] == ""
    assert outcome["status"] == "ok"


def test_every_provider_failing_is_a_session_init_failure(monkeypatch) -> None:
    def session_factory(_providers):
        raise RuntimeError("could not allocate arena")

    creations = _fake_ort(monkeypatch, available=[CPU_PROVIDER], session_factory=session_factory)
    outcome = DocLayoutDetector("/fake/dead.onnx").detect_with_status(
        Image.new("RGB", (100, 100), "white")
    )
    assert creations == [[CPU_PROVIDER]]
    assert outcome["status"] == "session_init_failed"
    assert outcome["error_type"] == "RuntimeError"
    assert outcome["actual_providers"] == []
    assert outcome["boxes"] == []
    assert outcome["available"] is False


def test_session_is_reused_across_pages_instead_of_reloaded(monkeypatch) -> None:
    creations = _fake_ort(
        monkeypatch, available=[CPU_PROVIDER], session_factory=lambda p: _session(p, pred=BOX)
    )
    image = Image.new("RGB", (1000, 800), "white")
    first = DocLayoutDetector("/fake/reuse.onnx").detect_with_status(image, "a" * 64)
    second = DocLayoutDetector("/fake/reuse.onnx").detect_with_status(image, "b" * 64)
    assert first["session_reused"] is False
    assert second["session_reused"] is True
    assert second["layout_cache_hit"] is False
    assert len(creations) == 1
    assert second["boxes"] == first["boxes"]
    # A different model keeps its own session; sharing one would be a lie.
    DocLayoutDetector("/fake/other.onnx").detect_with_status(image, "a" * 64)
    assert len(creations) == 2


def test_cuda_session_creation_failure_is_not_retried_on_later_pages(monkeypatch) -> None:
    def session_factory(providers):
        if providers[0] == CUDA_PROVIDER:
            raise RuntimeError("failed creating CUDA session for this build")
        return _session(providers, pred=BOX)

    creations = _fake_ort(monkeypatch, available=BOTH, session_factory=session_factory)
    image = Image.new("RGB", (1000, 800), "white")
    first = DocLayoutDetector("/fake/create.onnx").detect_with_status(image)
    assert first["status"] == "ok"
    assert first["actual_providers"] == [CPU_PROVIDER]
    assert first["device_reason"] == "cuda_create_failed:RuntimeError"

    second = DocLayoutDetector("/fake/create.onnx").detect_with_status(image)
    assert second["requested_providers"] == [CPU_PROVIDER]
    assert second["box_count"] == 1
    assert creations == [BOTH, [CPU_PROVIDER]]


def test_box_cache_is_isolated_by_the_device_that_produced_it(monkeypatch) -> None:
    def session_factory(providers):
        wants_gpu = providers[0] == CUDA_PROVIDER
        return _session(
            providers,
            bound=list(providers) if wants_gpu else [CPU_PROVIDER],
            pred=BOX,
        )

    _fake_ort(monkeypatch, available=BOTH, session_factory=session_factory)
    image = Image.new("RGB", (1000, 800), "white")
    digest = "f" * 64
    gpu = DocLayoutDetector("/fake/device.onnx", device_mode="cuda").detect_with_status(
        image, digest
    )
    assert gpu["actual_providers"] == BOTH
    assert gpu["layout_cache_hit"] is False
    # The same page answered by a different executor must not reuse GPU boxes.
    cpu = DocLayoutDetector("/fake/device.onnx", device_mode="cpu").detect_with_status(
        image, digest
    )
    assert cpu["actual_providers"] == [CPU_PROVIDER]
    assert cpu["layout_cache_hit"] is False
    again = DocLayoutDetector("/fake/device.onnx", device_mode="cuda").detect_with_status(
        image, digest
    )
    assert again["layout_cache_hit"] is True
    assert again["session_reused"] is True


def test_reused_session_does_not_reserve_a_cpu_memory_arena(monkeypatch) -> None:
    # A session now outlives the page that created it, so it must not keep its
    # reserved arena resident while the flood-fill stage works on the same page.
    made: list[_SessionOptions] = []

    def build(_path, **kwargs):
        made.append(kwargs["sess_options"])
        return _session(kwargs["providers"], pred=BOX)

    monkeypatch.setattr(ai_mask_doclayout.os.path, "exists", lambda _p: True)
    monkeypatch.setattr(ai_mask_doclayout, "onnxruntime", types.SimpleNamespace(
        get_available_providers=lambda: [CPU_PROVIDER],
        SessionOptions=_SessionOptions,
        InferenceSession=build,
    ))
    DocLayoutDetector("/fake/arena.onnx").detect_with_status(
        Image.new("RGB", (1000, 800), "white")
    )
    assert len(made) == 1
    assert made[0].enable_cpu_mem_arena is False


def test_failed_cuda_session_is_not_left_in_the_cache(monkeypatch) -> None:
    def session_factory(providers):
        wants_gpu = providers[0] == CUDA_PROVIDER
        return _session(
            providers,
            bound=[CPU_PROVIDER] if wants_gpu else list(providers),
            pred=BOX,
        )

    _fake_ort(monkeypatch, available=BOTH, session_factory=session_factory)
    image = Image.new("RGB", (1000, 800), "white")
    DocLayoutDetector("/fake/evict.onnx").detect_with_status(image)
    keys = list(ai_mask_doclayout._SESSION_CACHE)
    assert [key for key in keys if CUDA_PROVIDER in key] == []
    assert len(keys) == 1


def test_box_cache_hit_skips_inference_and_is_keyed_by_page_and_threshold(monkeypatch) -> None:
    runs: list[int] = []

    def session_factory(providers):
        def run(_names, feed):
            runs.append(1)
            return [BOX]

        session = _session(providers, pred=BOX)
        session.run = run  # type: ignore[attr-defined]
        return session

    _fake_ort(monkeypatch, available=[CPU_PROVIDER], session_factory=session_factory)
    image = Image.new("RGB", (1000, 800), "white")
    digest = "c" * 64
    detector = DocLayoutDetector("/fake/boxes.onnx")
    first = detector.detect_with_status(image, digest)
    hit = detector.detect_with_status(image, digest)
    assert first["layout_cache_hit"] is False
    assert hit["layout_cache_hit"] is True
    assert hit["boxes"] == first["boxes"]
    assert hit["status"] == "ok"
    assert len(runs) == 1

    # Another page, another image: the cache may not answer for it.
    assert detector.detect_with_status(image, "d" * 64)["layout_cache_hit"] is False
    # No page digest at all means no identity, so nothing is read or written.
    assert detector.detect_with_status(image)["layout_cache_hit"] is False
    # Boxes are threshold-bound; a stricter setting must recompute them.
    stricter = DocLayoutDetector("/fake/boxes.onnx", conf_threshold=0.95)
    assert stricter.detect_with_status(image, digest)["layout_cache_hit"] is False
    assert len(runs) == 4


def test_engine_reports_device_state_for_a_real_page(tmp_path: Path, monkeypatch) -> None:
    _fake_ort(
        monkeypatch,
        available=[CPU_PROVIDER],
        session_factory=lambda p: _session(p, pred=BOX),
    )
    capabilities = _Logger()
    settings = ai_mask_engine.normalize_settings(
        {"doclayout_enabled": True, "doclayout_model_path": "/fake/engine.onnx",
         "doclayout_device_mode": "cpu"}
    )
    page = _page(tmp_path)
    boxes, record = ai_mask_engine._detect_layout(capabilities, settings, page)
    assert record["device_mode"] == "cpu"
    assert record["actual_providers"] == [CPU_PROVIDER]
    assert record["layout_cache_hit"] is False
    assert record["session_reused"] is False
    assert boxes and record["box_count"] == 1

    _again, second = ai_mask_engine._detect_layout(capabilities, settings, page)
    assert second["layout_cache_hit"] is True
    assert second["session_reused"] is True
