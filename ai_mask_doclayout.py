"""DocLayout-YOLO (ONNX CPU) 版面检测桥接模块。

把开源 DocLayout-YOLO（OpenDataLab，YOLOv10 架构，DocLayNet AP50 93.4%）
作为“语义候选框”来源接入 AI Mask 标注：它对整页图片输出标题 / 正文 /
图片 / 表格 / 列表等版面区域的 bbox。上游 flood-fill 提供精确前景像素，
本模块提供“哪些组件应该聚合成一个语义元素”的分组边界，从而修复纯确定性
路径的两个经典缺陷：
  1. 形态学 closing 过度粘连导致的“多对象合并成一个大组件”；
  2. 嵌套 / 斜向 / 多栏布局下投影分割失败导致的“一个组件里塞进多个语义对象”。

设计契约（必须遵守）：
- 零硬依赖：onnxruntime 未安装或模型文件缺失时，detector.available() 返回
  False，上游流水线透明回退到纯 flood-fill 路径，不报错、不影响已有功能。
- 降级可诊断：透明回退不等于丢失信息。detect_with_status() 把“为什么没有版面
  框”区分成缺依赖 / 缺模型 / 会话初始化失败 / 推理异常 / 无框，并把会话加载与
  推理耗时分别计时；detect() 只是保留旧返回形态的薄封装。
- 本地失败不无限重试：会话初始化抛错后按模型路径进入进程内熔断，后续页面直接
  复用该诊断结果，不再重复昂贵的失败初始化。
- 确定性后处理：随仓模型按声明的 [x1, y1, x2, y2, score, class] 绝对坐标解析，
  未声明形态的其他模型才走 auto 猜测；再做类别白名单过滤 + 同类 NMS +
  跨类同区域去重 + 面积过滤，嵌套层级（父框含子框）不会被当成重复框删除。
"""

from __future__ import annotations

import ast
import hashlib
import os
from threading import Lock
import time
from typing import Any

import numpy as np
from PIL import Image

from ai_mask_contracts import (
    LAYOUT_STATUS_INFERENCE_FAILED,
    LAYOUT_STATUS_MISSING_DEPENDENCY,
    LAYOUT_STATUS_MISSING_MODEL,
    LAYOUT_STATUS_NO_BOXES,
    LAYOUT_STATUS_OK,
    LAYOUT_STATUS_SESSION_INIT_FAILED,
)

try:  # 可选依赖：未安装时整体降级为不可用
    import onnxruntime
except Exception:  # pragma: no cover - 依赖缺失分支
    onnxruntime = None  # type: ignore[assignment]


class LayoutOutputError(RuntimeError):
    """The model answered, but its output cannot be read as boxes.

    Kept apart from an empty detection list so a page with nothing on it and a
    page whose model contract broke never share one status.
    """


# 随仓模型是 Ultralytics YOLOv10-doclayout 导出：output0 为
# [1, 6, anchors]，列为 x1/y1/x2/y2/score/class，坐标在 letterbox 后的
# input_size 像素空间中（非 0-1 归一化）。声明它，避免用“坐标大小关系猜格式”
# 把一个合法的宽 xywh 框误读成 xyxy。
MODEL_COORDINATE_FORMAT = "xyxy"
MODEL_COORDINATE_NORMALIZED = False

# DocLayout-YOLO 官方类别（doclayout_yolo/utils/yolo_config.py），
# 仅作为无法从 ONNX metadata 读取类别名时的兜底。
DOCLAYOUT_CLASS_NAMES: tuple[str, ...] = (
    "title",            # 0
    "plain text",       # 1
    "abandon",          # 2  -> 忽略
    "figure",           # 3
    "figure caption",   # 4
    "table",            # 5
    "table caption",    # 6
    "table footnote",   # 7
    "isolate formula",  # 8  -> 忽略
    "formula caption",  # 9  -> 忽略
    "list",             # 10
)

# 类别名 -> PPT 视觉分组 role 白名单；abandon / 公式类噪声不在名单内会被忽略。
ROLE_BY_NAME: dict[str, str] = {
    "title": "title",
    "plain text": "text",
    "figure": "figure",
    "figure caption": "figure_caption",
    "table": "table",
    "table caption": "table_caption",
    "list": "list",
}



