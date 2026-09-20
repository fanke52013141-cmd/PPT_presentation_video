"""DocLayout-YOLO 集成测试：解析 / 后处理 / 融合 / 向后兼容回退。"""

from __future__ import annotations

import types
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

import ai_mask_doclayout
from ai_mask_doclayout import (
    DocLayoutDetector,
    MODEL_COORDINATE_FORMAT,
    _class_aware_nms,
    _parse_predictions,
    _suppress_cross_class_duplicates,
)
import ai_mask_component_detection as cdet
import ai_mask_engine


@pytest.fixture(autouse=True)
def _clear_doclayout_caches():
    """Sessions, boxes and breakers are process-wide, so each case starts clean.

    Every fake-``onnxruntime`` test uses the same ``/fake/model.onnx`` path; a
    session cached by the previous case would answer with the previous stub.
    """
    ai_mask_doclayout.reset_doclayout_caches()
    yield
    ai_mask_doclayout.reset_doclayout_caches()


def test_normalize_settings_has_doclayout_defaults() -> None:
    settings = ai_mask_engine.normalize_settings({})
    assert settings["doclayout_enabled"] is True
    assert settings["doclayout_model_path"] == ""
    assert settings["doclayout_conf_threshold"] == 0.35
    assert settings["doclayout_input_size"] == 1024
    assert settings["doclayout_iou_threshold"] == 0.45
    assert settings["doclayout_min_area_ratio"] == 0.002
    # 显式传入时生效
    enabled = ai_mask_engine.normalize_settings(
        {"doclayout_enabled": "true", "doclayout_model_path": "  model.onnx  "}
    )
    assert enabled["doclayout_enabled"] is True
    assert enabled["doclayout_model_path"] == "model.onnx"


def test_parse_predictions_xyxy_absolute() -> None:
    # [1, N, 6]，xyxy 绝对坐标，scale=1 pad=0（原图即 640 画布）
    pred = np.array([[
        [100.0, 200.0, 300.0, 400.0, 0.9, 1.0],
    ]], dtype=np.float32)
    boxes = _parse_predictions(pred, 1.0, 0, 0, 640, 640, 640)
    assert len(boxes) == 1
    assert boxes[0]["x1"] == 100.0
    assert boxes[0]["x2"] == 300.0
    assert boxes[0]["y1"] == 200.0
    assert boxes[0]["y2"] == 400.0
    assert boxes[0]["confidence"] == pytest.approx(0.9, abs=1e-6)
    assert boxes[0]["class_id"] == 1


def test_parse_predictions_xywh_normalized_transposed() -> None:
    # [1, 6, N]，xywh 归一化坐标（相对 640）
    pred = np.array([[
        [0.25, 0.5],
        [0.50, 0.5],
        [0.50, 0.2],
        [0.20, 0.4],
        [0.95, 0.8],
        [1.00, 3.00],
    ]], dtype=np.float32)
    boxes = _parse_predictions(pred, 1.0, 0, 0, 640, 640, 640)
    assert len(boxes) == 2
    first = next(box for box in boxes if box["class_id"] == 1)
    # cx=0.25*640=160, cy=0.5*640=320, w=0.5*640=320, h=0.2*640=128
    assert abs(first["x1"] - 0.0) < 1e-3
    assert abs(first["x2"] - 320.0) < 1e-3
    assert abs(first["y1"] - 256.0) < 1e-3
    assert abs(first["y2"] - 384.0) < 1e-3
    second = next(box for box in boxes if box["class_id"] == 3)
    assert second["confidence"] == pytest.approx(0.8, abs=1e-6)


def test_class_aware_nms_keeps_highest_confidence_per_class() -> None:
    boxes = [
        {"x1": 10, "y1": 10, "x2": 110, "y2": 110, "confidence": 0.6, "class_id": 1},
        {"x1": 12, "y1": 12, "x2": 112, "y2": 112, "confidence": 0.9, "class_id": 1},
    ]
    kept = _class_aware_nms(boxes, 0.45)
    assert len(kept) == 1
    assert kept[0]["confidence"] == 0.9


def test_class_aware_nms_does_not_suppress_across_classes() -> None:
    # A text box and a figure box on the same region are two honest answers;
    # the cross-class pass, not this one, decides what to keep.
    boxes = [
        {"x1": 10, "y1": 10, "x2": 110, "y2": 110, "confidence": 0.6, "class_id": 1},
        {"x1": 12, "y1": 12, "x2": 112, "y2": 112, "confidence": 0.9, "class_id": 3},
    ]
    assert len(_class_aware_nms(boxes, 0.45)) == 2


