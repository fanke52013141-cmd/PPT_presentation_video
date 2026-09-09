import json
import hashlib
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ai_mask_manifest_apply as ai_mask
import one_click_orchestrator as one_click
import one_click_routes
from fastapi import HTTPException
from route_inventory import iter_effective_routes
import server


def project_for(root: Path) -> SimpleNamespace:
    return SimpleNamespace(id="project-test", run_dir=str(root))


def test_quality_gates_use_normalized_project_profile_values() -> None:
    with tempfile.TemporaryDirectory() as value:
        root = Path(value)
        project = project_for(root)
        planning = root / "planning"
        planning.mkdir(parents=True)
        (planning / "project_profile.json").write_text(
            '{"quality_gates":{"pause_on_render_failure":"false"}}',
            encoding="utf-8",
        )

        gates = one_click._quality_gates(project)

        assert gates["pause_on_render_failure"] is False
        assert gates["pause_on_tts_failure"] is True


def test_image_parallelism_defaults_to_five_and_is_bounded() -> None:
    project = SimpleNamespace()
    assert one_click._bounded_parallelism(
        project,
        config_path="automation.image_concurrency",
        environment_name="PPT_STUDIO_TEST_IMAGE_CONCURRENCY",
        default=5,
        maximum=6,
    ) == 5
    assert one_click._reduced_image_parallelism(5) == 4
    assert one_click._reduced_image_parallelism(1) == 1


def test_narration_annotation_is_opt_in_for_automatic_runs(monkeypatch) -> None:
    project = SimpleNamespace()

    monkeypatch.setattr(one_click, "get_config_value", lambda *_args: False)
    assert one_click._should_annotate_narration(project) is False

    monkeypatch.setattr(one_click, "get_config_value", lambda *_args: True)
    assert one_click._should_annotate_narration(project) is True


def test_image_rate_limit_detection_and_backoff_hint() -> None:
    error = RuntimeError("HTTP 429: Retry-After: 7")
    assert one_click._is_rate_limit_error(error)
    assert one_click._image_rate_limit_delay_seconds(error, 1) == 7.0
    assert one_click._image_rate_limit_delay_seconds(RuntimeError("429"), 3) == 8.0


def test_manual_project_rejects_one_click_before_background_work_starts(monkeypatch) -> None:
    project = SimpleNamespace(id="manual-project", ai_mode="manual", run_dir="unused")
    dependencies_requested = False

    def unexpected_dependencies():
        nonlocal dependencies_requested
        dependencies_requested = True
        raise AssertionError("manual project must not initialize the one-click worker")

    monkeypatch.setattr(one_click, "get_one_click_dependencies", unexpected_dependencies)

    try:
        one_click.start_one_click(project)
    except one_click.ManualModeOneClickError as exc:
        assert "手动模式项目" in str(exc)
    else:
        raise AssertionError("manual project should reject one-click automation")

    assert dependencies_requested is False
    assert "manual-project" not in one_click._RUNNING


def test_auto_project_still_starts_one_click_worker(monkeypatch, tmp_path: Path) -> None:
    project = SimpleNamespace(id="auto-project", ai_mode="auto", run_dir=str(tmp_path), account_id="acct-a")
    status = one_click._initial_status(project.id, "run-test")
    started_threads = []

    class FakeThread:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.started = False

        def is_alive(self):
            return False

        def start(self):
            self.started = True
            started_threads.append(self)

    monkeypatch.setattr(one_click, "get_one_click_dependencies", lambda: object())
    monkeypatch.setattr(one_click, "_status_for_project", lambda *_args: {"status": "idle"})
    monkeypatch.setattr(one_click, "_resume_status", lambda *_args: (dict(status), 0))
    monkeypatch.setattr(one_click, "_save_status", lambda *_args: None)
    monkeypatch.setattr(one_click.threading, "Thread", FakeThread)

    try:
        result = one_click.start_one_click(project)
        assert result["started"] is True
        assert started_threads and started_threads[0].started is True
    finally:
        one_click._RUNNING.pop(project.id, None)


