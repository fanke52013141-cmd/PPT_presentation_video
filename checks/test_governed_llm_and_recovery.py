"""LLM per-request governance, TTS partial success, and startup race tests.

覆盖优化方案验证 §5.4 / §5.5 与第二阶段修复：
- 每次 LLM 真实请求同时计量项目槽与网关全局额度；
- 并发不突破网关上限、退避期间不占额度许可；
- 格式回退只对明确的格式不兼容错误展开；
- TTS 单页排队超时保留部分成功并完整收尾；
- 一键任务启动与状态对账无竞态窗口；
- ToAPIs 恢复已有任务而不是重复提交。
"""

from __future__ import annotations

import concurrent.futures
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import threading
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ai_provider_service as provider  # noqa: E402
import generation_governor  # noqa: E402
import llm_concurrency  # noqa: E402
import one_click_orchestrator as one_click  # noqa: E402
import tts_service as tts  # noqa: E402


# ── LLM 格式回退门控 ──────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "error,expected",
    [
        (RuntimeError("'response_format' is not supported by this model"), True),
        (RuntimeError("json_object is unsupported here"), True),
        (RuntimeError("server exploded"), False),
        (RuntimeError("Error code: 429 - too many requests"), False),
        (RuntimeError("401 unauthorized"), False),
        (RuntimeError("connection reset by peer"), False),
        (generation_governor.GovernorTimeout("排队超过 600 秒"), False),
    ],
)
def test_llm_format_fallback_gating(error, expected) -> None:
    assert llm_concurrency.is_llm_format_incompatibility(error) is expected


# ── LLM 逐请求治理 ────────────────────────────────────────────────────────
class _PeakTracker:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.active = 0
        self.peak = 0

    def enter(self) -> None:
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)

    def leave(self) -> None:
        with self.lock:
            self.active -= 1


def _patch_governor(monkeypatch: pytest.MonkeyPatch, llm_concurrency_limit: int = 4):
    """注入独立的治理器单例：网关并发 1、RPM 不限，便于断言峰值。"""

    def bounded(key, default, minimum, maximum):
        if key == "llm_gateway_max_concurrency":
            return 1
        return default

    governor = generation_governor.GenerationGovernor(
        generation_governor.GovernorDependencies(
            get_bounded_int_setting=bounded,
        ),
        enabled=True,
        max_wait_sec=10.0,
    )
    monkeypatch.setattr(generation_governor, "_GOVERNOR", governor)
    original_reader = llm_concurrency._setting_reader
    llm_concurrency.configure_llm_concurrency(
        lambda key, default, low, high: max(low, min(high, llm_concurrency_limit))
    )
    return governor, original_reader


def test_each_llm_request_consumes_gateway_budget_and_respects_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    governor, original_reader = _patch_governor(monkeypatch)
    tracker = _PeakTracker()
    gateway = "https://llm-gateway.test/v1"

    def one_request():
        with llm_concurrency.governed_llm_request(gateway):
            tracker.enter()
            time.sleep(0.02)
            tracker.leave()

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: one_request(), range(8)))
    finally:
        llm_concurrency._setting_reader = original_reader

    # 网关并发上限为 1：任何时刻活跃请求不超过 1，且 8 次请求全部按次计量。
    assert tracker.peak == 1
    scope = generation_governor.gateway_scope(gateway)
    snapshot = {item["gateway"]: item for item in governor.snapshot()}
    assert snapshot[scope]["passed"] == 8
    assert snapshot[scope]["active"] == 0


def test_governed_llm_request_releases_quota_after_each_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    governor, original_reader = _patch_governor(monkeypatch)
    gateway = "https://llm-gateway.test/v1"
    try:
        for _ in range(3):
            with llm_concurrency.governed_llm_request(gateway):
                pass
    finally:
        llm_concurrency._setting_reader = original_reader
    scope = generation_governor.gateway_scope(gateway)
    snapshot = {item["gateway"]: item for item in governor.snapshot()}
    # 每次请求结束即释放：没有许可泄漏，三次请求全部被计量。
    assert snapshot[scope]["active"] == 0
    assert snapshot[scope]["passed"] == 3


