"""Shared OpenAI-compatible client and image provider runtime."""

from __future__ import annotations

import base64
import json
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
import generation_governor
from generation_governor import RESOURCE_IMAGE


logger = logging.getLogger("PPTStudio.AIProvider")


# 1K 分辨率下的标准比例 → 像素尺寸映射（16:9 → 1280x720，9:16 → 720x1280）。
# 用户在模型设置中可以填写比例（如 "9:16"、"16:9"），这里统一解析为 1K 像素
# 尺寸，避免冒号分隔的比例被 normalize 后无法解析而回退到默认横屏 16:9。
_RATIO_TO_PIXELS: dict[str, str] = {
    "16:9": "1280x720",
    "9:16": "720x1280",
}


def normalize_image_size(size: Optional[str]) -> Optional[str]:
    """归一化生图尺寸参数，兼容全角乘号/空格/大写 X 以及比例写法。

    OpenAI 兼容 API 要求尺寸为 "auto" 或 "WIDTHxHEIGHT"（半角小写 x）。
    用户在设置里可能输入 "1536×864"（全角乘号）或 "1536X864"（大写 X），
    也可能直接填写比例 "9:16" / "16:9"。冒号分隔的比例会被解析为 1K 分辨率
    的像素尺寸（16:9 → 1280x720，9:16 → 720x1280），否则会因无法
    split('x') 而回退到默认横屏 16:9。
    """
    if not size:
        return size
    text = str(size).strip()
    if text.lower() == "auto":
        return "auto"
    # 先把冒号/斜杠比例归一为冒号形式，便于查表。
    normalized_ratio = (
        text.replace("/", ":")
        .replace(" ", "")
        .lower()
    )
    if ":" in normalized_ratio and normalized_ratio in _RATIO_TO_PIXELS:
        return _RATIO_TO_PIXELS[normalized_ratio]
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
TOAPIS_DEFAULT_TASK_TIMEOUT_SECONDS = 600
TOAPIS_MAX_TASK_TIMEOUT_SECONDS = 600
# 轮询退避：一次生图任务的状态查询会占用网关额度（500 请求/分钟是**网关全局**的）。
# 固定 5 秒轮询在 60 秒生成下要 12 次请求，指数退避只要 4-5 次，
# 把省下的额度留给真正并发的生图请求。
TOAPIS_POLL_INITIAL_SEC = 5.0
TOAPIS_POLL_BACKOFF_FACTOR = 1.6
TOAPIS_POLL_MAX_SEC = 30.0
# 撞上游限流时的有界重试次数：超过后抛给上层质量门（降级为暂停而不是硬失败）。
IMAGE_RATE_LIMIT_MAX_ATTEMPTS = 3
# httpx 不会因 4xx/5xx 抛异常，ToAPIs 的限流是以状态码返回的。
# 503 一并视为"上游过载、可退避重试"。
IMAGE_RATE_LIMIT_STATUS_CODES = frozenset({429, 503})


def _reraise_if_rate_limited(error: Exception) -> None:
    """限流不是"参数不兼容"，不能被降级重试链吞掉。

    参数兼容回退链会捕获所有异常；若不在这里拦住，一次 429 会退化成
    "换一组参数再打一次"，请求数翻倍且掩盖真实的限流原因。
    """
    if generation_governor.is_rate_limit_error(error):
        raise error


def _governed_image_request(
    base_url: Optional[str],
    call: Any,
    *,
    retry_on_rate_limit: bool = True,
) -> Any:
    """在网关预算内执行一次上游生图请求。

    每次调用先从治理器扣 1 个令牌（额度是**网关全局**的，所有账号/项目共享），
    因此请求速率不会再随项目数线性叠加。撞到 429 时登记 AIMD 降档并退避重试，
    退避期间不占用并发许可。

    注意：httpx 默认不对 4xx/5xx 抛异常，ToAPIs 的 429 是以**状态码**返回的，
    所以这里必须同时处理"抛出的异常"和"返回的限流状态码"，否则限流会被
    当成普通失败直接上抛，既不退避也不计入 AIMD。
    """
    governor = generation_governor.get_generation_governor()
    attempt = 0
    while True:
        rate_limit_error: Optional[Exception] = None
        try:
            with governor.request(RESOURCE_IMAGE, base_url):
                response = call()
        except Exception as error:
            if not retry_on_rate_limit or not generation_governor.is_rate_limit_error(error):
                raise
            rate_limit_error = error
        else:
            status = getattr(response, "status_code", None)
            if retry_on_rate_limit and status in IMAGE_RATE_LIMIT_STATUS_CODES:
                rate_limit_error = RuntimeError(
                    f"上游返回 HTTP {status}（限流/过载），需要在网关额度内退避重试"
                )
            else:
                governor.note_success(RESOURCE_IMAGE, base_url)
                return response

        attempt += 1
        if attempt > IMAGE_RATE_LIMIT_MAX_ATTEMPTS:
            raise rate_limit_error
        delay = governor.record_rate_limit(
            RESOURCE_IMAGE,
            base_url,
            error=rate_limit_error,
            attempt=attempt - 1,
        )
        logger.warning(
            "生图网关限流，%.1f 秒后重试（第 %s/%s 次）：%s",
            delay,
            attempt,
            IMAGE_RATE_LIMIT_MAX_ATTEMPTS,
            rate_limit_error,
        )
        time.sleep(delay)


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