def test_pause_at_preflight_boundary_stops_downstream_stages(monkeypatch, tmp_path: Path) -> None:
    """A requested pause is durable before the next stage can begin."""
    project = SimpleNamespace(id="pause-boundary", run_dir=str(tmp_path), account_id="acct-a")
    article = tmp_path / "inputs" / "article.md"
    article.parent.mkdir(parents=True)
    article.write_text("article", encoding="utf-8")
    calls: list[str] = []

    class Db:
        def query(self, _model):
            return self

        def filter(self, _criterion):
            return self

        def first(self):
            return project

        def close(self):
            return None

    dependencies = one_click.OneClickDependencies(
        session_factory=Db,
        project_model=SimpleNamespace(id="id"),
        get_setting=lambda _key, _default="": "configured",
        resolve_media_tool=lambda _name: "available",
        repo_root=ROOT,
        read_project_article_source=lambda *_args, **_kwargs: None,
        write_project_log=lambda *_args, **_kwargs: None,
        inspect_tts_preflight=lambda _workflow: {"success": True},
        pipeline_service_factory=lambda *_args: SimpleNamespace(
            storyboard_script=lambda: calls.append("storyboard") or {},
        ),
    )
    original_finish = one_click._finish_stage

    def request_pause_after_preflight(*args, **kwargs):
        original_finish(*args, **kwargs)
        if args[2] == "preflight":
            one_click._PAUSE_REQUESTS.add(project.id)

    monkeypatch.setattr(one_click, "_finish_stage", request_pause_after_preflight)
    try:
        one_click._run_pipeline(dependencies, project.id, "run-pause", mode="restart")
        status = one_click._status_for_project(project, project.id)
        assert status["status"] == "paused"
        assert status["current_stage"] == "preflight"
        assert one_click._stage(status, "preflight")["status"] == "done"
        assert one_click._stage(status, "storyboard")["status"] == "pending"
        assert calls == []
        assert "未能产出可下载的视频" not in status.get("message", "")
    finally:
        one_click._PAUSE_REQUESTS.discard(project.id)


def test_manual_project_route_returns_conflict(monkeypatch) -> None:
    project = SimpleNamespace(id="manual-project", ai_mode="manual", run_dir="unused")
    monkeypatch.setattr(one_click_routes, "_project_or_404", lambda *_args: project)

    try:
        one_click_routes.start_one_click_route(project.id, {}, db=object())
    except HTTPException as exc:
        assert exc.status_code == 409
        assert "手动模式项目" in str(exc.detail)
    else:
        raise AssertionError("manual project route should return HTTP 409")


def test_batch_statuses_are_limited_to_current_account(tmp_path: Path) -> None:
    class AccountColumn:
        def __eq__(self, value):
            return ("account_id", value)

    class ProjectModel:
        account_id = AccountColumn()

    account_a = SimpleNamespace(id="project-a", name="A", account_id="acct-a", run_dir=str(tmp_path / "a"))
    account_b = SimpleNamespace(id="project-b", name="B", account_id="acct-b", run_dir=str(tmp_path / "b"))

    class Query:
        def __init__(self, projects):
            self.projects = projects
            self.account_id = None

        def filter(self, criterion):
            assert criterion[0] == "account_id"
            self.account_id = criterion[1]
            return self

        def all(self):
            return [project for project in self.projects if project.account_id == self.account_id]

    class Db:
        def __init__(self):
            self.query_instance = Query([account_a, account_b])

        def query(self, _model):
            return self.query_instance

        def close(self):
            return None

    db = Db()
    result = one_click.batch_one_click_status(ProjectModel, lambda: db, "acct-a")

    assert [item["project_id"] for item in result["items"]] == ["project-a"]
    assert db.query_instance.account_id == "acct-a"


