"""Process-wide upstream request budget and concurrency governance.

为什么需要这个模块
------------------
额度是**网关全局**的（生图 500 请求/分钟、MiniMax 语音 10 请求/分钟），
而调用方的并发配置是**按项目**的。两者相乘就是超发：
N 个账号/项目同时自动生成时，实际请求速率是各项目配额的线性叠加。

本模块把"限流键"从项目改成 **（资源种类, 上游网关）**，让所有调用方
共享同一份额度，并把"额度耗尽"的语义从"降档后抛错"改成"排队等待"。

两种获取方式（对应两类真实调用点）
----------------------------------
1. :meth:`GenerationGovernor.request` —— 短时一次性 HTTP 调用
   （例如 ToAPIs 的参考图上传、任务提交、状态轮询）。
   每次调用前扣 1 个令牌，天然按真实请求数精确计量。
2. :meth:`GenerationGovernor.job` —— 长时任务（例如 MiniMax 语音合成子进程）。
   子进程内部的 HTTP 无法被父进程拦截，因此按"预估总请求数"一次性预留令牌，
   轮询间隔由全局预算反推（见 :meth:`GenerationGovernor.tts_reservation`）。

边界约束
--------
本模块只依赖标准库，**不得** import FastAPI、database、config_store 或应用模块。
全局设置的读取能力通过 :class:`GovernorDependencies` 显式注入，未注入时
使用内置默认值并且**仍然生效**（安全默认），避免漏配置导致静默不限流。

进程模型
--------
令牌桶在进程内共享。当前只有一个 Web 进程会做自动生成
（``cli``/``mcp_server``/``agent_client`` 都是本服务的 HTTP 客户端，
数字人服务走本地 ComfyUI），因此进程内单例已足够，不需要持久化令牌桶。
若将来出现第二个直连上游的进程，只需在 :class:`GenerationGovernor` 内部
增加一个共享存储实现，调用方接口不变。
"""

from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
import re
import threading
import time
import urllib.parse
from typing import Any, Callable, Iterator, Optional

RESOURCE_IMAGE = "image"
RESOURCE_TTS = "tts"
RESOURCE_LLM = "llm"

# 资源 -> (RPM 设置键, RPM 默认, RPM 下限, RPM 上限,
#         并发设置键, 并发默认, 并发下限, 并发上限)
_RESOURCE_SPECS: dict[str, tuple[str, int, int, int, str, int, int, int]] = {
    RESOURCE_IMAGE: (
        "image_gateway_requests_per_minute", 500, 1, 100000,
        "image_gateway_max_concurrency", 12, 1, 64,
    ),
    RESOURCE_TTS: (
        "tts_gateway_requests_per_minute", 10, 1, 600,
        "tts_gateway_max_concurrency", 4, 1, 16,
    ),
    RESOURCE_LLM: (
        "llm_gateway_requests_per_minute", 0, 0, 100000,
        "llm_gateway_max_concurrency", 8, 1, 64,
    ),
}
_ENABLED_KEY = "generation_governor_enabled"
_MAX_WAIT_SEC_KEY = "generation_queue_max_wait_sec"
_DEFAULT_MAX_WAIT_SEC = 600.0

# AIMD：撞限流就减半，连续成功若干次后逐格回升。
_RATE_LIMIT_RECOVERY_SUCCESSES = 20
_RATE_LIMIT_DEFAULT_DELAY_SEC = 5.0
_RATE_LIMIT_MAX_DELAY_SEC = 60.0

# 语音合成的预算切分与成本常量。
# 异步端点每页固定 3 次请求：上传文本、提交任务、取回音频。
TTS_ASYNC_FIXED_COST = 3
TTS_SYNC_FIXED_COST = 1
_TTS_SUBMIT_BUDGET_RATIO = 0.4
_TTS_POLL_INTERVAL_FLOOR_SEC = 8.0

_RETRY_AFTER_PATTERN = re.compile(
    r"retry(?:-| )?after\s*[:=]?\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_RATE_LIMIT_MARKERS = (
    "429",
    "rate limit",
    "rate_limit",
    "too many requests",
    "quota exceeded",
    "请求过于频繁",
    "请求频繁",
)


class GovernorTimeout(RuntimeError):
    """排队等待超过上限。

    这是"上游忙"，不是永久失败：调用方应把它当作可重试状态，
    并在质量门里降级为暂停而不是整体失败。
    """


