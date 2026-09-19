from __future__ import annotations

import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import global_image_style_service as global_style  # noqa: E402
import image_workflow_service as image_workflow  # noqa: E402
import repository_paths as paths  # noqa: E402
import server  # noqa: E402
import storyboard_service as storyboard  # noqa: E402


def test_repository_paths_are_canonical_and_application_free() -> None:
    source = (ROOT / "repository_paths.py").read_text(
        encoding="utf-8"
    )
    for forbidden in (
        "fastapi",
        "APIRouter",
        "Depends(",
        "get_db",
        "import server",
    ):
        assert forbidden not in source

    assert Path(paths.REPO_ROOT) == ROOT
    # RUNS_DIR 允许用 PPT_STUDIO_RUNS_DIR 显式覆盖（测试隔离、多环境并行）。
    # 测试会话本身会设置它，所以这里分两部分守护：
    # 1) 注册表源码里仍然只声明一次规范默认值（仓库根下的 runs/）；
    # 2) 运行时值必须严格等于被覆盖的值，未覆盖时等于规范默认值。
    assert 'os.path.join(REPO_ROOT, "runs")' in source
    configured_runs = os.environ.get("PPT_STUDIO_RUNS_DIR")
    if configured_runs:
        assert Path(paths.RUNS_DIR) == Path(os.path.abspath(configured_runs))
    else:
        assert Path(paths.RUNS_DIR) == ROOT / "runs"
    assert Path(paths.DATA_DIR) == ROOT / "data"
    assert Path(paths.STYLE_TOKENS_PATH) == (
        ROOT / "data" / "style_tokens.yaml"
    )
    assert Path(paths.STEP2_PROMPT_TEMPLATES_PATH) == (
        ROOT / "data" / "step2_prompt_templates.json"
    )
    assert Path(paths.STEP3_IMAGE_PROMPT_TEMPLATE_PATH) == (
        ROOT / "templates" / "prompts" / "step3_image_system.md"
    )


def test_consumers_reexport_shared_path_values() -> None:
    assert server.REPO_ROOT == paths.REPO_ROOT
    assert server.RUNS_DIR == paths.RUNS_DIR
    assert server.DATA_DIR == paths.DATA_DIR
    assert global_style.REPO_ROOT == paths.REPO_ROOT
    assert storyboard.REPO_ROOT == paths.REPO_ROOT
    assert image_workflow.REPO_ROOT == paths.REPO_ROOT

    assert (
        server.STYLE_REFERENCE_FILES
        is global_style.STYLE_REFERENCE_FILES
        is paths.STYLE_REFERENCE_FILES
    )
    assert (
        server.STEP2_PROMPT_TEMPLATE_FILES
        is storyboard.STEP2_PROMPT_TEMPLATE_FILES
        is paths.STEP2_PROMPT_TEMPLATE_FILES
    )
    assert (
        image_workflow.STEP3_IMAGE_PROMPT_TEMPLATE_PATH
        == paths.STEP3_IMAGE_PROMPT_TEMPLATE_PATH
    )


def test_consumers_do_not_redeclare_repository_paths() -> None:
    for filename in (
        "server.py",
        "global_image_style_service.py",
        "storyboard_service.py",
        "image_workflow_service.py",
    ):
        source = (ROOT / filename).read_text(encoding="utf-8")
        assert "REPO_ROOT = os.path.abspath" not in source
        assert 'DATA_DIR = os.path.join(REPO_ROOT, "data")' not in source


def test_server_reuses_image_style_storage_initialization() -> None:
    assert (
        server.ensure_active_image_style_storage
        is global_style.ensure_active_image_style_storage
    )
    server_source = (ROOT / "server.py").read_text(encoding="utf-8")
    assert "def ensure_active_image_style_storage(" not in server_source
