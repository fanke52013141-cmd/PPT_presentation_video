from datetime import datetime
from types import SimpleNamespace
from course_service import _project_brief


def test_course_tree_returns_output_and_workflow_completion(monkeypatch):
    monkeypatch.setattr("course_service.project_audio_confirmed", lambda _: True)
    artifact = SimpleNamespace(created_at=datetime(2026, 10, 9, 20, 54, 14), artifact_type="video")
    class Query:
        def query(self, *_args): return self
        def filter(self, *_args): return self
        def order_by(self, *_args): return self
        def first(self): return artifact
    status = {str(step): "completed" for step in range(1, 9)}
    project = SimpleNamespace(id="library-test", name="Exported video", description="", current_step=8,
        status="active", ai_mode="auto", sort_order=0, course_id=None, chapter_id=None,
        created_at=None, updated_at=None, get_step_status=lambda: status)
    brief = _project_brief(project, Query())
    assert brief["step_status"] == status
    assert brief["audio_confirmed"] is True
    assert brief["latest_output_type"] == "video"
    assert brief["latest_output_at"] == "2026-10-09T20:54:14"
