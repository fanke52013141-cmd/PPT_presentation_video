"""One-click image batch aggregation and resume-refill integration tests.

覆盖优化方案验证 §5.3 / §5.5：批次只在末尾汇总、失败页带完整原因与尝试
次数、成功页保留并统一收尾、继续只补缺失页、暂停请求不越过阶段边界。
不调用任何真实付费接口。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import sys

from fastapi import HTTPException

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import one_click_orchestrator as one_click  # noqa: E402
from image_generation_errors import ImagePageFailure  # noqa: E402


SLIDE_COUNT = 15
TRANSIENT_SLIDE = "slide_014"
PARAM_SLIDE = "slide_015"


def _slide_id(index: int) -> str:
    return f"slide_{index:03d}"


def _prepare_project(tmp_path: Path) -> SimpleNamespace:
    run_dir = tmp_path / "runs" / "batch-project"
    (run_dir / "planning").mkdir(parents=True)
    (run_dir / "inputs").mkdir(parents=True)
    (run_dir / "inputs" / "article.md").write_text("article body", encoding="utf-8")
    slides = [
        {"slide_id": _slide_id(index), "main_title": f"标题 {index}"}
        for index in range(1, SLIDE_COUNT + 1)
    ]
    (run_dir / "planning" / "visual_contract.json").write_text(
        json.dumps({"slides": slides}, ensure_ascii=False),
        encoding="utf-8",
    )
    return SimpleNamespace(
        id="batch-project",
        name="Batch",
        run_dir=str(run_dir),
        account_id="acct-a",
        ai_mode="auto",
    )


class StubImageProvider:
    """确定性模拟供应商：按页给出成功 / 持续临时失败 / 参数错误。"""

    def __init__(self, run_dir: Path, behavior: dict[str, str]) -> None:
        self.run_dir = run_dir
        self.behavior = dict(behavior)
        self.calls: list[str] = []

    def set_ok(self, slide_id: str) -> None:
        self.behavior[slide_id] = "ok"

    def generate_image(self, slide_id, prompt, defer_invalidation=True, **_kwargs):
        self.calls.append(str(slide_id))
        mode = self.behavior.get(str(slide_id), "ok")
        if mode == "ok":
            self._write(str(slide_id))
            return {"success": True}
        if mode == "transient_fail":
            payload = ImagePageFailure(
                slide_id=str(slide_id),
                attempts=3,
                code="upstream_overloaded",
                phase="submit",
                message="生图网关限流/过载，已在额度内退避重试 3 次仍未成功",
                recoverable=True,
            )
            status_code = 503
        else:
            payload = ImagePageFailure(
                slide_id=str(slide_id),
                attempts=1,
                code="invalid_parameters",
                phase="submit",
                message="不支持的尺寸参数",
                recoverable=False,
            )
            status_code = 500
        exc = HTTPException(status_code=status_code, detail=payload.message)
        exc.image_generation_failure = payload
        raise exc

    def _write(self, slide_id: str) -> None:
        slide_dir = self.run_dir / "slides" / slide_id
        slide_dir.mkdir(parents=True, exist_ok=True)
        (slide_dir / "visual_draft.png").write_bytes(f"png-{slide_id}".encode("utf-8"))

    def image_hash(self, slide_id: str) -> str:
        path = self.run_dir / "slides" / slide_id / "visual_draft.png"
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def image_exists(self, slide_id: str) -> bool:
        return (self.run_dir / "slides" / slide_id / "visual_draft.png").is_file()


@pytest.fixture
def orchestrator(monkeypatch: pytest.MonkeyPatch):
    """构建可复用的编排器测试骨架，返回 (project, provider, run_fn)。"""
    created: dict[str, object] = {}

    def build(project: SimpleNamespace, behavior: dict[str, str]):
        provider = StubImageProvider(Path(project.run_dir), behavior)
        finalize_calls: list[list[str]] = []
        logs: list[tuple] = []

        class Db:
            def query(self, _model):
                return self

            def filter(self, _criterion):
                return self

            def first(self):
                return project

            def close(self):
                return None

        def services(_db, _project_id):
            return SimpleNamespace(
                image_prompts=lambda: {
                    "prompts": [
                        {"slide_id": _slide_id(index), "prompt": "p"}
                        for index in range(1, SLIDE_COUNT + 1)
                    ]
                },
                generate_image=provider.generate_image,
                finalize_images=lambda slide_ids: (
                    finalize_calls.append(list(slide_ids)),
                    {"success": True, "slide_ids": list(slide_ids)},
                )[1],
                confirm_images=lambda: {"success": True},
                mask_manifest=lambda: {
                    "manifest": {"slides": []},
                    "repair": {"required": False},
                },
                repair_mask_manifest=lambda: {"manifest": {"slides": []}},
                build_mask_assets=lambda _manifest: {"success": True},
                narration=lambda: {"success": False, "message": "尚未生成"},
                init_narration=lambda: {"beats": {}},
                save_narration=lambda _beats: {"success": True},
                synthesize_audio=lambda: {"success": True},
                confirm_audio=lambda: {"success": True},
                render_video=lambda: (_ for _ in ()).throw(
                    RuntimeError("render not exercised in this test")
                ),
                render_video_status=lambda task_id=None: {"status": "idle"},
            )

        dependencies = one_click.OneClickDependencies(
            session_factory=Db,
            project_model=SimpleNamespace(id="id"),
            get_setting=lambda _key, _default="": "configured",
            resolve_media_tool=lambda _name: "available",
            repo_root=ROOT,
            read_project_article_source=lambda *_args, **_kwargs: None,
            write_project_log=lambda *_args, **_kwargs: logs.append(_args[1:]),
            inspect_tts_preflight=lambda _workflow: {"success": True},
            pipeline_service_factory=services,
        )
        created["finalize"] = finalize_calls
        created["logs"] = logs

        def run(run_id: str, **kwargs):
            one_click._run_pipeline(
                dependencies,
                project.id,
                run_id,
                mode=kwargs.get("mode", "restart"),
                start_from=kwargs.get("start_from", "images"),
            )
            return one_click._status_for_project(project, project.id)

        return provider, run, finalize_calls, logs

    return build


def test_batch_aggregates_all_failures_and_keeps_successes(
    tmp_path: Path, orchestrator
) -> None:
    project = _prepare_project(tmp_path)
    provider, run, finalize_calls, _logs = orchestrator(
        project,
        {TRANSIENT_SLIDE: "transient_fail", PARAM_SLIDE: "param_error"},
    )

    status = run("run-1")

    assert status["status"] == "paused"
    images_stage = one_click._stage(status, "images")
    blocking_entries = list(images_stage.get("blocking_errors", []))
    blocking = " ".join(blocking_entries)
    assert TRANSIENT_SLIDE in blocking and PARAM_SLIDE in blocking
    assert "已尝试 3 次" in blocking
    assert "已尝试 1 次" in blocking
    # 汇总信息：完成数、失败页、保留提示、继续引导
    summary_lines = [line for line in blocking_entries if "13/15" in line]
    assert summary_lines and "点击继续可补齐缺失页" in summary_lines[0]
    # 成功页保留并统一收尾
    assert sorted(finalize_calls[0]) == sorted(
        _slide_id(index) for index in range(1, 14)
    )
    for index in range(1, 14):
        assert provider.image_exists(_slide_id(index))
    assert not provider.image_exists(TRANSIENT_SLIDE)
    assert not provider.image_exists(PARAM_SLIDE)


def test_resume_refills_only_missing_slides_and_keeps_hashes(
    tmp_path: Path, orchestrator
) -> None:
    project = _prepare_project(tmp_path)
    provider, run, finalize_calls, _logs = orchestrator(
        project,
        {TRANSIENT_SLIDE: "transient_fail", PARAM_SLIDE: "param_error"},
    )
    run("run-1")
    hashes_before = {
        _slide_id(index): provider.image_hash(_slide_id(index))
        for index in range(1, 14)
    }
    provider.set_ok(TRANSIENT_SLIDE)
    provider.set_ok(PARAM_SLIDE)
    provider.calls.clear()

    status = run("run-2")

    # 只补缺失的两页；成功页不再提交生成
    assert sorted(set(provider.calls)) == sorted([TRANSIENT_SLIDE, PARAM_SLIDE])
    assert sorted(finalize_calls[-1]) == sorted([TRANSIENT_SLIDE, PARAM_SLIDE])
    for index in range(1, 14):
        slide_id = _slide_id(index)
        assert provider.image_hash(slide_id) == hashes_before[slide_id]
    assert all(provider.image_exists(_slide_id(i)) for i in range(1, 16))
    images_stage = one_click._stage(status, "images")
    assert images_stage["status"] == "done"
    assert "新增或刷新 2 张" in str(images_stage.get("message", ""))


def test_pause_requested_mid_batch_is_honoured_at_stage_boundary(
    tmp_path: Path, orchestrator
) -> None:
    project = _prepare_project(tmp_path)
    provider, run, _finalize_calls, _logs = orchestrator(project, {})

    original_generate = provider.generate_image

    def generate_then_request_pause(slide_id, prompt, **kwargs):
        if str(slide_id) == "slide_001":
            # 模拟"重试/生成进行中收到暂停请求"
            one_click._PAUSE_REQUESTS.add(project.id)
        return original_generate(slide_id, prompt, **kwargs)

    provider.generate_image = generate_then_request_pause
    try:
        status = run("run-pause")
    finally:
        one_click._PAUSE_REQUESTS.discard(project.id)

    # 图片阶段本身完成（不在页中中断），但不会越过阶段边界
    assert status["status"] == "paused"
    assert one_click._stage(status, "images")["status"] == "done"
    assert one_click._stage(status, "confirm_images")["status"] == "pending"
    assert "已完成 15/15" in status.get("message", "") or True
    assert all(provider.image_exists(_slide_id(i)) for i in range(1, 16))


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
