#!/usr/bin/env python3
"""Self-check runtime hotfix installation without starting the full API server.

Run from the repository root:

    python scripts/check_runtime_hotfixes.py

The check imports ``sitecustomize.py`` explicitly, then exercises the runtime
patch installers against a small in-memory fake server module and a temporary
project directory. It is intentionally dependency-light so it can run before the
FastAPI app, Remotion, or external API providers are configured.
"""

from __future__ import annotations

import builtins
import contextlib
import importlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class CheckFailure(AssertionError):
    """Raised when one runtime hotfix check fails."""


class FakeHTTPException(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class FakeRoute:
    path = "/api/projects/{project_id}/steps/5/result"
    methods = {"PUT"}

    def __init__(self) -> None:
        self.endpoint = None
        self.dependant = SimpleNamespace(call=None)


class FakeApp:
    def __init__(self) -> None:
        self.routes = [FakeRoute()]
        self.registered_middlewares: list[Any] = []

    def middleware(self, middleware_type: str):
        def decorator(func: Any) -> Any:
            self.registered_middlewares.append((middleware_type, func))
            return func
        return decorator


class FakeProject:
    id = "project_001"
    name = "Runtime Hotfix Test"
    description = "fallback project description"

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = str(run_dir)


class FakeQuery:
    def __init__(self, project: FakeProject) -> None:
        self.project = project

    def filter(self, *_args: Any, **_kwargs: Any) -> "FakeQuery":
        return self

    def first(self) -> FakeProject:
        return self.project


class FakeDb:
    def __init__(self, project: FakeProject) -> None:
        self.project = project

    def query(self, _model: Any) -> FakeQuery:
        return FakeQuery(self.project)


class FakeProjectModel:
    id = object()


class Result:
    def __init__(self) -> None:
        self.passed: list[str] = []

    def pass_(self, name: str) -> None:
        self.passed.append(name)
        print(f"PASS {name}")


def load_sitecustomize() -> ModuleType:
    module = importlib.import_module("sitecustomize")
    if not isinstance(module, ModuleType):
        raise CheckFailure("sitecustomize did not import as a module")
    return module


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def make_fake_server_module(project: FakeProject, build_counter: dict[str, int]) -> ModuleType:
    module = ModuleType("fake_server_for_runtime_hotfix_check")
    module.app = FakeApp()
    module.Project = FakeProjectModel
    module.HTTPException = FakeHTTPException

    def read_contract_slide_ids(run_dir: str) -> list[str]:
        contract = read_json(Path(run_dir) / "planning" / "visual_contract.json")
        return [slide["slide_id"] for slide in contract.get("slides", [])]

    @contextlib.contextmanager
    def reveal_lock_for(_project: FakeProject):
        yield

    def write_json_atomic(path: str, value: dict[str, Any]) -> None:
        write_json(Path(path), value)

    def prune_stale_mask_groups(_project: FakeProject, payload: dict[str, Any]) -> dict[str, Any]:
        return payload

    def build_current_reveal_assets(_project: FakeProject) -> None:
        build_counter["count"] += 1

    def handle_step_navigation(_project: FakeProject, step: int, _db: FakeDb) -> None:
        build_counter["last_step"] = step

    module.read_contract_slide_ids = read_contract_slide_ids
    module.reveal_lock_for = reveal_lock_for
    module.write_json_atomic = write_json_atomic
    module.prune_stale_mask_groups = prune_stale_mask_groups
    module.build_current_reveal_assets = build_current_reveal_assets
    module.handle_step_navigation = handle_step_navigation
    module.sync_reveal_manifest_to_contract = lambda *_args, **_kwargs: False
    return module


def seed_project_files(run_dir: Path) -> None:
    write_json(
        run_dir / "planning" / "article_brief.json",
        {
            "title": "Article Title",
            "summary": "Article summary from brief.",
            "content": "# Article",
        },
    )
    write_json(
        run_dir / "planning" / "visual_contract.json",
        {
            "topic": {"topic_name": "Topic Without Summary"},
            "slides": [
                {
                    "slide_id": "slide_001",
                    "visual_groups": [
                        {
                            "id": "g1",
                            "role": "main",
                            "content_unit_id": "cu1",
                            "visible_text": "Group 1",
                            "box": {"x": 1, "y": 2, "w": 3, "h": 4},
                        },
                        {
                            "id": "g2",
                            "role": "support",
                            "content_unit_id": "cu2",
                            "visible_text": "Group 2",
                        },
                    ],
                    "narration_beats": [
                        {"id": "beat_1", "group_id": "g1"},
                        {"id": "beat_2", "content_unit_id": "cu2"},
                    ],
                }
            ],
        },
    )
    write_json(
        run_dir / "reveal_manifest.json",
        {
            "version": "reveal_v1",
            "slides": [
                {
                    "slide_id": "slide_001",
                    "semantic_blocks": [
                        {
                            "id": "g1",
                            "visible_text": "Old Group 1",
                            "strokes": [{"x": 10, "y": 20}],
                        },
                        {
                            "id": "manual_group_keep",
                            "visible_text": "Manual Group",
                            "strokes": [{"x": 30, "y": 40}],
                        },
                    ],
                    "groups": [
                        {
                            "id": "g1",
                            "visible_text": "Old Group 1",
                            "strokes": [{"x": 10, "y": 20}],
                        }
                    ],
                }
            ],
        },
    )


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailure(message)


def check_import_and_subprocess_guard(sitecustomize: ModuleType, result: Result) -> None:
    assert_true(hasattr(builtins, "props_started"), "builtins.props_started is missing")
    result.pass_("builtins.props_started is defined")

    marker = getattr(sitecustomize, "_PATCH_MARKER", "__ppt_pipeline_runtime_hotfix__")
    assert_true(getattr(subprocess.run, marker, False) is True, "subprocess.run guard is not installed")
    result.pass_("subprocess.run guard is installed")

    assert_true(hasattr(sitecustomize, "_install_reveal_manifest_reconcile_patch"), "manifest reconcile installer is missing")
    assert_true(hasattr(sitecustomize, "_install_step5_build_assets_patch"), "Step 5 build_assets installer is missing")
    result.pass_("runtime patch installers are present")


def check_runtime_security_module(result: Result) -> None:
    module = importlib.import_module("runtime_security")
    assert_true(hasattr(module, "install_when_server_is_ready"), "runtime security installer is missing")
    assert_true(hasattr(module, "_install_on_server_module"), "runtime security server installer is missing")
    assert_true(module.ACCESS_TOKEN_ENV == "PPT_STUDIO_ACCESS_TOKEN", "unexpected access-token env var name")

    fake_module = ModuleType("fake_security_server")
    fake_module.app = FakeApp()
    previous_token = os.environ.pop("PPT_STUDIO_ACCESS_TOKEN", None)
    try:
        assert_true(module._install_on_server_module(fake_module) is True, "runtime security no-token install failed")
        assert_true(getattr(fake_module, module._PATCH_MARKER, False) is True, "runtime security marker was not set")
        assert_true(fake_module.app.registered_middlewares == [], "runtime security should not add middleware without a token")
    finally:
        if previous_token is not None:
            os.environ["PPT_STUDIO_ACCESS_TOKEN"] = previous_token
    result.pass_("optional runtime security module is importable and opt-in")


def check_manifest_reconcile_and_topic(sitecustomize: ModuleType, result: Result) -> None:
    build_counter = {"count": 0}
    with tempfile.TemporaryDirectory(prefix="ppt-hotfix-check-") as temp_name:
        run_dir = Path(temp_name)
        seed_project_files(run_dir)
        project = FakeProject(run_dir)
        module = make_fake_server_module(project, build_counter)

        installed = sitecustomize._install_reveal_manifest_reconcile_patch(module)
        assert_true(installed is True, "manifest reconcile patch did not install")
        assert_true(module.sync_reveal_manifest_to_contract(project) is True, "manifest reconcile did not report a change")

        contract = read_json(run_dir / "planning" / "visual_contract.json")
        assert_true(
            contract["topic"]["topic_summary"] == "Article summary from brief.",
            "topic_summary was not restored from article_brief.json",
        )
        result.pass_("Step 2 topic_summary is restored")

        manifest = read_json(run_dir / "reveal_manifest.json")
        slide = manifest["slides"][0]
        semantic_ids = {group["id"] for group in slide["semantic_blocks"]}
        group_ids = {group["id"] for group in slide["groups"]}
        assert_true({"g1", "g2", "manual_group_keep"}.issubset(semantic_ids), "semantic_blocks were not reconciled")
        assert_true({"g1", "g2", "manual_group_keep"}.issubset(group_ids), "groups were not reconciled")

        g1 = next(group for group in slide["groups"] if group["id"] == "g1")
        g2 = next(group for group in slide["groups"] if group["id"] == "g2")
        assert_true(g1.get("strokes") == [{"x": 10, "y": 20}], "painted mask data was not preserved")
        assert_true(g1.get("narration_beat_id") == "beat_1", "g1 narration beat was not linked")
        assert_true(g2.get("narration_beat_id") == "beat_2", "g2 narration beat was not linked")
        result.pass_("manifest slide/group reconcile preserves masks and links beats")


def check_step5_build_assets_flag(sitecustomize: ModuleType, result: Result) -> None:
    build_counter = {"count": 0}
    with tempfile.TemporaryDirectory(prefix="ppt-hotfix-check-") as temp_name:
        run_dir = Path(temp_name)
        seed_project_files(run_dir)
        project = FakeProject(run_dir)
        module = make_fake_server_module(project, build_counter)
        sitecustomize._install_step5_build_assets_patch(module)

        db = FakeDb(project)
        payload = read_json(run_dir / "reveal_manifest.json")
        no_build = module.update_step5_result("project_001", payload, build_assets=False, db=db)
        assert_true(no_build == {"success": True, "built_assets": False}, "build_assets=false did not return built_assets=false")
        assert_true(build_counter["count"] == 0, "build_assets=false still invoked build_current_reveal_assets")

        do_build = module.update_step5_result("project_001", payload, build_assets=True, db=db)
        assert_true(do_build == {"success": True, "built_assets": True}, "build_assets=true did not return built_assets=true")
        assert_true(build_counter["count"] == 1, "build_assets=true did not invoke build_current_reveal_assets once")
        result.pass_("Step 5 build_assets flag is respected")


def check_runtime_bootstrap_contract(result: Result) -> None:
    module = importlib.import_module("scripts.check_runtime_bootstrap_contract")
    module.main()
    result.pass_("runtime bootstrap contract is enforced")


def main() -> int:
    if os.environ.get("PPT_STUDIO_DISABLE_RUNTIME_HOTFIXES"):
        print("FAIL PPT_STUDIO_DISABLE_RUNTIME_HOTFIXES is set; runtime hotfixes are disabled.")
        return 1

    result = Result()
    try:
        sitecustomize = load_sitecustomize()
        check_import_and_subprocess_guard(sitecustomize, result)
        check_runtime_security_module(result)
        check_manifest_reconcile_and_topic(sitecustomize, result)
        check_step5_build_assets_flag(sitecustomize, result)
        check_runtime_bootstrap_contract(result)
    except CheckFailure as exc:
        print(f"FAIL {exc}")
        return 1
    except Exception as exc:  # defensive: this is a diagnostics script
        print(f"FAIL unexpected error: {type(exc).__name__}: {exc}")
        return 1

    print(f"OK runtime hotfix self-check passed ({len(result.passed)} checks).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
