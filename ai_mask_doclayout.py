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
- 会话按进程复用：ONNX 会话创建是每页数百毫秒的固定开销，会话按
  “模型 SHA + 实际绑定的 Provider”缓存，同模型跨页只加载一次；缓存命中会在
  诊断记录里显式报告 session_reused，绝不把复用伪装成"这页很快"。
- 设备模式可回退且如实报告：doclayout_device_mode = auto|cpu|cuda。cpu 立即
  只用 CPUExecutionProvider；cuda/auto 若 CUDA 只是"可用列表里有"而未真正绑定、
  会话创建抛错、或首次冒烟推理失败，则一次性回退 CPU 并熔断，后续页面不再重试
  GPU。报告的是实际运行 Provider，不是"检测到 NVIDIA"。
- 版面框结果按 (图片 SHA, 模型身份, 输入尺寸/阈值, 实际 Provider) 进程内缓存：
  同一张图重跑标注不再推理；缓存的会话关闭 CPU 内存池，避免复用会话在像素阶段
  仍然占住数百 MB。
- 确定性后处理：随仓模型按声明的 [x1, y1, x2, y2, score, class] 绝对坐标解析，
  未声明形态的其他模型才走 auto 猜测；再做类别白名单过滤 + 同类 NMS +
  跨类同区域去重 + 面积过滤，嵌套层级（父框含子框）不会被当成重复框删除。