def _letterbox(
    image: Image.Image,
    size: int,
) -> tuple[np.ndarray, float, int, int]:
    """等比缩放 + 灰边填充到 size×size，返回 (CHW float 张量, scale, pad_x, pad_y)。"""
    width, height = image.size
    scale = size / max(width, height)
    new_width = max(1, round(width * scale))
    new_height = max(1, round(height * scale))
    resized = image.resize((new_width, new_height), Image.BILINEAR)
    canvas = Image.new("RGB", (size, size), (114, 114, 114))
    pad_x = (size - new_width) // 2
    pad_y = (size - new_height) // 2
    canvas.paste(resized, (pad_x, pad_y))
    array = np.asarray(canvas, dtype=np.float32).transpose(2, 0, 1)[None]  # (1,3,H,W)
    return array, scale, pad_x, pad_y


def _parse_predictions(
    pred: Any,
    scale: float,
    pad_x: int,
    pad_y: int,
    input_size: int,
    orig_width: int,
    orig_height: int,
    coordinate_format: str = "auto",
    normalized: bool = False,
) -> list[dict[str, Any]]:
    """把 ONNX 输出解析为原图坐标系下的检测框。

    ``coordinate_format`` declares the model's convention (``xyxy`` / ``xywh``);
    ``auto`` is the compatibility guess for an undeclared model.  An unusable
    output raises :class:`LayoutOutputError` so "no detections" and "the model
    answer cannot be read" stay distinguishable.
    """
    if pred is None:
        return []
    try:
        array = np.asarray(pred, dtype=np.float64)
    except Exception as exc:  # not even a numeric array
        raise LayoutOutputError(f"output is not numeric: {type(exc).__name__}") from exc
    if array.ndim == 3:
        array = array[0]
    if array.ndim != 2:
        raise LayoutOutputError(f"unusable output rank {array.ndim}")
    n, m = array.shape
    if n == 6 and m != 6:  # [6, N] -> [N, 6]
        array = array.T
        n, m = array.shape
    if m < 6:
        raise LayoutOutputError(f"output has {m} columns, expected 6")
    if n and not np.isfinite(array).any():
        raise LayoutOutputError("output holds no finite value")
    boxes: list[dict[str, Any]] = []
    for row in array:
        values = row[0:6]
        if not np.isfinite(values).all():
            continue
        a, b, c, d = values[0], values[1], values[2], values[3]
        confidence = float(values[4])
        class_id = int(round(float(values[5])))
        if confidence <= 0:
            continue
        fmt = coordinate_format
        undeclared = fmt == "auto"
        if undeclared:
            # Only a guess for an undeclared model: c>a and d>b holds for every
            # valid xyxy box, so a wide xywh box is exactly what this misreads.
            fmt = "xyxy" if (c > a and d > b) else "xywh"
        if fmt == "xywh":
            x1, y1, x2, y2 = a - c / 2, b - d / 2, a + c / 2, b + d / 2
        else:
            x1, y1, x2, y2 = a, b, c, d
        if normalized:
            x1 *= input_size
            y1 *= input_size
            x2 *= input_size
            y2 *= input_size
        elif undeclared and max(abs(x1), abs(y1), abs(x2), abs(y2)) <= 1.0 + 1e-6:
            # Undeclared model whose values still sit in 0-1 space.
            x1 *= input_size
            y1 *= input_size
            x2 *= input_size
            y2 *= input_size
        # 逆 letterbox：映射回原图坐标，并裁剪至画布
        x1 = min(max((x1 - pad_x) / scale, 0.0), float(orig_width))
        y1 = min(max((y1 - pad_y) / scale, 0.0), float(orig_height))
        x2 = min(max((x2 - pad_x) / scale, 0.0), float(orig_width))
        y2 = min(max((y2 - pad_y) / scale, 0.0), float(orig_height))
        if x2 <= x1 or y2 <= y1:
            continue
        boxes.append({
            "x1": float(x1),
            "y1": float(y1),
            "x2": float(x2),
            "y2": float(y2),
            "confidence": confidence,
            "class_id": class_id,
            "coordinate_format": fmt,
        })
    return boxes


