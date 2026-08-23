# -*- coding: utf-8 -*-
"""主系统 → 数字人推理服务 的 HTTP 客户端。

数字人服务（digital_human_service.py）默认运行在 http://127.0.0.1:9001，
地址可用环境变量 PPT_DIGITAL_HUMAN_SERVICE_URL 覆盖。

所有 HTTP 调用均使用 trust_env=False 的持久 httpx.Client，确保
127.0.0.1 / localhost 请求不受系统代理或 HTTP_PROXY / HTTPS_PROXY 等环境变量
干扰 —— 否则当代理（如 Clash Verge）在线时，localhost 请求会被错误地
转发给代理，导致 502 Bad Gateway。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("PPTStudio.DigitalHumanClient")

DEFAULT_SERVICE_URL = os.environ.get(
    "PPT_DIGITAL_HUMAN_SERVICE_URL", "http://127.0.0.1:9001"
)


class DigitalHumanUnavailable(RuntimeError):
    """数字人服务不可用（未启动 / 模型未部署）。"""


class DigitalHumanClient:
    def __init__(self, base_url: str | None = None, timeout: float = 15.0):
        self.base_url = (base_url or DEFAULT_SERVICE_URL).rstrip("/")
        self._timeout = timeout
        # trust_env=False — 永不继承系统/环境代理，保证 localhost 直连。
        self._client = httpx.Client(trust_env=False)

    def _url(self, path: str) -> str:
        return f"{self.base_url}/api/digital-human{path}"

    def health(self) -> Dict[str, Any]:
        try:
            resp = self._client.get(self._url("/health"), timeout=self._timeout)
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise DigitalHumanUnavailable(
                f"数字人服务不可用（{self.base_url}）：{exc}"
            ) from exc

    def model_ready(self) -> bool:
        try:
            return bool(self.health().get("model_ready"))
        except DigitalHumanUnavailable:
            return False

    def upload_avatar(self, name: str, file_path: str | Path) -> Dict[str, Any]:
        with open(file_path, "rb") as f:
            resp = self._client.post(
                self._url("/avatars"),
                files={"file": (Path(file_path).name, f)},
                data={"name": name},
                timeout=300.0,
            )
        resp.raise_for_status()
        return resp.json()

    def list_avatars(self) -> list[Dict[str, Any]]:
        resp = self._client.get(self._url("/avatars"), timeout=self._timeout)
        resp.raise_for_status()
        data = resp.json()
        return data.get("avatars", [])

    def create_job(
        self,
        avatar_id: str = "",
        audio_path: str | Path = "",
        slide_id: str = "slide_000",
        sync_mode: str = "accurate",
        *,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """提交推理任务。

        可以传分散参数，也可以通过 payload 关键字传完整字典（含 ComfyUI 字段）。
        """
        if payload is not None:
            body = payload
        else:
            body = {
                "avatar_id": avatar_id,
                "audio_path": str(audio_path),
                "slide_id": slide_id,
                "sync_mode": sync_mode,
            }
        resp = self._client.post(
            self._url("/jobs"),
            json=body,
            timeout=self._timeout,
        )
        if resp.status_code == 503:
            try:
                resp_json = resp.json()
            except Exception:
                resp_json = {}
            raise DigitalHumanUnavailable(str(resp_json.get("detail", "模型未部署")))
        if resp.status_code >= 400:
            try:
                resp_json = resp.json()
            except Exception:
                resp_json = {}
            detail = resp_json.get("detail", "") if isinstance(resp_json, dict) else str(resp_json)
            raise DigitalHumanUnavailable(
                f"数字人服务返回 {resp.status_code}: {detail or resp.text[:200]}"
            )
        resp.raise_for_status()
        return resp.json()

    def get_job(self, job_id: str) -> Dict[str, Any]:
        resp = self._client.get(self._url(f"/jobs/{job_id}"), timeout=self._timeout)
        resp.raise_for_status()
        return resp.json()

    def download_result(self, job_id: str, dest: str | Path) -> Path:
        resp = self._client.get(self._url(f"/jobs/{job_id}/result"), timeout=300.0)
        resp.raise_for_status()
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)
        return dest

    def composite(
        self,
        *,
        digi_video: str | Path,
        base_video: str | Path | None,
        output: str | Path,
        circle: Dict[str, Any],
        position: Optional[Dict[str, Any]] = None,
        border: Optional[Dict[str, Any]] = None,
        video: Optional[Dict[str, Any]] = None,
        shape: str = "circle",
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "digi_video": str(digi_video),
            "output": str(output),
            "circle": circle,
            "shape": shape,
        }
        if base_video:
            payload["base_video"] = str(base_video)
        if position:
            payload["position"] = position
        if border:
            payload["border"] = border
        if video:
            payload["video"] = video
        resp = self._client.post(
            self._url("/composite"), json=payload, timeout=900.0
        )
        resp.raise_for_status()
        return resp.json()


_default_client: Optional[DigitalHumanClient] = None


def get_digital_human_client() -> DigitalHumanClient:
    global _default_client
    if _default_client is None:
        _default_client = DigitalHumanClient()
    return _default_client
