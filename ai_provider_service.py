"""Shared OpenAI-compatible client and image provider runtime."""

from __future__ import annotations

import base64
import math
import io
import logging
import os
import random
import time
from typing import Any, Dict, Optional
import warnings

import httpx
from openai import OpenAI
from PIL import Image

from scripts.background_color import normalize_connected_background


logger = logging.getLogger("PPTStudio.AIProvider")


def normalize_image_size(size: Optional[str]) -> Optional[str]:
    """归一化生图尺寸参数，兼容全角乘号/空格/大写 X。

    OpenAI 兼容 API 要求尺寸为 "auto" 或 "WIDTHxHEIGHT"（半角小写 x）。
    用户在设置里可能输入 "1536×864"（全角乘号）或 "1536X864"（大写 X），
    若不归一化，images/edits（携带 IP 参考图）会返回 400 被回退丢弃，
    导致 IP 参考图丢失、生图反复重试超时。这里统一转成半角小写 x 形式。
    """
    if not size:
        return size
    text = str(size).strip()
    if text.lower() == "auto":
        return "auto"
    text = (
        text.replace("\u00d7", "x")   # ×
        .replace("\uff38", "x")       # Ｘ 全角大写
        .replace("X", "x")
        .replace("*", "x")
        .replace(" ", "")
    )
    return text



MAX_IMAGE_UPLOAD_BYTES = int(
    os.environ.get(
        "PPT_STUDIO_MAX_IMAGE_UPLOAD_BYTES",
        str(20 * 1024 * 1024),
    )
)
MAX_IMAGE_PIXELS = int(
    os.environ.get("PPT_STUDIO_MAX_IMAGE_PIXELS", "50000000")
)


def get_openai_client(
    api_key: str,
    base_url: Optional[str] = None,
    timeout: float = 120.0,
    max_retries: int = 1,
) -> OpenAI:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    limits = httpx.Limits(
        max_keepalive_connections=5,
        max_connections=10,
    )
    http_client = httpx.Client(
        limits=limits,
        trust_env=False,
        headers=headers,
        timeout=timeout,
    )
    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        http_client=http_client,
        timeout=timeout,
        max_retries=max_retries,
    )


class ImagePayloadTooLarge(ValueError):
    """上传图片超出字节上限；HTTP 层应映射为 413（审查 L-07）。"""


def open_validated_image(image_bytes: bytes) -> Image.Image:
    if not image_bytes:
        raise ValueError("图片文件为空")
    if len(image_bytes) > MAX_IMAGE_UPLOAD_BYTES:
        raise ImagePayloadTooLarge(
            "图片文件超过 "
            f"{MAX_IMAGE_UPLOAD_BYTES // (1024 * 1024)} MB 限制"
        )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter(
                "error",
                Image.DecompressionBombWarning,
            )
            image = Image.open(io.BytesIO(image_bytes))
            if (
                image.width <= 0
                or image.height <= 0
                or image.width * image.height > MAX_IMAGE_PIXELS
            ):
                image.close()
                raise ValueError(
                    f"图片像素总量超过 {MAX_IMAGE_PIXELS} 限制"
                )
            image.load()
            return image
    except ValueError:
        raise
    except (
        Image.UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
    ) as exc:
        raise ValueError("无法识别或不安全的图片文件") from exc


def process_and_save_image(
    image_bytes: bytes,
    save_path: str,
    target_width: int = 1920,
    target_height: int = 1080,
) -> None:
    bg_color = (255, 255, 255)
    target_width = max(1, int(target_width))
    target_height = max(1, int(target_height))

    image = open_validated_image(image_bytes)
    if image.mode in ("RGBA", "LA") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        white = Image.new("RGBA", rgba.size, (*bg_color, 255))
        white.alpha_composite(rgba)
        image = white.convert("RGB")
    elif image.mode != "RGB":
        image = image.convert("RGB")

    source_width, source_height = image.width, image.height
    image_ratio = image.width / image.height
    target_ratio = target_width / target_height

    if image_ratio > target_ratio:
        new_width = target_width
        new_height = int(target_width / image_ratio)
    else:
        new_height = target_height
        new_width = int(target_height * image_ratio)

    resized_image = image.resize(
        (new_width, new_height),
        Image.Resampling.LANCZOS,
    )
    final_image = Image.new(
        "RGB",
        (target_width, target_height),
        bg_color,
    )
    paste_x = (target_width - new_width) // 2
    paste_y = (target_height - new_height) // 2
    final_image.paste(resized_image, (paste_x, paste_y))
    final_image, _ = normalize_connected_background(
        final_image,
        bg_color,
    )

    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    final_image.save(save_path, "PNG")
    logger.info(
        "Image normalized and saved: source=%sx%s "
        "fitted=%sx%s canvas=%sx%s path=%s",
        source_width,
        source_height,
        new_width,
        new_height,
        target_width,
        target_height,
        save_path,
    )


