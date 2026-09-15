"""Regression coverage for optional project-level Step 2 duration targets."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from project_service import ProjectCreate, ProjectDependencies, ProjectService
from storyboard_planning import (
    build_step2_script_user_prompt,
    target_duration_response,
)


def _service(tmp_path: Path) -> tuple[ProjectService, object]:
    engine = create_engine(f"sqlite:///{tmp_path / 'projects.db'}")
    Base.metadata.create_all(engine)
    return (
        ProjectService(
            ProjectDependencies(
                runs_root=tmp_path / "runs",
                project_audio_confirmed=lambda _project: False,
            )
        ),
        sessionmaker(bind=engine)(),
    )


def test_target_duration_defaults_to_none_and_is_returned(tmp_path: Path) -> None:
    service, db = _service(tmp_path)
    try:
        created = service.create(ProjectCreate(name="不限时长"), db)["project"]
        assert created["target_duration_sec"] is None
        assert service.get(created["id"], db)["target_duration_sec"] is None
    finally:
        db.close()


def test_valid_target_duration_is_saved_as_project_field(tmp_path: Path) -> None:
    service, db = _service(tmp_path)
    try:
        created = service.create(
            ProjectCreate(name="两分钟", target_duration_sec=120), db
        )["project"]
        assert created["target_duration_sec"] == 120
        assert service.get(created["id"], db)["target_duration_sec"] == 120
    finally:
        db.close()


@pytest.mark.parametrize("value", [0, 29, 31, 119, 601, "bad"])
def test_target_duration_rejects_values_outside_half_minute_range(value) -> None:
    with pytest.raises(ValidationError):
        ProjectCreate(name="无效时长", target_duration_sec=value)


def test_step2_prompt_has_no_duration_material_when_target_is_unset() -> None:
    prompt = build_step2_script_user_prompt(
        project_title="自由规划",
        article_content="正文",
        generation_requirement="",
    )
    assert "DurationConstraint" not in prompt
    assert "target_duration" not in prompt


def test_step2_prompt_injects_selected_duration_with_character_budget() -> None:
    prompt = build_step2_script_user_prompt(
        project_title="两分钟",
        article_content="正文",
        generation_requirement="",
        target_duration_sec=120,
    )
    assert "DurationConstraint" in prompt
    assert "2 分钟（120 秒）" in prompt
    assert "560 字" in prompt
    assert "480–640 字" in prompt
    assert "重复、空话、虚构事实" in prompt


def test_new_video_forms_offer_unset_and_half_minute_duration_choices() -> None:
    root = Path(__file__).resolve().parents[1]
    for path in (root / "static" / "index.html", root / "static" / "project_profile_extension.js"):
        source = path.read_text(encoding="utf-8")
        assert 'id="input-project-target-duration"' in source
        assert "不设置（默认）" in source
        assert 'value="30"' in source
        assert 'value="600"' in source


def test_duration_response_reports_estimated_duration_and_delta() -> None:
    summary = target_duration_response(
        60,
        {"slides": [{"narration": "字" * 280}]},
    )
    assert summary == {
        "target_duration_sec": 60,
        "target_duration_label": "1 分钟",
        "recommended_narration_chars": 280,
        "narration_chars_range": [240, 320],
        "actual_narration_chars": 280,
        "estimated_duration_sec": 60,
        "estimated_duration_delta_sec": 0,
    }
