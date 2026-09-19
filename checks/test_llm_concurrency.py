"""LLM concurrency gate and shared TTS launch throttle tests."""

from __future__ import annotations

import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import llm_concurrency  # noqa: E402
import tts_service as tts  # noqa: E402


@pytest.fixture
def configured_limit():
    original = llm_concurrency._setting_reader
    limits = {"value": 1}
    llm_concurrency.configure_llm_concurrency(
        lambda key, default, min_value, max_value: max(
            min_value, min(max_value, limits["value"])
        )
    )
    yield limits
    llm_concurrency._setting_reader = original


def _peak_concurrency(worker_count: int, hold_sec: float) -> int:
    state = {"active": 0, "peak": 0}
    lock = threading.Lock()

    def work():
        with llm_concurrency.llm_request_slot():
            with lock:
                state["active"] += 1
                state["peak"] = max(state["peak"], state["active"])
            time.sleep(hold_sec)
            with lock:
                state["active"] -= 1

    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = [pool.submit(work) for _ in range(worker_count)]
        for future in futures:
            future.result(timeout=30)
    return state["peak"]


def test_gate_serializes_requests_at_limit_one(configured_limit) -> None:
    configured_limit["value"] = 1
    assert _peak_concurrency(4, 0.05) == 1


def test_gate_allows_configured_parallelism(configured_limit) -> None:
    configured_limit["value"] = 3
    assert _peak_concurrency(6, 0.05) <= 3


def test_gate_honours_limit_changed_between_calls(configured_limit) -> None:
    configured_limit["value"] = 1
    assert _peak_concurrency(2, 0.02) == 1
    configured_limit["value"] = 4
    assert _peak_concurrency(4, 0.02) <= 4


def test_decorator_releases_slot_on_failure(configured_limit) -> None:
    configured_limit["value"] = 1

    @llm_concurrency.with_llm_request_slot
    def failing():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        failing()
    # The slot must be free again for the next request.
    assert _peak_concurrency(1, 0.01) == 1


def test_shared_throttle_is_one_gate_per_connection() -> None:
    first = tts._shared_tts_launch_throttle("minimax", "https://api.minimaxi.test/v1/", "key-a", 6.0)
    second = tts._shared_tts_launch_throttle("minimax", "https://api.minimaxi.test/v1", "key-a", 3.0)
    assert first is second
    # A stricter later request tightens the shared gate; a looser one never loosens it.
    assert first._minimum_interval_sec == 6.0
    third = tts._shared_tts_launch_throttle("minimax", "https://api.minimaxi.test/v1", "key-b", 6.0)
    assert third is not first
    fourth = tts._shared_tts_launch_throttle("volcengine", "https://api.minimaxi.test/v1", "key-a", 6.0)
    assert fourth is not first


def test_shared_throttle_spaces_starts_across_threads() -> None:
    throttle = tts._shared_tts_launch_throttle("minimax", "https://throttle.test/v1", "throttle-key", 0.25)
    starts: list[float] = []
    lock = threading.Lock()

    def launch():
        throttle.wait_for_turn()
        with lock:
            starts.append(time.monotonic())

    with ThreadPoolExecutor(max_workers=3) as pool:
        for _ in range(3):
            pool.submit(launch)
    assert len(starts) == 3
    assert starts == sorted(starts)
    assert starts[1] - starts[0] >= 0.2
    assert starts[2] - starts[1] >= 0.2


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
