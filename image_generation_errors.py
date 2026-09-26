"""Structured image-generation error classification.

为什么需要这个模块
------------------
一键流程会把异常逐层包装（``HTTPException -> RuntimeError ->
QualityGateFailure``），外层只能看到字符串，无法判断"这一页还应不应该重试"。
本模块把上游异常归一成带稳定字段的结构化信息，让图片任务执行层、HTTP 边界
和一键编排层共享同一份判断依据。

边界约束
--------
只依赖标准库。**不得** import FastAPI、database、config_store、openai/httpx
或应用组合根；对第三方异常一律用"类型名 + 属性 + 异常文本"做识别，且结构化
字段优先于文本匹配 —— 绝不因为错误文字里包含 "503" 就把一个真正的参数错误
判定为可重试。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Optional


# ── 失败阶段 ──────────────────────────────────────────────────────────────
PHASE_SUBMIT = "submit"        # 提交生成请求
PHASE_POLL = "poll"            # 异步任务状态轮询
PHASE_DOWNLOAD = "download"    # 下载生成结果
PHASE_DECODE = "decode"        # 解码 / 校验图片字节
PHASE_SAVE = "save"            # 本地写盘与收尾

# ── 重试范围 ──────────────────────────────────────────────────────────────
RETRY_SCOPE_NONE = "none"                    # 不允许自动重试
RETRY_SCOPE_REQUEST = "retry_request"        # 重新发起一次请求
RETRY_SCOPE_RESUME_TASK = "resume_task"      # 继续轮询已有上游任务
RETRY_SCOPE_REDOWNLOAD = "redownload"        # 重新下载已有结果地址
RETRY_SCOPE_REGENERATE = "regenerate"        # 重新生成一页

# ── 稳定错误码 ────────────────────────────────────────────────────────────
CODE_CONNECTION_FAILED = "connection_failed"
CODE_CONNECTION_RESET = "connection_reset"
CODE_READ_TIMEOUT = "read_timeout"
CODE_TIMEOUT = "timeout"
CODE_RATE_LIMITED = "rate_limited"
CODE_GATEWAY_BUSY = "gateway_busy"              # 治理器排队超时（上游忙）
CODE_UPSTREAM_OVERLOADED = "upstream_overloaded"  # 明确的临时 5xx / 408
CODE_POLL_TIMEOUT = "poll_timeout"
CODE_POLL_FAILED = "poll_failed"
CODE_DOWNLOAD_FAILED = "download_failed"
CODE_EMPTY_RESPONSE = "empty_response"
CODE_CORRUPT_IMAGE = "corrupt_image"
CODE_CONTENT_REJECTED = "content_rejected"
CODE_AUTH_FAILED = "auth_failed"
CODE_INVALID_PARAMETERS = "invalid_parameters"
CODE_SAVE_FAILED = "save_failed"
CODE_UNKNOWN = "unknown"

_RETRY_AFTER_PATTERN = re.compile(
    r"retry(?:-| )?after\D{0,4}(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)

# 这些状态码是"明确的临时故障"，允许有界重试。
_TRANSIENT_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})
# 这些状态码重试也不会成功。
_PERMANENT_STATUS_CODES = frozenset({400, 401, 402, 403, 404, 405, 413, 422})
# 认证/授权类错误：连"换一组参数再试"都不允许。
_AUTH_STATUS_CODES = frozenset({401, 402, 403})


@dataclass(frozen=True)
class ImageGenerationErrorInfo:
    """一次上游失败的结构化描述，供重试决策与日志共享。"""

    code: str
    phase: str
    retryable: bool
    retry_scope: str = RETRY_SCOPE_NONE
    status_code: Optional[int] = None
    retry_after_seconds: Optional[float] = None
    outcome_unknown: bool = False
    safe_message: str = ""
    upstream_task_id: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "phase": self.phase,
            "retryable": self.retryable,
            "retry_scope": self.retry_scope,
            "status_code": self.status_code,
            "retry_after_seconds": self.retry_after_seconds,
            "outcome_unknown": self.outcome_unknown,
            "upstream_task_id": self.upstream_task_id,
            "message": self.safe_message[:800],
        }


@dataclass(frozen=True)
class ImagePageFailure:
    """一页图片最终失败时的完整结果（不是首个异常的片段）。"""

    slide_id: str
    attempts: int
    code: str
    phase: str
    message: str
    retryable: bool = False
    recoverable: bool = False          # 继续任务可补齐，不需要人工排查
    outcome_unknown: bool = False
    status_code: Optional[int] = None
    image_saved: bool = False          # 图片已写盘，仅收尾缺失；恢复时不得重新生图
    elapsed_sec: float = 0.0
    upstream_task_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "slide_id": self.slide_id,
            "attempts": self.attempts,
            "code": self.code,
            "phase": self.phase,
            "message": self.message[:800],
            "retryable": self.retryable,
            "recoverable": self.recoverable,
            "outcome_unknown": self.outcome_unknown,
            "status_code": self.status_code,
            "image_saved": self.image_saved,
            "elapsed_sec": round(float(self.elapsed_sec), 3),
            "upstream_task_id": self.upstream_task_id,
        }


class ImageGenerationError(RuntimeError):
    """携带 :class:`ImageGenerationErrorInfo` 的生图失败。"""

    def __init__(
        self,
        info: ImageGenerationErrorInfo,
        *,
        cause: Optional[BaseException] = None,
    ) -> None:
        super().__init__(info.safe_message or info.code)
        self.info = info
        if cause is not None and self.__cause__ is None:
            self.__cause__ = cause


class ImageGenerationFailure(RuntimeError):
    """一页图片在预算内重试后仍失败；``failure`` 供编排层汇总。"""

    def __init__(self, failure: ImagePageFailure) -> None:
        super().__init__(failure.message or failure.code)
        self.failure = failure


def _status_code_of(error: Any) -> Optional[int]:
    """优先读取异常携带的结构化状态码（openai/httpx/自封装均适用）。"""
    status = getattr(error, "status_code", None)
    if isinstance(status, int) and 100 <= status < 600:
        return status
    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    if isinstance(status, int) and 100 <= status < 600:
        return status
    return None


def _retry_after_of(error: Any) -> Optional[float]:
    headers = getattr(getattr(error, "response", None), "headers", None)
    if headers is not None:
        try:
            value = headers.get("Retry-After")
        except Exception:
            value = None
        if value:
            try:
                return max(0.0, float(value))
            except (TypeError, ValueError):
                pass
    match = _RETRY_AFTER_PATTERN.search(str(error))
    if match:
        try:
            return max(0.0, float(match.group(1)))
        except (TypeError, ValueError):
            pass
    return None


def _type_name(error: Any) -> str:
    return type(error).__name__.lower()


def _timeout_error(error: Any) -> bool:
    return "timeout" in _type_name(error)


def _rate_limit_error(error: Any) -> bool:
    if "ratelimit" in _type_name(error):
        return True
    status = _status_code_of(error)
    if status == 429:
        return True
    return False


def is_parameter_incompatibility(error: BaseException) -> bool:
    """判断异常是否属于"参数/格式不被当前供应商支持"。

    该判断是生图参数兼容回退链的准入条件：只有参数类错误才值得换一组
    参数再试一次；限流、超时、认证、服务端故障一律原样上抛，交给有界的
    页级重试，避免"换参数"把请求数翻倍。
    """
    if isinstance(error, ImageGenerationError):
        return error.info.code == CODE_INVALID_PARAMETERS
    status = _status_code_of(error)
    if status is not None:
        if status in _AUTH_STATUS_CODES or status in _TRANSIENT_STATUS_CODES:
            return False
        if status in _PERMANENT_STATUS_CODES:
            # 400/404/422 等明确的请求错误是参数兼容回退的目标场景；
            # 认证类错误已在上面排除。
            return True
    if _rate_limit_error(error) or _timeout_error(error):
        return False
    if isinstance(error, (ConnectionError, OSError)):
        return False
    name = _type_name(error)
    if "badrequest" in name or "unprocessable" in name or "notfound" in name:
        return True
    text = f"{type(error).__name__}: {error}".lower()
    markers = (
        "invalid parameter",
        "invalid_parameter",
        "unknown parameter",
        "unrecognized",
        "not supported",
        "unsupported",
        "does not support",
        "invalid value",
        "invalid request",
        "must be one of",
        "size must be",
        "response_format",
        "invalid content type",
    )
    return any(marker in text for marker in markers)


def _info(
    code: str,
    phase: str,
    *,
    retryable: bool,
    scope: str = RETRY_SCOPE_NONE,
    status: Optional[int] = None,
    retry_after: Optional[float] = None,
    outcome_unknown: bool = False,
    message: str = "",
    task_id: str = "",
) -> ImageGenerationErrorInfo:
    return ImageGenerationErrorInfo(
        code=code,
        phase=phase,
        retryable=retryable,
        retry_scope=scope if retryable else RETRY_SCOPE_NONE,
        status_code=status,
        retry_after_seconds=retry_after,
        outcome_unknown=outcome_unknown,
        safe_message=str(message or code)[:800],
        upstream_task_id=task_id,
    )


def classify_image_error(
    error: BaseException,
    *,
    phase: str = PHASE_SUBMIT,
    upstream_task_id: str = "",
) -> ImageGenerationErrorInfo:
    """把任意异常归一成结构化生图错误信息。

    判定顺序：治理器超时 -> 异常类型（连接/超时/限流）-> 结构化状态码 ->
    兜底"未知程序错误"（默认不自动重试，保留诊断信息）。文本只用于提取
    ``Retry-After``，不作为"是否可重试"的主证据。
    """
    import generation_governor  # 局部导入保持本模块零依赖

    if isinstance(error, ImageGenerationError):
        return error.info

    if isinstance(error, generation_governor.GovernorTimeout):
        return _info(
            CODE_GATEWAY_BUSY,
            phase,
            retryable=False,
            status=None,
            outcome_unknown=False,
            message=str(error),
        )

    status = _status_code_of(error)
    retry_after = _retry_after_of(error)
    name = _type_name(error)

    if _rate_limit_error(error) or status == 429:
        return _info(
            CODE_RATE_LIMITED,
            phase,
            retryable=True,
            scope=RETRY_SCOPE_REQUEST,
            status=429,
            retry_after=retry_after,
            message=str(error),
        )

    if "connect" in name or isinstance(error, ConnectionError):
        return _info(
            CODE_CONNECTION_FAILED,
            phase,
            retryable=True,
            scope=RETRY_SCOPE_REQUEST,
            status=status,
            message=str(error),
        )
    if "remoteprotocol" in name or "incomplete" in name or "reset" in name:
        return _info(
            CODE_CONNECTION_RESET,
            phase,
            retryable=True,
            scope=RETRY_SCOPE_REQUEST if phase == PHASE_SUBMIT else RETRY_SCOPE_REDOWNLOAD,
            status=status,
            outcome_unknown=phase in (PHASE_SUBMIT, PHASE_POLL),
            message=str(error),
        )

    if _timeout_error(error):
        # 网络读取超时不等于上游没有生成。
        return _info(
            CODE_READ_TIMEOUT if phase in (PHASE_DOWNLOAD, PHASE_POLL) else CODE_TIMEOUT,
            phase,
            retryable=True,
            scope=RETRY_SCOPE_RESUME_TASK
            if phase == PHASE_POLL and upstream_task_id
            else (RETRY_SCOPE_REDOWNLOAD if phase == PHASE_DOWNLOAD else RETRY_SCOPE_REQUEST),
            status=status,
            outcome_unknown=True,
            message=str(error),
            task_id=upstream_task_id,
        )

    if status is not None:
        if status in _TRANSIENT_STATUS_CODES:
            if status == 429:
                return _info(
                    CODE_RATE_LIMITED,
                    phase,
                    retryable=True,
                    scope=RETRY_SCOPE_REQUEST,
                    status=status,
                    retry_after=retry_after,
                    message=str(error),
                )
            return _info(
                CODE_UPSTREAM_OVERLOADED,
                phase,
                retryable=True,
                scope=RETRY_SCOPE_REQUEST,
                status=status,
                retry_after=retry_after,
                outcome_unknown=status == 504,
                message=str(error),
            )
        if status in _PERMANENT_STATUS_CODES:
            if status in _AUTH_STATUS_CODES:
                code = CODE_AUTH_FAILED
            else:
                code = CODE_INVALID_PARAMETERS
            return _info(
                code,
                phase,
                retryable=False,
                status=status,
                message=str(error),
            )

    if isinstance(error, ValueError):
        text = str(error).lower()
        if "空" in text or "empty" in text or "no image" in text:
            return _info(
                CODE_EMPTY_RESPONSE,
                phase,
                retryable=True,
                scope=RETRY_SCOPE_REGENERATE,
                message=str(error),
            )
        return _info(
            CODE_CORRUPT_IMAGE,
            phase,
            retryable=True,
            scope=RETRY_SCOPE_REGENERATE,
            message=str(error),
        )

    if isinstance(error, OSError):
        return _info(
            CODE_SAVE_FAILED,
            PHASE_SAVE,
            retryable=False,
            message=str(error),
        )

    return _info(
        CODE_UNKNOWN,
        phase,
        retryable=False,
        status=status,
        message=f"{type(error).__name__}: {error}",
    )


def recoverable_codes() -> frozenset[str]:
    """继续任务可望自愈的错误码（资源忙/上游临时故障/预算耗尽类）。"""
    return frozenset(
        {
            CODE_GATEWAY_BUSY,
            CODE_RATE_LIMITED,
            CODE_UPSTREAM_OVERLOADED,
            CODE_CONNECTION_FAILED,
            CODE_CONNECTION_RESET,
            CODE_READ_TIMEOUT,
            CODE_TIMEOUT,
            CODE_POLL_TIMEOUT,
            CODE_POLL_FAILED,
            CODE_DOWNLOAD_FAILED,
            CODE_EMPTY_RESPONSE,
            CODE_CORRUPT_IMAGE,
        }
    )