def test_format_fallback_and_repair_count_as_separate_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """格式回退是独立的真实请求：必须单独计量，不能与首次请求合并。"""
    governor, original_reader = _patch_governor(monkeypatch)
    gateway = "https://llm-gateway.test/v1"
    calls: list[str] = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(str(kwargs.get("response_format")))
            if kwargs.get("response_format"):
                raise RuntimeError("'response_format' is not supported")
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))]
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    try:
        with llm_concurrency.governed_llm_request(gateway):
            pass
        # 模拟 json_llm_service 的回退结构：第二次真实请求单独计量。
        try:
            with llm_concurrency.governed_llm_request(gateway):
                client.chat.completions.create(response_format={"type": "json_object"})
        except RuntimeError:
            with llm_concurrency.governed_llm_request(gateway):
                client.chat.completions.create()
    finally:
        llm_concurrency._setting_reader = original_reader
    assert calls == ["{'type': 'json_object'}", "None"]
    scope = generation_governor.gateway_scope(gateway)
    snapshot = {item["gateway"]: item for item in governor.snapshot()}
    assert snapshot[scope]["passed"] == 3


# ── TTS 部分成功收尾 ──────────────────────────────────────────────────────
def _run_tts_with_stub(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, behavior: dict):
    run_dir = tmp_path / "runs" / "tts-project"
    (run_dir / "planning").mkdir(parents=True, exist_ok=True)
    (run_dir / "planning" / "visual_contract.json").write_text(
        json.dumps(
            {"slides": [{"slide_id": sid} for sid in ("slide_001", "slide_002", "slide_003")]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    project = SimpleNamespace(id="tts-project", name="T", run_dir=str(run_dir))
    rewritten: list[str] = []
    retry_marked: list[int] = []

    class Db:
        def commit(self):
            return None

    monkeypatch.setattr(tts, "project_or_404", lambda db, pid: project)
    monkeypatch.setattr(
        tts,
        "_resolve_tts_voice_profile",
        lambda _project: {
            "provider": "minimax",
            "project_runtime": None,
            "snapshot_value": lambda _k, _d="": "",
            "tts_api_key": "k",
            "tts_secret_key": "s",
            "runtime_secrets": {},
            "endpoint": "https://minimax.test",
            "model": "m",
            "voice_id": "v",
            "clone_voice_id": "c",
            "region": "r",
            "provider_extra": {},
            "speed": 1.0,
            "volume": 1.0,
            "pitch": 0,
            "concurrency": 4,
            "requests_per_minute": 10,
            "cache_key": {"provider": "minimax"},
        },
    )
    monkeypatch.setattr(tts, "_load_beats_by_slide", lambda *a, **k: {})
    monkeypatch.setattr(
        tts.invalidation_service, "narration_synthesis_started", lambda *_a: None
    )
    monkeypatch.setattr(
        tts,
        "slide_tts_artifact_paths",
        lambda project, sid: {
            "audio": str(tmp_path / f"{sid}.mp3"),
            "metadata": str(tmp_path / f"{sid}.json"),
            "srt": str(tmp_path / f"{sid}.srt"),
            "timeline": str(tmp_path / f"{sid}.timeline.json"),
        },
    )
    monkeypatch.setattr(
        tts, "ensure_slide_tts_text_file", lambda *a, **k: str(tmp_path / "text.txt")
    )
    monkeypatch.setattr(
        tts,
        "slide_tts_artifact_status",
        lambda *a, **k: {
            "complete": False,
            "audio_exists": False,
            "missing_artifacts": ["audio"],
            "stale": False,
        },
    )
    monkeypatch.setattr(tts, "remove_tts_artifacts", lambda _paths: None)
    monkeypatch.setattr(
        tts, "provider_tts_command", lambda **_kw: ["tts-helper", "stub"]
    )
    monkeypatch.setattr(tts, "provider_tts_environment", lambda *a, **k: {})
    monkeypatch.setattr(tts, "_shared_tts_launch_throttle", lambda *a, **k: None)
    monkeypatch.setattr(tts, "_minimax_poll_interval_seconds", lambda *a, **k: None)
    monkeypatch.setattr(tts, "is_minimax_async_endpoint", lambda *_a: False)

    synthesized: set[str] = set()

    def fake_run_tts(project_arg, slide_id, args, env, **kwargs):
        mode = behavior[slide_id]
        if mode == "ok":
            synthesized.add(slide_id)
            return {"ok": True, "returncode": 0, "stdout": "", "stderr": "", "attempts": 1}
        if mode == "queue_timeout":
            raise generation_governor.GovernorTimeout("tts 网关排队超过 600 秒")
        raise RuntimeError("tts worker exploded")

    def fake_artifact_status(_project, slide_id):
        complete = slide_id in synthesized
        return {
            "complete": complete,
            "audio_exists": complete,
            "missing_artifacts": [] if complete else ["audio"],
            "stale": False,
        }

    monkeypatch.setattr(tts, "slide_tts_artifact_status", fake_artifact_status)

    monkeypatch.setattr(tts, "run_tts_command_with_retries", fake_run_tts)
    monkeypatch.setattr(
        tts,
        "rewrite_audio_timeline_by_beats",
        lambda _timeline, slide_id, _beats: rewritten.append(slide_id),
    )
    monkeypatch.setattr(
        tts, "mark_step_retry_needed", lambda _project, step, _db: retry_marked.append(step)
    )
    monkeypatch.setattr(
        tts, "write_project_log", lambda *a, **k: None
    )

    result = tts.synthesize_tts_resumable("tts-project", Db())
    return result, rewritten, retry_marked


def test_tts_queue_timeout_keeps_partial_success_and_finalizes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, rewritten, retry_marked = _run_tts_with_stub(
        monkeypatch,
        tmp_path,
        {"slide_001": "ok", "slide_002": "queue_timeout", "slide_003": "ok"},
    )

    # 部分成功保留：成功页完成时间轴处理并进入 generated 列表
    assert result["success"] is False
    assert sorted(result["generated"]) == ["slide_001", "slide_003"]
    assert sorted(rewritten) == ["slide_001", "slide_003"]
    failed = result["failed"]
    assert [item["slide_id"] for item in failed] == ["slide_002"]
    assert "排队超时" in failed[0]["error"] or "TTS 网关" in failed[0]["error"]
    assert retry_marked == [7]


def test_tts_worker_crash_is_contained_per_slide(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, rewritten, _retry_marked = _run_tts_with_stub(
        monkeypatch,
        tmp_path,
        {"slide_001": "ok", "slide_002": "crash", "slide_003": "ok"},
    )
    assert result["success"] is False
    assert sorted(result["generated"]) == ["slide_001", "slide_003"]
    failed = result["failed"]
    assert [item["slide_id"] for item in failed] == ["slide_002"]
    assert "RuntimeError" in failed[0]["error"]


# ── 一键任务启动竞态 ──────────────────────────────────────────────────────
def test_start_registers_worker_before_status_readers_can_downgrade(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project = SimpleNamespace(
        id="race-project", ai_mode="auto", run_dir=str(tmp_path), account_id="acct-a"
    )
    status = one_click._initial_status(project.id, "run-race")
    saved: list[dict] = []
    real_thread_cls = threading.Thread
    run_started = threading.Event()

    class FakeThread:
        def __init__(self, **kwargs):
            self.alive_value = False

        def is_alive(self):
            return self.alive_value

        def start(self):
            self.alive_value = True
            run_started.set()

    monkeypatch.setattr(one_click, "get_one_click_dependencies", lambda: object())
    # worker 注册前的空闲状态、注册后的运行状态，与真实文件行为一致。
    monkeypatch.setattr(
        one_click,
        "_status_for_project",
        lambda *_a: {
            "status": "running" if run_started.is_set() else "idle"
        },
    )
    monkeypatch.setattr(one_click, "_resume_status", lambda *_a: (dict(status), 0))
    monkeypatch.setattr(
        one_click, "_save_status", lambda _project, value: saved.append(value)
    )
    monkeypatch.setattr(one_click.threading, "Thread", FakeThread)

    observations: list[str] = []
    stop_polling = threading.Event()

    def poll():
        while not stop_polling.is_set():
            try:
                current = one_click.get_one_click_status(project)
                observations.append(str(current["status"].get("status")))
            except Exception as exc:  # pragma: no cover - 观察线程不允许抛错
                observations.append(f"error:{type(exc).__name__}")
                return
            time.sleep(0.005)

    # 观察线程必须在替换 threading.Thread 之前用真实线程类创建。
    poller = real_thread_cls(target=poll, daemon=True)
    poller.start()
    try:
        result = one_click.start_one_click(project)
        # worker 已注册并存活：多次读取状态都必须保持 running。
        for _ in range(20):
            current = one_click.get_one_click_status(project)
            assert current["status"]["status"] == "running"
            time.sleep(0.005)
        # 负向对照：worker 退出（无存活注册线程）后，旧的 running 状态
        # 必须被对账为 paused —— 不会伪装成仍在执行。
        one_click._RUNNING.pop(project.id, None)
        downgraded = one_click.get_one_click_status(project)
        assert downgraded["status"]["status"] == "paused"
    finally:
        one_click._RUNNING.pop(project.id, None)
        stop_polling.set()
        poller.join(timeout=2)

    assert result["started"] is True
    assert saved and saved[0]["status"] == "running"
    assert saved[-1]["status"] == "paused"  # 负向对照的落盘结果
    # 启动期间与启动之后，只要 worker 仍然存活，读取方就不得误写成 paused。
    assert "paused" not in observations
    assert "error" not in ",".join(observations)


def test_thread_start_failure_cleans_registration_and_writes_terminal_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project = SimpleNamespace(
        id="start-fail-project", ai_mode="auto", run_dir=str(tmp_path), account_id="acct-a"
    )
    status = one_click._initial_status(project.id, "run-fail")
    saved: list[dict] = []

    class ExplodingThread:
        def __init__(self, **kwargs):
            pass

        def start(self):
            raise RuntimeError("cannot spawn thread")

    monkeypatch.setattr(one_click, "get_one_click_dependencies", lambda: object())
    monkeypatch.setattr(
        one_click, "_status_for_project", lambda *_a: {"status": "idle"}
    )
    monkeypatch.setattr(one_click, "_resume_status", lambda *_a: (dict(status), 0))
    monkeypatch.setattr(
        one_click, "_save_status", lambda _project, value: saved.append(value)
    )
    monkeypatch.setattr(one_click.threading, "Thread", ExplodingThread)

    with pytest.raises(RuntimeError):
        one_click.start_one_click(project)

    assert project.id not in one_click._RUNNING
    assert saved and saved[-1]["status"] == "failed"
    assert "启动失败" in str(saved[-1].get("message", ""))


# ── ToAPIs 任务恢复 ───────────────────────────────────────────────────────
class _FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = {}
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class _FakeHttpxClient:
    def __init__(self, responses: list[_FakeResponse], **_kwargs) -> None:
        self.responses = list(responses)
        self.gets: list[str] = []
        self.posts: list[str] = []

    def get(self, url, headers=None, **_kwargs):
        self.gets.append(url)
        return self.responses.pop(0)

    def post(self, url, **_kwargs):
        self.posts.append(url)
        raise AssertionError("resume_task_id must skip task submission")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_toapis_resume_polls_existing_task_without_resubmitting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = [
        _FakeResponse(200, {"status": "completed", "result": {"data": [{"url": "https://cdn.test/x.png"}]}}),
    ]
    fake_client = _FakeHttpxClient(responses)
    # 让 generate_toapis_image_response 打开的就是带记录的假客户端。
    monkeypatch.setattr(provider.httpx, "Client", lambda **kw: _SharedFake(fake_client))
    result = provider.generate_toapis_image_response(
        api_key="k",
        base_url="https://toapis.test",
        model="gpt-image-2-vip",
        prompt="p",
        size="16:9",
        resume_task_id="task-123",
    )
    assert result["toapis_task_id"] == "task-123"
    assert result["data"][0]["url"] == "https://cdn.test/x.png"
    assert fake_client.gets and "/v1/images/generations/task-123" in fake_client.gets[0]
    assert fake_client.posts == []


class _SharedFake(_FakeHttpxClient):
    """Delegate to one shared recorder so assertions see every call."""

    def __init__(self, shared: _FakeHttpxClient) -> None:
        self.__dict__ = shared.__dict__


def test_toapis_transient_poll_failure_keeps_polling_same_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = [
        _FakeResponse(503, {"message": "overloaded"}),
        _FakeResponse(200, {"status": "completed", "result": {"data": [{"url": "https://cdn.test/y.png"}]}}),
    ]
    shared = _FakeHttpxClient(responses)
    monkeypatch.setattr(provider.httpx, "Client", lambda **kw: _SharedFake(shared))
    result = provider.generate_toapis_image_response(
        api_key="k",
        base_url="https://toapis.test",
        model="gpt-image-2-vip",
        prompt="p",
        size="16:9",
        resume_task_id="task-456",
    )
    assert result["toapis_task_id"] == "task-456"
    assert len(shared.gets) == 2
    assert shared.posts == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