def enforce_white_image_region(
    image_path: str,
    *,
    top: int,
    bottom: int,
    white_threshold: int = 248,
) -> Dict[str, Any]:
    """Measure and then clear a production-owned white region.

    Prompt rules reduce violations, but generated pixels are never trusted as a
    layout guarantee.  The returned ratio is logged by the workflow so a model
    that repeatedly draws into the subtitle band remains observable.
    """
    with Image.open(image_path) as source:
        image = source.convert("RGB")
    top = max(0, min(image.height, int(top)))
    bottom = max(top, min(image.height, int(bottom)))
    if bottom <= top:
        return {"top": top, "bottom": bottom, "nonwhite_ratio": 0.0, "cleared": False}
    region = image.crop((0, top, image.width, bottom))
    # ``get_flattened_data`` was removed by newer Pillow releases. ``getdata``
    # provides the same row-major RGB iterator across supported versions.
    pixels = region.getdata()
    total = max(1, region.width * region.height)
    nonwhite = sum(
        1 for red, green, blue in pixels
        if min(red, green, blue) < white_threshold
    )
    ratio = nonwhite / total
    image.paste((255, 255, 255), (0, top, image.width, bottom))
    image.save(image_path, "PNG")
    return {
        "top": top,
        "bottom": bottom,
        "nonwhite_ratio": round(ratio, 6),
        "cleared": nonwhite > 0,
    }


def is_seedream_image_model(
    model: Optional[str],
    base_url: Optional[str] = None,
) -> bool:
    """Detect Seedream models behind OpenAI-compatible APIs."""
    text = f"{model or ''} {base_url or ''}".lower()
    return any(
        marker in text
        for marker in (
            "seedream",
            "doubao",
            "volcengine",
            "volces",
            "ark.cn",
            "ark.volc",
        )
    )


def is_toapis_image_provider(provider: Optional[str], base_url: Optional[str] = None) -> bool:
    """Identify the native ToAPIs asynchronous image transport."""
    return str(provider or "").strip().lower() == "toapis" or "toapis." in str(base_url or "").lower()


def _toapis_base_url(base_url: Optional[str]) -> str:
    return (str(base_url or "").strip() or "https://toapis.cn").rstrip("/")


def _toapis_ratio(size: Optional[str]) -> str:
    value = normalize_image_size(size) or "16x9"
    if value == "auto":
        return value
    try:
        width, height = (int(part) for part in value.split("x", 1))
        divisor = math.gcd(width, height)
        return f"{width // divisor}:{height // divisor}"
    except (TypeError, ValueError):
        return "16:9"


def _toapis_error(response: httpx.Response, payload: Any) -> RuntimeError:
    detail = payload.get("message") if isinstance(payload, dict) else None
    if not detail and isinstance(payload, dict):
        error = payload.get("error")
        detail = error.get("message") if isinstance(error, dict) else error
    return RuntimeError(f"ToAPIs HTTP {response.status_code}: {str(detail or payload)[:800]}")


def generate_toapis_image_response(
    *,
    api_key: str,
    base_url: Optional[str],
    model: str,
    prompt: str,
    size: Optional[str],
    resolution: str = "1k",
    quality: str = "low",
    reference_paths: Optional[list[str]] = None,
    timeout: int = 180,
) -> dict[str, Any]:
    """Upload local references, submit a ToAPIs task, then retain its result URL.

    ToAPIs deliberately rejects base64 references, unlike the OpenAI Images
    API.  The adapter therefore performs the documented upload -> task ->
    status polling sequence and returns the normal ``data[0].url`` shape used
    by the rest of the image workflow.
    """
    if not api_key:
        raise RuntimeError("ToAPIs 缺少 API Key")
    root = _toapis_base_url(base_url)
    headers = {"Authorization": f"Bearer {api_key}"}
    reference_urls: list[str] = []
    with httpx.Client(timeout=30, trust_env=False, follow_redirects=True) as client:
        for path in reference_paths or []:
            with open(path, "rb") as source:
                upload = client.post(f"{root}/v1/uploads/images", headers=headers, files={"file": (os.path.basename(path), source, "image/png")})
            try:
                upload_body = upload.json()
            except ValueError:
                upload_body = {"message": upload.text[:800]}
            if upload.status_code >= 400 or not upload_body.get("success", False):
                raise _toapis_error(upload, upload_body)
            url = ((upload_body.get("data") or {}).get("url"))
            if not isinstance(url, str) or not url.strip():
                raise RuntimeError("ToAPIs 上传参考图未返回 URL")
            reference_urls.append(url)
        payload: dict[str, Any] = {
            "model": model or "gpt-image-2-vip",
            "prompt": prompt,
            "n": 1,
            "size": _toapis_ratio(size),
            "resolution": resolution if resolution in {"1k", "2k", "4k"} else "2k",
            "quality": quality if quality in {"low", "medium", "high"} else "high",
            "response_format": "url",
        }
        if reference_urls:
            payload["reference_images"] = reference_urls
        created = client.post(f"{root}/v1/images/generations", headers={**headers, "Content-Type": "application/json"}, json=payload)
        try:
            task = created.json()
        except ValueError:
            task = {"message": created.text[:800]}
        if created.status_code >= 400 or (isinstance(task, dict) and task.get("success") is False):
            raise _toapis_error(created, task)
        task_id = task.get("id") if isinstance(task, dict) else None
        if not isinstance(task_id, str) or not task_id:
            raise RuntimeError("ToAPIs 创建图片任务未返回任务 ID")
        deadline = time.monotonic() + max(30, min(int(timeout or 180), 300))
        while time.monotonic() < deadline:
            status_response = client.get(f"{root}/v1/images/generations/{task_id}", headers=headers)
            try:
                status = status_response.json()
            except ValueError:
                status = {"message": status_response.text[:800]}
            if status_response.status_code >= 400:
                raise _toapis_error(status_response, status)
            state = str(status.get("status") or "").lower()
            if state == "completed":
                result = status.get("result") or {}
                items = result.get("data") if isinstance(result, dict) else []
                url = items[0].get("url") if isinstance(items, list) and items and isinstance(items[0], dict) else status.get("url")
                if isinstance(url, str) and url:
                    return {"data": [{"url": url}], "toapis_task_id": task_id}
                raise RuntimeError("ToAPIs 图片任务完成但未返回图片 URL")
            if state == "failed":
                raise RuntimeError(f"ToAPIs 图片任务失败: {str((status.get('error') or {}).get('message') or status.get('fail_reason') or '未知错误')[:800]}")
            retry_after = status_response.headers.get("Retry-After")
            try:
                wait_seconds = max(5.0, float(retry_after)) if retry_after else 5.0
            except ValueError:
                wait_seconds = 5.0
            time.sleep(wait_seconds + random.uniform(0, 0.5))
    raise RuntimeError("ToAPIs 图片任务等待超时")


