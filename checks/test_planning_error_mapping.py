"""PlanningError → HTTP 状态码映射（审查 M-08）。

纯层 storyboard_planning 不得依赖 FastAPI；手动编辑路径映射 400，
LLM 输出路径映射 502，纯层显式 400 的结构错误保持 400。
"""

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server  # noqa: F401,E402 与既有服务级测试保持一致的组合根导入
import storyboard_service as service  # noqa: E402
from storyboard_planning import PlanningError  # noqa: E402


class FakeProject:
    id = "planning-mapping-test"
    name = "Planning mapping test"

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = str(run_dir)
        self.current_step = 2

    def get_step_status(self, step=None):
        return {1: "completed", 2: "in_progress"}


class FakeQuery:
    def __init__(self, project) -> None:
        self.project = project

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.project


class FakeDb:
    def __init__(self, project) -> None:
        self.project = project

    def query(self, *_args, **_kwargs):
        return FakeQuery(self.project)

    def commit(self):
        pass


def test_helper_maps_explicit_and_fallback_statuses() -> None:
    assert service._planning_http_error(
        PlanningError("结构错误", status_code=400), 502
    ).status_code == 400
    assert service._planning_http_error(
        PlanningError("LLM 输出缺字段"), 502
    ).status_code == 502
    assert service._planning_http_error(
        PlanningError("手动内容缺字段"), 400
    ).status_code == 400


def test_manual_script_plan_update_returns_400_not_500(tmp_path) -> None:
    (tmp_path / "inputs").mkdir(parents=True)
    (tmp_path / "inputs" / "article.md").write_text(
        "# 映射测试\n\n这是一篇用于测试的文章正文。",
        encoding="utf-8",
    )
    project = FakeProject(tmp_path)

    with pytest.raises(HTTPException) as exc_info:
        service.update_step2_script_plan(
            FakeProject.id,
            {"slides": []},
            FakeDb(project),
        )

    assert exc_info.value.status_code == 400
    assert "slide_script_plan.slides" in exc_info.value.detail


def test_pure_layer_raises_planning_error_without_fastapi() -> None:
    source = (ROOT / "storyboard_planning.py").read_text(encoding="utf-8")
    assert "from fastapi" not in source
    assert "import fastapi" not in source
    assert "HTTPException" not in source