def gateway_scope(base_url: Any) -> str:
    """把端点归一化成"网关标识"，用作限流键的一部分。

    刻意**不含 api_key**：额度是网关全局的，同一网关的不同密钥/账号
    必须共用同一份额度；按密钥分桶会导致各自放行、叠加超发。
    """
    text = str(base_url or "").strip()
    if not text:
        return "default"
    parsed = urllib.parse.urlparse(text)
    if not parsed.scheme or not parsed.netloc:
        return text.lower()
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def is_rate_limit_error(error: Any) -> bool:
    """判断异常是否属于"上游限流"，从而应该退避重试而不是判死。"""
    detail = f"{type(error).__name__}: {error}".lower()
    return any(marker in detail for marker in _RATE_LIMIT_MARKERS)


def rate_limit_delay_seconds(error: Any, attempt: int) -> float:
    """优先使用上游提示的 Retry-After，否则指数退避（有上限）。"""
    match = _RETRY_AFTER_PATTERN.search(str(error))
    if match:
        try:
            return max(1.0, min(_RATE_LIMIT_MAX_DELAY_SEC, float(match.group(1))))
        except (TypeError, ValueError):
            pass
    safe_attempt = max(0, int(attempt))
    return float(min(_RATE_LIMIT_MAX_DELAY_SEC, _RATE_LIMIT_DEFAULT_DELAY_SEC * (2 ** safe_attempt)))


@dataclass(frozen=True)
class GovernorDependencies:
    """冻结依赖：只注入"读全局设置"和"写诊断日志"两个能力。"""

    get_bounded_int_setting: Optional[Callable[[str, int, int, int], int]] = None
    write_log: Optional[Callable[..., None]] = None

    def bounded(self, key: str, default: int, minimum: int, maximum: int) -> int:
        reader = self.get_bounded_int_setting
        if reader is None:
            return default
        try:
            return max(minimum, min(maximum, int(reader(key, default, minimum, maximum))))
        except Exception:
            return default

    def log(self, event: str, **fields: Any) -> None:
        writer = self.write_log
        if writer is None:
            return
        try:
            writer(event, **fields)
        except Exception:
            pass


@dataclass(frozen=True)
class ResourceBudget:
    """一个网关的额度快照。``requests_per_minute == 0`` 表示不限速。"""

    key: tuple[str, str]
    requests_per_minute: int
    max_concurrency: int
    max_wait_sec: float

    @property
    def unlimited(self) -> bool:
        return self.requests_per_minute <= 0


@dataclass
class _KeyState:
    """一个限流键的共享状态。

    令牌桶与并发许可共用一把条件变量，保证"取号 -> 判定 -> 占用"是原子的，
    也让 FIFO 票据队列能同时约束两类等待者。
    """

    budget: ResourceBudget
    condition: threading.Condition = field(default_factory=threading.Condition)
    tokens: float = 0.0
    updated_at: float = 0.0
    active: int = 0
    limit_current: int = 1
    tickets: deque[int] = field(default_factory=deque)
    next_ticket: int = 0
    consecutive_successes: int = 0
    passed: int = 0
    timeouts: int = 0
    waited_sec_total: float = 0.0
    rate_limit_events: int = 0

    def __post_init__(self) -> None:
        self.tokens = float(self.budget.requests_per_minute)
        self.updated_at = time.monotonic()
        self.limit_current = max(1, int(self.budget.max_concurrency))

    @property
    def refill_rate(self) -> float:
        """每秒补充的令牌数。"""
        return float(self.budget.requests_per_minute) / 60.0

    def refill(self, now: float) -> None:
        if self.budget.unlimited:
            return
        elapsed = max(0.0, now - self.updated_at)
        self.updated_at = now
        if elapsed <= 0:
            return
        capacity = float(self.budget.requests_per_minute)
        self.tokens = min(capacity, self.tokens + elapsed * self.refill_rate)

    def take_ticket(self) -> int:
        ticket = self.next_ticket
        self.next_ticket += 1
        self.tickets.append(ticket)
        return ticket

    def at_head(self, ticket: int) -> bool:
        return bool(self.tickets) and self.tickets[0] == ticket

    def abandon_ticket(self, ticket: int) -> None:
        """超时/异常退出时归还号牌，避免堵死后续等待者。"""
        try:
            self.tickets.remove(ticket)
        except ValueError:
            return
        self.condition.notify_all()

    def apply_budget(self, budget: ResourceBudget) -> None:
        """运行期额度变更立即生效（无需重启服务）。

        调用方必须在持有 ``condition`` 时调用。令牌余量与当前并发上限都会被
        钳制到新额度内，避免"把额度调小之后仍然按旧额度放行"。
        """
        self.budget = budget
        if budget.unlimited:
            self.tokens = 0.0
        else:
            self.tokens = min(self.tokens, float(budget.requests_per_minute))
        ceiling = max(1, int(budget.max_concurrency))
        if self.limit_current > ceiling:
            self.limit_current = ceiling


