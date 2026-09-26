"""Bounded retry policy for single-slide image generation.

职责边界
--------
本模块只回答三个问题：**还能不能重试、要等多久、等待是否超出预算**。
它不创建新的并发门或令牌桶 —— 网关额度与并发仍由 ``generation_governor``
唯一负责，每次真实上游请求在 provider 层重新申请额度。

可注入性
--------
退避抖动使用调用方注入的 ``random``（默认标准库 ``random.uniform``），
测试注入确定性的伪随机源即可表驱动验证，无需真实等待。
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import random as _random
from typing import Any, Callable, Optional

from image_generation_errors import (
    CODE_GATEWAY_BUSY,
    ImageGenerationErrorInfo,
    recoverable_codes,
)


@dataclass(frozen=True)
class ImageRetryPolicy:
    """单页生图的有界重试预算（初始默认值，非供应商真实限额）。"""

    enabled: bool = True
    max_generation_attempts: int = 3          # 首次请求 + 最多 2 次重新生成
    initial_backoff_sec: float = 5.0
    max_backoff_sec: float = 60.0
    jitter_sec: float = 2.0
    max_download_attempts: int = 3            # 复用同一结果地址的下载重试
    download_backoff_sec: float = 2.0
    total_budget_sec: float = 900.0           # 单页总执行预算（排队+请求+轮询+退避）

    @classmethod
    def from_environment(cls, env: Any = None) -> "ImageRetryPolicy":
        environ = os.environ if env is None else env

        def _float(name: str, default: float, minimum: float, maximum: float) -> float:
            try:
                value = float(str(environ.get(name, "")).strip())
            except (TypeError, ValueError):
                return default
            return max(minimum, min(maximum, value))

        def _int(name: str, default: int, minimum: int, maximum: int) -> int:
            try:
                value = int(str(environ.get(name, "")).strip())
            except (TypeError, ValueError):
                return default
            return max(minimum, min(maximum, value))

        enabled = str(environ.get("PPT_STUDIO_IMAGE_RETRY_ENABLED", "1")).strip().lower() not in {
            "0",
            "false",
            "off",
            "no",
        }
        return cls(
            enabled=enabled,
            max_generation_attempts=_int(
                "PPT_STUDIO_IMAGE_RETRY_MAX_ATTEMPTS", 3, 1, 8
            ),
            initial_backoff_sec=_float(
                "PPT_STUDIO_IMAGE_RETRY_INITIAL_BACKOFF_SEC", 5.0, 0.0, 300.0
            ),
            max_backoff_sec=_float(
                "PPT_STUDIO_IMAGE_RETRY_MAX_BACKOFF_SEC", 60.0, 1.0, 600.0
            ),
            jitter_sec=_float(
                "PPT_STUDIO_IMAGE_RETRY_JITTER_SEC", 2.0, 0.0, 60.0
            ),
            max_download_attempts=_int(
                "PPT_STUDIO_IMAGE_RETRY_DOWNLOAD_ATTEMPTS", 3, 1, 8
            ),
            total_budget_sec=_float(
                "PPT_STUDIO_IMAGE_RETRY_BUDGET_SEC", 900.0, 30.0, 7200.0
            ),
        )


@dataclass(frozen=True)
class RetryVerdict:
    """一次失败后的重试裁决。``retry=False`` 时 ``reason`` 说明停因。"""

    retry: bool
    delay_sec: float = 0.0
    recoverable: bool = False
    reason: str = ""

    @property
    def no_retry_reason(self) -> str:
        return self.reason


def compute_backoff(
    attempt: int,
    policy: ImageRetryPolicy,
    info: ImageGenerationErrorInfo,
    *,
    random_source: Callable[[float, float], float] = _random.uniform,
) -> float:
    """指数退避 + 随机抖动；上游给了 ``Retry-After`` 则尊重它。

    返回值保证 ``0 <= delay <= policy.max_backoff_sec``，且随机抖动让多张
    失败图片不会在同一瞬间重试。
    """
    if info.retry_after_seconds is not None and info.retry_after_seconds > 0:
        return float(min(policy.max_backoff_sec, info.retry_after_seconds))
    safe_attempt = max(0, int(attempt) - 1)
    delay = policy.initial_backoff_sec * (2 ** safe_attempt)
    delay = min(delay, policy.max_backoff_sec)
    if policy.jitter_sec > 0:
        delay += max(0.0, float(random_source(0.0, policy.jitter_sec)))
    return float(min(delay, policy.max_backoff_sec * 1.5))


def decide_retry(
    info: ImageGenerationErrorInfo,
    *,
    attempt: int,
    policy: ImageRetryPolicy,
    remaining_sec: float,
    cancelled: Optional[Callable[[], bool]] = None,
    random_source: Callable[[float, float], float] = _random.uniform,
) -> RetryVerdict:
    """判定一次失败后是否继续、等待多久。

    - 只对明确可重试的错误自动重试（未知程序错误默认不重试）。
    - 重试次数有上限（``max_generation_attempts``）。
    - 等待时长受该页剩余预算约束：``Retry-After`` 或退避超过剩余预算时
      结束本轮并标记**可恢复**（继续任务可补齐），绝不提前强行请求。
    - 治理器排队超时（``gateway_busy``）不自动重试：它意味着额度紧张，
      重新排队只会重复占用预算，应当暂停并等待用户继续。
    """
    if cancelled is not None:
        try:
            if cancelled():
                return RetryVerdict(
                    retry=False,
                    recoverable=True,
                    reason="cancelled",
                )
        except Exception:
            pass
    if not policy.enabled:
        return RetryVerdict(
            retry=False,
            recoverable=info.code in recoverable_codes() or info.retryable,
            reason="auto_retry_disabled",
        )
    if not info.retryable:
        return RetryVerdict(
            retry=False,
            recoverable=info.code in recoverable_codes(),
            reason=f"not_retryable:{info.code}",
        )
    if info.code == CODE_GATEWAY_BUSY:
        # 额度排队超时属于"上游忙"：标记可恢复，交给用户继续，不绕过额度。
        return RetryVerdict(
            retry=False,
            recoverable=True,
            reason="gateway_busy",
        )
    if attempt >= max(1, int(policy.max_generation_attempts)):
        return RetryVerdict(
            retry=False,
            recoverable=True,
            reason="attempts_exhausted",
        )
    delay = compute_backoff(attempt, policy, info, random_source=random_source)
    remaining = max(0.0, float(remaining_sec))
    if delay >= remaining:
        return RetryVerdict(
            retry=False,
            recoverable=True,
            reason="budget_exhausted",
        )
    return RetryVerdict(retry=True, delay_sec=delay)


def decide_download_retry(
    info: ImageGenerationErrorInfo,
    *,
    attempt: int,
    policy: ImageRetryPolicy,
    remaining_sec: float,
    random_source: Callable[[float, float], float] = _random.uniform,
) -> RetryVerdict:
    """下载失败的独立小预算：复用同一结果地址，不重新调用生图接口。"""
    if not info.retryable:
        return RetryVerdict(retry=False, recoverable=False, reason=f"not_retryable:{info.code}")
    if attempt >= max(1, int(policy.max_download_attempts)):
        return RetryVerdict(retry=False, recoverable=True, reason="download_attempts_exhausted")
    delay = compute_backoff(attempt, policy, info, random_source=random_source)
    if delay >= max(0.0, float(remaining_sec)):
        return RetryVerdict(retry=False, recoverable=True, reason="budget_exhausted")
    return RetryVerdict(retry=True, delay_sec=delay)