def test_class_aware_nms_is_stable_for_equal_confidence() -> None:
    first = {"x1": 10, "y1": 10, "x2": 110, "y2": 110, "confidence": 0.8, "class_id": 1}
    second = {"x1": 11, "y1": 10, "x2": 111, "y2": 110, "confidence": 0.8, "class_id": 1}
    forward = _class_aware_nms([first, second], 0.45)
    backward = _class_aware_nms([second, first], 0.45)
    assert [box["x1"] for box in forward] == [box["x1"] for box in backward]


def test_cross_class_duplicates_keep_the_confident_box() -> None:
    boxes = [
        {"x1": 10, "y1": 10, "x2": 110, "y2": 110, "confidence": 0.7, "class_id": 1},
        {"x1": 12, "y1": 12, "x2": 112, "y2": 112, "confidence": 0.95, "class_id": 3},
    ]
    kept = _suppress_cross_class_duplicates(boxes, 0.5)
    assert len(kept) == 1
    assert kept[0]["class_id"] == 3


def test_cross_class_duplicates_preserve_a_nested_caption() -> None:
    # A caption fully inside a figure is hierarchy, not a duplicate rectangle.
    figure = {"x1": 0, "y1": 0, "x2": 600, "y2": 400, "confidence": 0.5, "class_id": 3}
    caption = {"x1": 40, "y1": 340, "x2": 560, "y2": 390, "confidence": 0.9, "class_id": 4}
    kept = _suppress_cross_class_duplicates([figure, caption], 0.45)
    assert [box["class_id"] for box in kept] == [4, 3]


def test_declared_xyxy_format_does_not_guess_from_coordinates() -> None:
    # cx=100 with w=900 is a legal xywh box; the old size comparison misread it
    # as xyxy and produced a 800-wide box shifted right by half its width.
    pred = np.array([[[100.0, 200.0, 900.0, 300.0, 0.9, 1.0]]], dtype=np.float32)
    guessed = _parse_predictions(pred, 1.0, 0, 0, 1024, 1024, 1024)
    declared = _parse_predictions(
        pred, 1.0, 0, 0, 1024, 1024, 1024, coordinate_format="xywh"
    )
    assert guessed[0]["x2"] == 900.0
    assert declared[0]["x1"] == 0.0  # -350 clipped to the canvas edge
    assert declared[0]["x2"] == 550.0


def test_parsed_boxes_are_clipped_to_the_canvas() -> None:
    pred = np.array(
        [[[900.0, 900.0, 1300.0, 1300.0, 0.9, 1.0]]], dtype=np.float32
    )
    boxes = _parse_predictions(
        pred, 1.0, 0, 0, 1024, 640, 480, coordinate_format="xyxy"
    )
    assert boxes == []  # entirely outside the original canvas after clipping
    partial = _parse_predictions(
        np.array([[[600.0, 400.0, 700.0, 900.0, 0.9, 1.0]]], dtype=np.float32),
        1.0, 0, 0, 1024, 640, 480, coordinate_format="xyxy",
    )
    assert partial[0]["x2"] == 640.0
    assert partial[0]["y2"] == 480.0


def test_shipped_model_output_format_is_declared_not_guessed() -> None:
    assert MODEL_COORDINATE_FORMAT == "xyxy"
    detector = DocLayoutDetector("", conf_threshold=0.35)
    assert detector.coordinate_format == "xyxy"
    assert detector.coordinate_normalized is False


def test_detector_unavailable_without_model(monkeypatch) -> None:
    monkeypatch.setattr(
        DocLayoutDetector, "_discover_default_model", staticmethod(lambda: "")
    )
    detector = DocLayoutDetector("", conf_threshold=0.35)
    assert detector.available() is False
    assert detector.detect(Image.new("RGB", (100, 100), "white")) == []


def _status_detector(monkeypatch, *, session_factory, model_path: str = "/fake/model.onnx") -> DocLayoutDetector:
    """Build a detector over a fake ORT whose session creation is controlled.

    Pass a distinct ``model_path`` per stub: the session cache is keyed by the
    model, so two stubs under one path would share whichever session came first.
    """
    monkeypatch.setattr(ai_mask_doclayout.os.path, "exists", lambda _p: True)
    monkeypatch.setattr(ai_mask_doclayout, "onnxruntime", types.SimpleNamespace(
        get_available_providers=lambda: ["CPUExecutionProvider"],
        SessionOptions=lambda: types.SimpleNamespace(enable_cpu_mem_arena=True),
        InferenceSession=session_factory,
    ))
    return DocLayoutDetector(model_path)


