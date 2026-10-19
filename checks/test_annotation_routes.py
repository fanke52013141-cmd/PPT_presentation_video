# -*- coding: utf-8 -*-
"""annotation_routes/service 集成测试:CRUD、revision 冲突、账号隔离、门禁。

使用 conftest 隔离的临时数据库与 runs 目录;服务/存储以生产依赖装配
(真实 write_json_atomic + 项目锁),路由用独立 FastAPI 应用挂载。
"""
from __future__ import annotations

import hashlib
import json
import sys
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from account_context import account_scope  # noqa: E402
from annotation_routes import router  # noqa: E402
from annotation_service import (  # noqa: E402
    AnnotationServiceDependencies,
    configure_annotation_service,
    get_annotation_service,
)
from annotation_store import (  # noqa: E402
    AnnotationStoreDependencies,
    configure_annotation_store,
    get_annotation_store,
)
from database import Project, SessionLocal  # noqa: E402
from pipeline_lifecycle import write_json_atomic  # noqa: E402
from project_runtime_service import reveal_lock_for  # noqa: E402
from repository_paths import RUNS_DIR  # noqa: E402

SPOKEN = "报名时间到9月30日截止"  # "9月30日" = 码点 [5, 9)


def _make_project(account_id: str = "default") -> tuple[str, Path]:
    from database import Account

    project_id = "ann" + uuid.uuid4().hex[:12]
    run_root = Path(RUNS_DIR) / project_id
    (run_root / "planning").mkdir(parents=True)
    slide_root = run_root / "slides" / "slide_001"
    slide_root.mkdir(parents=True)
    (run_root / "planning" / "visual_contract.json").write_text(
        json.dumps({"slides": [{"slide_id": "slide_001"}]}), encoding="utf-8"
    )
    (slide_root / "visual_draft.png").write_bytes(b"\x89PNG-fake-bytes")
    (slide_root / "narration_beats.json").write_text(
        json.dumps(
            {"slide_id": "slide_001", "beats": [{"id": "slide_001_beat_001", "spoken_text": SPOKEN}]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    db = SessionLocal()
    if account_id != "default":
        db.add(Account(id=account_id, name=account_id, status="active"))
        db.commit()
    # 生产约定:Project.run_dir 存绝对路径(RUNS_DIR / project_id)
    db.add(Project(id=project_id, name="annotation-test", run_dir=str(run_root), account_id=account_id))
    db.commit()
    db.close()
    return project_id, run_root


def _drop_project(project_id: str) -> None:
    db = SessionLocal()
    db.query(Project).filter(Project.id == project_id).delete()
    db.commit()
    db.close()


@pytest.fixture(scope="module")
def client():
    configure_annotation_store(AnnotationStoreDependencies(write_json_atomic=write_json_atomic))
    configure_annotation_service(
        AnnotationServiceDependencies(store=get_annotation_store(), lock_for=reveal_lock_for)
    )
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def project():
    project_id, run_root = _make_project()
    yield project_id, run_root
    _drop_project(project_id)


REGION_ITEM = {
    "target": {
        "kind": "region",
        "layout_revision": None,
        "token_ids": [],
        "polygons": [[[100, 200], [400, 200], [400, 260], [100, 260]]],
        "quote": None,
        "granularity": "region",
        "mask_group_ids": [],
    },
    "style": {"type": "ellipse", "color": "#F46A38", "opacity": 0.85, "width": 5, "padding": 8, "seed": 11},
    "timing": {"trigger_mode": "anchor_start", "offset_sec": 0.0, "draw_duration_sec": 0.6, "hold_mode": "beat_end", "exit_duration_sec": 0.15},
}

# 可直接确认的条目:manual 定时不依赖词级对齐(confirm 构建要求精确锚点,
# anchor_start 条目必须先有音频字词对齐数据)。
MANUAL_REGION_ITEM = {
    "target": REGION_ITEM["target"],
    "style": REGION_ITEM["style"],
    "timing": {
        "trigger_mode": "manual", "offset_sec": 0.0, "manual_start_sec": 0.5,
        "draw_duration_sec": 0.6, "hold_mode": "slide_end", "exit_duration_sec": 0.15,
    },
}


def _make_audio(run_root: Path) -> None:
    """写入确认构建所需的最小音频时间轴(页长 8s,单语块)。"""
    (run_root / "slides" / "slide_001" / "audio_timeline.json").write_text(
        json.dumps(
            {
                "slide_id": "slide_001",
                "audio_content_duration_sec": 8.0,
                "audio_start_sec": 0.0,
                "segments": [
                    {"id": "slide_001_beat_001", "beat_id": "slide_001_beat_001",
                     "start": 0.0, "end": 4.0}
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

TEXT_ITEM = {
    "target": {
        "kind": "text",
        "layout_revision": 1,
        "token_ids": ["token_07"],
        "polygons": [[[800, 400], [960, 400], [960, 445], [800, 445]]],
        "quote": "9月30日",
        "granularity": "word",
        "mask_group_ids": [],
    },
    "anchor": {
        "beat_id": "slide_001_beat_001",
        "offset_unit": "unicode_codepoint",
        "range": [5, 10],
        "quote": "9月30日",
        "occurrence": 1,
        "context_before": "报名时间到",
        "context_after": "截止",
    },
    "style": {"type": "underline", "color": "#1D4ED8", "opacity": 0.7, "width": 4, "padding": 3, "seed": 5},
    "timing": {"trigger_mode": "anchor_start", "offset_sec": -0.1, "draw_duration_sec": 0.5, "hold_mode": "beat_end", "exit_duration_sec": 0.1},
}


# ---------------------------------------------------------------- 基础读取


def test_unknown_project_404(client):
    assert client.get("/api/projects/no-such/annotations").status_code == 404


def test_summary_defaults_and_readiness_unused(client, project):
    project_id, _ = project
    resp = client.get(f"/api/projects/{project_id}/annotations")
    assert resp.status_code == 200
    body = resp.json()
    assert body["settings"]["enabled"] is False
    # 缺设置文件 = 未使用,revision 0;首次 PUT expected_revision=0 创建
    assert body["settings"]["revision"] == 0
    assert body["readiness"]["can_render"] is True
    assert body["slides"] == [{"slide_id": "slide_001", "revision": 0, "counts": {"total": 0, "draft": 0, "confirmed": 0, "disabled": 0}}]


def test_get_slide_returns_narration_and_input_hashes(client, project):
    project_id, run_root = project
    resp = client.get(f"/api/projects/{project_id}/annotations/slides/slide_001")
    assert resp.status_code == 200
    body = resp.json()
    assert body["revision"] == 0 and body["items"] == []
    assert body["narration"]["beats"][0]["beat_id"] == "slide_001_beat_001"
    assert body["narration"]["beats"][0]["spoken_text"] == SPOKEN
    assert body["image"]["hash"] == hashlib.sha256(b"\x89PNG-fake-bytes").hexdigest()
    assert body["layout"] is None


def test_listening_cue_never_uses_replaced_audio_or_narration(client, project):
    project_id, run_root = project
    import copy
    item = copy.deepcopy(REGION_ITEM)
    item['anchor'] = copy.deepcopy(TEXT_ITEM['anchor'])
    base = f'/api/projects/{project_id}/annotations/slides/slide_001'
    response = client.patch(base, json={'expected_revision': 0, 'operations': [{'op': 'add', 'item': item}]})
    assert response.status_code == 200, response.text
    aid = response.json()['items'][0]['annotation_id']
    directory = run_root / 'slides/slide_001'
    (directory / 'voice.mp3').write_bytes(b'current audio')
    tokens = [{'beat_id': item['anchor']['beat_id'], 'range': [i, i+1], 'text': SPOKEN[i],
               'start': 1 + (i-5)*.1, 'end': 1.09 + (i-5)*.1,
               'source': 'provider_word', 'precision': 'character'} for i in range(5, 10)]
    write_json_atomic(directory / 'word_alignment.json', {
        'tokens': tokens, 'audio_hash': hashlib.sha256(b'current audio').hexdigest(),
        'narration_hash': hashlib.sha256((directory / 'narration_beats.json').read_bytes()).hexdigest()})
    cue = client.get(base).json()['audio_locator'][aid]
    assert cue['start'] == 1 and cue['range'] == [5, 10]
    assert ''.join(t['text'] for t in cue['characters']) == item['anchor']['quote']
    (directory / 'voice.mp3').write_bytes(b'replaced audio')
    assert client.get(base).json()['audio_locator'] == {}
    (directory / 'voice.mp3').write_bytes(b'current audio')
    (directory / 'narration_beats.json').write_text('{"beats": []}', encoding='utf-8')
    assert client.get(base).json()['audio_locator'] == {}


def test_unknown_slide_404(client, project):
    project_id, _ = project
    assert client.get(f"/api/projects/{project_id}/annotations/slides/slide_999").status_code == 404


# ---------------------------------------------------------------- 设置


def test_settings_revision_conflict(client, project):
    project_id, _ = project
    resp = client.put(
        f"/api/projects/{project_id}/annotations/settings",
        json={"expected_revision": 5, "enabled": True},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["current_revision"] == 0


def test_settings_update_creates_and_bumps(client, project):
    project_id, _ = project
    resp = client.put(
        f"/api/projects/{project_id}/annotations/settings",
        json={"expected_revision": 0, "enabled": True},
    )
    assert resp.status_code == 200 and resp.json()["revision"] == 1
    resp = client.put(
        f"/api/projects/{project_id}/annotations/settings",
        json={"expected_revision": 1, "enabled": False, "defaults": {"color": "#123456"}},
    )
    assert resp.status_code == 200 and resp.json()["revision"] == 2
    assert resp.json()["defaults"]["color"] == "#123456"
    summary = client.get(f"/api/projects/{project_id}/annotations").json()
    assert summary["settings"]["revision"] == 2 and summary["settings"]["enabled"] is False


# ---------------------------------------------------------------- 条目编辑


def test_add_region_and_text_items_assign_ids_and_server_inputs(client, project):
    project_id, run_root = project
    resp = client.patch(
        f"/api/projects/{project_id}/annotations/slides/slide_001",
        json={"expected_revision": 0, "operations": [{"op": "add", "item": REGION_ITEM}]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["revision"] == 1
    item = body["items"][0]
    assert item["annotation_id"] == "ann_001"
    assert item["protection"]["source"] == "manual"
    assert item["inputs"]["image_hash"] == hashlib.sha256(b"\x89PNG-fake-bytes").hexdigest()
    assert item["status"]["content"] == "draft"

    resp = client.patch(
        f"/api/projects/{project_id}/annotations/slides/slide_001",
        json={"expected_revision": 1, "operations": [{"op": "add", "item": TEXT_ITEM}]},
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 2 and items[1]["annotation_id"] == "ann_002"
    assert items[1]["anchor"]["quote"] == "9月30日"


def test_manual_freehand_is_persisted_and_returned_as_renderable_stroke(client, project):
    project_id, _run_root = project
    manual = json.loads(json.dumps(REGION_ITEM))
    manual["target"]["path_points"] = [[120, 210], [170, 230], [240, 220], [330, 250]]
    manual["timing"] = {
        "trigger_mode": "manual", "manual_start_sec": 0, "offset_sec": 0,
        "draw_duration_sec": 0.6, "hold_mode": "slide_end", "exit_duration_sec": 0.15,
    }
    response = client.patch(
        f"/api/projects/{project_id}/annotations/slides/slide_001",
        json={"expected_revision": 0, "operations": [{"op": "add", "item": manual}]},
    )
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["target"]["path_points"] == manual["target"]["path_points"]
    assert item["strokes"][0]["points"] == manual["target"]["path_points"]
    assert item["strokes"][0]["closed"] is False


def test_manual_freehand_uses_portrait_project_canvas(client, project):
    project_id, run_root = project
    db = SessionLocal()
    db.query(Project).filter(Project.id == project_id).update({"canvas_profile": "portrait_9_16"})
    db.commit()
    db.close()

    manual = json.loads(json.dumps(REGION_ITEM))
    manual["target"]["polygons"] = [[[460, 1660], [620, 1660], [620, 1810], [460, 1810]]]
    manual["target"]["path_points"] = [[480, 1680], [530, 1740], [600, 1790]]
    manual["timing"] = {
        "trigger_mode": "manual", "manual_start_sec": 0, "offset_sec": 0,
        "draw_duration_sec": 0.6, "hold_mode": "slide_end", "exit_duration_sec": 0.15,
    }
    response = client.patch(
        f"/api/projects/{project_id}/annotations/slides/slide_001",
        json={"expected_revision": 0, "operations": [{"op": "add", "item": manual}]},
    )
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["target"]["path_points"] == manual["target"]["path_points"]

    slide_root = run_root / "slides" / "slide_001"
    (slide_root / "audio_timeline.json").write_text(json.dumps({
        "duration_sec": 1.0,
        "audio_content_duration_sec": 1.0,
        "segments": [{"beat_id": "slide_001_beat_001", "start": 0.0, "end": 0.9}],
    }), encoding="utf-8")
    settings = client.put(
        f"/api/projects/{project_id}/annotations/settings",
        json={"expected_revision": 0, "enabled": True},
    )
    assert settings.status_code == 200, settings.text
    confirmation = client.post(
        f"/api/projects/{project_id}/annotations/slides/slide_001/confirm",
        json={"expected_revision": 1},
    )
    assert confirmation.status_code == 200, confirmation.text
    assert confirmation.json()["timeline_built"] is True

    timeline = json.loads((slide_root / "annotation_timeline.json").read_text(encoding="utf-8"))
    event = timeline["events"][0]
    assert timeline["canvas"] == [1080, 1920]
    assert event["strokes"][0]["points"] == manual["target"]["path_points"]
    assert event["strokes"][0]["ink"]["canvas"] == [1080, 1920]


def test_add_text_with_bad_quote_rejected(client, project):
    project_id, _ = project
    bad = json.loads(json.dumps(TEXT_ITEM, ensure_ascii=False))
    bad["anchor"]["quote"] = "十月一日"
    resp = client.patch(
        f"/api/projects/{project_id}/annotations/slides/slide_001",
        json={"expected_revision": 0, "operations": [{"op": "add", "item": bad}]},
    )
    assert resp.status_code == 422
    issues = resp.json()["detail"]["issues"]
    assert any(issue["code"] == "quote_mismatch" for issue in issues)


def test_add_text_with_unknown_beat_rejected(client, project):
    project_id, _ = project
    bad = json.loads(json.dumps(TEXT_ITEM, ensure_ascii=False))
    bad["anchor"]["beat_id"] = "slide_001_beat_099"
    resp = client.patch(
        f"/api/projects/{project_id}/annotations/slides/slide_001",
        json={"expected_revision": 0, "operations": [{"op": "add", "item": bad}]},
    )
    assert resp.status_code == 422
    assert any(issue["code"] == "unknown_beat" for issue in resp.json()["detail"]["issues"])


def test_page_revision_conflict_returns_409(client, project):
    project_id, _ = project
    resp = client.patch(
        f"/api/projects/{project_id}/annotations/slides/slide_001",
        json={"expected_revision": 3, "operations": [{"op": "add", "item": REGION_ITEM}]},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["current_revision"] == 0


def test_update_maintains_modified_fields(client, project):
    project_id, _ = project
    client.patch(
        f"/api/projects/{project_id}/annotations/slides/slide_001",
        json={"expected_revision": 0, "operations": [{"op": "add", "item": REGION_ITEM}]},
    )
    resp = client.patch(
        f"/api/projects/{project_id}/annotations/slides/slide_001",
        json={
            "expected_revision": 1,
            "operations": [
                {
                    "op": "update",
                    "annotation_id": "ann_001",
                    "patch": {"style": {**REGION_ITEM["style"], "color": "#00AA00"}},
                }
            ],
        },
    )
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["style"]["color"] == "#00AA00"
    assert "style" in item["protection"]["modified_fields"]


def test_cannot_forge_confirmation_or_protection(client, project):
    project_id, _ = project
    client.patch(
        f"/api/projects/{project_id}/annotations/slides/slide_001",
        json={"expected_revision": 0, "operations": [{"op": "add", "item": REGION_ITEM}]},
    )
    resp = client.patch(
        f"/api/projects/{project_id}/annotations/slides/slide_001",
        json={
            "expected_revision": 1,
            "operations": [{"op": "update", "annotation_id": "ann_001", "patch": {"status": {"content": "confirmed"}}}],
        },
    )
    assert resp.status_code == 422
    resp = client.patch(
        f"/api/projects/{project_id}/annotations/slides/slide_001",
        json={
            "expected_revision": 1,
            "operations": [{"op": "update", "annotation_id": "ann_001", "patch": {"protection": {"source": "ai"}}}],
        },
    )
    assert resp.status_code == 422


def test_delete_item(client, project):
    project_id, _ = project
    client.patch(
        f"/api/projects/{project_id}/annotations/slides/slide_001",
        json={"expected_revision": 0, "operations": [{"op": "add", "item": REGION_ITEM}]},
    )
    resp = client.patch(
        f"/api/projects/{project_id}/annotations/slides/slide_001",
        json={"expected_revision": 1, "operations": [{"op": "delete", "annotation_id": "ann_001"}]},
    )
    assert resp.status_code == 200 and resp.json()["items"] == []
    # 删除后文件仍在(revision 3),重开可读
    page = json.loads((project[1] / "slides" / "slide_001" / "annotations.json").read_text(encoding="utf-8"))
    assert page["revision"] == 2 and page["items"] == []


def test_missing_image_blocks_edit(client, project):
    project_id, run_root = project
    (run_root / "slides" / "slide_001" / "visual_draft.png").unlink()
    resp = client.patch(
        f"/api/projects/{project_id}/annotations/slides/slide_001",
        json={"expected_revision": 0, "operations": [{"op": "add", "item": REGION_ITEM}]},
    )
    assert resp.status_code == 422
    assert "图片" in resp.json()["detail"]


def test_corrupt_page_file_is_500_with_diagnostics(client, project):
    project_id, run_root = project
    page_path = run_root / "slides" / "slide_001" / "annotations.json"
    page_path.parent.mkdir(parents=True, exist_ok=True)
    page_path.write_text("{ broken", encoding="utf-8")
    resp = client.get(f"/api/projects/{project_id}/annotations/slides/slide_001")
    assert resp.status_code == 500
    assert "annotations.json" in resp.json()["detail"]


# ---------------------------------------------------------------- 门禁与隔离


def test_readiness_gates_per_handover(client, project):
    project_id, run_root = project
    # enabled + 无任何条目 → 空页是有效的"无标注页",可导出(R2 方案:不伪造标注)
    client.put(f"/api/projects/{project_id}/annotations/settings", json={"expected_revision": 0, "enabled": True})
    body = client.get(f"/api/projects/{project_id}/annotations").json()
    assert body["readiness"] == {"can_render": True, "reason": "", "blocking": []}

    # enabled + 未确认条目 → unconfirmed_items 且逐条列出
    client.patch(
        f"/api/projects/{project_id}/annotations/slides/slide_001",
        json={"expected_revision": 0, "operations": [{"op": "add", "item": MANUAL_REGION_ITEM}]},
    )
    body = client.get(f"/api/projects/{project_id}/annotations").json()
    assert body["readiness"]["can_render"] is False
    assert body["readiness"]["reason"] == "unconfirmed_items"
    assert body["readiness"]["blocking"] == [{"slide_id": "slide_001", "annotation_id": "ann_001", "reason": "unconfirmed"}]

    # 确认后产物齐备 → 可导出
    _make_audio(run_root)
    resp = client.post(f"/api/projects/{project_id}/annotations/slides/slide_001/confirm", json={"expected_revision": 1})
    assert resp.status_code == 200
    body = client.get(f"/api/projects/{project_id}/annotations").json()
    assert body["readiness"]["can_render"] is True, body["readiness"]

    # 音频时间轴变化后,旧时间轴输入过期 → 导出再次被阻塞(annotation_not_ready)
    (run_root / "slides" / "slide_001" / "audio_timeline.json").write_text(
        json.dumps({"slide_id": "slide_001", "audio_content_duration_sec": 9.0,
                    "segments": [{"id": "slide_001_beat_001", "beat_id": "slide_001_beat_001",
                                  "start": 0.0, "end": 5.0}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    body = client.get(f"/api/projects/{project_id}/annotations").json()
    assert body["readiness"]["can_render"] is False
    assert body["readiness"]["reason"] == "annotation_not_ready"

    # 关闭功能 → 恢复可导出,草稿(已确认)保留
    client.put(f"/api/projects/{project_id}/annotations/settings", json={"expected_revision": 1, "enabled": False})
    body = client.get(f"/api/projects/{project_id}/annotations").json()
    assert body["readiness"]["can_render"] is True
    assert body["slides"][0]["counts"]["confirmed"] == 1


def test_account_isolation_other_account_gets_404(client, project):
    other_id, _ = _make_project(account_id="acct_other_" + uuid.uuid4().hex[:8])
    try:
        # 默认账号看不到 other 账号的项目
        assert client.get(f"/api/projects/{other_id}/annotations").status_code == 404
    finally:
        _drop_project(other_id)


def test_account_scope_allows_owner(client, project):
    project_id, _ = project
    account = "acct_owner_" + uuid.uuid4().hex[:8]
    owned_id, _ = _make_project(account_id=account)
    try:
        db = SessionLocal()
        try:
            with account_scope(account):
                summary = get_annotation_service().get_summary(db, owned_id)
            assert summary["settings"]["enabled"] is False
        finally:
            db.close()
    finally:
        _drop_project(owned_id)


# ---------------------------------------------------------------- W4: 确认门禁


def test_confirm_gate_flow(client, project):
    project_id, run_root = project
    base = f"/api/projects/{project_id}/annotations"
    _make_audio(run_root)
    # 添加可确认的手动定时条目
    client.patch(
        f"{base}/slides/slide_001",
        json={"expected_revision": 0, "operations": [{"op": "add", "item": MANUAL_REGION_ITEM}]},
    )
    # 启用勾画
    client.put(f"{base}/settings", json={"expected_revision": 1, "enabled": True})

    # revision 冲突
    resp = client.post(f"{base}/slides/slide_001/confirm", json={"expected_revision": 99})
    assert resp.status_code == 409

    # 正常确认:确认内联完成构建并发布 v2 时间轴
    resp = client.post(f"{base}/slides/slide_001/confirm", json={"expected_revision": 1})
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["confirmed"] == 1
    assert body["timeline_built"] is True
    assert body["readiness"]["can_render"] is True  # 全部确认且产物就绪后可导出
    timeline = json.loads(
        (run_root / "slides" / "slide_001" / "annotation_timeline.json").read_text(encoding="utf-8")
    )
    assert timeline["resolver_version"] == "annotation_timeline_v2"
    assert timeline["events"][0]["strokes"][0]["ink"]["kind"] == "raster"
    # 确认后的条目带构建输入快照
    detail = client.get(f"{base}/slides/slide_001").json()
    item = detail["items"][0]
    assert item["status"]["content"] == "confirmed"
    assert item["status"]["temporal"] == "manual"
    assert item["confirmed_inputs"]["image_hash"] == item["inputs"]["image_hash"]
    assert item["confirmed_inputs"]["build_id"] == timeline["build_id"]

    # 已确认页幂等重确认成功,且不产生新的改动
    resp = client.post(f"{base}/slides/slide_001/confirm", json={"expected_revision": 2})
    assert resp.status_code == 200
    assert resp.json()["revision"] == 2


def test_confirm_requires_explicit_review_acceptance(client, project):
    project_id, run_root = project
    base = f"/api/projects/{project_id}/annotations"
    _make_audio(run_root)
    client.patch(
        f"{base}/slides/slide_001",
        json={"expected_revision": 0, "operations": [{"op": "add", "item": MANUAL_REGION_ITEM}]},
    )
    # 人为把 spatial 置为 needs_review(模拟规划器/换图结果)
    page_path = run_root / "slides" / "slide_001" / "annotations.json"
    page = json.loads(page_path.read_text(encoding="utf-8"))
    page["items"][0]["status"]["spatial"] = "needs_review"
    page_path.write_text(json.dumps(page, ensure_ascii=False), encoding="utf-8")

    # 不带 accepted_review → 422 review_required(复核检查先于构建)
    resp = client.post(f"{base}/slides/slide_001/confirm", json={"expected_revision": 1})
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["code"] == "review_required"
    assert detail["items"][0]["reason"] == "review_required"

    # 显式接受后确认成功
    annotation_id = detail["items"][0]["annotation_id"]
    resp = client.post(
        f"{base}/slides/slide_001/confirm",
        json={"expected_revision": 1, "accepted_review": [annotation_id]},
    )
    assert resp.status_code == 200
    assert resp.json()["confirmed"] == 1


# ---------------------------------------------------------------- R4-004: 确认后编辑


def _manual_item() -> dict:
    item = json.loads(json.dumps(REGION_ITEM))
    item["target"]["path_points"] = [[120, 210], [170, 230], [240, 220], [330, 250]]
    item["timing"] = {
        "trigger_mode": "manual", "manual_start_sec": 0, "offset_sec": 0,
        "draw_duration_sec": 0.6, "hold_mode": "slide_end", "exit_duration_sec": 0.15,
    }
    return item


def _prepare_confirmed_project(client, project):
    """添加手动定时条目并确认,返回 (base, timeline_path, timeline_bytes)。"""
    project_id, run_root = project
    base = f"/api/projects/{project_id}/annotations"
    client.patch(
        f"{base}/slides/slide_001",
        json={"expected_revision": 0, "operations": [{"op": "add", "item": _manual_item()}]},
    )
    (run_root / "slides" / "slide_001" / "audio_timeline.json").write_text(json.dumps({
        "duration_sec": 1.0,
        "audio_content_duration_sec": 1.0,
        "segments": [{"beat_id": "slide_001_beat_001", "start": 0.0, "end": 0.9}],
    }), encoding="utf-8")
    client.put(f"{base}/settings", json={"expected_revision": 0, "enabled": True})
    confirm = client.post(f"{base}/slides/slide_001/confirm", json={"expected_revision": 1})
    assert confirm.status_code == 200 and confirm.json()["timeline_built"] is True, confirm.text
    timeline_path = run_root / "slides" / "slide_001" / "annotation_timeline.json"
    assert timeline_path.is_file()
    return base, timeline_path


def test_editing_confirmed_item_resets_draft_and_invalidates_timeline(client, project):
    base, timeline_path = _prepare_confirmed_project(client, project)
    resp = client.patch(
        f"{base}/slides/slide_001",
        json={
            "expected_revision": 2,
            "operations": [{"op": "update", "annotation_id": "ann_001", "patch": {"style": {"type": "ellipse", "color": "#00AA00", "opacity": 0.85, "width": 5, "padding": 8, "seed": 11}}}],
        },
    )
    assert resp.status_code == 200, resp.text
    item = resp.json()["items"][0]
    assert item["status"]["content"] == "draft"
    assert item["style"]["color"] == "#00AA00"
    assert not timeline_path.is_file()


def test_same_value_save_keeps_confirmed_state(client, project):
    base, timeline_path = _prepare_confirmed_project(client, project)
    resp = client.patch(
        f"{base}/slides/slide_001",
        json={
            "expected_revision": 2,
            "operations": [{"op": "update", "annotation_id": "ann_001", "patch": {"style": {"type": "ellipse", "color": "#F46A38", "opacity": 0.85, "width": 5, "padding": 8, "seed": 11}}}],
        },
    )
    assert resp.status_code == 200, resp.text
    item = resp.json()["items"][0]
    assert item["status"]["content"] == "confirmed"
    assert timeline_path.is_file()


def test_same_value_anchor_save_keeps_confirmed_state(client, project):
    """编辑器 autosave 常携带未变化的 anchor;同值 anchor 不得把已确认
    条目重置为 draft 或删除时间轴(此前 anchor 分支无条件 modified)。"""
    base, timeline_path = _prepare_confirmed_project(client, project)
    # 先给区域条目挂上讲稿锚点(真实变化 → 重置 draft),再确认。
    anchor = json.loads(json.dumps(TEXT_ITEM["anchor"]))
    resp = client.patch(
        f"{base}/slides/slide_001",
        json={"expected_revision": 2, "operations": [
            {"op": "update", "annotation_id": "ann_001", "patch": {"anchor": anchor}}]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["items"][0]["status"]["content"] == "draft"
    confirm = client.post(f"{base}/slides/slide_001/confirm", json={"expected_revision": 3})
    assert confirm.status_code == 200, confirm.text
    revision = confirm.json()["revision"]

    # 同值 anchor 再保存:无修改、无重置、revision 不变。
    resp = client.patch(
        f"{base}/slides/slide_001",
        json={"expected_revision": revision, "operations": [
            {"op": "update", "annotation_id": "ann_001", "patch": {"anchor": json.loads(json.dumps(anchor))}}]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["items"][0]["status"]["content"] == "confirmed"
    assert body["revision"] == revision
    assert timeline_path.is_file()


def test_same_value_status_and_lock_save_is_noop(client, project):
    """同值 status.content / protection.locked 不得造成 revision 自增。"""
    base, _ = _prepare_confirmed_project(client, project)
    # 先降为 draft(真实变化),此后对 draft 条目提交同值 status/lock。
    client.patch(
        f"{base}/slides/slide_001",
        json={"expected_revision": 2, "operations": [
            {"op": "update", "annotation_id": "ann_001", "patch": {"status": {"content": "draft"}}}]},
    )
    revision = client.get(f"{base}/slides/slide_001").json()["revision"]
    resp = client.patch(
        f"{base}/slides/slide_001",
        json={"expected_revision": revision, "operations": [
            {"op": "update", "annotation_id": "ann_001", "patch": {
                "status": {"content": "draft"}, "protection": {"locked": False}}}]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["revision"] == revision, "同值 status/lock 保存必须是无操作"
    assert body["items"][0]["protection"]["modified_fields"] == ["status.content"], (
        "同值保存不得追加 modified_fields(第一次降 draft 的真实变更除外)"
    )


def test_prepare_with_malformed_audio_timeline_returns_422(client, project):
    """audio_timeline.json 结构损坏(缺 segments)必须返回结构化 422,
    而不是让 AlignmentError 穿透成裸 500。"""
    project_id, run_root = project
    base = f"/api/projects/{project_id}/annotations/slides/slide_001"
    _make_audio(run_root)
    client.patch(base, json={"expected_revision": 0, "operations": [{"op": "add", "item": MANUAL_REGION_ITEM}]})
    # 写入损坏的时间轴:存在但缺 segments 数组。
    (run_root / "slides" / "slide_001" / "audio_timeline.json").write_text(
        json.dumps({"slide_id": "slide_001", "duration_sec": 8.0}), encoding="utf-8"
    )
    resp = client.post(base + "/prepare", json={"expected_revision": 1})
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "annotation_prepare_failed"
    assert detail["items"][0]["reason"] == "audio_timeline_invalid"



def test_lock_toggle_does_not_reset_confirmed_item(client, project):
    base, timeline_path = _prepare_confirmed_project(client, project)
    resp = client.patch(
        f"{base}/slides/slide_001",
        json={
            "expected_revision": 2,
            "operations": [{"op": "update", "annotation_id": "ann_001", "patch": {"protection": {"locked": True}}}],
        },
    )
    assert resp.status_code == 200, resp.text
    item = resp.json()["items"][0]
    assert item["protection"]["locked"] is True
    assert item["status"]["content"] == "confirmed"
    assert timeline_path.is_file()


def test_deleting_confirmed_item_invalidates_timeline(client, project):
    """R4-004(B2): 删除已确认条目同样删除派生 timeline,被删笔迹不得进视频。"""
    project_id, run_root = project
    base = f"/api/projects/{project_id}/annotations"
    base_resp, timeline_path = _prepare_confirmed_project(client, project)
    resp = client.patch(
        f"{base}/slides/slide_001",
        json={
            "expected_revision": 2,
            "operations": [{"op": "delete", "annotation_id": "ann_001"}],
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["items"] == []
    assert not timeline_path.is_file()


def test_failed_prepare_does_not_confirm_draft(client, project):
    project_id, run_root = project
    base = f"/api/projects/{project_id}/annotations/slides/slide_001"
    client.patch(base, json={"expected_revision":0,"operations":[{"op":"add","item":MANUAL_REGION_ITEM}]})
    response = client.post(base+"/confirm",json={"expected_revision":1})
    assert response.status_code == 422
    assert client.get(base).json()["items"][0]["status"]["content"] == "draft"
    assert not (run_root/"slides"/"slide_001"/"annotation_timeline.json").exists()


def test_prepared_build_assets_and_stale_audio_rejected(client, project):
    from PIL import Image
    import io
    project_id, run_root = project
    base = f"/api/projects/{project_id}/annotations/slides/slide_001"
    _make_audio(run_root)
    client.patch(base,json={"expected_revision":0,"operations":[{"op":"add","item":MANUAL_REGION_ITEM}]})
    prepared = client.post(base+"/prepare",json={"expected_revision":1})
    assert prepared.status_code == 200, prepared.json()
    build_id = prepared.json()["build_id"]
    ink_url = f"{base}/ink/{build_id}/ann_001/0/0"
    frame = client.get(ink_url)
    assert frame.status_code == 200
    assert Image.open(io.BytesIO(frame.content)).getchannel("A").getbbox() is None
    assert client.get(base+"/scene-asset",params={"asset":"../narration_beats.json"}).status_code == 404
    assert client.get(ink_url.replace(build_id,"wrong")).status_code == 404
    assert client.get(base).json()["revision"] == 1
    (run_root/"slides"/"slide_001"/"voice.mp3").write_bytes(b"replacement audio")
    response = client.post(base+"/confirm",json={"expected_revision":1,"prepared_build_id":build_id})
    assert response.status_code == 409
    assert client.get(base).json()["items"][0]["status"]["content"] == "draft"


def test_formal_export_loader_accepts_confirmed_and_blocks_missing_ink(client, project):
    from scripts.build_remotion_props import _load_annotation_timeline_for_render, BuildError
    project_id, run_root = project
    base = f"/api/projects/{project_id}/annotations"
    directory = run_root / "slides" / "slide_001"
    client.put(base+"/settings",json={"expected_revision":0,"enabled":True})
    assert _load_annotation_timeline_for_render(directory,"slide_001") is None
    _make_audio(run_root)
    client.patch(base+"/slides/slide_001",json={"expected_revision":0,"operations":[{"op":"add","item":MANUAL_REGION_ITEM}]})
    response=client.post(base+"/slides/slide_001/confirm",json={"expected_revision":1})
    assert response.status_code == 200, response.json()
    timeline=_load_annotation_timeline_for_render(directory,"slide_001")
    stroke=timeline["events"][0]["strokes"][0]
    (directory/"annotation_ink"/"ann_001"/stroke["ink"]["dir"]/"frame_001.png").unlink()
    with pytest.raises(BuildError,match="ink_asset_missing"):
        _load_annotation_timeline_for_render(directory,"slide_001")


def test_audio_regeneration_requires_manual_recalibration_before_prepare(client, project):
    from annotation_invalidation import invalidate_for_audio_change
    from types import SimpleNamespace
    project_id, run_root = project
    base = f"/api/projects/{project_id}/annotations/slides/slide_001"
    _make_audio(run_root)
    response = client.patch(base,json={"expected_revision":0,"operations":[{"op":"add","item":MANUAL_REGION_ITEM}]})
    assert response.status_code == 200
    invalidate_for_audio_change(SimpleNamespace(run_dir=run_root), "slide_001")
    page = client.get(base).json()
    assert page["items"][0]["timing"]["calibration_stale"] is True
    original_start = page["items"][0]["timing"]["manual_start_sec"]
    response = client.post(base+"/prepare",json={"expected_revision":page["revision"]})
    assert response.status_code == 422
    assert "manual_calibration_stale" in response.text
    timing = {**page["items"][0]["timing"], "draw_duration_sec":0.8}
    timing.pop("calibration_stale")  # Legacy clients must not clear the marker by omission.
    response = client.patch(base,json={"expected_revision":page["revision"],"operations":[
        {"op":"update","annotation_id":"ann_001","patch":{"timing":timing}}]})
    assert response.status_code == 200, response.text
    page = response.json()
    assert page["items"][0]["timing"]["manual_start_sec"] == original_start
    assert page["items"][0]["timing"]["calibration_stale"] is True
    timing["calibration_stale"] = False
    response = client.patch(base,json={"expected_revision":page["revision"],"operations":[
        {"op":"update","annotation_id":"ann_001","patch":{"timing":timing}}]})
    assert response.status_code == 200, response.text
    response = client.post(base+"/prepare",json={"expected_revision":response.json()["revision"]})
    assert response.status_code == 200, response.text
