# -*- coding: utf-8 -*-
"""ComfyUI 后端：上传图片+音频 → 提交 Wan2.2 S2V 工作流 → 轮询 → 下载视频。

通过 ComfyUI 的 HTTP API（/upload/image、/prompt、/history、/view）驱动
数字人对口型工作流。所有 httpx 调用均设置 trust_env=False 以避免代理干扰。
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("PPTStudio.ComfyUIBackend")

# 工作流模板中需要动态注入文件名的节点 — 优先通过 class_type 匹配
# 如果工作流中只有一个匹配的节点，即使 ID 不同也能正确注入；
# 硬编码 ID 作为 fallback（兼容旧工作流）
NODE_CLASS_PATTERNS = {
    "load_image": ["LoadImage", "LoadImageDevice", "LoadImageBase64"],
    "load_audio": ["LoadAudio", "VHS_LoadAudio", "VHS_LoadAudioUpload"],
    "video_combine": ["VHS_VideoCombine", "SaveAnimatedWEBP", "SaveVideo"],
}

# 旧工作流的硬编码节点 ID（fallback 用）
NODE_IDS_FALLBACK = {
    "load_image": "252",
    "load_audio": "254",
    "video_combine": "278",
}


def _find_node_by_class(
    wf: Dict[str, Any],
    patterns: list[str],
    fallback_id: Optional[str] = None,
) -> Optional[str]:
    """通过 class_type 模糊匹配节点 ID，兼容任意工作流布局。

    查找顺序：
    1. 遍历所有节点，按 class_type 模糊匹配
    2. 如果匹配到多个，返回第一个
    3. 如果未匹配到，使用 fallback_id（旧工作流硬编码 ID）
    """
    found = None
    for nid, node in wf.items():
        ct = node.get("class_type", "")
        for pat in patterns:
            if pat.lower() in ct.lower():
                return nid
    # fallback：尝试硬编码 ID
    if fallback_id and fallback_id in wf:
        logger.info("[comfyui] class_type 未匹配，回退到硬编码 ID: %s", fallback_id)
        return fallback_id
    return None


class ComfyUIError(RuntimeError):
    """ComfyUI 调用异常。"""


def get_comfyui_url() -> str:
    """获取 ComfyUI 服务地址（默认 http://127.0.0.1:8188）。"""
    return os.environ.get("PPT_COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/")


# 模块级连接池单例：避免每次操作都新建 TCP 连接
_client_singleton: Optional[httpx.Client] = None
_client_lock = threading.Lock()


def _make_client(timeout: float = 30.0) -> httpx.Client:
    """获取 ComfyUI httpx 客户端（连接池单例，复用 TCP 连接）。

    第一次调用时创建带连接池限制的 Client，后续调用复用同一实例。
    trust_env=False 关键：不继承系统代理，避免 localhost 被 Clash 劫持。
    """
    global _client_singleton
    with _client_lock:
        if _client_singleton is None or _client_singleton.is_closed:
            _client_singleton = httpx.Client(
                base_url=get_comfyui_url(),
                timeout=httpx.Timeout(timeout, connect=10.0),
                trust_env=False,
                limits=httpx.Limits(
                    max_connections=4,
                    max_keepalive_connections=2,
                    keepalive_expiry=30.0,
                ),
            )
        # 动态调整超时（轮询需要更长超时）
        _client_singleton.timeout = httpx.Timeout(timeout, connect=10.0)
    return _client_singleton


def check_health() -> bool:
    """检查 ComfyUI 是否在线。"""
    try:
        with _make_client(timeout=5.0) as c:
            resp = c.get("/system_stats")
            return resp.status_code == 200
    except Exception:
        return False


