"""并发治理器回归测试。

覆盖审核报告中的 P0/P1 问题：
- 额度是网关全局的，多调用方必须共享同一份预算（不能按项目/密钥分桶叠加）；
- 额度耗尽时**排队等待**而不是降档抛错；
- 并发上限有界，等待者按先到先服务顺序放行，超时不会堵死后续等待者；
- 长任务按预估成本整体预留令牌（子进程内的 HTTP 无法逐请求计量）；
- 撞限流后并发上限减半、连续成功后回升（AIMD）。
"""

import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from generation_governor import (  # noqa: E402
    GenerationGovernor,
    GovernorDependencies,
    GovernorTimeout,
    RESOURCE_IMAGE,
    RESOURCE_TTS,
    gateway_scope,
    rate_limit_delay_seconds,
)

IMAGE_URL = "https://api.toapis.com"


def _deps(**values):
    """构造只读固定值的设置读取器。"""

    def reader(key, default, minimum, maximum):
        return values.get(key, default)

    return GovernorDependencies(get_bounded_int_setting=reader)


def _image_governor(*, rpm=60000, concurrency=12, max_wait_sec=10.0):
    return GenerationGovernor(
        _deps(
            image_gateway_requests_per_minute=rpm,
            image_gateway_max_concurrency=concurrency,
        ),
        max_wait_sec=max_wait_sec,
    )


def _wait_until(predicate, timeout=3.0, interval=0.005):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


# ---------------------------------------------------------------------------
# 限流键
# ---------------------------------------------------------------------------
def test_gateway_key_never_contains_credentials():
    """额度是网关全局的：同一网关的不同密钥/路径必须落进同一个桶。"""
    assert gateway_scope("https://api.toapis.com/v1/images") == "https://api.toapis.com"
    assert gateway_scope("HTTPS://API.TOAPIS.COM/other") == "https://api.toapis.com"
    assert gateway_scope("") == "default"
    assert gateway_scope(None) == "default"

    governor = _image_governor()
    with governor.request(RESOURCE_IMAGE, "https://api.toapis.com/v1/images?key=A"):
        pass
    with governor.request(RESOURCE_IMAGE, "https://api.toapis.com/v2/other?key=B"):
        pass
    assert len(governor.snapshot()) == 1


# ---------------------------------------------------------------------------
# 令牌桶：额度真的被强制执行
# ---------------------------------------------------------------------------
def test_token_refill_matches_requests_per_minute():
    """补充速率必须等于 rpm/60，而不是"每分钟整批重置"。"""
    governor = _image_governor(rpm=60)
    state = governor._state(RESOURCE_IMAGE, IMAGE_URL)
    with state.condition:
        state.tokens = 0.0
        state.updated_at = time.monotonic() - 30.0
        state.refill(time.monotonic())
    assert state.tokens == pytest.approx(30.0, abs=1.5)


def test_exhausted_budget_queues_instead_of_failing():
    """额度耗尽时排队；超时才抛 GovernorTimeout（不是"降档到 1 就判死"）。"""
    governor = _image_governor(rpm=60, concurrency=4, max_wait_sec=30.0)
    with governor.request(RESOURCE_IMAGE, IMAGE_URL, cost=60):
        pass  # 一次性抽干整桶（capacity == rpm）

    with pytest.raises(GovernorTimeout):
        with governor.request(RESOURCE_IMAGE, IMAGE_URL, cost=1, timeout_sec=0.3):
            pass

    # 恢复 1 个令牌约需 1 秒；给足等待时间后必须能成功，而不是永久失败。
    started = time.monotonic()
    with governor.request(RESOURCE_IMAGE, IMAGE_URL, cost=1, timeout_sec=10.0):
        pass
    waited = time.monotonic() - started
    assert waited >= 0.4, f"应当排队等待而不是立刻放行，实际只等了 {waited:.3f}s"

    snapshot = governor.snapshot()[0]
    assert snapshot["timeouts"] == 1
    assert snapshot["passed"] == 2