def _toapis_safe_diagnostic(value: Any, api_key: str) -> str:
    """Return a bounded task-status diagnostic without credential values."""
    sensitive_keys = {
        "api_key", "apikey", "authorization", "password", "secret", "token",
        "access_token", "refresh_token",
    }

    def sanitize(item: Any, key: Optional[str] = None) -> Any:
        if key and key.lower() in sensitive_keys:
            return "[REDACTED]"
        if isinstance(item, dict):
            return {
                str(child_key): sanitize(child_value, str(child_key))
                for child_key, child_value in item.items()
            }
        if isinstance(item, (list, tuple)):
            return [sanitize(child) for child in item]
        if isinstance(item, str):
            safe_text = item.replace(api_key, "[REDACTED]") if api_key else item
            return safe_text[:800]
        if isinstance(item, (str, int, float, bool)) or item is None:
            return item
        return str(item)[:800]

    try:
        return json.dumps(sanitize(value), ensure_ascii=False, separators=(",", ":"))[:1600]
    except (TypeError, ValueError):
        return "[unserializable status]"


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
    timeout: int = TOAPIS_DEFAULT_TASK_TIMEOUT_SECONDS,
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

            def _upload_reference(path: str = path) -> httpx.Response:
                with open(path, "rb") as source:
                    return client.post(
                        f"{root}/v1/uploads/images",
                        headers=headers,
                        files={"file": (os.path.basename(path), source, "image/png")},
                    )

            upload = _governed_image_request(base_url, _upload_reference)
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
        }
        if reference_urls:
            payload["reference_images"] = reference_urls
        created = _governed_image_request(
            base_url,
            lambda: client.post(
                f"{root}/v1/images/generations",
                headers={**headers, "Content-Type": "application/json"},
                json=payload,
            ),
        )
        try:
            task = created.json()
        except ValueError:
            task = {"message": created.text[:800]}
        if created.status_code >= 400 or (isinstance(task, dict) and task.get("success") is False):
            raise _toapis_error(created, task)
        task_id = task.get("id") if isinstance(task, dict) else None
        if not isinstance(task_id, str) or not task_id:
            raise RuntimeError("ToAPIs 创建图片任务未返回任务 ID")
        try:
            task_timeout = int(timeout or TOAPIS_DEFAULT_TASK_TIMEOUT_SECONDS)
        except (TypeError, ValueError):
            task_timeout = TOAPIS_DEFAULT_TASK_TIMEOUT_SECONDS
        task_timeout = max(30, min(task_timeout, TOAPIS_MAX_TASK_TIMEOUT_SECONDS))
        started_at = time.monotonic()
        deadline = started_at + task_timeout
        last_status: Any = None
        poll_interval = TOAPIS_POLL_INITIAL_SEC
        while time.monotonic() < deadline:
            status_response = _governed_image_request(
                base_url,
                lambda: client.get(
                    f"{root}/v1/images/generations/{task_id}", headers=headers
                ),
            )
            try:
                status = status_response.json()
            except ValueError:
                status = {"message": status_response.text[:800]}
            if status_response.status_code >= 400:
                raise _toapis_error(status_response, status)
            last_status = status
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
            # 指数退避轮询：状态查询同样消耗网关额度，固定 5 秒会把额度吃掉一半。
            retry_after = status_response.headers.get("Retry-After")
            hinted = 0.0
            try:
                if retry_after:
                    hinted = max(TOAPIS_POLL_INITIAL_SEC, float(retry_after))
            except (TypeError, ValueError):
                hinted = 0.0
            poll_interval = min(
                TOAPIS_POLL_MAX_SEC,
                max(poll_interval * TOAPIS_POLL_BACKOFF_FACTOR, hinted),
            )
            remaining_seconds = deadline - time.monotonic()
            if remaining_seconds > 0:
                time.sleep(min(poll_interval + random.uniform(0, 0.5), remaining_seconds))
    waited_seconds = min(task_timeout, max(0, round(time.monotonic() - started_at)))
    raise RuntimeError(
        "ToAPIs 图片任务等待超时: "
        f"task_id={_toapis_safe_diagnostic(task_id, api_key)}, "
        f"waited_seconds={waited_seconds}, "
        f"last_status={_toapis_safe_diagnostic(last_status, api_key)}"
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
            reference_paths=reference_paths,
            timeout=(
                timeout
                if timeout is not None
                else TOAPIS_DEFAULT_TASK_TIMEOUT_SECONDS
            ),
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

    def _generate(**call_kwargs: Any) -> Any:
        # 每次 images.generate 都占用网关额度，必须计费并排队。
        return _governed_image_request(
            base_url,
            lambda: client.images.generate(**call_kwargs),
        )

    if seedream_mode:
        try:
            return _generate(
                **kwargs,
                size=size,
                response_format="b64_json",
            )
        except Exception as response_format_error:
            _reraise_if_rate_limited(response_format_error)
            logger.warning(
                "Seedream image generation with response_format "
                "failed, retrying without it: %s",
                response_format_error,
            )
            try:
                return _generate(
                    **kwargs,
                    size=size,
                )
            except Exception as size_error:
                _reraise_if_rate_limited(size_error)
                logger.warning(
                    "Seedream image generation with size failed, "
                    "retrying minimal params: %s",
                    size_error,
                )
                return _generate(**kwargs)

    try:
        return _generate(
            **kwargs,
            size=size,
            quality="standard",
        )
    except Exception as full_params_error:
        _reraise_if_rate_limited(full_params_error)
        logger.warning(
            "Image gen with full params failed (%s). Retrying "
            "with size only for compatible providers...",
            full_params_error,
        )
        try:
            return _generate(
                **kwargs,
                size=size,
            )
        except Exception as size_error:
            _reraise_if_rate_limited(size_error)
            logger.warning(
                "Image gen with size failed (%s). Retrying "
                "minimal params...",
                size_error,
            )
            return _generate(**kwargs)
