# -*- coding: utf-8 -*-
"""PPTX 任务构造回归(R2-001):首发与重试共用 _prepared_export_job。

历史缺陷:retry_job 只传 project_id/mode,account_id 落默认 "default"、
input_digest 为空——非 default 账号的重试导出必然失败,且没有输入变化保护。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import Base, LocalJob, Project  # noqa: E402
from pptx_service import PptxExportService, PptxServiceError, PptxServiceDependencies  # noqa: E402


@pytest.fixture()
def service(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'retry.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    run_root = tmp_path / "runs" / "acct-project"
    (run_root / "slides" / "slide_001").mkdir(parents=True)
    db = testing_session()
    try:
        db.add(
            Project(
                id="acct-project",
                name="B 账号项目",
                run_dir=str(run_root),
                account_id="acct_b",
            )
        )
        db.add(
            LocalJob(
                id="job-old",
                project_id="acct-project",
                job_type="pptx_export",
                status="failed",
                progress=0,
                stage="failed",
                error="boom",
                payload_json=json.dumps({"filename": "old.pptx", "mode": "image_only"}),
            )
        )
        db.commit()
    finally:
        db.close()

    svc = PptxExportService(
        PptxServiceDependencies(
            session_factory=testing_session,
            runs_root=tmp_path / "runs",
            executor=Mock(),
        )
    )
    # 就绪检查不属于本用例(本用例验证任务构造);显式替换为就绪
    svc._resolve_export_mode = lambda run_dir: ("image_only", {"ready": True, "issues": []})
    return svc, testing_session


def test_retry_job_inherits_project_account(service):
    svc, testing_session = service
    from account_context import account_scope

    # R5-001(N1): default 上下文访问 acct_b 项目必须 404
    db = testing_session()
    try:
        with pytest.raises(PptxServiceError) as forbidden:
            svc.retry_job(db, "acct-project", "job-old")
        assert forbidden.value.status_code == 404
    finally:
        db.close()

    # 项目归属账号上下文内重试成功:归属必须来自项目行
    db = testing_session()
    try:
        with account_scope("acct_b"):
            result = svc.retry_job(db, "acct-project", "job-old")
    finally:
        db.close()
    assert result["success"] is True and result["reused"] is False

    db = testing_session()
    try:
        new_job = (
            db.query(LocalJob)
            .filter(LocalJob.id != "job-old", LocalJob.job_type == "pptx_export")
            .order_by(LocalJob.created_at.desc())
            .first()
        )
        assert new_job is not None
        payload = json.loads(new_job.payload_json)
        assert payload["account_id"] == "acct_b", "重试必须继承项目的账号归属"
        assert payload["input_digest"], "重试必须重新生成输入指纹,不能为空"
        assert isinstance(payload["impact_snapshot"], list), (
            "重试必须按当前状态重建影响快照(无待办时允许为空列表)"
        )
        assert new_job.status == "queued"
    finally:
        db.close()


def test_create_export_records_account_and_digest(service):
    svc, testing_session = service
    from account_context import account_scope

    db = testing_session()
    try:
        with account_scope("acct_b"):
            result = svc.create_export(db, "acct-project")
    finally:
        db.close()
    assert result["success"] is True and result["reused"] is False
    payload = json.loads(
        testing_session()
        .query(LocalJob)
        .filter(LocalJob.id != "job-old")
        .order_by(LocalJob.created_at.desc())
        .first()
        .payload_json
    )
    assert payload["account_id"] == "acct_b"
    assert payload["input_digest"]
    assert isinstance(payload["impact_snapshot"], list)
