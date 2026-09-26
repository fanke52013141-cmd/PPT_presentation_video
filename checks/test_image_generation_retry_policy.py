"""Structured image-error classification and bounded retry policy tests.

表驱动验证"是否应该重试、等多久"，全部使用注入的随机源与剩余预算，
不产生真实等待。对应优化方案的验证方案 §5.1。
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import generation_governor  # noqa: E402
import image_generation_errors as errors  # noqa: E402
import image_generation_retry as retry  # noqa: E402


POLICY = retry.ImageRetryPolicy(
    enabled=True,
    max_generation_attempts=3,
    initial_backoff_sec=5.0,
    max_backoff_sec=60.0,
    jitter_sec=2.0,
    max_download_attempts=3,
    total_budget_sec=900.0,
)


def _no_jitter(low: float, high: float) -> float:
    return low


class StatusError(RuntimeError):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


# ── 分类表：输入 -> (code, retryable) ─────────────────────────────────────
@pytest.mark.parametrize(
    "error,expected_code,expected_retryable",
    [
        (StatusError("server exploded", 503), errors.CODE_UPSTREAM_OVERLOADED, True),
        (StatusError("too many requests", 429), errors.CODE_RATE_LIMITED, True),
        (StatusError("bad gateway", 502), errors.CODE_UPSTREAM_OVERLOADED, True),
        (StatusError("request timeout", 408), errors.CODE_UPSTREAM_OVERLOADED, True),
        (StatusError("invalid api key", 401), errors.CODE_AUTH_FAILED, False),
        (StatusError("forbidden", 403), errors.CODE_AUTH_FAILED, False),
        (StatusError("unknown size '1024x7'", 400), errors.CODE_INVALID_PARAMETERS, False),
        (ConnectionError("connection refused"), errors.CODE_CONNECTION_FAILED, True),
        (
            errors.ImageGenerationError(
                errors.ImageGenerationErrorInfo(
                    code=errors.CODE_DOWNLOAD_FAILED,
                    phase=errors.PHASE_DOWNLOAD,
                    retryable=True,
                    retry_scope=errors.RETRY_SCOPE_REDOWNLOAD,
                )
            ),
            errors.CODE_DOWNLOAD_FAILED,
            True,
        ),
    ],
)
def test_classification_table(error, expected_code, expected_retryable) -> None:
    info = errors.classify_image_error(error)
    assert info.code == expected_code
    assert info.retryable is expected_retryable


def test_message_containing_503_does_not_override_parameter_error() -> None:
    """错误文字包含"503"，真实错误是参数错误：不因文字误判为可重试。"""
    misleading = StatusError("size 1024x7 not in allowed set (saw near 503 variants)", 400)
    info = errors.classify_image_error(misleading)
    assert info.code == errors.CODE_INVALID_PARAMETERS
    assert info.retryable is False


def test_governor_timeout_is_gateway_busy_and_recoverable() -> None:
    info = errors.classify_image_error(generation_governor.GovernorTimeout("排队超过 600 秒"))
    assert info.code == errors.CODE_GATEWAY_BUSY
    assert info.retryable is False
    verdict = retry.decide_retry(
        info, attempt=1, policy=POLICY, remaining_sec=600.0
    )
    assert verdict.retry is False
    assert verdict.recoverable is True


def test_unknown_program_error_is_not_auto_retried() -> None:
    info = errors.classify_image_error(RuntimeError("provider exploded"))
    assert info.code == errors.CODE_UNKNOWN
    assert info.retryable is False
    verdict = retry.decide_retry(
        info, attempt=1, policy=POLICY, remaining_sec=600.0
    )
    assert verdict.retry is False


def test_retry_after_honoured_and_capped() -> None:
    info = errors.classify_image_error(
        StatusError("too many requests; retry after 20", 429)
    )
    delay = retry.compute_backoff(1, POLICY, info, random_source=_no_jitter)
    assert delay == 20.0


# ── 重试裁决表 ────────────────────────────────────────────────────────────
def _retryable_info(code: str = errors.CODE_CONNECTION_FAILED) -> errors.ImageGenerationErrorInfo:
    return errors.ImageGenerationErrorInfo(
        code=code,
        phase=errors.PHASE_SUBMIT,
        retryable=True,
        retry_scope=errors.RETRY_SCOPE_REQUEST,
    )


@pytest.mark.parametrize(
    "attempt,remaining,expect_retry",
    [
        (1, 600.0, True),   # 第一次失败 -> 重试
        (2, 600.0, True),   # 第二次失败 -> 还能再试一次
        (3, 600.0, False),  # 达到单页尝试上限
        (1, 0.5, False),    # 等待超过剩余预算：结束本轮
        (2, 0.5, False),
    ],
)
def test_retry_decision_table(attempt, remaining, expect_retry) -> None:
    verdict = retry.decide_retry(
        _retryable_info(),
        attempt=attempt,
        policy=POLICY,
        remaining_sec=remaining,
        random_source=_no_jitter,
    )
    assert verdict.retry is expect_retry
    if not expect_retry and attempt >= POLICY.max_generation_attempts:
        assert verdict.recoverable is True
        assert verdict.reason == "attempts_exhausted"


def test_budget_exhausted_is_recoverable_not_failure() -> None:
    verdict = retry.decide_retry(
        _retryable_info(),
        attempt=1,
        policy=POLICY,
        remaining_sec=0.5,
        random_source=_no_jitter,
    )
    assert verdict.retry is False
    assert verdict.recoverable is True
    assert verdict.reason == "budget_exhausted"


def test_disabled_policy_keeps_recoverable_flag() -> None:
    verdict = retry.decide_retry(
        _retryable_info(),
        attempt=1,
        policy=retry.ImageRetryPolicy(enabled=False),
        remaining_sec=600.0,
    )
    assert verdict.retry is False
    assert verdict.recoverable is True
    assert verdict.reason == "auto_retry_disabled"


def test_backoff_grows_exponentially_with_jitter_cap() -> None:
    delays = [
        retry.compute_backoff(
            attempt, POLICY, _retryable_info(), random_source=_no_jitter
        )
        for attempt in (1, 2, 3)
    ]
    assert delays == [5.0, 10.0, 20.0]
    # 抖动只会推迟、不会提前；并受上限约束。
    capped = retry.compute_backoff(
        9, POLICY, _retryable_info(), random_source=_no_jitter
    )
    assert capped == 60.0
    jittered = retry.compute_backoff(1, POLICY, _retryable_info(), random_source=lambda lo, hi: hi)
    assert jittered == pytest.approx(7.0)


def test_download_retry_reuses_result_until_cap() -> None:
    info = errors.ImageGenerationErrorInfo(
        code=errors.CODE_DOWNLOAD_FAILED,
        phase=errors.PHASE_DOWNLOAD,
        retryable=True,
        retry_scope=errors.RETRY_SCOPE_REDOWNLOAD,
    )
    assert retry.decide_download_retry(
        info, attempt=1, policy=POLICY, remaining_sec=600.0, random_source=_no_jitter
    ).retry is True
    final = retry.decide_download_retry(
        info, attempt=3, policy=POLICY, remaining_sec=600.0, random_source=_no_jitter
    )
    assert final.retry is False
    assert final.recoverable is True


def test_policy_defaults_and_environment_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    defaults = retry.ImageRetryPolicy.from_environment(env={})
    assert defaults.enabled is True
    assert defaults.max_generation_attempts == 3
    assert defaults.initial_backoff_sec == 5.0
    assert defaults.total_budget_sec == 900.0
    monkeypatch.setenv("PPT_STUDIO_IMAGE_RETRY_MAX_ATTEMPTS", "5")
    monkeypatch.setenv("PPT_STUDIO_IMAGE_RETRY_BUDGET_SEC", "1200")
    monkeypatch.setenv("PPT_STUDIO_IMAGE_RETRY_ENABLED", "0")
    overridden = retry.ImageRetryPolicy.from_environment()
    assert overridden.max_generation_attempts == 5
    assert overridden.total_budget_sec == 1200.0
    assert overridden.enabled is False


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