def test_atomic_status_write_and_resume_rewinds_when_upstream_is_missing() -> None:
    with tempfile.TemporaryDirectory() as value:
        root = Path(value)
        project = project_for(root)
        status = one_click._initial_status(project.id, "run-old")
        one_click._finish_stage(project, status, "preflight", "ok")
        one_click._finish_stage(project, status, "storyboard", "ok")
        one_click._fail_stage(project, status, "images", "provider failed")

        resumed, start_index = one_click._resume_status(project, project.id, "run-new", "resume")
        assert start_index == one_click._stage_index("preflight")
        assert resumed["run_id"] == "run-new"
        assert resumed["status"] == "running"
        assert one_click._stage(resumed, "preflight")["status"] == "pending"
        assert one_click._stage(resumed, "storyboard")["status"] == "pending"
        assert one_click._stage(resumed, "images")["status"] == "pending"
        assert resumed["effective_start_stage"] == "preflight"
        assert resumed["revalidation"][0]["reasons"] == ["article_missing"]
        assert not list((root / "planning").glob("*.tmp"))
        json.loads((root / "planning" / one_click.STATUS_FILENAME).read_text(encoding="utf-8"))

        one_click._save_status(project, resumed)
        thread_resumed, thread_start_index = one_click._resume_status(project, project.id, "run-new", "resume")
        assert thread_start_index == one_click._stage_index("preflight")
        assert thread_resumed["run_id"] == "run-new"


def test_resume_keeps_failed_stage_when_upstream_artifacts_are_valid() -> None:
    with tempfile.TemporaryDirectory() as value:
        root = Path(value)
        project = project_for(root)
        (root / "inputs").mkdir(parents=True)
        (root / "planning").mkdir(parents=True)
        article = root / "inputs" / "article.md"
        contract = root / "planning" / "visual_contract.json"
        article.write_text("article", encoding="utf-8")
        contract.write_text('{"slides":[{"slide_id":"slide_001"}]}', encoding="utf-8")
        os.utime(article, (10, 10))
        os.utime(contract, (20, 20))
        (root / "planning" / "visual_contract.validation.json").write_text(
            json.dumps({
                "valid": True,
                "contract_sha256": hashlib.sha256(contract.read_bytes()).hexdigest(),
            }),
            encoding="utf-8",
        )
        status = one_click._initial_status(project.id, "run-old")
        one_click._finish_stage(project, status, "preflight", "ok")
        one_click._finish_stage(project, status, "storyboard", "ok")
        one_click._fail_stage(project, status, "images", "provider failed")

        resumed, start_index = one_click._resume_status(project, project.id, "run-new", "resume")

        assert start_index == one_click._stage_index("images")
        assert resumed["effective_start_stage"] == "images"
        assert all(item["valid"] for item in resumed["revalidation"][:-1])
        assert resumed["revalidation"][-1]["reasons"] == ["previous_stage_failed"]


def test_resume_rewinds_render_to_tts_when_audio_is_not_confirmed() -> None:
    with tempfile.TemporaryDirectory() as value:
        root = Path(value)
        project = project_for(root)
        planning = root / "planning"
        slide_dir = root / "slides" / "slide_001"
        inputs = root / "inputs"
        planning.mkdir(parents=True)
        slide_dir.mkdir(parents=True)
        inputs.mkdir(parents=True)
        article = inputs / "article.md"
        contract = planning / "visual_contract.json"
        image = slide_dir / "visual_draft.png"
        manifest = root / "reveal_manifest.json"
        narration = planning / "narration_beats.json"
        article.write_text("article", encoding="utf-8")
        contract.write_text('{"slides":[{"slide_id":"slide_001"}]}', encoding="utf-8")
        (planning / "visual_contract.validation.json").write_text(
            json.dumps({
                "valid": True,
                "contract_sha256": hashlib.sha256(contract.read_bytes()).hexdigest(),
            }),
            encoding="utf-8",
        )
        image.write_bytes(b"image")
        manifest.write_text(
            json.dumps({
                "slides": [{"slide_id": "slide_001"}],
                "ai_mask_annotation": {"status": "completed"},
            }),
            encoding="utf-8",
        )
        for filename in ("scene.json", "animation_timeline.json", "reveal_report.json"):
            (slide_dir / filename).write_text("{}", encoding="utf-8")
        narration.write_text(
            '{"slides":[{"slide_id":"slide_001","beats":[]}]}',
            encoding="utf-8",
        )
        for path, stamp in (
            (article, 10),
            (contract, 20),
            (image, 30),
            (manifest, 40),
            (slide_dir / "scene.json", 50),
            (slide_dir / "animation_timeline.json", 50),
            (slide_dir / "reveal_report.json", 50),
            (narration, 60),
        ):
            os.utime(path, (stamp, stamp))
        status = one_click._initial_status(project.id, "run-old")
        one_click._fail_stage(project, status, "render", "render failed")

        resumed, start_index = one_click._resume_status(project, project.id, "run-new", "resume")

        assert start_index == one_click._stage_index("tts")
        assert resumed["effective_start_stage"] == "tts"
        tts_check = next(item for item in resumed["revalidation"] if item["stage"] == "tts")
        assert tts_check["reasons"] == ["audio_not_confirmed:missing_confirmation"]