def test_timeout_releases_its_ticket_so_others_proceed():
    """超时的等待者必须归还号牌，否则会永久堵死后面的调用方。"""
    governor = _image_governor(rpm=60000, concurrency=1)
    state = governor._state(RESOURCE_IMAGE, IMAGE_URL)
    observed = []

    def worker():
        try:
            with governor.request(RESOURCE_IMAGE, IMAGE_URL, timeout_sec=0.2):
                observed.append("acquired")
        except GovernorTimeout:
            observed.append("timeout")

    with governor.request(RESOURCE_IMAGE, IMAGE_URL):
        thread = threading.Thread(target=worker)
        thread.start()
        assert _wait_until(lambda: state.next_ticket >= 2)
        thread.join(3.0)

    assert observed == ["timeout"]
    assert _wait_until(lambda: len(state.tickets) == 0)
    # 号牌归还后，后续调用方仍然能正常拿到许可。
    with governor.request(RESOURCE_IMAGE, IMAGE_URL, timeout_sec=2.0):
        pass


# ---------------------------------------------------------------------------
# 并发许可
# ---------------------------------------------------------------------------
def test_concurrency_limit_is_shared_and_not_exceeded():
    """并发上限对所有调用方共享；同时必须真的允许并行（不是被串行化）。"""
    governor = _image_governor(rpm=60000, concurrency=2)
    lock = threading.Lock()
    both_inside = threading.Event()
    peak = 0
    active = 0

    def worker():
        nonlocal peak, active
        with governor.request(RESOURCE_IMAGE, IMAGE_URL):
            with lock:
                active += 1
                peak = max(peak, active)
                if active >= 2:
                    both_inside.set()
            both_inside.wait(2.0)
            with lock:
                active -= 1

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5.0)

    assert both_inside.is_set(), "并发上限为 2 时应当允许两个调用方同时进入"
    assert peak <= 2, f"并发上限被突破：{peak}"


def test_waiters_are_served_in_fifo_order():
    """先到先服务：后启动的项目不能插队抢占（修 P1-5）。"""
    governor = _image_governor(rpm=60000, concurrency=1)
    state = governor._state(RESOURCE_IMAGE, IMAGE_URL)
    order = []

    def worker(index):
        with governor.request(RESOURCE_IMAGE, IMAGE_URL, timeout_sec=5.0):
            order.append(index)

    with governor.request(RESOURCE_IMAGE, IMAGE_URL):
        threads = []
        for index in range(3):
            thread = threading.Thread(target=worker, args=(index,))
            thread.start()
            threads.append(thread)
            # 等这个线程登记号牌后再启动下一个，保证入队顺序确定。
            assert _wait_until(lambda expected=index: state.next_ticket >= expected + 2)
    # 主线程释放许可后，三个等待者必须按入队顺序依次通过。
    for thread in threads:
        thread.join(5.0)

    assert order == [0, 1, 2], f"等待顺序应为先到先服务，实际 {order}"


def test_job_reservation_counts_against_the_global_budget():
    """长任务按预估成本整体预留：rpm=10、每页 5 个令牌时最多 2 个在飞。"""
    governor = GenerationGovernor(
        _deps(tts_gateway_requests_per_minute=10, tts_gateway_max_concurrency=4),
        max_wait_sec=30.0,
    )
    holding = threading.Event()

    def holder():
        with governor.job(RESOURCE_TTS, "https://api.minimaxi.com", reserved_cost=5):
            holding.wait(3.0)

    threads = [threading.Thread(target=holder) for _ in range(2)]
    for thread in threads:
        thread.start()
    assert _wait_until(lambda: governor.snapshot()[0]["active"] == 2)

    # 第 3 个任务需要再预留 5 个令牌，但额度已被前两个占满。
    with pytest.raises(GovernorTimeout):
        with governor.job(
            RESOURCE_TTS, "https://api.minimaxi.com", reserved_cost=5, timeout_sec=0.3
        ):
            pass

    holding.set()
    for thread in threads:
        thread.join(5.0)


