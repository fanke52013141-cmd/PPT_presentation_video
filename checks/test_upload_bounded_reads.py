"""上传通道必须有界读取且上限一致（审查 M-01 / M-02）。

回归背景：
- 数字人路由与背景/反向分析上传曾"先无界读入内存、后校验大小"，
  2GB 视频上传即 2GB 内存峰值；
- 项目级风格参考图上传完全没有大小上限与 MIME 校验；
- 头像大小在主应用路由（500MB）与数字人独立服务（200MB）不一致。
"""

import re
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import digital_human_routes as dh_routes  # noqa: E402


REPO_PY_FILES = [p for p in ROOT.glob("*.py") if p.name != "__pycache__"]


def test_no_unbounded_upload_reads_anywhere() -> None:
    """守护：全仓禁止无参的全量上传读取。"""
    offenders: list[str] = []
    for path in REPO_PY_FILES:
        source = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"await file\.read\(\)", source):
            offenders.append(f"{path.name}: await file.read()")
        if re.search(r"file\.file\.read\(\)", source):
            offenders.append(f"{path.name}: file.file.read()")
    assert offenders == [], "存在无界上传读取: " + "; ".join(offenders)


def test_avatar_limits_are_consistent_across_layers() -> None:
    """守护：路由层与数字人独立服务的头像上限必须同为 200MB。"""
    routes_source = (ROOT / "digital_human_routes.py").read_text(
        encoding="utf-8"
    )
    service_source = (ROOT / "digital_human_service.py").read_text(
        encoding="utf-8"
    )
    assert "PPT_MAX_AVATAR_UPLOAD_BYTES" in routes_source
    assert "PPT_DIGITAL_HUMAN_MAX_AVATAR_BYTES" in service_source
    assert re.search(
        r"PPT_MAX_AVATAR_UPLOAD_BYTES\",\s*str\(200 \* 1024 \* 1024\)",
        routes_source,
    ), "路由层头像上限应为 200MB"
    assert re.search(
        r"PPT_DIGITAL_HUMAN_MAX_AVATAR_BYTES\",\s*str\(200 \* 1024 \* 1024\)",
        service_source,
    ), "服务端头像上限应为 200MB"


def test_style_reference_upload_has_limit_and_mime_guard() -> None:
    """守护：项目级参考图上传必须带 12MB 上限与 image/* 校验。"""
    source = (ROOT / "project_style_routes.py").read_text(encoding="utf-8")
    assert "MAX_REFERENCE_IMAGE_BYTES = 12 * 1024 * 1024" in source
    assert "await file.read(MAX_REFERENCE_IMAGE_BYTES + 1)" in source
    assert 'startswith("image/")' in source


class _FakeUpload:
    def __init__(self, content_type: str | None) -> None:
        self.content_type = content_type
        self.filename = "fake.bin"


def test_validate_upload_rejects_empty_oversize_and_bad_mime() -> None:
    _validate = dh_routes._validate_upload
    mimes = set(dh_routes.ALLOWED_VIDEO_MIMES)

    with pytest.raises(HTTPException) as empty:
        _validate(b"", _FakeUpload("video/mp4"), 100, mimes)
    assert empty.value.status_code == 400

    with pytest.raises(HTTPException) as oversize:
        _validate(b"x" * 101, _FakeUpload("video/mp4"), 100, mimes)
    assert oversize.value.status_code == 413

    with pytest.raises(HTTPException) as bad_mime:
        _validate(b"x" * 10, _FakeUpload("text/html"), 100, mimes)
    assert bad_mime.value.status_code == 415

    # 合法路径不抛出
    _validate(b"x" * 10, _FakeUpload("video/mp4"), 100, mimes)
    _validate(b"x" * 10, _FakeUpload(None), 100, mimes)
    _validate(b"x" * 10, _FakeUpload("application/octet-stream"), 100, mimes)


def test_avatar_route_limit_matches_service_default_value() -> None:
    assert dh_routes.MAX_AVATAR_UPLOAD_BYTES == 200 * 1024 * 1024


def test_saved_comfyui_workflow_corruption_is_not_silently_ignored(
    tmp_path: Path,
) -> None:
    project = type("Project", (), {"id": "workflow-test", "run_dir": str(tmp_path)})()
    workflow_path = tmp_path / "planning" / "digital_human" / "comfyui_workflow.json"
    workflow_path.parent.mkdir(parents=True)
    workflow_path.write_text("{broken", encoding="utf-8")

    with pytest.raises(HTTPException) as invalid:
        dh_routes._read_comfyui_workflow_template(project)

    assert invalid.value.status_code == 409
    assert "重新上传" in str(invalid.value.detail)