def _upload_file(client: httpx.Client, file_path: Path) -> Dict[str, str]:
    """上传文件到 ComfyUI input 目录，返回 {"name": ..., "subfolder": ...}。"""
    if not file_path.exists():
        raise ComfyUIError(f"文件不存在: {file_path}")
    with open(file_path, "rb") as f:
        files = {"image": (file_path.name, f, "application/octet-stream")}
        resp = client.post("/upload/image", files=files)
    if resp.status_code != 200:
        raise ComfyUIError(f"上传失败 {file_path.name}: HTTP {resp.status_code} {resp.text}")
    data = resp.json()
    return {"name": data["name"], "subfolder": data.get("subfolder", "")}


def _patch_workflow(
    template: Dict[str, Any],
    image_info: Dict[str, str],
    audio_info: Dict[str, str],
) -> Dict[str, Any]:
    """将动态文件名注入工作流模板，返回可提交的 prompt JSON。

    重要：只注入必须动态变化的值（图片名、音频名）。
    分辨率、步数、CFG 等画质参数尊重用户工作流模板中的原始设置，
    不做覆盖——用户的工作流 JSON 是画质的唯一权威来源。
    """
    # 只保留合法节点（dict 且含 class_type），跳过元数据等非节点条目
    wf = {}
    for k, v in template.items():
        if not isinstance(v, dict) or "class_type" not in v:
            logger.debug("[comfyui] 跳过非节点条目: %s", k)
            continue
        wf[k] = {"inputs": dict(v.get("inputs", {})), "class_type": v["class_type"]}
        if "_meta" in v:
            wf[k]["_meta"] = v["_meta"]

    # 通过 class_type 匹配节点（兼容任意工作流布局）
    img_id = _find_node_by_class(
        wf, NODE_CLASS_PATTERNS["load_image"], NODE_IDS_FALLBACK["load_image"]
    )
    audio_id = _find_node_by_class(
        wf, NODE_CLASS_PATTERNS["load_audio"], NODE_IDS_FALLBACK["load_audio"]
    )
    if not img_id:
        raise ComfyUIError("工作流中未找到 LoadImage 节点（class_type 匹配失败）")
    if not audio_id:
        raise ComfyUIError("工作流中未找到 LoadAudio 节点（class_type 匹配失败）")

    # 只注入必须动态变化的输入文件名
    wf[img_id]["inputs"]["image"] = image_info["name"]
    wf[audio_id]["inputs"]["audio"] = audio_info["name"]
    # 清除可能残留的 audioUI 路径
    wf[audio_id]["inputs"].pop("audioUI", None)

    logger.info(
        "[comfyui] 已注入动态文件名，画质参数沿用工作流模板原始值 "
        "(resolution/steps/cfg/lora/shift/fps/crf 不覆盖)"
    )
    return wf


def _submit_prompt(client: httpx.Client, workflow: Dict[str, Any]) -> str:
    """提交工作流到 ComfyUI，返回 prompt_id。"""
    client_id = f"ppt_studio_{uuid.uuid4().hex[:8]}"
    payload = {"prompt": workflow, "client_id": client_id}
    resp = client.post("/prompt", json=payload)
    if resp.status_code != 200:
        raise ComfyUIError(f"提交工作流失败: HTTP {resp.status_code} {resp.text}")
    data = resp.json()
    prompt_id = data.get("prompt_id")
    if not prompt_id:
        raise ComfyUIError(f"ComfyUI 未返回 prompt_id: {data}")
    return prompt_id


def _poll_history(
    client: httpx.Client,
    prompt_id: str,
    timeout: float = 7200.0,
    poll_interval: float = 3.0,
    max_poll_interval: float = 30.0,
    cancel_event: Optional["threading.Event"] = None,
) -> Dict[str, Any]:
    """轮询 /history/{prompt_id}，返回完成的 history 条目。

    采用指数退避策略：初始间隔 poll_interval 秒，每次轮询后乘以 1.5，
    上限 max_poll_interval 秒。减少长任务期间的无效请求。

    参数:
        cancel_event: 可选的取消事件，设置后立即停止轮询并抛出异常
    """
    deadline = time.time() + timeout
    current_interval = poll_interval
    while time.time() < deadline:
        if cancel_event is not None and cancel_event.is_set():
            raise ComfyUIError("任务已被取消（服务关闭）")
        resp = client.get(f"/history/{prompt_id}")
        if resp.status_code == 200:
            data = resp.json()
            entry = data.get(prompt_id)
            if entry:
                status = entry.get("status", {})
                if status.get("completed"):
                    return entry
                # 检查是否出错
                if status.get("status_str") == "error":
                    err_msg = status.get("messages", "")
                    raise ComfyUIError(f"ComfyUI 工作流执行失败: {err_msg}")
        time.sleep(current_interval)
        # 指数退避：间隔逐渐增大，但不超过上限
        current_interval = min(current_interval * 1.5, max_poll_interval)
    raise ComfyUIError(f"等待 ComfyUI 结果超时（{timeout:.0f}s）")


