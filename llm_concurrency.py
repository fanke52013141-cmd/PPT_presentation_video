"""Process-wide gate for concurrent outbound LLM chat-completion requests.

治理模型
--------
LLM 请求有两层约束，都必须按**真实请求数**计量：

1. ``llm_request_slot`` —— 项目级并发子配额（``llm_max_concurrency``，
   默认 2），约束单项目的扇出；
2. :mod:`generation_governor` —— 网关全局 RPM + 并发（键为
   ``(RESOURCE_LLM, gateway)``，所有项目/账号共享）。

:gfunc:`governed_llm_request` 把两层组合成"每次真实请求申请一次、结束即
释放"的单一入口。格式回退、JSON 修复是**独立的真实请求**，必须各自申请，
不能与首次请求合并计量。
"""

from __future__ import annotations

import functools
import threading
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Optional

import generation_governor

DEFAULT_LLM_MAX_CONCURRENCY = 2
LLM_MAX_CONCURRENCY_BOUNDS = (1, 4)

_setting_reader: Optional[Callable[[str, int, int, int], int]] = None


def configure_llm_concurrency(setting_reader: Callable[[str, int, int, int], int]) -> None:
    """Inject ``get_bounded_int_setting``-compatible reader (kept out of imports for tests)."""
    global _setting_reader
    _setting_reader = setting_reader


def _resolve_limit() -> int:
    if _setting_reader is not None:
        return _setting_reader("llm_max_concurrency", DEFAULT_LLM_MAX_CONCURRENCY, *LLM_MAX_CONCURRENCY_BOUNDS)
    from config_store import get_bounded_int_setting

    return get_bounded_int_setting(
        "llm_max_concurrency", DEFAULT_LLM_MAX_CONCURRENCY, *LLM_MAX_CONCURRENCY_BOUNDS
    )


class _LlmConcurrencyGate:
    """Condition-based slot counter so the configured limit can change at runtime."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._active = 0

    @contextmanager
    def slot(self) -> Iterator[None]:
        limit = max(1, _resolve_limit())
        with self._condition:
            while self._active >= limit:
                self._condition.wait()
            self._active += 1
        try:
            yield
        finally:
            with self._condition:
                self._active -= 1
                self._condition.notify_all()


_GATE = _LlmConcurrencyGate()


@contextmanager
def llm_request_slot() -> Iterator[None]:
    """Hold one shared LLM request slot; callers queue while the gate is full."""
    with _GATE.slot():
        yield


def with_llm_request_slot(func):
    """Decorate an entry-point request builder so the whole call holds one slot.

    Only outer entry points may use this: nested gated calls would deadlock at
    a limit of 1 because the gate is not re-entrant.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with llm_request_slot():
            return func(*args, **kwargs)

    return wrapper


@contextmanager
def governed_llm_request(base_url: Any = "") -> Iterator[None]:
    """按**一次真实请求**同时申请项目并发槽与网关全局额度。

    - 每次真实上游请求（含格式回退重试、JSON 修复请求）单独调用一次；
    - 请求结束即释放两层许可，排队/解析阶段不占用额度；
    - 排队等待受治理器全局 ``max_wait`` 约束，超时抛
      :class:`generation_governor.GovernorTimeout`（上游忙，可恢复）。
    """
    with llm_request_slot(), generation_governor.get_generation_governor().request(
        generation_governor.RESOURCE_LLM, base_url
    ):
        yield


# 会触发"去掉 response_format 再试一次"回退的异常，必须先排除这些
# 非参数类故障：429/认证错误/排队超时/服务端故障走治理与重试路径，
# 绝不能伪装成"参数不兼容"多打一次请求。
_FORMAT_INCOMPATIBILITY_MARKERS = (
    "response_format",
    "json_object",
    "json_schema",
    "invalid parameter",
    "invalid_parameter",
    "unknown parameter",
    "unrecognized",
    "not supported",
    "unsupported",
    "does not support",
    "must be one of",
)

_FORMAT_FALLBACK_EXCLUDED_MARKERS = (
    "429",
    "rate limit",
    "rate_limit",
    "too many requests",
    "quota exceeded",
    "401",
    "403",
    "unauthorized",
    "forbidden",
    "timeout",
    "timed out",
    "connection",
)


def is_llm_format_incompatibility(error: BaseException) -> bool:
    """判断异常是否属于"response_format 不被当前模型支持"。

    只有明确的参数/格式不兼容才值得去掉 ``response_format`` 重试一次；
    限流、认证错误、排队超时与网络故障一律返回 ``False``。
    """
    import generation_governor as _governor

    if isinstance(error, _governor.GovernorTimeout):
        return False
    name = type(error).__name__.lower()
    if "ratelimit" in name or "auth" in name or "timeout" in name:
        return False
    status = getattr(error, "status_code", None)
    if isinstance(status, int):
        if status in (401, 402, 403, 408, 429) or status >= 500:
            return False
    text = f"{type(error).__name__}: {error}".lower()
    if any(marker in text for marker in _FORMAT_FALLBACK_EXCLUDED_MARKERS):
        return False
    return any(marker in text for marker in _FORMAT_INCOMPATIBILITY_MARKERS)