"""

from __future__ import annotations

import ast
import hashlib
import os
from collections import OrderedDict
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


# Device selection is a user-visible setting, and ``cpu`` must be an immediate
# bypass rather than a hint: one bad GPU experience must not cost every page a
# round trip through a provider that cannot serve it.
DEVICE_MODE_AUTO = "auto"
DEVICE_MODE_CPU = "cpu"
DEVICE_MODE_CUDA = "cuda"
DEVICE_MODES: tuple[str, ...] = (DEVICE_MODE_AUTO, DEVICE_MODE_CPU, DEVICE_MODE_CUDA)
CUDA_PROVIDER = "CUDAExecutionProvider"
CPU_PROVIDER = "CPUExecutionProvider"


def normalize_device_mode(value: Any) -> str:
    mode = str(value or DEVICE_MODE_AUTO).strip().lower()
    return mode if mode in DEVICE_MODES else DEVICE_MODE_AUTO


def available_device_modes() -> dict[str, Any]:
    """Report what this ONNX build can actually run, not what was requested."""
    available = list(onnxruntime.get_available_providers()) if onnxruntime else []
    return {
        "onnxruntime_installed": onnxruntime is not None,
        "available_providers": available,
        "cuda_available": CUDA_PROVIDER in available,
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
        device_mode: str = DEVICE_MODE_AUTO,
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
        self.device_mode = normalize_device_mode(device_mode)
        self._session: Any = None
        self._input_name: str = ""
        self._output_names: list[str] = []
        self._load_error: str = ""
        self._class_names: list[str] = list(DOCLAYOUT_CLASS_NAMES)
        self._requested_providers: list[str] = []
        self._actual_providers: list[str] = []
        self._model_sha256 = ""
        self._session_reused = False
        self._device_reason = ""

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

    def _plan_providers(self) -> tuple[list[list[str]], str]:
        """Return the provider attempts this page may make, and why GPU is out.

        Listing a provider as *available* is not the same as being able to serve
        a model with it, so a planned CUDA attempt is still verified after the
        session is created.  Once that verification has failed for this model the
        breaker keeps every later page on CPU for the rest of the process.
        """
        available = list(onnxruntime.get_available_providers()) if onnxruntime else []
        if self.device_mode == DEVICE_MODE_CPU:
            return [[CPU_PROVIDER]], "device_mode=cpu"
        if CUDA_PROVIDER not in available:
            return [[CPU_PROVIDER]], "cuda_provider_not_installed"
        if _gpu_breakers().get(self.model_path):
            return [[CPU_PROVIDER]], str(_gpu_breakers()[self.model_path])
        return [[CUDA_PROVIDER, CPU_PROVIDER], [CPU_PROVIDER]], ""

    def _verify_gpu_session(self, session: Any) -> str:
        """Prove the CUDA provider really runs this model before trusting it.

        The smoke input is a tiny all-zero tensor: it cannot produce meaningful
        boxes, and it is not used as a detection.  It only answers the question
        this page cannot answer any other way — will a CUDA kernel launch fail?
        """
        try:
            if session is None:
                return "cuda_session_missing"
            bound = _session_providers(session, [CUDA_PROVIDER])
            if CUDA_PROVIDER not in bound:
                return "cuda_provider_not_bound"
            shape = None
            try:
                dimensions = session.get_inputs()[0].shape
                if len(dimensions) == 4 and all(isinstance(value, int) and value > 0 for value in dimensions):
                    shape = [int(value) for value in dimensions]
                    shape[0] = 1
                    shape[2] = shape[3] = 64
            except Exception:
                shape = None
            probe = np.zeros(shape or [1, 3, 64, 64], dtype=np.float32)
            session.run(None, {session.get_inputs()[0].name: probe})
        except Exception as exc:
            return f"cuda_smoke_failed:{type(exc).__name__}"[:200]
        return ""

    def _ensure_session(self) -> dict[str, Any]:
        """Bind the model session once per process, reporting real device evidence."""
        outcome: dict[str, Any] = {
            "ok": self._session is not None,
            "status": LAYOUT_STATUS_OK,
            "reason": "",
            "error_type": "",
            "elapsed_ms": 0.0,
            "session_reused": self._session_reused,
            "device_reason": self._device_reason,
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
        model_sha = _sha256_of_model(self.model_path)
        attempts, device_reason = self._plan_providers()
        self._device_reason = device_reason
        outcome["device_reason"] = device_reason
        last_error: BaseException | None = None
        for providers in attempts:
            self._requested_providers = list(providers)
            wants_gpu = providers[0] == CUDA_PROVIDER
            try:
                session, actual, reused = _acquire_session(self.model_path, model_sha, providers)
            except Exception as exc:
                last_error = exc
                if wants_gpu:
                    # A provider that cannot even build the session is the same
                    # class of failure as one that cannot run it: retrying it per
                    # page would pay the same crash for every remaining slide.
                    reason = f"cuda_create_failed:{type(exc).__name__}"[:200]
                    _trip_gpu_breaker(self.model_path, reason)
                    self._device_reason = reason
                    outcome["device_reason"] = reason
                continue
            if wants_gpu:
                failure = self._verify_gpu_session(session)
                if failure:
                    # A GPU that cannot serve this model must not be rediscovered
                    # on every page: the breaker sends the rest of the run to CPU,
                    # and the unusable session is dropped instead of being cached.
                    _discard_session(self.model_path, model_sha, providers)
                    _trip_gpu_breaker(self.model_path, failure)
                    self._device_reason = failure
                    outcome["device_reason"] = failure
                    continue
            self._session = session
            self._input_name = session.get_inputs()[0].name
            self._output_names = [output.name for output in session.get_outputs()]
            self._actual_providers = actual
            self._model_sha256 = model_sha
            self._session_reused = bool(reused)
            self._load_metadata_names()
            self._load_error = ""
            outcome.update(
                ok=True,
                status=LAYOUT_STATUS_OK,
                reason="",
                elapsed_ms=_ms(started),
                session_reused=bool(reused),
                device_reason=self._device_reason,
            )
            return outcome
        self._session = None
        exc = last_error or RuntimeError("no usable ONNX execution provider")
        self._load_error = str(exc)
        _record_init_failure(self.model_path, LAYOUT_STATUS_SESSION_INIT_FAILED, exc)
        outcome.update(
            status=LAYOUT_STATUS_SESSION_INIT_FAILED,
            reason=self._load_error,
            error_type=type(exc).__name__,
            elapsed_ms=_ms(started),
            session_reused=False,
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

    def detect_with_status(
        self,
        image: Image.Image,
        source_sha256: str = "",
    ) -> dict[str, Any]:
        """Detect layout boxes and return the boxes plus the degradation record.

        ``source_sha256`` lets a caller that already hashed the page prove that a
        cache hit is the same image; without it no box cache entry is read or
        written, because guessing at identity is worse than recomputing.
        """
        load = self._ensure_session()
        record: dict[str, Any] = {
            "status": str(load["status"]),
            "available": bool(load["ok"]),
            "box_count": 0,
            "raw_box_count": 0,
            "filtered_box_count": 0,
            "device_mode": self.device_mode,
            "requested_providers": list(self._requested_providers),
            "actual_providers": list(self._actual_providers),
            "session_reused": bool(load.get("session_reused")),
            "device_reason": str(load.get("device_reason") or ""),
            "layout_cache_hit": False,
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
        cache_key: tuple[Any, ...] | None = None
        if source_sha256:
            cache_key = (
                str(source_sha256),
                # Same reasoning as the session key: an unhashable model must not
                # have its boxes shared with every other unhashable model.
                self._model_sha256 or self.model_path,
                self.input_size,
                self.conf_threshold,
                self.iou_threshold,
                self.min_area_ratio,
                self.coordinate_format,
                self.coordinate_normalized,
                tuple(self._actual_providers),
            )
            cached = _cached_boxes(cache_key)
            if cached is not None:
                record["layout_cache_hit"] = True
                record["box_count"] = len(cached)
                record["filtered_box_count"] = len(cached)
                record["raw_box_count"] = len(cached)
                record["status"] = LAYOUT_STATUS_OK if cached else LAYOUT_STATUS_NO_BOXES
                record["boxes"] = cached
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
        if cache_key is not None:
            _remember_boxes(cache_key, kept)
        return record

    def detect(self, image: Image.Image) -> list[dict[str, Any]]:
        """返回原图坐标系下的版面框（已做类别白名单过滤、NMS、面积过滤）。"""
        return self.detect_with_status(image)["boxes"]


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000.0, 1)


_INIT_FAILURE_LOCK = Lock()
_INIT_FAILURES: dict[str, dict[str, str]] = {}
_MODEL_SHA_CACHE: dict[str, str] = {}
_SESSION_CACHE_LOCK = Lock()
_SESSION_CACHE: dict[str, tuple[Any, list[str]]] = {}
_GPU_BREAKER_LOCK = Lock()
_GPU_BREAKERS: dict[str, str] = {}
_BOX_CACHE_LOCK = Lock()
_BOX_CACHE: "OrderedDict[tuple[Any, ...], list[dict[str, Any]]]" = OrderedDict()
# A run is one project's page set; 32 entries keep repeated re-annotation cheap
# without letting the process hold box lists for slides nobody looks at again.
_BOX_CACHE_MAX = 32


def _session_options() -> Any:
    """Options for a session that the process intends to keep and reuse.

    The CPU memory arena is switched off on purpose: a cached session would
    otherwise hold its reserved arena resident while the flood-fill stage works
    on the same page, and inference on the shipped model measured the same speed
    without it.
    """
    options = onnxruntime.SessionOptions()
    options.enable_cpu_mem_arena = False
    return options


def _session_key(model_path: str, model_sha256: str, providers: list[str]) -> str:
    # A model whose bytes cannot be hashed still has to stay separate from every
    # other unreadable path, so the path is the fallback identity.
    return f"{model_sha256 or model_path}|{'+'.join(providers)}"


def _acquire_session(
    model_path: str,
    model_sha256: str,
    providers: list[str],
) -> tuple[Any, list[str], bool]:
    """Return (session, bound providers, cache_hit) for this model and provider set.

    The cache key carries the provider list on purpose: a CUDA session and a CPU
    session of the same weights are different executors, and mixing them up would
    report one device while the other actually ran the model.
    """
    key = _session_key(model_path, model_sha256, providers)
    with _SESSION_CACHE_LOCK:
        cached = _SESSION_CACHE.get(key)
        if cached is not None:
            return cached[0], list(cached[1]), True
        session = onnxruntime.InferenceSession(
            model_path,
            sess_options=_session_options(),
            providers=list(providers),
        )
        actual = _session_providers(session, list(providers))
        _SESSION_CACHE[key] = (session, actual)
        return session, actual, False


def _discard_session(model_path: str, model_sha256: str, providers: list[str]) -> None:
    """Drop a session whose device verification failed, freeing its memory."""
    with _SESSION_CACHE_LOCK:
        _SESSION_CACHE.pop(_session_key(model_path, model_sha256, providers), None)


def _gpu_breakers() -> dict[str, str]:
    return _GPU_BREAKERS


def _trip_gpu_breaker(model_path: str, reason: str) -> None:
    with _GPU_BREAKER_LOCK:
        _GPU_BREAKERS[model_path] = str(reason)[:400]


def reset_doclayout_caches() -> None:
    """Drop every per-process DocLayout cache (config change, tests, model swap).

    The model hash is part of this set: a file replaced at the same path must
    not keep serving a session or a box list that was keyed by the old bytes.
    """
    with _INIT_FAILURE_LOCK:
        _INIT_FAILURES.clear()
    with _SESSION_CACHE_LOCK:
        _SESSION_CACHE.clear()
        _MODEL_SHA_CACHE.clear()
    with _GPU_BREAKER_LOCK:
        _GPU_BREAKERS.clear()
    with _BOX_CACHE_LOCK:
        _BOX_CACHE.clear()


def _cached_boxes(key: tuple[Any, ...]) -> list[dict[str, Any]] | None:
    with _BOX_CACHE_LOCK:
        cached = _BOX_CACHE.get(key)
        if cached is None:
            return None
        _BOX_CACHE.move_to_end(key)
        return [dict(box) for box in cached]


def _remember_boxes(key: tuple[Any, ...], boxes: list[dict[str, Any]]) -> None:
    with _BOX_CACHE_LOCK:
        _BOX_CACHE[key] = [dict(box) for box in boxes]
        _BOX_CACHE.move_to_end(key)
        while len(_BOX_CACHE) > _BOX_CACHE_MAX:
            _BOX_CACHE.popitem(last=False)


def _init_failures() -> dict[str, dict[str, str]]:
    return _INIT_FAILURES


def _record_init_failure(model_path: str, status: str, exc: BaseException) -> None:
    with _INIT_FAILURE_LOCK:
        _INIT_FAILURES[model_path] = {
            "status": status,
            "reason": f"{type(exc).__name__}: {exc}"[:400],
            "error_type": type(exc).__name__,
        }


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