def _find_output_video(entry: Dict[str, Any], wf: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, str]]:
    """从 history 条目中提取输出视频的下载信息。"""
    outputs = entry.get("outputs", {})
    # 优先通过 class_type 匹配的节点 ID 查找（如果提供了工作流）
    vc_id = None
    if wf:
        vc_id = _find_node_by_class(
            wf, NODE_CLASS_PATTERNS["video_combine"], NODE_IDS_FALLBACK["video_combine"]
        )
    node_out = outputs.get(vc_id) if vc_id else None
    if not node_out:
        # 尝试遍历所有输出节点
        for nid_key, node_data in outputs.items():
            if "videos" in node_data or "gifs" in node_data:
                node_out = node_data
                break
    if not node_out:
        return None
    # VHS_VideoCombine 输出在 "videos" 或 "gifs" 字段
    for key in ("videos", "gifs"):
        items = node_out.get(key)
        if items and isinstance(items, list) and len(items) > 0:
            item = items[0]
            return {
                "filename": item.get("filename", ""),
                "subfolder": item.get("subfolder", ""),
                "type": item.get("type", "output"),
            }
    return None


def _download_video(
    client: httpx.Client,
    file_info: Dict[str, str],
    dest: Path,
) -> None:
    """从 ComfyUI 下载输出视频到指定路径。"""
    params = {
        "filename": file_info["filename"],
        "subfolder": file_info.get("subfolder", ""),
        "type": file_info.get("type", "output"),
    }
    with client.stream("GET", "/view", params=params) as resp:
        if resp.status_code != 200:
            raise ComfyUIError(f"下载视频失败: HTTP {resp.status_code}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            for chunk in resp.iter_bytes(chunk_size=65536):
                f.write(chunk)


def run_comfyui_inference(
    image_path: Path,
    audio_path: Path,
    output_path: Path,
    workflow_template: Dict[str, Any],
    timeout: float = 7200.0,
    cancel_event: Optional["threading.Event"] = None,
) -> Dict[str, Any]:
    """完整执行 ComfyUI 推理流程。

    参数:
        image_path: 输入人物图片路径
        audio_path: 输入音频路径
        output_path: 输出视频保存路径
        workflow_template: ComfyUI API 格式工作流模板 JSON
        timeout: 总超时秒数

    返回:
        包含 prompt_id、output 路径等信息的字典
    """
    logger.info("[comfyui] start: image=%s audio=%s", image_path, audio_path)

    with _make_client(timeout=60.0) as upload_client:
        image_info = _upload_file(upload_client, image_path)
        logger.info("[comfyui] uploaded image: %s", image_info)
        audio_info = _upload_file(upload_client, audio_path)
        logger.info("[comfyui] uploaded audio: %s", audio_info)

    workflow = _patch_workflow(workflow_template, image_info, audio_info)

    with _make_client(timeout=30.0) as submit_client:
        prompt_id = _submit_prompt(submit_client, workflow)
        logger.info("[comfyui] submitted prompt_id=%s", prompt_id)

    with _make_client(timeout=30.0) as poll_client:
        entry = _poll_history(poll_client, prompt_id, timeout=timeout, cancel_event=cancel_event)
        logger.info("[comfyui] prompt %s completed", prompt_id)

        file_info = _find_output_video(entry, wf=workflow)
        if not file_info:
            raise ComfyUIError("工作流完成但未找到输出视频节点")
        logger.info("[comfyui] output video: %s", file_info)

        _download_video(poll_client, file_info, output_path)
        logger.info("[comfyui] downloaded to %s (%d bytes)", output_path, output_path.stat().st_size)

    return {
        "prompt_id": prompt_id,
        "output": str(output_path),
        "video_info": file_info,
    }


# ============================================================
# ComfyUI TTS（IndexTTS2）工作流支持
# ============================================================

# IndexTTS2 工作流模板中需要动态注入值的节点 ID 映射
# 这些 ID 来自用户在 ComfyUI 中导出的 IndexTTS2 API 格式工作流 JSON
TTS_NODE_IDS = {
    "load_ref_audio": "4",   # LoadAudio（参考音频，声音克隆用）
    "tts_node": "2",          # IndexTTS2 Text to Speech
    "save_audio": "3",        # SaveAudio / SaveAudioWire
}


def _patch_tts_workflow(
    template: Dict[str, Any],
    text: str,
    ref_audio_info: Optional[Dict[str, str]] = None,
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """将动态值注入 TTS 工作流模板，返回可提交的 prompt JSON。

    注入内容：
    - text → IndexTTS2 节点的 text 输入
    - 参考音频文件名 → LoadAudio 节点（如有）
    - overrides 中的额外参数（speed 等）

    画质/音质参数尊重用户工作流模板中的原始设置，不做覆盖。
    """
    wf = {}
    for k, v in template.items():
        if not isinstance(v, dict) or "class_type" not in v:
            logger.debug("[comfyui-tts] 跳过非节点条目: %s", k)
            continue
        wf[k] = {"inputs": dict(v.get("inputs", {})), "class_type": v["class_type"]}
        if "_meta" in v:
            wf[k]["_meta"] = v["_meta"]

    nid = TTS_NODE_IDS

    # 注入待合成文本
    tts_id = nid["tts_node"]
    if tts_id in wf:
        wf[tts_id]["inputs"]["text"] = text
    else:
        # 尝试通过 class_type 匹配
        for k, v in wf.items():
            ct = v.get("class_type", "")
            if "indextts" in ct.lower() or ("tts" in ct.lower() and "speech" in ct.lower()):
                v["inputs"]["text"] = text
                nid_actual = k
                logger.info("[comfyui-tts] 通过 class_type 匹配到 TTS 节点: %s (%s)", k, ct)
                break

    # 注入参考音频文件名（声音克隆）
    if ref_audio_info:
        ref_id = nid["load_ref_audio"]
        if ref_id in wf:
            wf[ref_id]["inputs"]["audio"] = ref_audio_info["name"]
        else:
            for k, v in wf.items():
                ct = v.get("class_type", "")
                if ct.lower() in ("loadaudio", "load audio", "audioload"):
                    v["inputs"]["audio"] = ref_audio_info["name"]
                    logger.info("[comfyui-tts] 通过 class_type 匹配到 LoadAudio 节点: %s", k)
                    break

    # 注入额外覆盖参数（speed 等）
    if overrides and isinstance(overrides, dict):
        if tts_id in wf:
            for key, val in overrides.items():
                if key in wf[tts_id]["inputs"]:
                    wf[tts_id]["inputs"][key] = val
                    logger.info("[comfyui-tts] 覆盖 %s=%s", key, val)

    logger.info("[comfyui-tts] 已注入文本和参考音频，其他参数沿用模板")
    return wf


def _find_output_audio(entry: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """从 history 条目中提取输出音频的下载信息。"""
    outputs = entry.get("outputs", {})
    sa_id = TTS_NODE_IDS["save_audio"]

    # 优先按已知节点 ID 查找
    node_out = outputs.get(sa_id) or outputs.get(str(sa_id))
    if not node_out:
        # 遍历所有输出节点，查找含音频字段的
        for nid_key, node_data in outputs.items():
            for key in ("audio", "wav", "result", "audios"):
                if key in node_data:
                    node_out = node_data
                    break
            if node_out:
                break
    if not node_out:
        return None

    # SaveAudio 输出字段名可能是 "audio"、"wav"、"result" 等
    for key in ("audio", "wav", "result", "audios"):
        items = node_out.get(key)
        if items and isinstance(items, list) and len(items) > 0:
            item = items[0]
            if isinstance(item, dict):
                return {
                    "filename": item.get("filename", ""),
                    "subfolder": item.get("subfolder", ""),
                    "type": item.get("type", "output"),
                }
        elif isinstance(items, dict):
            return {
                "filename": items.get("filename", ""),
                "subfolder": items.get("subfolder", ""),
                "type": items.get("type", "output"),
            }
    return None


def _download_audio(
    client: httpx.Client,
    file_info: Dict[str, str],
    dest: Path,
) -> None:
    """从 ComfyUI 下载输出音频到指定路径。"""
    params = {
        "filename": file_info["filename"],
        "subfolder": file_info.get("subfolder", ""),
        "type": file_info.get("type", "output"),
    }
    with client.stream("GET", "/view", params=params) as resp:
        if resp.status_code != 200:
            raise ComfyUIError(f"下载音频失败: HTTP {resp.status_code}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            for chunk in resp.iter_bytes(chunk_size=65536):
                f.write(chunk)


def run_comfyui_tts(
    text: str,
    ref_audio_path: Optional[Path],
    output_path: Path,
    workflow_template: Dict[str, Any],
    *,
    overrides: Optional[Dict[str, Any]] = None,
    timeout: float = 300.0,
    cancel_event: Optional["threading.Event"] = None,
) -> Dict[str, Any]:
    """通过 ComfyUI IndexTTS2 工作流合成语音。

    参数:
        text: 待合成的纯文本（不含 TTS 标记）
        ref_audio_path: 参考音频路径（声音克隆用，可选）
        output_path: 输出音频保存路径
        workflow_template: ComfyUI API 格式的 IndexTTS2 工作流模板 JSON
        overrides: 需要覆盖工作流模板的额外参数（如 speed 等）
        timeout: 总超时秒数（TTS 通常比视频快，默认 300s）

    返回:
        包含 prompt_id、output 路径等信息的字典
    """
    logger.info("[comfyui-tts] start: text=%d chars, ref_audio=%s", len(text), ref_audio_path)

    # 上传参考音频（如有）
    ref_audio_info: Optional[Dict[str, str]] = None
    if ref_audio_path and Path(ref_audio_path).exists():
        with _make_client(timeout=60.0) as upload_client:
            ref_audio_info = _upload_file(upload_client, Path(ref_audio_path))
            logger.info("[comfyui-tts] uploaded ref audio: %s", ref_audio_info)

    # 构建工作流
    workflow = _patch_tts_workflow(workflow_template, text, ref_audio_info, overrides)

    # 提交
    with _make_client(timeout=30.0) as submit_client:
        prompt_id = _submit_prompt(submit_client, workflow)
        logger.info("[comfyui-tts] submitted prompt_id=%s", prompt_id)

    # 轮询 + 下载
    with _make_client(timeout=30.0) as poll_client:
        entry = _poll_history(poll_client, prompt_id, timeout=timeout, cancel_event=cancel_event)
        logger.info("[comfyui-tts] prompt %s completed", prompt_id)

        file_info = _find_output_audio(entry)
        if not file_info:
            raise ComfyUIError("TTS 工作流完成但未找到输出音频节点")
        logger.info("[comfyui-tts] output audio: %s", file_info)

        _download_audio(poll_client, file_info, output_path)
        logger.info("[comfyui-tts] downloaded to %s (%d bytes)", output_path, output_path.stat().st_size)

    return {
        "prompt_id": prompt_id,
        "output": str(output_path),
        "audio_info": file_info,
    }
