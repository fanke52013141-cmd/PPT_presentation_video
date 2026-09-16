"""ToAPIs 生图链路的**网关额度集成测试**。

单元测试证明了令牌桶 / 并发许可 / FIFO 排队本身正确；这里证明的是另一件事：
**真实生图代码路径里的每一次上游请求都确实过了治理器**。

覆盖审核报告里的两个 P0：
- 参考图上传、任务提交、状态轮询三类请求全部计费（旧实现完全不计量）；
- 撞 429 时退避重试，且重试也走同一份额度。

用假的 httpx 客户端替换真实网络，因此不产生任何真实调用。
"""

import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ai_provider_service  # noqa: E402
import generation_governor  # noqa: E402
from generation_governor import (  # noqa: E402
    GenerationGovernor,
    GovernorDependencies,
    RESOURCE_IMAGE,
)

BASE_URL = "https://api.toapis.com"


class _FakeResponse:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)
        self.headers: dict[str, str] = {}

    def json(self) -> Any:
        return self._payload


class _RecordingTransport:
    """记录每一次请求，并统计同时在飞的请求数。"""

    def __init__(self, *, fail_first_submit: bool = False) -> None:
        self.calls: list[tuple[str, float]] = []
        self.in_flight = 0
        self.peak_in_flight = 0
        self._lock = threading.Lock()
        self._fail_first_submit = fail_first_submit
        self._submit_attempts = 0

    def __enter__(self) -> "_RecordingTransport":
        return self

    def __exit__(self, *_exc: Any) -> bool:
        return False

    def _enter(self, method: str, url: str) -> None:
        with self._lock:
            self.calls.append((f"{method} {url}", time.monotonic()))
            self.in_flight += 1
            self.peak_in_flight = max(self.peak_in_flight, self.in_flight)

    def _exit(self) -> None:
        with self._lock:
            self.in_flight -= 1

    def post(self, url: str, **_kwargs: Any) -> _FakeResponse:
        self._enter("POST", url)
        try:
            if "/v1/uploads/images" in url:
                return _FakeResponse(200, {"success": True, "data": {"url": "https://cdn/ref.png"}})
            if url.rstrip("/").endswith("/v1/images/generations"):
                with self._lock:
                    self._submit_attempts += 1
                    attempt = self._submit_attempts
                if self._fail_first_submit and attempt == 1:
                    return _FakeResponse(429, {"message": "rate limit exceeded"})
                return _FakeResponse(200, {"success": True, "id": "task-1"})
            raise AssertionError(f"unexpected POST {url}")
        finally:
            self._exit()

    def get(self, url: str, **_kwargs: Any) -> _FakeResponse:
        self._enter("GET", url)
        try:
            # 第一次轮询就完成，避免测试里出现真实等待。
            return _FakeResponse(
                200,
                {"status": "completed", "result": {"data": [{"url": "https://cdn/out.png"}]}},
            )
        finally:
            self._exit()


@pytest.fixture()
def governor():
    """用一个额度很小但足够跑完测试的治理器替换进程单例。"""
    configured = generation_governor.configure_generation_governor(
        GovernorDependencies(
            get_bounded_int_setting=lambda key, default, minimum, maximum: {
                "image_gateway_requests_per_minute": 6000,
                "image_gateway_max_concurrency": 3,
            }.get(key, default)
        )
    )
    yield configured
    generation_governor.reset_generation_governor()


@pytest.fixture()
def transport(monkeypatch: pytest.MonkeyPatch):
    def _install(*, fail_first_submit: bool = False) -> _RecordingTransport:
        recorder = _RecordingTransport(fail_first_submit=fail_first_submit)
        monkeypatch.setattr(
            ai_provider_service.httpx, "Client", lambda **_kwargs: recorder
        )
        return recorder

    return _install


def _generate(reference: Path | None, results: list, index: int) -> None:
    try:
        results.append(
            ai_provider_service.generate_toapis_image_response(
                api_key="test-key",
                base_url=BASE_URL,
                model="gpt-image-2-vip",
                prompt="draw something",
                size="1920x1080",
                reference_paths=[str(reference)] if reference else None,
            )
        )
    except Exception as exc:  # pragma: no cover - 失败信息由断言呈现
        results.append(exc)


def test_every_toapis_request_goes_through_the_gateway_budget(
    governor: GenerationGovernor,
    transport,
    tmp_path: Path,
) -> None:
    """一次生图 = 上传参考图 + 提交任务 + 轮询状态，三次请求都必须计费。"""
    recorder = transport()
    reference = tmp_path / "ref.png"
    reference.write_bytes(b"fake-png")

    ai_provider_service.generate_toapis_image_response(
        api_key="test-key",
        base_url=BASE_URL,
        model="gpt-image-2-vip",
        prompt="draw something",
        size="1920x1080",
        reference_paths=[str(reference)],
    )

    kinds = [call.split(" ")[0] for call, _ in recorder.calls]
    assert kinds == ["POST", "POST", "GET"], recorder.calls
    assert any("/v1/uploads/images" in call for call, _ in recorder.calls)
    assert any("/v1/images/generations" in call for call, _ in recorder.calls)

    snapshot = governor.snapshot()[0]
    assert snapshot["resource"] == "image"
    assert snapshot["gateway"] == BASE_URL
    assert snapshot["passed"] == 3, "上传/提交/轮询三次请求都必须计入网关额度"


def test_concurrent_image_jobs_share_one_global_gateway_budget(
    governor: GenerationGovernor,
    transport,
) -> None:
    """多项目/多账号并发生图时，合计请求仍然只走同一份额度与同一个并发上限。"""
    recorder = transport()
    results: list = []
    threads = [
        threading.Thread(target=_generate, args=(None, results, index))
        for index in range(6)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)

    assert len(results) == 6
    assert all(not isinstance(item, Exception) for item in results), results
    # 6 个任务 × (提交 + 轮询) = 12 次请求，全部计入同一个网关条目。
    snapshots = governor.snapshot()
    assert len(snapshots) == 1, "同一网关的不同账号必须落在同一个额度桶里"
    assert snapshots[0]["passed"] == 12
    assert recorder.peak_in_flight <= 3, (
        f"同时在飞请求数突破全局并发上限：{recorder.peak_in_flight}"
    )


def test_rate_limited_request_is_retried_within_the_same_budget(
    governor: GenerationGovernor,
    transport,
) -> None:
    """撞 429 时退避重试；重试同样计费，并触发 AIMD 降档。"""
    recorder = transport(fail_first_submit=True)

    response = ai_provider_service.generate_toapis_image_response(
        api_key="test-key",
        base_url=BASE_URL,
        model="gpt-image-2-vip",
        prompt="draw something",
        size="1920x1080",
    )

    assert response["data"][0]["url"] == "https://cdn/out.png"
    submits = [
        call
        for call, _ in recorder.calls
        if call.startswith("POST") and call.rstrip("/").endswith("/v1/images/generations")
    ]
    assert len(submits) == 2, "第一次 429 应当被退避后重试一次"

    snapshot = governor.snapshot()[0]
    assert snapshot["rate_limit_events"] == 1
    assert snapshot["concurrency_limit_current"] == 1, "撞限流后并发上限应当减半"
    # 429 提交 + 重试提交 + 轮询 = 3 次全部计费
    assert snapshot["passed"] == 3