def _box_matrix(boxes: list[dict[str, Any]]) -> np.ndarray:
    return np.array([
        [box["x1"], box["y1"], box["x2"], box["y2"], box["confidence"], box["class_id"]]
        for box in boxes
    ], dtype=np.float64)


def _box_areas(data: np.ndarray) -> np.ndarray:
    return np.maximum(0.0, data[:, 2] - data[:, 0]) * np.maximum(0.0, data[:, 3] - data[:, 1])


def _iou_batch(
    index: int,
    rest: np.ndarray,
    data: np.ndarray,
    areas: np.ndarray,
) -> np.ndarray:
    """IoU of one kept box against the remaining candidates."""
    x1, y1, x2, y2 = data[:, 0], data[:, 1], data[:, 2], data[:, 3]
    xx1 = np.maximum(x1[index], x1[rest])
    yy1 = np.maximum(y1[index], y1[rest])
    xx2 = np.minimum(x2[index], x2[rest])
    yy2 = np.minimum(y2[index], y2[rest])
    inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
    return inter / np.maximum(1e-6, areas[index] + areas[rest] - inter)


def _order_by_confidence(data: np.ndarray) -> np.ndarray:
    """Deterministic descending-confidence order with a geometry tie-break.

    ``np.lexsort`` takes the primary key last, so ``-score`` ascending already is
    confidence descending; reversing it again would rank the weakest box first.
    """
    keys = np.rec.fromarrays(
        [data[:, 4], data[:, 1], data[:, 0], data[:, 2], data[:, 3], data[:, 5]],
        names="score,y1,x1,x2,y2,class",
    )
    return np.lexsort((keys["x2"], keys["y2"], keys["x1"], keys["y1"], -keys["score"]))


def _class_aware_nms(boxes: list[dict[str, Any]], iou_threshold: float) -> list[dict[str, Any]]:
    """Suppress duplicate detections of the same class, never across classes.

    A layout model legitimately puts a ``text`` box and a ``figure`` box on the
    same region; suppressing across classes would delete one of them here, and
    the cross-class decision belongs to :func:`_suppress_cross_class_duplicates`.
    """
    if not boxes:
        return []
    data = _box_matrix(boxes)
    areas = _box_areas(data)
    order = [int(index) for index in _order_by_confidence(data)]
    kept: list[int] = []
    while order:
        index = order.pop(0)
        kept.append(index)
        if not order:
            break
        same_class = [i for i in order if data[i, 5] == data[index, 5]]
        if not same_class:
            continue
        candidates = np.array(same_class, dtype=np.int64)
        duplicate = _iou_batch(index, candidates, data, areas) > iou_threshold
        drop = {int(box_index) for box_index, is_duplicate in zip(same_class, duplicate) if is_duplicate}
        if drop:
            order = [i for i in order if i not in drop]
    return [boxes[index] for index in kept]


def _containment(child: dict[str, Any], parent: dict[str, Any]) -> float:
    width = min(child["x2"], parent["x2"]) - max(child["x1"], parent["x1"])
    height = min(child["y2"], parent["y2"]) - max(child["y1"], parent["y1"])
    area = max(0.0, child["x2"] - child["x1"]) * max(0.0, child["y2"] - child["y1"])
    if width <= 0 or height <= 0 or area <= 0:
        return 0.0
    return (width * height) / area


def _is_nested_pair(first: dict[str, Any], second: dict[str, Any]) -> bool:
    """True when one box sits inside the other at a genuinely different scale.

    A caption inside a figure is a hierarchy the binder needs, so it must not be
    collapsed here; two same-size rectangles from two classes are a duplicate.
    """
    areas = sorted([
        max(0.0, first["x2"] - first["x1"]) * max(0.0, first["y2"] - first["y1"]),
        max(0.0, second["x2"] - second["x1"]) * max(0.0, second["y2"] - second["y1"]),
    ])
    if areas[1] <= 0 or areas[0] / areas[1] >= 0.9:
        return False
    return (
        _containment(first, second) >= 0.9 or _containment(second, first) >= 0.9
    )


