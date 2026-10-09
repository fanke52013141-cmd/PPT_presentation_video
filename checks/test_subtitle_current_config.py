import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import creation_config_service
from project_config_runtime import project_subtitles_enabled
from scripts.build_remotion_props import read_subtitle_style
from visual_settings_service import VisualSettingsDependencies, VisualSettingsService


def setup_project(tmp_path, monkeypatch):
    (tmp_path / "planning").mkdir()
    (tmp_path / "planning/project_config.json").write_text(json.dumps({"payload": {
        "schema_version": "creation_config_v1", "subtitle": {"enabled": False, "font_size": 40}
    }}), encoding="utf-8")
    monkeypatch.setattr(creation_config_service, "resolve_creation_config", lambda *args, **kwargs: {
        "payload": {"schema_version": "creation_config_v1", "subtitle": {"enabled": True, "font_size": 48}}
    })
    return SimpleNamespace(id="subtitle-config-test", run_dir=str(tmp_path), creation_config_package_id="test-package")


def test_current_checked_subtitles_replace_old_copied_defaults(tmp_path, monkeypatch):
    project = setup_project(tmp_path, monkeypatch)
    (tmp_path / "visual_settings.json").write_text(json.dumps({"subtitle_style": {
        "enabled": False, "font_size": 40
    }}), encoding="utf-8")
    assert project_subtitles_enabled(project) is True
    style = read_subtitle_style(tmp_path, project)
    assert style["enabled"] is True
    assert style["font_size"] == 48


def test_explicit_project_subtitle_disable_stays_disabled(tmp_path, monkeypatch):
    project = setup_project(tmp_path, monkeypatch)
    (tmp_path / "visual_settings.json").write_text(json.dumps({
        "subtitle_style_source": "project", "subtitle_style": {"enabled": False}
    }), encoding="utf-8")
    assert project_subtitles_enabled(project) is False
    assert read_subtitle_style(tmp_path, project)["enabled"] is False


def test_invalid_legacy_style_keeps_current_package_defaults(tmp_path, monkeypatch):
    project = setup_project(tmp_path, monkeypatch)
    (tmp_path / "visual_settings.json").write_text("{broken", encoding="utf-8")
    assert read_subtitle_style(tmp_path, project)["enabled"] is True


def test_background_change_preserves_legacy_subtitle_edits(tmp_path, monkeypatch):
    project = setup_project(tmp_path, monkeypatch)
    (tmp_path / "visual_settings.json").write_text(json.dumps({"subtitle_style": {
        "enabled": False, "font_size": 52
    }}), encoding="utf-8")
    service = VisualSettingsService(VisualSettingsDependencies(
        read_contract_slide_ids=lambda _: [], reveal_lock_for=lambda _: nullcontext(),
        write_json_atomic=lambda path, value: Path(path).write_text(json.dumps(value), encoding="utf-8"),
        style_reference_dir=tmp_path / "styles", style_reference_template="unused.png",
    ))
    service.write_settings(project, video_background="#FFFFFF")
    style = read_subtitle_style(tmp_path, project)
    assert style["enabled"] is True
    assert style["font_size"] == 52


def test_render_subprocess_receives_current_subtitle_settings(tmp_path, monkeypatch):
    from remotion_runner import RemotionRunner, RemotionRunnerDependencies
    from video_contracts import VideoRenderConfig
    project = setup_project(tmp_path, monkeypatch)
    (tmp_path / "visual_settings.json").write_text(json.dumps({"subtitle_style": {"enabled": False}}), encoding="utf-8")
    received = []
    def execute(args, **kwargs):
        received.extend(args)
        (tmp_path / "remotion_props.json").write_text('{"slides":[]}', encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    config = VideoRenderConfig(repo_root=tmp_path, runs_root=tmp_path, pipeline_version="test",
        reveal_visual_lead_sec=.2, bind_timeout_sec=1, build_props_timeout_sec=1,
        npm_install_timeout_sec=1, render_timeout_sec=1, color_process_timeout_sec=1)
    runner = RemotionRunner(RemotionRunnerDependencies(config=config,
        build_reveal_assets=lambda _: None, write_project_log=lambda *args, **kwargs: None,
        run_subprocess_bounded=execute, resolve_media_tool=lambda _: None))
    runner._build_remotion_props(project, lambda _: None)
    passed_style = json.loads(received[received.index("--subtitle-style-json") + 1])
    assert passed_style["enabled"] is True
    assert passed_style["font_size"] == 48