def first_image_response_item(response: Any) -> Any:
    data = (
        response.get("data")
        if isinstance(response, dict)
        else getattr(response, "data", None)
    )
    if not data:
        return None
    return data[0]


def image_response_value(item: Any, key: str) -> Any:
    if item is None:
        return None
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def response_has_image_data(response: Any) -> bool:
    first_item = first_image_response_item(response)
    return bool(
        image_response_value(first_item, "b64_json")
        or image_response_value(first_item, "url")
    )


def extract_image_bytes_from_response(response: Any) -> bytes:
    """Read image bytes from b64_json or URL response fields."""
    first_item = first_image_response_item(response)
    b64_json = image_response_value(first_item, "b64_json")
    if b64_json:
        b64_text = str(b64_json)
        if (
            "," in b64_text
            and b64_text.strip().startswith("data:")
        ):
            b64_text = b64_text.split(",", 1)[1]
        return base64.b64decode(b64_text)

    image_url = image_response_value(first_item, "url")
    if image_url:
        logger.info(
            "Image URL received, downloading generated asset."
        )
        with httpx.Client(
            timeout=60,
            trust_env=False,
        ) as http_client:
            image_response = http_client.get(str(image_url))
        if image_response.status_code != 200:
            raise RuntimeError(
                "下载生成图片失败: "
                f"HTTP {image_response.status_code}"
            )
        return image_response.content

    raise RuntimeError(
        "API 响应中既没有 url 也没有 b64_json，无法获取图片数据。"
    )


def generate_image_response(
    client: Optional[OpenAI],
    model: str,
    prompt: str,
    size: str,
    base_url: Optional[str] = None,
    timeout: Optional[int] = None,
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    reference_paths: Optional[list[str]] = None,
    public_config: Optional[Dict[str, Any]] = None,
) -> Any:
    """Generate an image with provider-specific fallbacks."""
    if is_toapis_image_provider(provider, base_url):
        config = public_config or {}
        return generate_toapis_image_response(
            api_key=str(api_key or ""), base_url=base_url, model=model,
            prompt=prompt, size=size,
            resolution=str(config.get("toapis_resolution") or "1k"),
            quality=str(config.get("toapis_quality") or "low"),
            reference_paths=reference_paths, timeout=timeout or 180,
        )
    if client is None:
        raise RuntimeError("图片服务客户端未初始化")
    seedream_mode = is_seedream_image_model(model, base_url)
    kwargs: Dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "n": 1,
    }
    if timeout:
        kwargs["timeout"] = timeout

    if seedream_mode:
        try:
            return client.images.generate(
                **kwargs,
                size=size,
                response_format="b64_json",
            )
        except Exception as response_format_error:
            logger.warning(
                "Seedream image generation with response_format "
                "failed, retrying without it: %s",
                response_format_error,
            )
            try:
                return client.images.generate(
                    **kwargs,
                    size=size,
                )
            except Exception as size_error:
                logger.warning(
                    "Seedream image generation with size failed, "
                    "retrying minimal params: %s",
                    size_error,
                )
                return client.images.generate(**kwargs)

    try:
        return client.images.generate(
            **kwargs,
            size=size,
            quality="standard",
        )
    except Exception as full_params_error:
        logger.warning(
            "Image gen with full params failed (%s). Retrying "
            "with size only for compatible providers...",
            full_params_error,
        )
        try:
            return client.images.generate(
                **kwargs,
                size=size,
            )
        except Exception as size_error:
            logger.warning(
                "Image gen with size failed (%s). Retrying "
                "minimal params...",
                size_error,
            )
            return client.images.generate(**kwargs)