def test_restart_does_not_reuse_failed_stage_state() -> None:
    with tempfile.TemporaryDirectory() as value:
        project = project_for(Path(value))
        status = one_click._initial_status(project.id, "run-old")
        one_click._fail_stage(project, status, "ai_mask", "low quality")
        restarted, start_index = one_click._resume_status(project, project.id, "run-new", "restart")
        assert start_index == 0
        assert restarted["run_id"] == "run-new"
        assert all(stage["status"] == "pending" for stage in restarted["stages"])


def test_completed_run_smart_resume_revalidates_from_render() -> None:
    with tempfile.TemporaryDirectory() as value:
        project = project_for(Path(value))
        status = one_click._initial_status(project.id, "run-old")
        one_click._complete(
            project,
            status,
            SimpleNamespace(commit=lambda: None, rollback=lambda: None),
            video={"url": "/video.mp4"},
        )

        resumed, start_index = one_click._resume_status(project, project.id, "run-new", "resume")

        assert start_index == one_click._stage_index("preflight")
        assert resumed["previous_failed_stage"] == "render"
        assert resumed["effective_start_stage"] == "preflight"


def test_legacy_status_is_migrated_in_memory_to_v2() -> None:
    with tempfile.TemporaryDirectory() as value:
        root = Path(value)
        project = project_for(root)
        status = one_click._initial_status(project.id, "run-old")
        status["version"] = "one_click_orchestrator_v1"
        status.pop("requested_mode", None)
        status.pop("effective_start_stage", None)
        status.pop("revalidation", None)
        one_click._write_json(root / "planning" / one_click.STATUS_FILENAME, status)

        migrated = one_click._status_for_project(project, project.id)

        assert migrated["version"] == one_click.STATUS_VERSION
        assert migrated["effective_start_stage"] == "preflight"
        assert migrated["revalidation"] == []


def test_one_click_run_duration_uses_the_current_invocation() -> None:
    status = {
        "started_at": "2026-09-06T08:00:00",
        "run_started_at": "2026-09-06T09:00:00",
        "run_finished_at": "2026-09-06T09:02:05",
        "status": "completed",
    }

    assert one_click._run_elapsed_seconds(status) == 125


def test_running_one_click_duration_uses_current_time() -> None:
    status = {
        "run_started_at": "2026-09-06T09:00:00",
        "run_finished_at": "",
        "status": "running",
    }

    assert one_click._run_elapsed_seconds(status, "2026-09-06T09:01:01") == 61


def test_legacy_terminal_status_backfills_total_duration() -> None:
    with tempfile.TemporaryDirectory() as value:
        root = Path(value)
        project = project_for(root)
        status = one_click._initial_status(project.id, "run-old")
        status.update(
            {
                "status": "completed",
                "started_at": "2026-09-06T09:00:00",
                "completed_at": "2026-09-06T09:03:20",
            }
        )
        for key in ("run_started_at", "run_finished_at", "run_elapsed_seconds"):
            status.pop(key, None)
        one_click._write_json(root / "planning" / one_click.STATUS_FILENAME, status)

        migrated = one_click._status_for_project(project, project.id)

        assert migrated["run_finished_at"] == "2026-09-06T09:03:20"
        assert migrated["run_elapsed_seconds"] == 200


