import json
import hashlib
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ai_mask_engine as ai_mask
import one_click_orchestrator as one_click
from route_inventory import iter_effective_routes
import server


def project_for(root: Path) -> SimpleNamespace:
    return SimpleNamespace(id="project-test", run_dir=str(root))


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


def test_one_click_uses_safe_mask_and_audio_modes() -> None:
    source = Path("one_click_orchestrator.py").read_text(encoding="utf-8")
    services_source = Path("pipeline_services.py").read_text(encoding="utf-8")
    assert '"overwrite_existing_manual_mask": False' in source
    assert '"overwrite_existing_ai_mask": True' in source
    assert '"skip_locked_groups": True' in source
    assert '"confirmation_mode": "automatic_technical"' in services_source
    assert "pipeline_service_factory" in source
    assert "services.narration" in source
    assert "services.save_narration" in source
    assert "TestClient" not in source
    assert "client.get(" not in source
    assert "client.post(" not in source
    assert "client.put(" not in source
    assert 'mode == "restart" or not _has_contract(project)' in source
    for gate_name in one_click.DEFAULT_QUALITY_GATES:
        assert source.count(gate_name) >= 2


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