def _suppress_cross_class_duplicates(
    boxes: list[dict[str, Any]],
    iou_threshold: float,
) -> list[dict[str, Any]]:
    """Drop cross-class boxes that describe the same region, keep nested ones.

    A page frame that contains a caption is a real hierarchy, not a duplicate, so
    only high-IoU (roughly the same rectangle) overlaps of comparable size are
    merged and the higher-confidence box survives.
    """
    if len(boxes) < 2:
        return boxes
    data = _box_matrix(boxes)
    areas = _box_areas(data)
    order = [int(index) for index in _order_by_confidence(data)]
    kept: list[int] = []
    while order:
        index = order.pop(0)
        kept.append(index)
        if not order:
            break
        other_class = [i for i in order if data[i, 5] != data[index, 5]]
        if not other_class:
            continue
        candidates = np.array(other_class, dtype=np.int64)
        duplicate = _iou_batch(index, candidates, data, areas) > iou_threshold
        drop = {
            int(candidate)
            for candidate, is_duplicate in zip(other_class, duplicate)
            if is_duplicate
            and not _is_nested_pair(boxes[index], boxes[int(candidate)])
        }
        if drop:
            order = [i for i in order if i not in drop]
    return [boxes[index] for index in kept]


class DocLayoutDetector:
    """DocLayout-YOLO ONNX 推理器。惰性加载，可用性可探测，降级状态可诊断。"""

    def __init__(
        self,
        model_path: str,
        conf_threshold: float = 0.35,
        input_size: int = 1024,
        iou_threshold: float = 0.45,
        min_area_ratio: float = 0.002,
        coordinate_format: str = MODEL_COORDINATE_FORMAT,
        coordinate_normalized: bool = MODEL_COORDINATE_NORMALIZED,
    ) -> None:
        self.model_path = str(model_path or "").strip()
        if not self.model_path:
            # 未配置时自动发现项目内 tools/doclayout/*.onnx，便于开箱即用
            self.model_path = self._discover_default_model()
        self.conf_threshold = max(0.0, min(1.0, float(conf_threshold)))
        self.input_size = max(64, int(input_size))
        self.iou_threshold = max(0.0, min(1.0, float(iou_threshold)))
        self.min_area_ratio = max(0.0, float(min_area_ratio))
        self.coordinate_format = str(coordinate_format or "auto")
        self.coordinate_normalized = bool(coordinate_normalized)
        self._session: Any = None
        self._input_name: str = ""
        self._output_names: list[str] = []
        self._load_error: str = ""
        self._class_names: list[str] = list(DOCLAYOUT_CLASS_NAMES)
        self._requested_providers: list[str] = []
        self._actual_providers: list[str] = []
        self._model_sha256 = ""

    @staticmethod
    def _discover_default_model() -> str:
        """扫描项目 tools/doclayout 目录，返回第一个 ONNX 模型路径。"""
        project_root = os.path.dirname(os.path.abspath(__file__))
        tool_dir = os.path.join(project_root, "tools", "doclayout")
        if os.path.isdir(tool_dir):
            for name in sorted(os.listdir(tool_dir)):
                if name.lower().endswith(".onnx"):
                    return os.path.join(tool_dir, name)
        return ""

    @staticmethod
    def _preferred_providers() -> list[str]:
        """Request the fastest provider this ONNX build actually ships."""
        available = list(onnxruntime.get_available_providers()) if onnxruntime else []
        return [
            provider for provider in ("CUDAExecutionProvider", "CPUExecutionProvider")
            if provider in available
        ] or ["CPUExecutionProvider"]

    def _ensure_session(self) -> dict[str, Any]:
        """Create the ORT session once, reporting a diagnosable degradation state."""
        outcome: dict[str, Any] = {
            "ok": self._session is not None,
            "status": LAYOUT_STATUS_OK,
            "reason": "",
            "error_type": "",
            "elapsed_ms": 0.0,
        }
        if self._session is not None:
            outcome["reason"] = self._load_error
            return outcome
        if onnxruntime is None:
            self._load_error = "onnxruntime 未安装（pip install onnxruntime）"
            outcome.update(status=LAYOUT_STATUS_MISSING_DEPENDENCY, reason=self._load_error)
            return outcome
        if not self.model_path or not os.path.exists(self.model_path):
            self._load_error = f"模型文件不存在: {self.model_path or '(未配置)'}"
            outcome.update(status=LAYOUT_STATUS_MISSING_MODEL, reason=self._load_error)
            return outcome
        breaker = _init_failures().get(self.model_path)
        if breaker is not None:
            self._load_error = str(breaker.get("reason") or "")
            outcome.update(
                status=str(breaker.get("status") or LAYOUT_STATUS_SESSION_INIT_FAILED),
                reason=self._load_error,
                error_type=str(breaker.get("error_type") or ""),
            )
            return outcome
        started = time.perf_counter()
        preferred = self._preferred_providers()
        self._requested_providers = list(preferred)
        try:
            self._session = onnxruntime.InferenceSession(
                self.model_path,
                providers=preferred,
            )
            self._input_name = self._session.get_inputs()[0].name
            self._output_names = [output.name for output in self._session.get_outputs()]
            self._actual_providers = _session_providers(self._session, preferred)
            self._model_sha256 = _sha256_of_model(self.model_path)
            self._load_metadata_names()
            self._load_error = ""
            outcome.update(ok=True, status=LAYOUT_STATUS_OK, reason="", elapsed_ms=_ms(started))
        except Exception as exc:  # pragma: no cover - 依赖环境差异
            self._session = None
            self._load_error = str(exc)
            _record_init_failure(self.model_path, LAYOUT_STATUS_SESSION_INIT_FAILED, exc)
            outcome.update(
                status=LAYOUT_STATUS_SESSION_INIT_FAILED,
                reason=self._load_error,
                error_type=type(exc).__name__,
                elapsed_ms=_ms(started),
            )
        return outcome

    def _load_metadata_names(self) -> None:
        """优先从 ONNX metadata 读取类别名；失败时回退到内置常量。"""
        try:
            meta = self._session.get_modelmeta()
            raw = meta.custom_metadata_map.get("names", "")
            if not raw:
                return
            parsed = ast.literal_eval(raw)
            if isinstance(parsed, dict) and parsed:
                max_index = max(int(index) for index in parsed)
                names = [str(parsed.get(index, "")) for index in range(max_index + 1)]
                if any(names):
                    self._class_names = names
        except Exception:  # pragma: no cover - 无 metadata 时保持兜底
            return

    def available(self) -> bool:
        return bool(self._ensure_session()["ok"])

    def load_error(self) -> str:
        return self._load_error

    def detect_with_status(self, image: Image.Image) -> dict[str, Any]:
        """Detect layout boxes and return the boxes plus the degradation record."""
        load = self._ensure_session()
        record: dict[str, Any] = {
            "status": str(load["status"]),
            "available": bool(load["ok"]),
            "box_count": 0,
            "raw_box_count": 0,
            "filtered_box_count": 0,
            "requested_providers": list(self._requested_providers),
            "actual_providers": list(self._actual_providers),
            "model_path": self.model_path,
            "model_sha256": self._model_sha256,
            "input_size": self.input_size,
            "conf_threshold": self.conf_threshold,
            "coordinate_format": self.coordinate_format,
            "coordinate_normalized": self.coordinate_normalized,
            "load_error": str(load["reason"]),
            "error_type": str(load["error_type"]),
            "fallback_reason": "",
            "elapsed_ms": {"layout_load": float(load["elapsed_ms"]), "layout_infer": 0.0},
        }
        if not load["ok"]:
            record["fallback_reason"] = str(load["reason"]) or record["status"]
            record["boxes"] = []
            return record
        started = time.perf_counter()
        try:
            tensor, scale, pad_x, pad_y = _letterbox(image, self.input_size)
            tensor = tensor / 255.0  # 该 DocLayout ONNX 需要 [0,1] 归一化
            outputs = self._session.run(self._output_names, {self._input_name: tensor})
        except Exception as exc:
            record["status"] = LAYOUT_STATUS_INFERENCE_FAILED
            record["error_type"] = type(exc).__name__
            record["fallback_reason"] = f"{type(exc).__name__}: {exc}"[:400]
            record["elapsed_ms"]["layout_infer"] = _ms(started)
            record["boxes"] = []
            return record
        record["elapsed_ms"]["layout_infer"] = _ms(started)
        try:
            raw = _parse_predictions(
                outputs[0] if outputs else None,
                scale,
                pad_x,
                pad_y,
                self.input_size,
                int(image.width),
                int(image.height),
                self.coordinate_format,
                self.coordinate_normalized,
            )
        except LayoutOutputError as exc:
            record["status"] = LAYOUT_STATUS_INFERENCE_FAILED
            record["error_type"] = type(exc).__name__
            record["fallback_reason"] = str(exc)[:400]
            record["elapsed_ms"]["layout_infer"] = _ms(started)
            record["boxes"] = []
            return record
        record["raw_box_count"] = len(raw)
        # 类别白名单（按名称）+ 置信度 + 面积过滤
        kept: list[dict[str, Any]] = []
        canvas_area = max(1, image.width * image.height)
        for box in raw:
            class_id = int(box["class_id"])
            class_name = (
                self._class_names[class_id]
                if 0 <= class_id < len(self._class_names)
                else str(class_id)
            )
            role = ROLE_BY_NAME.get(class_name)
            if role is None:
                continue
            if box["confidence"] < self.conf_threshold:
                continue
            box_area = max(0.0, box["x2"] - box["x1"]) * max(0.0, box["y2"] - box["y1"])
            if box_area < canvas_area * self.min_area_ratio:
                continue
            box["class_name"] = class_name
            box["role"] = role
            box["box"] = {
                "x": max(0.0, round(box["x1"])),
                "y": max(0.0, round(box["y1"])),
                "w": max(1, round(box["x2"] - box["x1"])),
                "h": max(1, round(box["y2"] - box["y1"])),
            }
            kept.append(box)
        record["filtered_box_count"] = len(kept)
        kept = _class_aware_nms(kept, self.iou_threshold)
        kept = _suppress_cross_class_duplicates(kept, self.iou_threshold)
        kept.sort(key=lambda box: (box["box"]["y"], box["box"]["x"]))
        record["box_count"] = len(kept)
        record["status"] = LAYOUT_STATUS_OK if kept else LAYOUT_STATUS_NO_BOXES
        record["boxes"] = kept
        return record

    def detect(self, image: Image.Image) -> list[dict[str, Any]]:
        """返回原图坐标系下的版面框（已做类别白名单过滤、NMS、面积过滤）。"""
        return self.detect_with_status(image)["boxes"]


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000.0, 1)