# ---------------------------------------------------------------------------
# AIMD 反馈
# ---------------------------------------------------------------------------
def test_rate_limit_halves_concurrency_and_successes_recover():
    """修 P1-1：撞限流减半，但必须能回升，不能"只降不升"。"""
    governor = _image_governor(rpm=60000, concurrency=8)
    state = governor._state(RESOURCE_IMAGE, IMAGE_URL)
    assert state.limit_current == 8

    assert (
        governor.record_rate_limit(
            RESOURCE_IMAGE, IMAGE_URL, error=RuntimeError("HTTP 429 Retry-After: 7")
        )
        == 7.0
    )
    assert state.limit_current == 4
    governor.record_rate_limit(RESOURCE_IMAGE, IMAGE_URL, error=RuntimeError("429"))
    assert state.limit_current == 2
    governor.record_rate_limit(RESOURCE_IMAGE, IMAGE_URL, error=RuntimeError("429"))
    assert state.limit_current == 1
    governor.record_rate_limit(RESOURCE_IMAGE, IMAGE_URL, error=RuntimeError("429"))
    assert state.limit_current == 1, "并发下限不得低于 1"

    for _ in range(19):
        governor.note_success(RESOURCE_IMAGE, IMAGE_URL)
    assert state.limit_current == 1, "未达到回升阈值前不应提前回升"
    governor.note_success(RESOURCE_IMAGE, IMAGE_URL)
    assert state.limit_current == 2

    for _ in range(20 * 8):
        governor.note_success(RESOURCE_IMAGE, IMAGE_URL)
    assert state.limit_current == 8, "回升不得超过配置的并发上限"


def test_rate_limit_delay_prefers_retry_after_then_backs_off():
    assert rate_limit_delay_seconds(RuntimeError("429 Retry-After: 7"), 0) == 7.0
    assert rate_limit_delay_seconds(RuntimeError("no hint"), 0) == 5.0
    assert rate_limit_delay_seconds(RuntimeError("no hint"), 2) == 20.0
    assert rate_limit_delay_seconds(RuntimeError("no hint"), 9) == 60.0


def test_backoff_sleep_does_not_hold_a_concurrency_slot():
    """退避发生在治理器之外，期间并发许可必须可被其他调用方使用。"""
    governor = _image_governor(rpm=60000, concurrency=1)
    governor.record_rate_limit(RESOURCE_IMAGE, IMAGE_URL, error=RuntimeError("429"))
    with governor.request(RESOURCE_IMAGE, IMAGE_URL, timeout_sec=1.0):
        pass  # 减半后 limit=1，仍然可以进入
    assert governor.snapshot()[0]["active"] == 0


# ---------------------------------------------------------------------------
# 语音合成成本模型
# ---------------------------------------------------------------------------
def test_tts_async_reservation_fits_the_ten_per_minute_budget():
    """异步端点每页真实成本是 3 次固定请求加轮询，不是 1 次。"""
    governor = GenerationGovernor(
        _deps(tts_gateway_requests_per_minute=10, tts_gateway_max_concurrency=4),
        max_wait_sec=30.0,
    )
    reserved, interval = governor.tts_async_reservation(
        base_url="https://api.minimaxi.com",
        expected_duration_sec=40.0,
    )
    # 提交预算 4/min、固定成本 3 → 起搏 1.33 页/min → 在飞 1 页；
    # 轮询预算 6/min → 间隔 10 秒 → 预留 3 + 4 = 7 个令牌。
    assert interval == 10.0
    assert reserved == 7
    # 关键不变量：在飞页数 × 每页成本不得超过一分钟的额度。
    assert reserved * 1 <= 10


def test_tts_async_reservation_scales_with_higher_entitlement():
    """额度更高时轮询更密（取到 8 秒下限），页吞吐必须超过线性增长。"""
    low = GenerationGovernor(
        _deps(tts_gateway_requests_per_minute=10, tts_gateway_max_concurrency=4),
        max_wait_sec=30.0,
    )
    high = GenerationGovernor(
        _deps(tts_gateway_requests_per_minute=600, tts_gateway_max_concurrency=10),
        max_wait_sec=30.0,
    )
    low_reserved, low_interval = low.tts_async_reservation(
        base_url="https://api.minimaxi.com", expected_duration_sec=40.0
    )
    high_reserved, high_interval = high.tts_async_reservation(
        base_url="https://api.minimaxi.com", expected_duration_sec=40.0
    )

    assert low_interval == 10.0
    assert high_interval == 8.0, "轮询间隔不得快于 8 秒下限"
    assert low_reserved == 7
    assert high_reserved == 8
    # 不变量一：一分钟内能被消耗的令牌不得超过额度。
    assert low_reserved * 1 <= 10
    assert high_reserved * 10 <= 600
    # 不变量二：每页成本不随额度恶化（低额度 7、高额度 8，差距来自轮询下限）。
    assert high_reserved <= low_reserved + 2
    # 不变量三：页吞吐随额度显著提升（额度 ×60，页吞吐至少 ×30）。
    low_pages_per_minute = 10 / low_reserved
    high_pages_per_minute = 600 / high_reserved
    assert high_pages_per_minute > low_pages_per_minute * 30


