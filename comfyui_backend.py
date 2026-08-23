# -*- coding: utf-8 -*-
"""ComfyUI 后端：上传图片+音频 → 提交 Wan2.2 S2V 工作流 → 轮询 → 下载视频。

通过 ComfyUI 的 HTTP API（/upload/image、/prompt、/history、/view）驱动
数字人对口型工作流。所有 httpx 调用均设置 trust_env=False 以避免代理干扰。
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("PPTStudio.ComfyUIBackend")

# 工作流模板中需要动态注入文件名的节点 ID 映射
# 这些 ID 来自用户提供的 Wan2.2 S2V API 格式工作流 JSON
# 画质参数（分辨率/步数/CFG 等）由用户在工作流 JSON 中直接设定，此处不覆盖
NODE_IDS = {
    "load_image": "252",
    "load_audio": "254",
    "video_combine": "278",
}


class ComfyUIError(RuntimeError):
    """ComfyUI 调用异常。"""


def get_comfyui_url() -> str:
    """获取 ComfyUI 服务地址（默认 http://127.0.0.1:8188）。"""
    return os.environ.get("PPT_COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/")


def _make_client(timeout: float = 30.0) -> httpx.Client:
    """创建禁用环境代理的 httpx 客户端。"""
    return httpx.Client(
        base_url=get_comfyui_url(),
        timeout=timeout,
        trust_env=False,   # 关键：不继承系统代理，避免 localhost 被 Clash 劫持
    )


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

    nid = NODE_IDS
    # 只注入必须动态变化的输入文件名
    wf[nid["load_image"]]["inputs"]["image"] = image_info["name"]
    wf[nid["load_audio"]]["inputs"]["audio"] = audio_info["name"]
    # 清除可能残留的 audioUI 路径
    wf[nid["load_audio"]]["inputs"].pop("audioUI", None)

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
) -> Dict[str, Any]:
    """轮询 /history/{prompt_id}，返回完成的 history 条目。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
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
        time.sleep(poll_interval)
    raise ComfyUIError(f"等待 ComfyUI 结果超时（{timeout:.0f}s）")


def _find_output_video(entry: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """从 history 条目中提取输出视频的下载信息。"""
    outputs = entry.get("outputs", {})
    vc_id = NODE_IDS["video_combine"]
    node_out = outputs.get(vc_id) or outputs.get(str(vc_id))
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
        entry = _poll_history(poll_client, prompt_id, timeout=timeout)
        logger.info("[comfyui] prompt %s completed", prompt_id)

        file_info = _find_output_video(entry)
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