def test_missing_narration_is_the_only_safe_initialization_fallback() -> None:
    calls = []
    services = SimpleNamespace(
        narration=lambda: {"success": False, "message": "演讲稿尚未生成"},
    )

    assert one_click._load_existing_narration(services, lambda: calls.append("backup")) is None
    assert calls == []


def test_narration_read_failure_pauses_instead_of_becoming_empty() -> None:
    def fail_read():
        raise OSError("disk unavailable")

    services = SimpleNamespace(narration=fail_read)

    try:
        one_click._load_existing_narration(services, lambda: None)
    except RuntimeError as exc:
        assert "读取现有演讲稿失败" in str(exc)
    else:
        raise AssertionError("narration read failures must block initialization")


def test_narration_is_backed_up_before_repair() -> None:
    calls = []
    services = SimpleNamespace(
        narration=lambda: {
            "success": True,
            "beats": {"slides": []},
            "repair": {"required": True},
        },
        repair_narration=lambda: calls.append("repair") or {
            "success": True,
            "beats": {"slides": []},
        },
    )

    payload = one_click._load_existing_narration(services, lambda: calls.append("backup"))

    assert payload["success"] is True
    assert calls == ["backup", "repair"]


def test_one_click_narration_backup_preserves_original_bytes() -> None:
    with tempfile.TemporaryDirectory() as value:
        root = Path(value)
        project = project_for(root)
        source = root / "planning" / "narration_beats.json"
        source.parent.mkdir(parents=True)
        original = b'{"slides":[{"slide_id":"slide_001"}]}'
        source.write_bytes(original)

        backup = one_click._backup_narration(project, "run-safe")

        assert backup is not None
        assert backup.read_bytes() == original
        assert source.read_bytes() == original


def test_contract_and_narration_are_only_reused_when_fresh_and_validated() -> None:
    with tempfile.TemporaryDirectory() as value:
        root = Path(value)
        project = project_for(root)
        (root / "planning").mkdir(parents=True)
        (root / "inputs").mkdir(parents=True)
        article = root / "inputs" / "article.md"
        contract = root / "planning" / "visual_contract.json"
        narration = root / "planning" / "narration_beats.json"
        article.write_text("article", encoding="utf-8")
        contract.write_text('{"slides":[{"slide_id":"slide_001"}]}', encoding="utf-8")
        narration.write_text('{"slides":[{"slide_id":"slide_001","beats":[]}]}', encoding="utf-8")
        for path, stamp in ((article, 10), (contract, 20), (narration, 30)):
            os.utime(path, (stamp, stamp))
        validation = {
            "valid": True,
            "contract_sha256": hashlib.sha256(contract.read_bytes()).hexdigest(),
        }
        (root / "planning" / "visual_contract.validation.json").write_text(
            json.dumps(validation),
            encoding="utf-8",
        )
        assert one_click._has_contract(project)
        assert one_click._has_fresh_narration(project)

        os.utime(article, (40, 40))
        assert not one_click._has_contract(project)
        contract.write_text('{"slides":[{"slide_id":"changed"}]}', encoding="utf-8")
        os.utime(contract, (50, 50))
        assert not one_click._has_contract(project), "changed contracts require a matching validation hash"
        assert not one_click._has_fresh_narration(project)


def test_disabled_quality_gate_marks_terminal_failure() -> None:
    with tempfile.TemporaryDirectory() as value:
        project = project_for(Path(value))
        status = one_click._initial_status(project.id, "run-old")
        one_click._fail_stage(project, status, "render", "render failed", pause=False)
        assert status["status"] == "failed"
        restarted, start_index = one_click._resume_status(project, project.id, "run-new", "resume")
        assert start_index == 0
        assert restarted["run_id"] == "run-new"


