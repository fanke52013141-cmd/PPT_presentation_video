# -*- coding: utf-8 -*-
"""AI Mask 分割引擎层：确定性白底检测 vs ComfyUI + SAM2 智能分割。

本模块是 ``ai_mask_component_detection.detect_elements`` 的上游路由，不改变
下游元素契约（element_id / bbox / mask_rle=row_runs_v1），也不引入 torch：

- 自动探测可用的 ComfyUI 后端（支持多地址、/system_stats、/object_info 节点
  与模型校验），可用时逐对象调用 SAM2 分割，输出与 ``detect_elements`` 同构。
- 探测不到、断路器打开或调用失败时，静默回退到确定性 ``detect_elements``，
  不阻断主流程；取消信号（check_cancelled）正常透传。

所有 httpx 调用均 trust_env=False，避免系统代理劫持本地/局域网地址。
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import httpx
import numpy as np
from PIL import Image

from ai_mask_component_detection import (
    _pad_box,
    _position,
    _rle_pixel_count,
    _write_json,
    detect_elements,
)
from repository_paths import REPO_ROOT

logger = logging.getLogger("PPTStudio.SegmentBackend")

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

ENGINE_DETERMINISTIC = "deterministic"
ENGINE_SAM2 = "sam2"

DEVICE_MODE_AUTO = "auto"
DEVICE_MODE_CPU = "cpu"
DEVICE_MODE_CUDA = "cuda"
DEVICE_MODES: tuple[str, ...] = (DEVICE_MODE_AUTO, DEVICE_MODE_CPU, DEVICE_MODE_CUDA)

# SAM2 档位（kijai DownloadAndLoadSAM2Model 使用的 safetensors 权重文件名）
SAM2_TIERS: dict[str, str] = {
    "tiny": "sam2.1_hiera_tiny.safetensors",
    "small": "sam2.1_hiera_small.safetensors",
    "base_plus": "sam2.1_hiera_base_plus.safetensors",
    "large": "sam2.1_hiera_large.safetensors",
}
DEFAULT_SAM2_TIER = "large"  # RTX 5080 16GB 全档位无压力，默认 large

DEFAULT_WORKFLOW_PATH = str(Path(REPO_ROOT) / "config" / "sam2_segmentation_api.json")
DEFAULT_BASE_URL = "http://127.0.0.1:8188"

# 节点 class_type 匹配模式（小写包含匹配）
NODE_CLASSES = {
    "load_image": ["loadimage"],
    "sam2_loader": ["downloadandloadsam2model", "sam2modelloader", "loadsam2model"],
    "sam2_segment": ["sam2segmentation"],
    "mask_to_image": ["mask to image", "masktoimage"],
    "save_image": ["saveimage"],
}

# 探测与断路器时序（秒）
PROBE_CACHE_TTL = 60.0
BREAKER_TTL = 120.0
HTTP_CONNECT_TIMEOUT = 3.0
POLL_INTERVAL = 1.0
POLL_TIMEOUT = 120.0


def normalize_device_mode(value: Any) -> str:
    mode = str(value or DEVICE_MODE_AUTO).strip().lower()
    return mode if mode in DEVICE_MODES else DEVICE_MODE_AUTO


def normalize_sam2_tier(value: Any) -> str:
    tier = str(value or DEFAULT_SAM2_TIER).strip().lower()
    return tier if tier in SAM2_TIERS else DEFAULT_SAM2_TIER


# ---------------------------------------------------------------------------
# 纯工具：二值 mask → row_runs_v1
# ---------------------------------------------------------------------------

def _rle(runs: list[list[int]], width: int, height: int) -> dict[str, Any]:
    return {"encoding": "row_runs_v1", "width": width, "height": height, "runs": runs}


def binary_mask_to_rle(mask: np.ndarray) -> dict[str, Any]:
    """把 H×W 布尔/0-1 二值图按行编码为 row_runs_v1。"""
    binary = np.asarray(mask).astype(bool)
    height, width = binary.shape
    runs: list[list[int]] = []
    for y in range(height):
        xs = np.flatnonzero(binary[y])
        if xs.size == 0:
            continue
        start = previous = int(xs[0])
        for value in xs[1:]:
            current = int(value)
            if current != previous + 1:
                runs.append([y, start, previous + 1])
                start = current
            previous = current
        runs.append([y, start, previous + 1])
    return _rle(runs, width, height)


def _rle_bounds(rle: dict[str, Any]) -> dict[str, int] | None:
    valid = [
        run for run in rle.get("runs", [])
        if isinstance(run, list) and len(run) >= 3 and int(run[2]) > int(run[1])
    ]
    if not valid:
        return None
    return {
        "x": min(int(run[1]) for run in valid),
        "y": min(int(run[0]) for run in valid),
        "w": max(int(run[2]) for run in valid) - min(int(run[1]) for run in valid),
        "h": max(int(run[0]) + 1 for run in valid) - min(int(run[0]) for run in valid),
    }


# ---------------------------------------------------------------------------
# 后端状态：探测缓存 + 断路器（线程安全）
# ---------------------------------------------------------------------------

class _BackendState:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.base_url: str | None = None
        self.status: str = "unknown"  # available / unavailable / breaker_open
        self.device_name: str = ""
        self.vram_total: int = 0
        self.tier: str = DEFAULT_SAM2_TIER
        self.reason: str = ""
        self.checked_at: float = 0.0
        self.breaker_until: float = 0.0

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "status": self.status,
                "base_url": self.base_url,
                "device_name": self.device_name,
                "vram_total": self.vram_total,
                "tier": self.tier,
                "reason": self.reason,
                "checked_at": round(self.checked_at, 2),
                "breaker_until": round(self.breaker_until, 2),
            }


_STATE = _BackendState()


def reset_backend_state() -> None:
    """强制清空缓存与断路器（设置变更或手动重试用）。"""
    with _STATE.lock:
        _STATE.base_url = None
        _STATE.status = "unknown"
        _STATE.device_name = ""
        _STATE.vram_total = 0
        _STATE.reason = ""
        _STATE.checked_at = 0.0
        _STATE.breaker_until = 0.0


def _trip_breaker(reason: str) -> None:
    with _STATE.lock:
        _STATE.status = "breaker_open"
        _STATE.base_url = None
        _STATE.reason = reason
        now = time.monotonic()
        _STATE.checked_at = now
        _STATE.breaker_until = now + BREAKER_TTL


# ---------------------------------------------------------------------------
# HTTP 客户端（自定义 base_url，trust_env=False）
# ---------------------------------------------------------------------------

def _make_client(base_url: str, timeout: float = 30.0) -> httpx.Client:
    return httpx.Client(
        base_url=base_url.rstrip("/"),
        timeout=httpx.Timeout(timeout, connect=HTTP_CONNECT_TIMEOUT),
        trust_env=False,
        limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
    )


def _candidate_base_urls(settings: dict[str, Any]) -> list[str]:
    """配置地址（可逗号分隔多个）→ 本机回环，去重保序。"""
    configured = str(settings.get("comfyui_base_url") or "").strip()
    urls = [part.strip() for part in configured.split(",") if part.strip()]
    urls.append(DEFAULT_BASE_URL)
    seen: set[str] = set()
    result: list[str] = []
    for url in urls:
        normalized = url.rstrip("/")
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


# ---------------------------------------------------------------------------
# 能力探测
# ---------------------------------------------------------------------------

def _read_system_stats(client: httpx.Client) -> dict[str, Any]:
    resp = client.get("/system_stats")
    resp.raise_for_status()
    data = resp.json()
    system = data.get("system", {}) if isinstance(data, dict) else {}
    devices = system.get("devices") or []
    device = devices[0] if devices else {}
    return {
        "device_name": str(device.get("name") or system.get("gpu_type") or "unknown"),
        "vram_total": int(device.get("vram_total") or 0),
    }


def _validate_nodes_and_model(client: httpx.Client, workflow: dict[str, Any]) -> str:
    """校验工作流所需节点是否已安装，返回缺失说明（空串=通过）。

    权重是否已下载无法通过 /object_info 判断（选项列表是节点静态定义的，
    实际缺失时 DownloadAndLoadSAM2Model 会在首次运行时自动下载），故此处
    只校验节点 class_type。
    """
    resp = client.get("/object_info")
    resp.raise_for_status()
    available = resp.json()
    available_classes = set(available.keys()) if isinstance(available, dict) else set()

    required = {
        str(node.get("class_type", ""))
        for node in workflow.values()
        if isinstance(node, dict) and node.get("class_type")
    }
    missing_nodes = sorted(name for name in required if name not in available_classes)
    if missing_nodes:
        return "ComfyUI 缺少节点: " + ", ".join(missing_nodes)
    return ""


def probe_backend(settings: dict[str, Any], force: bool = False) -> dict[str, Any]:
    """探测可用 ComfyUI 后端，结果缓存；断路器打开期间直接返回不可用。"""
    now = time.monotonic()
    with _STATE.lock:
        if not force and _STATE.status == "breaker_open" and now < _STATE.breaker_until:
            return _STATE.snapshot()
        if (
            not force
            and _STATE.status == "available"
            and now - _STATE.checked_at < PROBE_CACHE_TTL
        ):
            return _STATE.snapshot()

    workflow = _load_workflow(settings)
    if workflow is None:
        with _STATE.lock:
            _STATE.status = "unavailable"
            _STATE.base_url = None
            _STATE.reason = "SAM2 工作流模板缺失或非法"
            _STATE.checked_at = now
            return _STATE.snapshot()

    last_reason = "未发现可达的 ComfyUI 服务"
    for base_url in _candidate_base_urls(settings):
        try:
            with _make_client(base_url, timeout=8.0) as client:
                stats = _read_system_stats(client)
                missing = _validate_nodes_and_model(client, workflow)
                if missing:
                    last_reason = missing
                    continue
        except Exception as exc:  # 连接失败/超时，尝试下一个地址
            last_reason = f"{base_url} 连接失败: {type(exc).__name__}"
            continue

        with _STATE.lock:
            _STATE.base_url = base_url
            _STATE.status = "available"
            _STATE.device_name = stats["device_name"]
            _STATE.vram_total = stats["vram_total"]
            _STATE.tier = normalize_sam2_tier(settings.get("sam2_tier"))
            _STATE.reason = ""
            _STATE.checked_at = time.monotonic()
            _STATE.breaker_until = 0.0
        return _STATE.snapshot()

    with _STATE.lock:
        _STATE.status = "unavailable"
        _STATE.base_url = None
        _STATE.reason = last_reason
        _STATE.checked_at = now
    return _STATE.snapshot()


# ---------------------------------------------------------------------------
# 工作流加载、节点定位与注入
# ---------------------------------------------------------------------------

def _find_node(workflow: dict[str, Any], patterns: list[str]) -> str | None:
    for node_id, node in workflow.items():
        class_type = str(node.get("class_type", "")).lower().replace(" ", "")
        if any(pattern.lower().replace(" ", "") in class_type for pattern in patterns):
            return node_id
    return None


def _load_workflow(settings: dict[str, Any]) -> dict[str, Any] | None:
    path_value = str(settings.get("sam2_workflow_path") or DEFAULT_WORKFLOW_PATH).strip()
    path = Path(path_value)
    if not path.is_absolute():
        path = Path(REPO_ROOT) / path
    if not path.exists():
        return None
    try:
        workflow = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("[segment] 工作流解析失败 %s: %s", path, exc)
        return None
    if not isinstance(workflow, dict) or not any(
        isinstance(node, dict) and node.get("class_type") for node in workflow.values()
    ):
        return None
    return workflow


def _build_prompt(
    template: dict[str, Any],
    image_name: str,
    positive: list[dict[str, int]],
    negative: list[dict[str, int]],
    model_filename: str | None = None,
) -> dict[str, Any]:
    """复制模板并注入图像文件名、模型权重与正/负提示点，其余参数沿用模板。"""
    workflow = {
        node_id: {"inputs": dict(node.get("inputs", {})), "class_type": node["class_type"]}
        for node_id, node in template.items()
        if isinstance(node, dict) and node.get("class_type")
    }
    load_id = _find_node(workflow, NODE_CLASSES["load_image"])
    if load_id is None:
        raise RuntimeError("工作流缺少 LoadImage 节点")
    workflow[load_id]["inputs"]["image"] = image_name

    if model_filename:
        loader_id = _find_node(workflow, NODE_CLASSES["sam2_loader"])
        if loader_id is not None:
            workflow[loader_id]["inputs"]["model"] = model_filename

    seg_id = _find_node(workflow, NODE_CLASSES["sam2_segment"])
    if seg_id is None:
        raise RuntimeError("工作流缺少 Sam2Segmentation 节点")
    workflow[seg_id]["inputs"]["coordinates_positive"] = json.dumps(positive, ensure_ascii=False)
    workflow[seg_id]["inputs"]["coordinates_negative"] = json.dumps(negative, ensure_ascii=False)
    return workflow


# ---------------------------------------------------------------------------
# 上传 / 提交 / 轮询 / 下载
# ---------------------------------------------------------------------------

def _upload_image(client: httpx.Client, image_path: Path) -> str:
    with open(image_path, "rb") as handle:
        files = {"image": (image_path.name, handle, "application/octet-stream")}
        resp = client.post("/upload/image", files=files)
    resp.raise_for_status()
    return resp.json()["name"]


def _submit(client: httpx.Client, workflow: dict[str, Any]) -> str:
    payload = {"prompt": workflow, "client_id": f"ppt_seg_{uuid.uuid4().hex[:8]}"}
    resp = client.post("/prompt", json=payload)
    if resp.status_code != 200:
        raise RuntimeError(f"提交失败 HTTP {resp.status_code}: {resp.text[:300]}")
    prompt_id = resp.json().get("prompt_id")
    if not prompt_id:
        raise RuntimeError("ComfyUI 未返回 prompt_id")
    return prompt_id


def _poll(client: httpx.Client, prompt_id: str, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = client.get(f"/history/{prompt_id}")
        if resp.status_code == 200:
            entry = resp.json().get(prompt_id)
            if entry:
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    raise RuntimeError(f"工作流执行错误: {status.get('messages', '')}")
                if status.get("completed"):
                    return entry
        time.sleep(POLL_INTERVAL)
    raise RuntimeError(f"等待结果超时（{timeout:.0f}s）prompt={prompt_id}")


def _output_info(entry: dict[str, Any]) -> dict[str, str] | None:
    """遍历输出节点，返回第一个含 images 的 SaveImage 输出信息。"""
    outputs = entry.get("outputs", {})
    for node_out in outputs.values():
        items = node_out.get("images") if isinstance(node_out, dict) else None
        if items:
            item = items[0]
            return {
                "filename": item.get("filename", ""),
                "subfolder": item.get("subfolder", ""),
                "type": item.get("type", "output"),
            }
    return None


def _download_mask(client: httpx.Client, info: dict[str, str]) -> bytes:
    resp = client.get(
        "/view",
        params={
            "filename": info["filename"],
            "subfolder": info.get("subfolder", ""),
            "type": info.get("type", "output"),
        },
    )
    resp.raise_for_status()
    return resp.content


def _decode_mask(content: bytes, expected_size: tuple[int, int]) -> np.ndarray:
    """解码黑白 mask PNG 为布尔数组；尺寸不符时最近邻缩放兜底。"""
    from io import BytesIO

    image = Image.open(BytesIO(content)).convert("L")
    if image.size != expected_size:
        logger.warning("[segment] mask 尺寸 %s 与原图 %s 不一致，最近邻缩放", image.size, expected_size)
        image = image.resize(expected_size, Image.NEAREST)
    array = np.asarray(image, dtype=np.uint8)
    return array >= 128


# ---------------------------------------------------------------------------
# 单对象分割（自动流程与手动智能选区共用）
# ---------------------------------------------------------------------------

def _segment_one(
    base_url: str,
    image_name: str,
    template: dict[str, Any],
    positive: list[dict[str, int]],
    negative: list[dict[str, int]],
    expected_size: tuple[int, int],
    timeout: float,
    model_filename: str | None = None,
) -> np.ndarray:
    workflow = _build_prompt(
        template, image_name, positive, negative, model_filename
    )
    with _make_client(base_url, timeout=30.0) as client:
        prompt_id = _submit(client, workflow)
        entry = _poll(client, prompt_id, timeout)
        info = _output_info(entry)
        if info is None:
            raise RuntimeError("工作流完成但未找到 SaveImage 输出")
        content = _download_mask(client, info)
    return _decode_mask(content, expected_size)


# ---------------------------------------------------------------------------
# 元素组装
# ---------------------------------------------------------------------------

def _build_element(
    mask: np.ndarray,
    index: int,
    width: int,
    height: int,
    padding: int,
) -> dict[str, Any]:
    rle = binary_mask_to_rle(mask)
    raw_bbox = _rle_bounds(rle)
    if raw_bbox is None:  # 空 mask，不产生元素
        return {}
    bbox = _pad_box(raw_bbox, width, height, padding)
    cx = bbox["x"] + bbox["w"] / 2
    cy = bbox["y"] + bbox["h"] / 2
    pixel_count = _rle_pixel_count(rle)
    return {
        "element_id": f"el_auto_{index:03d}",
        "bbox": bbox,
        "raw_bbox": raw_bbox,
        "center": {"x": round(cx, 2), "y": round(cy, 2)},
        "area": pixel_count,
        "mask_pixel_count": pixel_count,
        "source_ink_pixel_count": pixel_count,
        "position": _position(cx, cy, width, height),
        "ocr_text": "",
        "source_ink_rle": rle,
        "mask_rle": rle,
    }


# ---------------------------------------------------------------------------
# SAM2 Provider（整页：逐对象分割）
# ---------------------------------------------------------------------------

def _run_sam2(
    capabilities: Any,
    image_path: Path,
    slide_dir: Path,
    settings: dict[str, Any],
    layout_boxes: list[dict[str, Any]],
) -> dict[str, Any]:
    started = time.perf_counter()
    probe = probe_backend(settings)
    base_url = probe.get("base_url")
    if not base_url:
        raise RuntimeError(probe.get("reason") or "SAM2 后端不可用")

    template = _load_workflow(settings)
    if template is None:
        raise RuntimeError("SAM2 工作流模板缺失")

    # 以原图实际尺寸为准
    with Image.open(image_path).convert("RGB") as source:
        width, height = source.size

    # 提示点：优先用 DocLayout 框中心；无框则不进行智能分割（交回确定性）
    prompts: list[dict[str, int]] = []
    for box in layout_boxes or []:
        x1 = float(box.get("x1", 0))
        y1 = float(box.get("y1", 0))
        x2 = float(box.get("x2", width))
        y2 = float(box.get("y2", height))
        cx = int(min(max(round((x1 + x2) / 2), 0), width - 1))
        cy = int(min(max(round((y1 + y2) / 2), 0), height - 1))
        prompts.append({"x": cx, "y": cy})
    if not prompts:
        raise RuntimeError("无 DocLayout 框可作为 SAM2 提示")

    padding = int(settings.get("component_padding_px", 12))
    model_filename = SAM2_TIERS[normalize_sam2_tier(settings.get("sam2_tier"))]
    elements: list[dict[str, Any]] = []
    image_name = ""
    with _make_client(base_url, timeout=30.0) as upload_client:
        image_name = _upload_image(upload_client, image_path)

    for point in prompts:
        if capabilities is not None:
            capabilities.check_cancelled("")
        mask = _segment_one(
            base_url,
            image_name,
            template,
            [point],
            [],
            (width, height),
            POLL_TIMEOUT,
            model_filename,
        )
        element = _build_element(mask, len(elements), width, height, padding)
        if element:
            elements.append(element)

    if not elements:
        raise RuntimeError("SAM2 未产出有效元素")

    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    source_sha256 = _sha256(image_path)
    payload = {
        "stage_timing_ms": {"smart_segment": elapsed_ms},
        "layout_detection": {},
        "layout_binding": {"engine": ENGINE_SAM2},
        "slide_id": slide_dir.name,
        "source_sha256": source_sha256,
        "detection_settings_fingerprint": "",
        "detection_settings": settings,
        "canvas": {"width": width, "height": height},
        "elements": elements,
        "residual_elements": [],
        "source_foreground_pixel_count": sum(int(e["area"]) for e in elements),
        "grouping_pixel_count": sum(int(e["area"]) for e in elements),
        "pixel_evidence_separation": True,
        "foreground_pixel_count": sum(int(e["area"]) for e in elements),
        "segmentation_engine": ENGINE_SAM2,
        "engine_device": probe,
    }
    out_dir = slide_dir / "auto_mask"
    _write_json(out_dir / "auto_elements.json", payload)
    return payload


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# 路由：确定性 vs SAM2
# ---------------------------------------------------------------------------

def segment_elements(
    capabilities: Any,
    image_path: Path,
    slide_dir: Path,
    settings: dict[str, Any],
    layout_boxes: list[dict[str, Any]] | None = None,
    layout_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """分割引擎路由。任何智能路径失败都回退确定性 ``detect_elements``。"""
    device_mode = normalize_device_mode(settings.get("segmentation_device_mode"))
    layout_boxes = layout_boxes or []

    if device_mode == DEVICE_MODE_CPU:
        return detect_elements(image_path, slide_dir, settings, layout_boxes, layout_record)

    if device_mode in (DEVICE_MODE_AUTO, DEVICE_MODE_CUDA):
        try:
            probe = probe_backend(settings)
            if probe.get("status") == "available" and (
                device_mode == DEVICE_MODE_AUTO or _is_cuda(probe)
            ):
                return _run_sam2(capabilities, image_path, slide_dir, settings, layout_boxes)
        except Exception as exc:
            if _is_cancellation(exc):
                raise
            logger.warning("[segment] SAM2 路径失败，回退确定性方案: %s", exc)
            _trip_breaker(f"SAM2 调用失败: {type(exc).__name__}: {str(exc)[:200]}")

    return detect_elements(image_path, slide_dir, settings, layout_boxes, layout_record)


def _is_cuda(probe: dict[str, Any]) -> bool:
    name = str(probe.get("device_name", "")).lower()
    return bool(name) and "cpu" not in name


def _is_cancellation(exc: BaseException) -> bool:
    return type(exc).__name__ in {"CancelledError", "GenerationStopped", "StopRequested"}


# ---------------------------------------------------------------------------
# 手动智能选区：给定点/框，返回单对象二值 mask（供 mask editor 路由调用）
# ---------------------------------------------------------------------------

def run_smart_selection(
    image_path: Path,
    positive: list[dict[str, int]],
    negative: list[dict[str, int]] | None = None,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """手动勾画智能选区：返回 mask 的 row_runs_v1 与后端信息。"""
    settings = settings or {}
    probe = probe_backend(settings)
    base_url = probe.get("base_url")
    if not base_url:
        return {
            "success": False,
            "reason": probe.get("reason") or "智能分割后端不可用",
            "backend": probe,
        }
    template = _load_workflow(settings)
    if template is None:
        return {"success": False, "reason": "SAM2 工作流模板缺失", "backend": probe}

    with Image.open(image_path).convert("RGB") as source:
        width, height = source.size

    with _make_client(base_url, timeout=30.0) as upload_client:
        image_name = _upload_image(upload_client, Path(image_path))
    model_filename = SAM2_TIERS[normalize_sam2_tier(settings.get("sam2_tier"))]
    mask = _segment_one(
        base_url,
        image_name,
        template,
        positive,
        negative or [],
        (width, height),
        POLL_TIMEOUT,
        model_filename,
    )
    rle = binary_mask_to_rle(mask)
    return {
        "success": True,
        "width": width,
        "height": height,
        "rle": rle,
        "pixel_count": _rle_pixel_count(rle),
        "backend": probe,
    }