class GenerationGovernor:
    """进程级上游预算与并发治理器。"""

    def __init__(
        self,
        dependencies: Optional[GovernorDependencies] = None,
        *,
        enabled: Optional[bool] = None,
        max_wait_sec: Optional[float] = None,
    ) -> None:
        self.dependencies = dependencies or GovernorDependencies()
        self._states: dict[tuple[str, str], _KeyState] = {}
        self._guard = threading.Lock()
        if enabled is None:
            enabled = self.dependencies.bounded(_ENABLED_KEY, 1, 0, 1) == 1
        self.enabled = bool(enabled)
        if max_wait_sec is None:
            max_wait_sec = float(
                self.dependencies.bounded(
                    _MAX_WAIT_SEC_KEY, int(_DEFAULT_MAX_WAIT_SEC), 5, 3600
                )
            )
        self.max_wait_sec = max(1.0, float(max_wait_sec))

    # ------------------------------------------------------------------
    # 预算解析
    # ------------------------------------------------------------------
    def budget(self, resource: str, base_url: Any = "") -> ResourceBudget:
        spec = _RESOURCE_SPECS.get(str(resource))
        if spec is None:
            raise KeyError(f"未知的资源种类: {resource!r}")
        (
            rpm_key, rpm_default, rpm_min, rpm_max,
            concurrency_key, concurrency_default, concurrency_min, concurrency_max,
        ) = spec
        return ResourceBudget(
            key=(str(resource), gateway_scope(base_url)),
            requests_per_minute=self.dependencies.bounded(
                rpm_key, rpm_default, rpm_min, rpm_max
            ),
            max_concurrency=self.dependencies.bounded(
                concurrency_key, concurrency_default, concurrency_min, concurrency_max
            ),
            max_wait_sec=self.max_wait_sec,
        )

    def _state(self, resource: str, base_url: Any) -> _KeyState:
        resolved = self.budget(resource, base_url)
        with self._guard:
            state = self._states.get(resolved.key)
            if state is None:
                state = _KeyState(budget=resolved)
                self._states[resolved.key] = state
                return state
        # 额度可以在运行期通过系统设置调整；旧状态必须跟着变，否则会出现
        # "设置里调小了额度但仍在按旧额度超发"。
        if state.budget != resolved:
            with state.condition:
                state.apply_budget(resolved)
                state.condition.notify_all()
        return state

    # ------------------------------------------------------------------
    # 获取 / 释放
    # ------------------------------------------------------------------
    def _acquire(
        self,
        state: _KeyState,
        *,
        cost: int,
        want_slot: bool,
        timeout_sec: Optional[float],
    ) -> None:
        budget = state.budget
        if not self.enabled:
            return
        safe_cost = max(1, int(cost))
        limit_sec = budget.max_wait_sec if timeout_sec is None else float(timeout_sec)
        deadline = time.monotonic() + max(0.01, limit_sec)
        started_at = time.monotonic()
        ticket = -1
        with state.condition:
            ticket = state.take_ticket()
        try:
            with state.condition:
                while True:
                    now = time.monotonic()
                    state.refill(now)
                    remaining = deadline - now
                    if remaining <= 0:
                        state.timeouts += 1
                        state.waited_sec_total += now - started_at
                        raise GovernorTimeout(
                            f"{budget.key[0]} 网关 {budget.key[1]} 排队超过 "
                            f"{limit_sec:.0f} 秒仍未获得额度"
                        )
                    slots_ok = (not want_slot) or state.active < state.limit_current
                    tokens_ok = budget.unlimited or state.tokens >= safe_cost
                    if state.at_head(ticket) and slots_ok and tokens_ok:
                        state.tickets.popleft()
                        if not budget.unlimited:
                            state.tokens -= safe_cost
                        state.active += 1 if want_slot else 0
                        state.passed += 1
                        state.waited_sec_total += now - started_at
                        return
                    if not tokens_ok and state.refill_rate > 0:
                        need = (safe_cost - state.tokens) / state.refill_rate
                        wait_sec = min(remaining, max(0.01, need))
                    else:
                        # 只在等并发许可/FIFO 号牌：靠 notify_all 唤醒，
                        # 但仍保留一个有界超时，避免极端情况下永久挂起。
                        wait_sec = min(remaining, 0.25)
                    state.condition.wait(wait_sec)
        except BaseException:
            with state.condition:
                state.abandon_ticket(ticket)
            raise

    def _release_slot(self, state: _KeyState) -> None:
        if not self.enabled:
            return
        with state.condition:
            state.active = max(0, state.active - 1)
            state.condition.notify_all()

    @contextmanager
    def request(
        self,
        resource: str,
        base_url: Any = "",
        *,
        cost: int = 1,
        timeout_sec: Optional[float] = None,
    ) -> Iterator[None]:
        """短时一次性 HTTP 调用：按真实请求数扣令牌，调用结束归还并发许可。"""
        if not self.enabled:
            yield
            return
        state = self._state(resource, base_url)
        self._acquire(state, cost=cost, want_slot=True, timeout_sec=timeout_sec)
        try:
            yield
        finally:
            self._release_slot(state)

    @contextmanager
    def job(
        self,
        resource: str,
        base_url: Any = "",
        *,
        reserved_cost: int = 1,
        timeout_sec: Optional[float] = None,
    ) -> Iterator[None]:
        """长时任务：一次性预留全部预估请求数，并持有并发许可到任务结束。

        子进程内的 HTTP（如 MiniMax 语音助手）无法逐请求计量，只能在启动前
        按预估成本整体预留。预留值一旦确定就全部消耗，不做退还——保守估计
        只会让整体变慢，不会超发。
        """
        if not self.enabled:
            yield
            return
        state = self._state(resource, base_url)
        self._acquire(state, cost=reserved_cost, want_slot=True, timeout_sec=timeout_sec)
        try:
            yield
        finally:
            self._release_slot(state)

    # ------------------------------------------------------------------
    # AIMD 反馈
    # ------------------------------------------------------------------
    def record_rate_limit(
        self,
        resource: str,
        base_url: Any = "",
        *,
        error: Any = None,
        attempt: int = 0,
        retry_after: Optional[float] = None,
    ) -> float:
        """登记一次上游限流：减半并发上限并返回建议退避秒数。

        调用方负责 sleep；退避期间**不占用**并发许可，因此其他等待者可以继续。
        """
        if not self.enabled:
            if retry_after is not None:
                try:
                    return max(1.0, min(_RATE_LIMIT_MAX_DELAY_SEC, float(retry_after)))
                except (TypeError, ValueError):
                    pass
            return rate_limit_delay_seconds(error, attempt)
        state = self._state(resource, base_url)
        with state.condition:
            state.rate_limit_events += 1
            state.consecutive_successes = 0
            previous = state.limit_current
            state.limit_current = max(1, previous // 2)
            current = state.limit_current
            state.condition.notify_all()
        self.dependencies.log(
            "generation_governor_backoff",
            resource=state.budget.key[0],
            gateway=state.budget.key[1],
            previous_concurrency=previous,
            concurrency=current,
        )
        if retry_after is not None:
            try:
                return max(1.0, min(_RATE_LIMIT_MAX_DELAY_SEC, float(retry_after)))
            except (TypeError, ValueError):
                pass
        return rate_limit_delay_seconds(error, attempt)

    def note_success(self, resource: str, base_url: Any = "") -> None:
        """登记一次成功；连续成功后把并发上限逐格抬回配置值（AIMD 回升）。"""
        if not self.enabled:
            return
        state = self._state(resource, base_url)
        raised_to: Optional[int] = None
        with state.condition:
            state.consecutive_successes += 1
            ceiling = max(1, int(state.budget.max_concurrency))
            if (
                state.limit_current < ceiling
                and state.consecutive_successes >= _RATE_LIMIT_RECOVERY_SUCCESSES
            ):
                state.consecutive_successes = 0
                state.limit_current += 1
                raised_to = state.limit_current
                state.condition.notify_all()
        if raised_to is not None:
            self.dependencies.log(
                "generation_governor_recover",
                resource=state.budget.key[0],
                gateway=state.budget.key[1],
                concurrency=raised_to,
            )

    # ------------------------------------------------------------------
    # 成本模型
    # ------------------------------------------------------------------
    def tts_async_reservation(
        self,
        *,
        base_url: Any = "",
        expected_duration_sec: float,
        fixed_cost: int = TTS_ASYNC_FIXED_COST,
    ) -> tuple[int, float]:
        """算出一页**异步**语音的预留令牌数与建议轮询间隔。

        异步端点每页固定消耗 ``fixed_cost`` 次请求（默认＝上传文本＋提交任务＋
        取回音频＝3，见 ``scripts/minimax_tts.py:773-784``），此外还要持续轮询。

        额度按"固定成本 40% / 轮询 60%"切分，避免出现
        "提交占满全部额度、轮询再额外索要"的超发结构：

        ``rpm=10``、``fixed_cost=3``、``expected=40s`` 时，
        提交预算 4/min → 起搏 1.33 页/min → 在飞 1 页 →
        轮询预算 6/min → 间隔 10 秒 → 每页预留 ``3 + 4 = 7`` 个令牌。
        即 10/min 额度下约 1.3 页/分钟，而不是当前代码假定的 10 页/分钟。

        同步端点没有轮询，调用方应直接用 :meth:`request` 逐页计 1 个令牌。
        """
        state = self._state(RESOURCE_TTS, base_url)
        rpm = state.budget.requests_per_minute
        cost = max(1, int(fixed_cost))
        expected = max(1.0, float(expected_duration_sec))
        if state.budget.unlimited:
            interval = _TTS_POLL_INTERVAL_FLOOR_SEC
            polls = max(1, int(expected / interval + 0.999))
            return cost + polls, interval

        safe_rpm = max(1, int(rpm))
        submit_share = max(1.0, safe_rpm * _TTS_SUBMIT_BUDGET_RATIO)
        poll_share = max(1.0, safe_rpm - submit_share)
        starts_per_minute = submit_share / cost
        ceiling = max(1, int(state.budget.max_concurrency))
        if state.limit_current < ceiling:
            ceiling = max(1, int(state.limit_current))
        inflight = max(1, min(ceiling, int(starts_per_minute * expected / 60.0 + 0.999)))
        interval = max(_TTS_POLL_INTERVAL_FLOOR_SEC, (60.0 * inflight) / poll_share)
        polls = max(1, int(expected / interval + 0.999))
        return cost + polls, round(interval, 2)

    # ------------------------------------------------------------------
    # 诊断
    # ------------------------------------------------------------------
    def snapshot(self) -> list[dict[str, Any]]:
        """返回每个限流键的当前状态（只读，供诊断接口使用）。"""
        with self._guard:
            states = list(self._states.values())
        result: list[dict[str, Any]] = []
        for state in states:
            with state.condition:
                state.refill(time.monotonic())
                result.append(
                    {
                        "resource": state.budget.key[0],
                        "gateway": state.budget.key[1],
                        "requests_per_minute": state.budget.requests_per_minute,
                        "max_concurrency": state.budget.max_concurrency,
                        "concurrency_limit_current": state.limit_current,
                        "active": state.active,
                        "queued": max(0, len(state.tickets) - 1) if state.tickets else 0,
                        "tokens_available": round(state.tokens, 2),
                        "passed": state.passed,
                        "timeouts": state.timeouts,
                        "rate_limit_events": state.rate_limit_events,
                        "waited_sec_total": round(state.waited_sec_total, 2),
                    }
                )
        return sorted(result, key=lambda item: (item["resource"], item["gateway"]))


_DEPENDENCIES: GovernorDependencies | None = None
_GOVERNOR: GenerationGovernor | None = None
_GOVERNOR_LOCK = threading.Lock()


def configure_generation_governor(
    dependencies: GovernorDependencies,
) -> GenerationGovernor:
    """由组合根调用一次；未调用时使用内置默认额度（仍然生效）。"""
    global _DEPENDENCIES, _GOVERNOR
    with _GOVERNOR_LOCK:
        _DEPENDENCIES = dependencies
        _GOVERNOR = GenerationGovernor(dependencies)
        return _GOVERNOR


def get_generation_governor() -> GenerationGovernor:
    global _GOVERNOR
    with _GOVERNOR_LOCK:
        if _GOVERNOR is None:
            _GOVERNOR = GenerationGovernor(_DEPENDENCIES)
        return _GOVERNOR


def reset_generation_governor() -> None:
    """测试用：清掉单例，下次调用按当前依赖重建。"""
    global _GOVERNOR
    with _GOVERNOR_LOCK:
        _GOVERNOR = None