def test_only_uncorrected_ai_masks_are_replaceable() -> None:
    base = {
        "source": "ai_auto_mask",
        "review_status": "ai_matched",
        "manual_mask": {
            "source": "ai_auto_mask_v3_exact_rle",
            "rle": {"runs": [[1, 1, 5]]},
            "strokes": [],
        },
    }
    assert ai_mask._replaceable_ai_mask(base)

    corrected = {**base, "manual_mask": {**base["manual_mask"], "strokes": [{"mode": "erase", "points": [{"x": 2, "y": 2}]}]}}
    assert not ai_mask._replaceable_ai_mask(corrected)

    locked = {**base, "review_status": "locked"}
    assert not ai_mask._replaceable_ai_mask(locked)

    manual = {**base, "manual_mask": {**base["manual_mask"], "source": "manual_paint"}}
    assert not ai_mask._replaceable_ai_mask(manual)


def test_ai_mask_retry_selects_only_failed_slides() -> None:
    result = {
        "slides": [
            {"slide_id": "slide_001", "quality": {"passed": True}},
            {"slide_id": "slide_002", "quality": {"passed": False}},
            {"slide_id": "slide_003", "quality": {"passed": True}, "review_required": True},
        ],
        "review_issues": [{"slide_id": "slide_003", "reason": "check"}],
    }

    selected = one_click._ai_mask_failed_slide_ids(
        result,
        ["slide_001", "slide_002", "slide_003"],
    )

    assert selected == ["slide_002", "slide_003"]


def test_ai_mask_retry_falls_back_to_all_slides_without_slide_details() -> None:
    assert one_click._ai_mask_failed_slide_ids(
        {"complete": False, "slides": []},
        ["slide_001", "slide_002"],
    ) == ["slide_001", "slide_002"]


def test_one_click_uses_full_frame_and_safe_audio_modes() -> None:
    source = Path("one_click_orchestrator.py").read_text(encoding="utf-8")
    services_source = Path("pipeline_services.py").read_text(encoding="utf-8")
    assert "Build full-frame scenes" in source
    assert 'services.annotate_ai_mask' not in source
    assert '"confirmation_mode": "automatic_technical"' in services_source
    assert "pipeline_service_factory" in source
    assert "services.narration" in source
    assert "services.save_narration" in source
    assert "TestClient" not in source
    assert "client.get(" not in source
    assert "client.post(" not in source
    assert "client.put(" not in source
    assert 'mode == "restart" or not _has_contract(project)' in source
    assert "from project_profile_store import DEFAULT_QUALITY_GATES, load_profile" in source
    assert "dict(load_profile(project)[\"quality_gates\"])" in source
    for gate_name in one_click.DEFAULT_QUALITY_GATES:
        if gate_name == "pause_on_ai_mask_low_confidence":
            continue
        assert gate_name in source


def test_one_click_builds_static_scenes_without_ai_mask() -> None:
    """One-click keeps Step 7 scene assets but never annotates elements."""
    source = Path("one_click_orchestrator.py").read_text(encoding="utf-8")
    assert 'if should_run("confirm_images"):' in source
    assert 'services.build_mask_assets(manifest)' in source
    assert 'services.annotate_ai_mask' not in source


def test_preflight_migrates_legacy_article_before_checking_source() -> None:
    with tempfile.TemporaryDirectory() as value:
        root = Path(value)
        project = project_for(root)
        calls = []

        def migrate_article(_project, *, required=True):
            calls.append(required)
            article_path = root / "inputs" / "article.md"
            article_path.parent.mkdir(parents=True, exist_ok=True)
            article_path.write_text("legacy article", encoding="utf-8")
            return {"content": "legacy article"}

        module = SimpleNamespace(
            read_project_article_source=migrate_article,
            get_setting=lambda _key: "configured",
            resolve_media_tool=lambda _name: "available",
            repo_root=ROOT,
        )

        errors = one_click._preflight_errors(module, project)

        assert calls == [False]
        assert not any("导入文章" in error for error in errors)