_INIT_FAILURE_LOCK = Lock()
_INIT_FAILURES: dict[str, dict[str, str]] = {}
_MODEL_SHA_CACHE: dict[str, str] = {}


def _init_failures() -> dict[str, dict[str, str]]:
    return _INIT_FAILURES


def _record_init_failure(model_path: str, status: str, exc: BaseException) -> None:
    with _INIT_FAILURE_LOCK:
        _INIT_FAILURES[model_path] = {
            "status": status,
            "reason": f"{type(exc).__name__}: {exc}"[:400],
            "error_type": type(exc).__name__,
        }


def reset_session_init_failures() -> None:
    """Clear the per-process session-init circuit breaker (config change/tests)."""
    with _INIT_FAILURE_LOCK:
        _INIT_FAILURES.clear()


def _session_providers(session: Any, requested: list[str]) -> list[str]:
    """Read the providers ORT actually bound, falling back to the request order."""
    getter = getattr(session, "get_providers", None)
    if not callable(getter):
        return list(requested)
    try:
        return list(getter())
    except Exception:  # pragma: no cover - provider introspection is optional
        return list(requested)


def _sha256_of_model(path: str) -> str:
    """Hash the model file once per process; never let diagnostics break inference."""
    cached = _MODEL_SHA_CACHE.get(path)
    if cached is not None:
        return cached
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        value = digest.hexdigest()
    except Exception:
        value = ""
    _MODEL_SHA_CACHE[path] = value
    return value

