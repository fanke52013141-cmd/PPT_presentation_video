"""跨项目后台任务排队位次（queue_ahead）单测。

覆盖：VideoJobStore.count_queued_ahead、PptxExportService._queued_ahead、
TtsAsyncService._queued_ahead 的排序计数、跨 job_type 隔离、
非 queued 状态返回 None 的语义，以及 job_item 的透传保护。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base, LocalJob, Project
from pptx_service import PptxExportService, PptxServiceDependencies
from tts_service import TTS_JOB_TYPE, TtsAsyncDependencies, TtsAsyncService
from video_job_store import VIDEO_RENDER_JOB_TYPE, VideoJobStore


def _session_factory(tmp_path: Path, db_name: str):
    test_engine = create_engine(
        f"sqlite:///{tmp_path / db_name}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(test_engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def _insert_job(
    session_factory,
    *,
    job_id: str,
    project_id: str,
    job_type: str,
    status: str = "queued",
    created_at: datetime,
) -> LocalJob:
    db = session_factory()
    try:
        job = LocalJob(
            id=job_id,
            project_id=project_id,
            job_type=job_type,
            status=status,
            progress=0,
            stage=status,
            payload_json="{}",
            created_at=created_at,
            updated_at=datetime.now(),
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        db.expunge(job)
        return job
    finally:
        db.close()


def test_video_job_store_counts_earlier_queued_siblings(tmp_path: Path) -> None:
    testing_session = _session_factory(tmp_path, "queue-ahead-video.db")
    store = VideoJobStore(testing_session)

    base = datetime.now() - timedelta(minutes=10)
    first = _insert_job(
        testing_session,
        job_id="video-q-001",
        project_id="project-a",
        job_type=VIDEO_RENDER_JOB_TYPE,
        created_at=base,
    )
    second = _insert_job(
        testing_session,
        job_id="video-q-002",
        project_id="project-b",
        job_type=VIDEO_RENDER_JOB_TYPE,
        created_at=base + timedelta(seconds=30),
    )
    other_type = _insert_job(
        testing_session,
        job_id="pptx-q-001",
        project_id="project-c",
        job_type="pptx_export",
        created_at=base + timedelta(seconds=15),
    )

    # 先入队者前面没有同类排队任务；后入队者前面有 1 个。
    assert (
        store.count_queued_ahead(
            VIDEO_RENDER_JOB_TYPE, before_created_at=first.created_at
        )
        == 0
    )
    assert (
        store.count_queued_ahead(
            VIDEO_RENDER_JOB_TYPE, before_created_at=second.created_at
        )
        == 1
    )
    # 跨 job_type 隔离：更早的 PPTX 排队任务不计入视频位次。
    assert (
        store.count_queued_ahead(
            "pptx_export", before_created_at=other_type.created_at
        )
        == 0
    )

    # 非 queued 状态不占位次：先入队者进入 rendering 后，后入队者成为队首。
    store.update(first.id, status="running", stage="rendering", progress=10)
    assert (
        store.count_queued_ahead(
            VIDEO_RENDER_JOB_TYPE, before_created_at=second.created_at
        )
        == 0
    )


def test_pptx_service_queue_ahead_semantics(tmp_path: Path) -> None:
    testing_session = _session_factory(tmp_path, "queue-ahead-pptx.db")
    service = PptxExportService(
        PptxServiceDependencies(
            session_factory=testing_session,
            runs_root=tmp_path,
        )
    )

    base = datetime.now() - timedelta(minutes=10)
    first = _insert_job(
        testing_session,
        job_id="pptx-ahead-001",
        project_id="project-a",
        job_type="pptx_export",
        created_at=base,
    )
    second = _insert_job(
        testing_session,
        job_id="pptx-ahead-002",
        project_id="project-b",
        job_type="pptx_export",
        created_at=base + timedelta(seconds=30),
    )
    tts_job = _insert_job(
        testing_session,
        job_id="tts-ahead-001",
        project_id="project-c",
        job_type=TTS_JOB_TYPE,
        created_at=base + timedelta(seconds=15),
    )

    db = testing_session()
    try:
        assert service._queued_ahead(db, first) == 0
        assert service._queued_ahead(db, second) == 1
        # 跨 job_type 隔离：更早的 TTS 排队任务不影响 PPTX 位次。
        assert service._queued_ahead(db, tts_job) == 0

        first_row = (
            db.query(LocalJob).filter(LocalJob.id == first.id).first()
        )
        first_row.status = "running"
        first_row.stage = "rendering"
        db.commit()
        db.refresh(first_row)

        # 非 queued 状态返回 None；队列空出后后入队者位次归零。
        assert service._queued_ahead(db, first_row) is None
        second_row = (
            db.query(LocalJob).filter(LocalJob.id == second.id).first()
        )
        assert service._queued_ahead(db, second_row) == 0

        # job_item 透传保护：running 任务即使误传 queue_ahead 也输出 None。
        assert service.job_item(first_row, queue_ahead=0)["queue_ahead"] is None
        assert service.job_item(
            second_row, queue_ahead=service._queued_ahead(db, second_row)
        )["queue_ahead"] == 0
    finally:
        db.close()


def test_tts_service_queue_ahead_semantics(tmp_path: Path) -> None:
    testing_session = _session_factory(tmp_path, "queue-ahead-tts.db")
    service = TtsAsyncService(
        TtsAsyncDependencies(
            session_factory=testing_session,
            synthesize=lambda project_id, db: {"success": True},
        )
    )

    base = datetime.now() - timedelta(minutes=10)
    # get_job 会做 project_or_404 校验，先建齐项目行。
    seed_db = testing_session()
    try:
        seed_db.add(
            Project(id="project-a", name="项目A", run_dir=str(tmp_path / "a"))
        )
        seed_db.add(
            Project(id="project-b", name="项目B", run_dir=str(tmp_path / "b"))
        )
        seed_db.commit()
    finally:
        seed_db.close()
    first = _insert_job(
        testing_session,
        job_id="tts-sem-001",
        project_id="project-a",
        job_type=TTS_JOB_TYPE,
        created_at=base,
    )
    second = _insert_job(
        testing_session,
        job_id="tts-sem-002",
        project_id="project-b",
        job_type=TTS_JOB_TYPE,
        created_at=base + timedelta(seconds=30),
    )
    other_type = _insert_job(
        testing_session,
        job_id="video-sem-001",
        project_id="project-c",
        job_type=VIDEO_RENDER_JOB_TYPE,
        created_at=base + timedelta(seconds=15),
    )

    db = testing_session()
    try:
        assert service._queued_ahead(db, first) == 0
        assert service._queued_ahead(db, second) == 1
        # 跨 job_type 隔离：更早的视频排队任务不影响 TTS 位次。
        assert service._queued_ahead(db, other_type) == 0

        first_row = (
            db.query(LocalJob).filter(LocalJob.id == first.id).first()
        )
        first_row.status = "running"
        first_row.stage = "synthesizing"
        db.commit()
        db.refresh(first_row)

        assert service._queued_ahead(db, first_row) is None
        second_row = (
            db.query(LocalJob).filter(LocalJob.id == second.id).first()
        )
        assert service._queued_ahead(db, second_row) == 0

        # get_job 把位次透传给前端响应（建议值，0 表示下一个就轮到）。
        response = service.get_job(db, "project-b", second.id)
        assert response["job"]["queue_ahead"] == 0
    finally:
        db.close()
