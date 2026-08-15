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
- 确定性后处理：兼容常见 YOLOv10 ONNX 输出形态（[1, N, 6] 或 [1, 6, N]、
  绝对坐标或归一化坐标、xyxy 或 xywh），并做类别白名单过滤 + NMS + 面积过滤。
"""

from __future__ import annotations

import ast
import os
from typing import Any

import numpy as np
from PIL import Image

try:  # 可选依赖：未安装时整体降级为不可用
    import onnxruntime
except Exception:  # pragma: no cover - 依赖缺失分支
    onnxruntime = None  # type: ignore[assignment]

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
) -> list[dict[str, Any]]:
    """把 ONNX 输出解析为原图坐标系下的检测框。

    兼容 [1, N, 6] / [1, 6, N] 两种形态，xyxy / xywh、绝对 / 归一化坐标。
    """
    if pred is None:
        return []
    try:
        array = np.asarray(pred)
    except Exception:
        return []
    if array.ndim == 3:
        array = array[0]
    if array.ndim != 2:
        return []
    n, m = array.shape
    if n == 6 and m != 6:  # [6, N] -> [N, 6]
        array = array.T
        n, m = array.shape
    if m < 6:
        return []
    boxes: list[dict[str, Any]] = []
    for row in array:
        try:
            values = row.astype(float)
        except Exception:
            continue
        a, b, c, d = values[0], values[1], values[2], values[3]
        confidence = float(values[4])
        class_id = int(round(float(values[5])))
        if confidence <= 0 or not np.isfinite(values[0:6]).all():
            continue
        if c > a and d > b:
            x1, y1, x2, y2 = a, b, c, d
        else:  # xywh
            cx, cy, w, h = a, b, c, d
            x1, y1, x2, y2 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
        # 归一化坐标（0-1）还原到 letterbox 输入尺寸
        if max(abs(x1), abs(y1), abs(x2), abs(y2)) <= 1.0 + 1e-6:
            x1 *= input_size
            y1 *= input_size
            x2 *= input_size
            y2 *= input_size
        # 逆 letterbox：映射回原图坐标
        x1 = (x1 - pad_x) / scale
        y1 = (y1 - pad_y) / scale
        x2 = (x2 - pad_x) / scale
        y2 = (y2 - pad_y) / scale
        if x2 <= x1 or y2 <= y1:
            continue
        boxes.append({
            "x1": float(x1),
            "y1": float(y1),
            "x2": float(x2),
            "y2": float(y2),
            "confidence": confidence,
            "class_id": class_id,
        })
    return boxes


def _nms(boxes: list[dict[str, Any]], iou_threshold: float) -> list[dict[str, Any]]:
    """类别内 IoU NMS。"""
    if not boxes:
        return []
    data = np.array([
        [box["x1"], box["y1"], box["x2"], box["y2"], box["confidence"], box["class_id"]]
        for box in boxes
    ], dtype=np.float64)
    x1, y1, x2, y2, scores = data[:, 0], data[:, 1], data[:, 2], data[:, 3], data[:, 4]
    areas = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size > 0:
        index = int(order[0])
        keep.append(index)
        rest = order[1:]
        if rest.size == 0:
            break
        xx1 = np.maximum(x1[index], x1[rest])
        yy1 = np.maximum(y1[index], y1[rest])
        xx2 = np.minimum(x2[index], x2[rest])
        yy2 = np.minimum(y2[index], y2[rest])
        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        iou = inter / np.maximum(1e-6, areas[index] + areas[rest] - inter)
        order = rest[iou <= iou_threshold]
    return [boxes[index] for index in keep]


def _fuse_overlapping(boxes: list[dict[str, Any]], iou_threshold: float) -> list[dict[str, Any]]:
    """跨类别高重叠时保留置信度更高者，避免同一区域被多个类别重复框住。"""
    if len(boxes) < 2:
        return boxes
    data = np.array([
        [box["x1"], box["y1"], box["x2"], box["y2"], box["confidence"], box["class_id"]]
        for box in boxes
    ], dtype=np.float64)
    x1, y1, x2, y2, scores = data[:, 0], data[:, 1], data[:, 2], data[:, 3], data[:, 4]
    areas = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size > 0:
        index = int(order[0])
        keep.append(index)
        rest = order[1:]
        if rest.size == 0:
            break
        xx1 = np.maximum(x1[index], x1[rest])
        yy1 = np.maximum(y1[index], y1[rest])
        xx2 = np.minimum(x2[index], x2[rest])
        yy2 = np.minimum(y2[index], y2[rest])
        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        iou = inter / np.maximum(1e-6, areas[index] + areas[rest] - inter)
        order = rest[iou <= iou_threshold]
    return [boxes[index] for index in keep]


class DocLayoutDetector:
    """DocLayout-YOLO ONNX 推理器（CPU）。惰性加载，可用性可探测。"""

    def __init__(
        self,
        model_path: str,
        conf_threshold: float = 0.35,
        input_size: int = 1024,
        iou_threshold: float = 0.45,
        min_area_ratio: float = 0.002,
    ) -> None:
        self.model_path = str(model_path or "").strip()
        if not self.model_path:
            # 未配置时自动发现项目内 tools/doclayout/*.onnx，便于开箱即用
            self.model_path = self._discover_default_model()
        self.conf_threshold = max(0.0, min(1.0, float(conf_threshold)))
        self.input_size = max(64, int(input_size))
        self.iou_threshold = max(0.0, min(1.0, float(iou_threshold)))
        self.min_area_ratio = max(0.0, float(min_area_ratio))
        self._session: Any = None
        self._input_name: str = ""
        self._output_names: list[str] = []
        self._load_error: str = ""
        self._class_names: list[str] = list(DOCLAYOUT_CLASS_NAMES)

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

    def available(self) -> bool:
        if self._session is not None:
            return True
        if onnxruntime is None:
            self._load_error = "onnxruntime 未安装（pip install onnxruntime）"
            return False
        if not self.model_path or not os.path.exists(self.model_path):
            self._load_error = f"模型文件不存在: {self.model_path or '(未配置)'}"
            return False
        try:
            providers = [
                provider for provider in ("CUDAExecutionProvider", "CPUExecutionProvider")
                if provider in onnxruntime.get_available_providers()
            ] or ["CPUExecutionProvider"]
            self._session = onnxruntime.InferenceSession(
                self.model_path,
                providers=providers,
            )
            self._input_name = self._session.get_inputs()[0].name
            self._output_names = [output.name for output in self._session.get_outputs()]
            self._load_metadata_names()
        except Exception as exc:  # pragma: no cover - 依赖环境差异
            self._load_error = str(exc)
            self._session = None
            return False
        return True

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

    def load_error(self) -> str:
        return self._load_error

    def detect(self, image: Image.Image) -> list[dict[str, Any]]:
        """返回原图坐标系下的版面框（已做类别白名单过滤、NMS、面积过滤）。"""
        if not self.available():
            return []
        tensor, scale, pad_x, pad_y = _letterbox(image, self.input_size)
        tensor = tensor / 255.0  # 该 DocLayout ONNX 需要 [0,1] 归一化
        try:
            outputs = self._session.run(self._output_names, {self._input_name: tensor})
        except Exception:  # pragma: no cover - 运行时异常回退
            return []
        raw = _parse_predictions(
            outputs[0] if outputs else None,
            scale,
            pad_x,
            pad_y,
            self.input_size,
            int(image.width),
            int(image.height),
        )
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
        kept = _nms(kept, self.iou_threshold)
        kept = _fuse_overlapping(kept, self.iou_threshold)
        kept.sort(key=lambda box: (box["box"]["y"], box["box"]["x"]))
        return kept
