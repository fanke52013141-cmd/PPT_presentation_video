"""Tests for the structured pipeline error logging service."""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from error_log_service import (
    ERROR_LOG_DIR,
    _extract_project_id_from_path,
    _resolve_step_label,
    log_pipeline_error,
    get_latest_error_log_path,
)


def test_basic_error_logging():
    """log_pipeline_error writes a JSON Lines entry with all fields."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("error_log_service.ERROR_LOG_DIR", os.path.join(tmpdir, "errors")):
            log_path = log_pipeline_error(
                project_id="test_123",
                project_name="测试项目",
                step="speed",
                error_message="生成调速视频失败：test error",
                error_type="VideoRenderError",
                details={"speed": 1.25, "ffmpeg_returncode": 1},
            )
            assert os.path.isfile(log_path)
            with open(log_path, encoding="utf-8") as fh:
                entry = json.loads(fh.readline())
            assert entry["project_id"] == "test_123"
            assert entry["project_name"] == "测试项目"
            assert entry["step"] == "Step 8 视频调速"
            assert entry["error_type"] == "VideoRenderError"
            assert "test error" in entry["message"]
            assert entry["details"]["speed"] == 1.25
    print("test_basic_error_logging passed")


def test_step_label_resolution():
    """Short step keys are resolved to human-readable labels."""
    assert "Step 8" in _resolve_step_label("step8")
    assert "Step 8" in _resolve_step_label("speed")
    assert "Step 8" in _resolve_step_label("render")
    assert "Step 1" in _resolve_step_label("step1")
    # Unknown keys pass through unchanged.
    assert _resolve_step_label("custom_step") == "custom_step"
    print("test_step_label_resolution passed")


def test_project_id_extraction_from_path():
    """project_id is extracted from URL paths."""
    assert _extract_project_id_from_path("/api/projects/abc_123/videos") == "abc_123"
    assert _extract_project_id_from_path("/api/projects/xyz/speed") == "xyz"
    # No project in path.
    assert _extract_project_id_from_path("/api/settings") == ""
    assert _extract_project_id_from_path("") == ""
    print("test_project_id_extraction_from_path passed")


def test_auto_extract_project_id():
    """When project_id is empty, it's extracted from request_path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("error_log_service.ERROR_LOG_DIR", os.path.join(tmpdir, "errors")):
            log_path = log_pipeline_error(
                project_id="",
                step="step8",
                error_message="render failed",
                request_path="/api/projects/auto_456/steps/8/render",
            )
            with open(log_path, encoding="utf-8") as fh:
                entry = json.loads(fh.readline())
            assert entry["project_id"] == "auto_456"
    print("test_auto_extract_project_id passed")


def test_multiple_entries_appended():
    """Multiple errors are appended to the same daily log file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("error_log_service.ERROR_LOG_DIR", os.path.join(tmpdir, "errors")):
            for i in range(3):
                log_pipeline_error(
                    project_id=f"proj_{i}",
                    step="step8",
                    error_message=f"error {i}",
                )
            import datetime
            today = datetime.datetime.now().strftime("%Y%m%d")
            log_file = os.path.join(tmpdir, "errors", f"error_log_{today}.jsonl")
            with open(log_file, encoding="utf-8") as fh:
                lines = [json.loads(l) for l in fh if l.strip()]
            assert len(lines) == 3
            assert lines[0]["project_id"] == "proj_0"
            assert lines[2]["project_id"] == "proj_2"
    print("test_multiple_entries_appended passed")


def test_get_latest_error_log_path():
    """get_latest_error_log_path returns None when no log exists."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("error_log_service.ERROR_LOG_DIR", os.path.join(tmpdir, "errors")):
            assert get_latest_error_log_path() is None
            log_pipeline_error(
                project_id="x",
                step="step8",
                error_message="test",
            )
            path = get_latest_error_log_path()
            assert path is not None
            assert os.path.isfile(path)
    print("test_get_latest_error_log_path passed")


def test_unicode_project_name():
    """Chinese project names are preserved correctly in the log."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("error_log_service.ERROR_LOG_DIR", os.path.join(tmpdir, "errors")):
            log_pipeline_error(
                project_id="9bb33709",
                project_name="三色法错题整理",
                step="speed",
                error_message="生成调速视频失败：FFmpeg error",
            )
            import datetime
            today = datetime.datetime.now().strftime("%Y%m%d")
            log_file = os.path.join(tmpdir, "errors", f"error_log_{today}.jsonl")
            raw = Path(log_file).read_text(encoding="utf-8")
            entry = json.loads(raw.strip())
            assert entry["project_name"] == "三色法错题整理"
    print("test_unicode_project_name passed")


def test_empty_details_defaults_to_dict():
    """When details is None, an empty dict is stored."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("error_log_service.ERROR_LOG_DIR", os.path.join(tmpdir, "errors")):
            log_pipeline_error(
                project_id="p",
                step="step8",
                error_message="err",
            )
            import datetime
            today = datetime.datetime.now().strftime("%Y%m%d")
            log_file = os.path.join(tmpdir, "errors", f"error_log_{today}.jsonl")
            with open(log_file, encoding="utf-8") as fh:
                entry = json.loads(fh.readline())
            assert entry["details"] == {}
    print("test_empty_details_defaults_to_dict passed")


test_basic_error_logging()
test_step_label_resolution()
test_project_id_extraction_from_path()
test_auto_extract_project_id()
test_multiple_entries_appended()
test_get_latest_error_log_path()
test_unicode_project_name()
test_empty_details_defaults_to_dict()

print("error log service tests passed")