# ---------------------------------------------------------------------------
# 开关与诊断
# ---------------------------------------------------------------------------
def test_disabled_governor_is_transparent():
    """kill switch：关闭后完全透传，不排队、不计数。"""
    governor = GenerationGovernor(GovernorDependencies(), enabled=False)
    started = time.monotonic()
    for _ in range(50):
        with governor.request(RESOURCE_IMAGE, IMAGE_URL, cost=1000):
            pass
    assert time.monotonic() - started < 2.0
    assert governor.snapshot() == []


def test_runtime_budget_change_takes_effect_without_restart():
    """系统设置里把额度调小后，必须立刻生效，不能继续按旧额度放行。"""
    live_settings = {
        "image_gateway_requests_per_minute": 6000,
        "image_gateway_max_concurrency": 8,
    }

    def reader(key, default, minimum, maximum):
        return live_settings.get(key, default)

    governor = GenerationGovernor(
        GovernorDependencies(get_bounded_int_setting=reader), max_wait_sec=30.0
    )
    state = governor._state(RESOURCE_IMAGE, IMAGE_URL)
    for _ in range(3):
        governor.record_rate_limit(RESOURCE_IMAGE, IMAGE_URL, error=RuntimeError("429"))
    assert state.limit_current == 1

    live_settings["image_gateway_max_concurrency"] = 2
    live_settings["image_gateway_requests_per_minute"] = 60
    refreshed = governor._state(RESOURCE_IMAGE, IMAGE_URL)

    assert refreshed is state
    assert state.budget.max_concurrency == 2
    assert state.budget.requests_per_minute == 60
    assert state.limit_current <= 2, "当前并发上限不得高于新的配置上限"
    assert state.tokens <= 60.0, "令牌余量不得高于新额度"

    snapshot = governor.snapshot()[0]
    assert snapshot["requests_per_minute"] == 60
    assert snapshot["max_concurrency"] == 2


def test_tts_endpoint_marker_matches_the_helper_script():
    """端点判定必须与 scripts/minimax_tts.py 的异步分支保持一致。

    判定漂移的后果很直接：同步端点被当成异步（按 4-7 次请求预留，白等），
    或异步端点被当成同步（按 1 次请求放行，超发 4 倍）。
    """
    from tts_provider_service import is_minimax_async_endpoint

    assert is_minimax_async_endpoint("https://api.minimaxi.com/v1/t2a_async_v2")
    assert not is_minimax_async_endpoint("https://api.minimaxi.com/v1/t2a_v2")
    assert not is_minimax_async_endpoint("https://tts.example/v1")
    assert not is_minimax_async_endpoint("")
    # 与助手脚本的判定实现保持同源。
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from minimax_tts import is_async_endpoint  # type: ignore

    for endpoint in (
        "https://api.minimaxi.com/v1/t2a_async_v2",
        "https://api.minimaxi.com/v1/t2a_v2",
    ):
        assert is_minimax_async_endpoint(endpoint) == is_async_endpoint(endpoint)


def test_snapshot_reports_every_gateway_separately():
    governor = _image_governor()
    tts_governor = GenerationGovernor(
        _deps(tts_gateway_requests_per_minute=10, tts_gateway_max_concurrency=2)
    )
    with governor.request(RESOURCE_IMAGE, IMAGE_URL):
        pass
    with tts_governor.request(RESOURCE_TTS, "https://api.minimaxi.com"):
        pass

    image_snapshot = governor.snapshot()
    tts_snapshot = tts_governor.snapshot()
    assert [(item["resource"], item["gateway"]) for item in image_snapshot] == [
        ("image", "https://api.toapis.com")
    ]
    assert [(item["resource"], item["gateway"]) for item in tts_snapshot] == [
        ("tts", "https://api.minimaxi.com")
    ]
    assert tts_snapshot[0]["requests_per_minute"] == 10
    assert tts_snapshot[0]["passed"] == 1