def test_status_reports_missing_dependency(monkeypatch) -> None:
    monkeypatch.setattr(ai_mask_doclayout, "onnxruntime", None)
    detector = DocLayoutDetector("/fake/model.onnx")
    outcome = detector.detect_with_status(Image.new("RGB", (100, 100), "white"))
    assert outcome["status"] == "missing_dependency"
    assert outcome["boxes"] == []
    assert outcome["available"] is False
    assert "onnxruntime" in outcome["fallback_reason"]
    assert set(outcome["elapsed_ms"]) == {"layout_load", "layout_infer"}


def test_status_reports_missing_model(monkeypatch) -> None:
    monkeypatch.setattr(ai_mask_doclayout, "onnxruntime", types.SimpleNamespace(
        get_available_providers=lambda: ["CPUExecutionProvider"],
        SessionOptions=lambda: types.SimpleNamespace(enable_cpu_mem_arena=True),
        InferenceSession=lambda *_a, **_k: None,
    ))
    detector = DocLayoutDetector("/nonexistent/doclayout.onnx")
    outcome = detector.detect_with_status(Image.new("RGB", (100, 100), "white"))
    assert outcome["status"] == "missing_model"
    assert outcome["boxes"] == []
    assert "模型文件不存在" in outcome["fallback_reason"]


def test_status_reports_session_init_failure_without_retrying(monkeypatch) -> None:
    calls = {"count": 0}

    def failing_session(*_args, **_kwargs):
        calls["count"] += 1
        raise RuntimeError("could not allocate CUDA arena")

    first = _status_detector(monkeypatch, session_factory=failing_session)
    outcome = first.detect_with_status(Image.new("RGB", (100, 100), "white"))
    assert outcome["status"] == "session_init_failed"
    assert outcome["error_type"] == "RuntimeError"
    assert outcome["actual_providers"] == []
    assert calls["count"] == 1

    # A later page builds a fresh detector; the recorded failure must be
    # replayed instead of paying for the same broken initialization again.
    second = _status_detector(monkeypatch, session_factory=failing_session)
    replayed = second.detect_with_status(Image.new("RGB", (100, 100), "white"))
    assert replayed["status"] == "session_init_failed"
    assert "CUDA" in replayed["fallback_reason"]
    assert calls["count"] == 1

    ai_mask_doclayout.reset_doclayout_caches()
    third = _status_detector(monkeypatch, session_factory=failing_session)
    assert third.detect_with_status(Image.new("RGB", (100, 100), "white"))["status"] == "session_init_failed"
    assert calls["count"] == 2


def test_status_reports_inference_failure(monkeypatch) -> None:
    def session_factory(*_args, **_kwargs):
        return types.SimpleNamespace(
            get_inputs=lambda: [types.SimpleNamespace(name="images")],
            get_outputs=lambda: [types.SimpleNamespace(name="output0")],
            get_providers=lambda: ["CPUExecutionProvider"],
            run=lambda *_a, **_k: (_ for _ in ()).throw(ValueError("bad output shape")),
        )

    detector = _status_detector(monkeypatch, session_factory=session_factory)
    outcome = detector.detect_with_status(Image.new("RGB", (640, 640), "white"))
    assert outcome["status"] == "inference_failed"
    assert outcome["error_type"] == "ValueError"
    assert outcome["boxes"] == []
    assert outcome["available"] is True
    assert outcome["elapsed_ms"]["layout_infer"] >= 0.0


def test_status_reports_no_boxes_only_for_an_empty_detection(monkeypatch) -> None:
    def session_with(pred):
        def session_factory(*_args, **_kwargs):
            return types.SimpleNamespace(
                get_inputs=lambda: [types.SimpleNamespace(name="images")],
                get_outputs=lambda: [types.SimpleNamespace(name="output0")],
                get_providers=lambda: ["CPUExecutionProvider"],
                run=lambda *_a, **_k: [pred],
            )
        return session_factory

    image = Image.new("RGB", (640, 640), "white")
    outcome = _status_detector(
        monkeypatch,
        model_path="/fake/empty.onnx",
        session_factory=session_with(np.zeros((1, 0, 6), dtype=np.float32)),
    ).detect_with_status(image)
    assert outcome["status"] == "no_boxes"
    assert outcome["raw_box_count"] == 0
    assert outcome["box_count"] == 0
    assert outcome["boxes"] == []

    # Rows that are all NaN are dropped as unusable predictions; an empty answer
    # is still a legitimate "nothing detected" for this page.
    garbage = _status_detector(
        monkeypatch,
        model_path="/fake/nan.onnx",
        session_factory=session_with(np.array([[[float("nan")] * 6]], dtype=np.float32)),
    ).detect_with_status(image)
    assert garbage["status"] == "inference_failed"
    assert garbage["error_type"] == "LayoutOutputError"
    assert "no finite value" in garbage["fallback_reason"]
    assert garbage["boxes"] == []

    wrong_columns = _status_detector(
        monkeypatch,
        model_path="/fake/short.onnx",
        session_factory=session_with(np.zeros((1, 40, 5), dtype=np.float32)),
    ).detect_with_status(image)
    assert wrong_columns["status"] == "inference_failed"
    assert "expected 6" in wrong_columns["fallback_reason"]