def test_preflight_does_not_require_cloud_tts_key_for_local_comfyui() -> None:
    with tempfile.TemporaryDirectory() as value:
        root = Path(value)
        project = project_for(root)
        article_path = root / "inputs" / "article.md"
        article_path.parent.mkdir(parents=True, exist_ok=True)
        article_path.write_text("local tts article", encoding="utf-8")
        workflow_path = root / "data" / "digital_human" / "comfyui_tts_workflow.json"
        workflow_path.parent.mkdir(parents=True, exist_ok=True)
        workflow_path.write_text("{}", encoding="utf-8")

        def get_setting(key, default=""):
            return {
                "tts_provider": "IndexTTS-2.5",
                "tts_endpoint": str(workflow_path),
                "tts_api_key": "",
                "llm_api_key": "configured",
                "image_api_key": "configured",
            }.get(key, default)

        module = SimpleNamespace(
            read_project_article_source=lambda *_args, **_kwargs: None,
            get_setting=get_setting,
            resolve_media_tool=lambda _name: "available",
            repo_root=root,
            inspect_tts_preflight=lambda _workflow: {"success": True, "errors": []},
        )

        errors = one_click._preflight_errors(module, project)

        assert not any("TTS API Key" in error for error in errors)
        assert not any("工作流不存在" in error for error in errors)


def test_preflight_blocks_offline_comfyui_before_storyboard_generation() -> None:
    with tempfile.TemporaryDirectory() as value:
        root = Path(value)
        project = project_for(root)
        article_path = root / "inputs" / "article.md"
        article_path.parent.mkdir(parents=True, exist_ok=True)
        article_path.write_text("local tts article", encoding="utf-8")
        workflow_path = root / "data" / "digital_human" / "comfyui_tts_workflow.json"
        workflow_path.parent.mkdir(parents=True, exist_ok=True)
        workflow_path.write_text(
            json.dumps({"1": {"class_type": "BSAI_IndexTTS2.5Synthesis", "inputs": {}}}),
            encoding="utf-8",
        )

        module = SimpleNamespace(
            read_project_article_source=lambda *_args, **_kwargs: None,
            get_setting=lambda key, default="": {
                "tts_provider": "comfyui_tts",
                "tts_endpoint": str(workflow_path),
                "tts_api_key": "",
                "llm_api_key": "configured",
                "image_api_key": "configured",
            }.get(key, default),
            resolve_media_tool=lambda _name: "available",
            repo_root=root,
            inspect_tts_preflight=lambda _workflow: {
                "success": False,
                "errors": ["ComfyUI 连接失败: ConnectError"],
            },
        )

        errors = one_click._preflight_errors(module, project)

        assert any("ComfyUI/IndexTTS 不可用" in error for error in errors)
        assert any("127.0.0.1:8188" in error for error in errors)


def test_one_click_routes_are_explicit_and_unique() -> None:
    route_methods = [
        (getattr(route, "path", ""), frozenset(getattr(route, "methods", set()) or set()))
        for route in iter_effective_routes(server.app)
    ]
    assert route_methods.count(("/api/projects/{project_id}/one-click-generate", frozenset({"POST"}))) == 1
    assert route_methods.count(("/api/projects/{project_id}/one-click-generate/status", frozenset({"GET"}))) == 1
    assert not hasattr(one_click, "_register")
    assert not hasattr(one_click, "PATCH_MARKER")
    assert not hasattr(one_click, "_install_when_ready")
    assert not hasattr(one_click, "_candidate_modules")
    dependencies = one_click.get_one_click_dependencies()
    assert dependencies.project_model is server.Project
    assert not hasattr(dependencies, "app")
    assert not hasattr(dependencies, "server_module")


if __name__ == "__main__":
    test_atomic_status_write_and_resume()
    test_restart_does_not_reuse_failed_stage_state()
    test_contract_and_narration_are_only_reused_when_fresh_and_validated()
    test_disabled_quality_gate_marks_terminal_failure()
    test_only_uncorrected_ai_masks_are_replaceable()
    test_one_click_uses_safe_mask_and_audio_modes()
    test_preflight_migrates_legacy_article_before_checking_source()
    test_one_click_routes_are_explicit_and_unique()
    print("one-click orchestrator checks passed")
