"""持久化 TTS 合成任务（审查 M-09 第二步）。

覆盖：创建→完成、失败语义、活动任务复用、进程重启恢复。
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base, LocalJob, Project
import tts_service
from tts_service import TTS_JOB_TYPE, TtsAsyncDependencies


def _session_factory(tmp_path: Path):
    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'tts-jobs.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(test_engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def _make_project(session_factory, tmp_path: Path, project_id: str = "project-tts") -> None:
    run_dir = tmp_path / "runs" / project_id
    run_dir.mkdir(parents=True, exist_ok=True)
    session = session_factory()
    try:
        session.add(
        Project(
            id=project_id,
            name="TTS job test",
            run_dir=str(run_dir),
            current_step=6,
        )
    )
        session.commit()
    finally:
        session.close()


def _build_service(session_factory, synthesize, *, submit_noop: bool = False):
    service = tts_service.TtsAsyncService(
        TtsAsyncDependencies(
            session_factory=session_factory,
            synthesize=synthesize,
        )
    )
    if submit_noop:
        service.submit = lambda job_id: None
    return service


def test_job_runs_to_completed_with_summary(tmp_path: Path) -> None:
    testing_session = _session_factory(tmp_path)
    db = testing_session()
    _make_project(testing_session, tmp_path)

    calls: list[tuple[str, object]] = []

    def fake_synthesize(project_id: str, db) -> dict:
        calls.append((project_id, type(db).__name__))
        return {
            "success": True,
            "generated": ["slide_001", "slide_002"],
            "skipped": ["slide_003"],
            "failed": [],
            "message": "音频生成完成",
        }

    service = _build_service(testing_session, fake_synthesize, submit_noop=True)
    response = service.create_job(db, "project-tts")

    assert response["success"] is True
    assert response["reused"] is False
    job_id = response["job"]["id"]
    assert response["job"]["status"] == "queued"

    service.run_job(job_id)

    final = service.get_job(db, "project-tts", job_id)["job"]
    assert final["status"] == "completed"
    assert final["progress"] == 100
    assert final["result"]["generated"] == 2
    assert final["result"]["skipped"] == 1
    assert final["result"]["failed_ids"] == []
    assert calls and calls[0][0] == "project-tts"


def test_failed_synthesis_marks_job_failed(tmp_path: Path) -> None:
    testing_session = _session_factory(tmp_path)
    db = testing_session()
    _make_project(testing_session, tmp_path)

    def failing_synthesize(project_id: str, db) -> dict:
        return {
            "success": False,
            "generated": [],
            "skipped": [],
            "failed": [{"slide_id": "slide_001", "error": "timeout"}],
            "message": "音频部分生成失败，请重试缺失页面：slide_001",
        }

    service = _build_service(testing_session, failing_synthesize, submit_noop=True)
    response = service.create_job(db, "project-tts")
    service.run_job(response["job"]["id"])

    final = service.get_job(db, "project-tts", response["job"]["id"])["job"]
    assert final["status"] == "failed"
    assert "slide_001" in final["error"]
    assert final["result"]["failed_ids"] == ["slide_001"]


def test_synthesis_exception_marks_job_failed(tmp_path: Path) -> None:
    testing_session = _session_factory(tmp_path)
    db = testing_session()
    _make_project(testing_session, tmp_path)

    def exploding_synthesize(project_id: str, db) -> dict:
        raise RuntimeError("TTS provider exploded")

    service = _build_service(testing_session, exploding_synthesize, submit_noop=True)
    response = service.create_job(db, "project-tts")
    service.run_job(response["job"]["id"])

    final = service.get_job(db, "project-tts", response["job"]["id"])["job"]
    assert final["status"] == "failed"
    assert "TTS provider exploded" in (final["error"] or "")


def test_active_job_is_reused_not_duplicated(tmp_path: Path) -> None:
    testing_session = _session_factory(tmp_path)
    db = testing_session()
    _make_project(testing_session, tmp_path)

    service = _build_service(
        testing_session,
        lambda project_id, db: {"success": True},
        submit_noop=True,
    )
    first = service.create_job(db, "project-tts")
    second = service.create_job(db, "project-tts")

    assert first["reused"] is False
    assert second["reused"] is True
    assert second["job"]["id"] == first["job"]["id"]
    jobs = service.list_jobs(db, "project-tts")["jobs"]
    assert len(jobs) == 1


def test_recover_marks_running_jobs_interrupted(tmp_path: Path) -> None:
    testing_session = _session_factory(tmp_path)
    db = testing_session()
    _make_project(testing_session, tmp_path)

    service = _build_service(
        testing_session,
        lambda project_id, db: {"success": True},
        submit_noop=True,
    )
    created = service.create_job(db, "project-tts")
    job = (
        db.query(LocalJob)
        .filter(LocalJob.id == created["job"]["id"])
        .first()
    )
    job.status = "running"
    db.commit()

    interrupted_count = service.recover_jobs()
    assert interrupted_count == 1

    final = service.get_job(
        db, "project-tts", created["job"]["id"]
    )["job"]
    assert final["status"] == "interrupted"
    assert "中断" in (final["error"] or "")


def test_job_type_is_namespaced() -> None:
    assert TTS_JOB_TYPE == "tts_synthesis"