def test_status_reports_ok_with_providers_and_elapsed(monkeypatch) -> None:
    def session_factory(*_args, **_kwargs):
        return types.SimpleNamespace(
            get_inputs=lambda: [types.SimpleNamespace(name="images")],
            get_outputs=lambda: [types.SimpleNamespace(name="output0")],
            get_providers=lambda: ["CPUExecutionProvider"],
            run=lambda *_a, **_k: [np.array([[
                [100.0, 100.0, 500.0, 500.0, 0.9, 1.0],
            ]], dtype=np.float32)],
        )

    detector = _status_detector(monkeypatch, session_factory=session_factory)
    image = Image.new("RGB", (1000, 800), "white")
    outcome = detector.detect_with_status(image)
    assert outcome["status"] == "ok"
    assert outcome["box_count"] == len(outcome["boxes"]) == 1
    assert outcome["requested_providers"] == ["CPUExecutionProvider"]
    assert outcome["actual_providers"] == ["CPUExecutionProvider"]
    assert outcome["load_error"] == ""
    assert outcome["model_path"] == "/fake/model.onnx"
    assert detector.detect(image) == outcome["boxes"]


def test_detector_unavailable_without_onnxruntime(monkeypatch) -> None:
    monkeypatch.setattr(ai_mask_doclayout, "onnxruntime", None)
    detector = DocLayoutDetector("/nonexistent/model.onnx")
    assert detector.available() is False
    assert "onnxruntime" in detector.load_error()


def test_detect_filters_classes_and_small_boxes(monkeypatch) -> None:
    monkeypatch.setattr(ai_mask_doclayout.os.path, "exists", lambda _p: True)
    monkeypatch.setattr(ai_mask_doclayout, "onnxruntime", types.SimpleNamespace(
        get_available_providers=lambda: ["CPUExecutionProvider"],
        SessionOptions=lambda: types.SimpleNamespace(enable_cpu_mem_arena=True),
        InferenceSession=lambda *_args, **_kwargs: types.SimpleNamespace(
            get_inputs=lambda: [types.SimpleNamespace(name="images")],
            get_outputs=lambda: [types.SimpleNamespace(name="output0")],
            run=lambda _names, _feed: [np.array([[
                [100.0, 100.0, 500.0, 500.0, 0.9, 1.0],   # plain text（保留）
                [200.0, 200.0, 400.0, 400.0, 0.8, 2.0],   # abandon（过滤）
                [600.0, 100.0, 900.0, 300.0, 0.85, 3.0],  # figure（保留）
                [50.0, 50.0, 60.0, 60.0, 0.9, 10.0],      # list 但面积过小（过滤）
            ]], dtype=np.float32)],
        ),
    ))
    detector = DocLayoutDetector("/fake/model.onnx", conf_threshold=0.35, min_area_ratio=0.002)
    image = Image.new("RGB", (1000, 800), "white")
    boxes = detector.detect(image)
    roles = {box["role"] for box in boxes}
    assert roles == {"text", "figure"}
    text_box = next(box for box in boxes if box["role"] == "text")
    assert text_box["class_id"] == 1
    assert text_box["box"]["x"] == 98  # letterbox 逆变换: (100-0)/1.024=97.656→98


def _fake_element(eid: str, x: int, y: int, w: int, h: int, width: int, height: int) -> dict:
    raw = {"x": x, "y": y, "w": w, "h": h}
    runs = [[y + row, x, x + w] for row in range(h)]
    return {
        "element_id": eid,
        "bbox": dict(raw),
        "raw_bbox": dict(raw),
        "center": {"x": x + w / 2, "y": y + h / 2},
        "area": w * h,
        "mask_pixel_count": w * h,
        "position": "center_middle",
        "ocr_text": "",
        "mask_rle": {"encoding": "row_runs_v1", "width": width, "height": height, "runs": runs},
    }


