"""Shared OpenAI-compatible client and image provider runtime."""

from __future__ import annotations

import base64
import io
import logging
import os
from typing import Any, Dict, Optional
import warnings

import httpx
from openai import OpenAI
from PIL import Image

from scripts.background_color import normalize_connected_background


logger = logging.getLogger("PPTStudio.AIProvider")
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


def open_validated_image(image_bytes: bytes) -> Image.Image:
    if not image_bytes:
        raise ValueError("图片文件为空")
    if len(image_bytes) > MAX_IMAGE_UPLOAD_BYTES:
        raise ValueError(
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
) -> None:
    bg_color = (255, 255, 255)
    target_width, target_height = 1920, 1080

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
    client: OpenAI,
    model: str,
    prompt: str,
    size: str,
    base_url: Optional[str] = None,
    timeout: Optional[int] = None,
) -> Any:
    """Generate an image with provider-specific fallbacks."""
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