def test_apply_layout_binding_groups_components() -> None:
    width, height = 1000, 800
    settings = ai_mask_engine.normalize_settings({"component_padding_px": 4, "min_element_area": 120})
    candidates = [
        _fake_element("el_a", 200, 300, 80, 30, width, height),
        _fake_element("el_b", 300, 305, 70, 28, width, height),
        _fake_element("el_c", 600, 400, 90, 40, width, height),
    ]
    layout_boxes = [
        {"class_id": 1, "class_name": "plain text", "role": "text", "confidence": 0.9,
         "box": {"x": 180, "y": 290, "w": 300, "h": 60}},
        {"class_id": 3, "class_name": "figure", "role": "figure", "confidence": 0.85,
         "box": {"x": 580, "y": 390, "w": 120, "h": 60}},
    ]
    merged, residual = cdet._apply_layout_binding(candidates, [], layout_boxes, width, height, settings)
    # el_a 与 el_b 同框合并为 1 个 layout 元素；el_c 命中 figure 框合并为 1 个
    assert len(merged) == 2
    layout_elements = [e for e in merged if e.get("detection_source") == "doclayout"]
    assert len(layout_elements) == 2
    text_elem = next(e for e in layout_elements if e["layout_role"] == "text")
    assert text_elem["layout_member_count"] == 2
    assert text_elem["area"] == 80 * 30 + 70 * 28
    assert text_elem["raw_bbox"]["w"] == 170  # 200..370
    assert len(residual) == 0


def test_apply_layout_binding_keeps_unbound_components() -> None:
    width, height = 1000, 800
    settings = ai_mask_engine.normalize_settings({})
    candidates = [
        _fake_element("el_a", 100, 100, 60, 30, width, height),
        _fake_element("el_b", 700, 700, 50, 30, width, height),
    ]
    layout_boxes = [
        {"class_id": 1, "class_name": "plain text", "role": "text", "confidence": 0.9,
         "box": {"x": 0, "y": 0, "w": 300, "h": 200}},
    ]
    merged, _ = cdet._apply_layout_binding(candidates, [], layout_boxes, width, height, settings)
    layout_elements = [e for e in merged if e.get("detection_source") == "doclayout"]
    assert len(layout_elements) == 1
    assert len(merged) == 2  # 1 个聚合 + 1 个独立 el_b
    independent = next(e for e in merged if e.get("element_id") == "el_b")
    assert independent.get("detection_source") is None


def test_apply_layout_binding_small_group_stays_individual() -> None:
    width, height = 1000, 800
    settings = ai_mask_engine.normalize_settings({"min_element_area": 10000})
    candidates = [
        _fake_element("el_a", 200, 300, 20, 10, width, height),
        _fake_element("el_b", 230, 300, 20, 10, width, height),
    ]
    layout_boxes = [
        {"class_id": 1, "class_name": "plain text", "role": "text", "confidence": 0.9,
         "box": {"x": 180, "y": 290, "w": 200, "h": 40}},
    ]
    merged, _ = cdet._apply_layout_binding(candidates, [], layout_boxes, width, height, settings)
    # 聚合后面积(400) < min_element_area(10000) -> 保留原成员，不合并
    assert all(e.get("detection_source") is None for e in merged)
    assert len(merged) == 2


def test_detect_elements_fallback_without_model(tmp_path: Path) -> None:
    slide_dir = tmp_path / "slide_001"
    slide_dir.mkdir(parents=True)
    image_path = slide_dir / "visual_draft.png"
    image = Image.new("RGB", (400, 300), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((50, 50, 150, 120), fill="black")
    draw.rectangle((200, 150, 360, 260), fill=(20, 30, 40))
    image.save(image_path)

    settings = ai_mask_engine.normalize_settings({})  # doclayout 默认启用（模型/onnxruntime 不可用时自动降级为纯 flood-fill）
    payload = cdet.detect_elements(image_path, slide_dir, settings)
    assert payload["canvas"]["width"] == 400
    assert payload["canvas"]["height"] == 300
    assert len(payload["elements"]) >= 1
    detection = payload.get("layout_detection", {})
    assert detection.get("enabled") is False
    assert detection.get("available") is False
    assert detection.get("box_count") == 0
    # 无模型时输出结构保持向后兼容
    for element in payload["elements"]:
        assert "mask_rle" in element
        assert "bbox" in element


from PIL import ImageDraw  # noqa: E402
