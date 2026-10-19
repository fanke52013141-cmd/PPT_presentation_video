import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.validate_run import (  # noqa: E402
    StageError,
    production_allowed_image_providers,
    validate_image_provenance,
)
from visual_provenance import (  # noqa: E402
    LEGACY_CONTRACT_HASH_SCHEMA_VERSION,
    PROVENANCE_SCHEMA_VERSION,
    promote_candidate_provenance,
    render_allowed_providers,
    refresh_provenance_contract_hashes,
    visual_provenance_status,
    write_visual_provenance,
)


def _contract(run_dir: Path, slides: list[dict]) -> Path:
    path = run_dir / "planning" / "visual_contract.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": "visual_contract_v1",
                "slides": slides,
            }
        ),
        encoding="utf-8",
    )
    return path


def _provenance_run(tmp: Path, slides: list[dict]) -> tuple[Path, Path]:
    contract_path = _contract(tmp, slides)
    for slide in slides:
        slide_id = str(slide["slide_id"])
        image = tmp / "slides" / slide_id / "visual_draft.png"
        image.parent.mkdir(parents=True, exist_ok=True)
        image.write_bytes(slide_id.encode("utf-8"))
        write_visual_provenance(
            tmp,
            slide_id,
            image_path=image,
            provider="manual_upload",
            source_type="local_upload",
            source_bytes=image.read_bytes(),
        )
    return tmp, contract_path


def test_generated_provenance_is_verifiable_and_promotable() -> None:
    with tempfile.TemporaryDirectory() as value:
        run_dir = Path(value)
        _contract(run_dir, [{"slide_id": "slide_001"}])
        slide_dir = run_dir / "slides" / "slide_001"
        slide_dir.mkdir(parents=True)
        candidate = slide_dir / "visual_candidate.png"
        candidate.write_bytes(b"candidate-image")
        write_visual_provenance(
            run_dir,
            "slide_001",
            image_path=candidate,
            provider="openai_compatible",
            source_type="api_generation",
            model="gpt-image-1",
            prompt="prompt",
            source_bytes=b"provider-response",
            candidate=True,
        )

        final_image = slide_dir / "visual_draft.png"
        candidate.replace(final_image)
        promoted = promote_candidate_provenance(run_dir, "slide_001")
        assert promoted and promoted["copied_to"].endswith("visual_draft.png")
        validate_image_provenance(slide_dir, {"openai_compatible"})

        final_image.write_bytes(b"tampered-image")
        with pytest.raises(StageError, match="output hash"):
            validate_image_provenance(slide_dir, {"openai_compatible"})


def test_order_only_change_can_refresh_contract_hash_without_fabricating_output() -> None:
    with tempfile.TemporaryDirectory() as value:
        run_dir = Path(value)
        contract_path = _contract(run_dir, [{"slide_id": "a"}, {"slide_id": "b"}])
        for slide_id in ("a", "b"):
            image = run_dir / "slides" / slide_id / "visual_draft.png"
            image.parent.mkdir(parents=True)
            image.write_bytes(slide_id.encode("utf-8"))
            write_visual_provenance(
                run_dir,
                slide_id,
                image_path=image,
                provider="manual_upload",
                source_type="local_upload",
                source_bytes=image.read_bytes(),
            )
        contract_path.write_text(
            json.dumps({"version": "visual_contract_v1", "slides": [{"slide_id": "b"}, {"slide_id": "a"}]}),
            encoding="utf-8",
        )
        assert refresh_provenance_contract_hashes(run_dir, ["b", "a"]) == 2
        for slide_id in ("a", "b"):
            validate_image_provenance(run_dir / "slides" / slide_id, {"manual_upload"})


def test_production_provider_policy_is_configurable() -> None:
    with patch.dict(os.environ, {"PPT_STUDIO_PRODUCTION_IMAGE_PROVIDERS": "codex_image_gen,manual_upload"}):
        assert production_allowed_image_providers() == ("codex_image_gen", "manual_upload")
    assert "codex2api" in render_allowed_providers()
    assert "toapis" in render_allowed_providers()
    assert "toapis" in production_allowed_image_providers()

    source = (
        ROOT / "image_workflow_service.py"
    ).read_text(encoding="utf-8")
    assert "write_visual_provenance(" in source
    assert "project_generate_prompt_for_slide(" in source


def test_toapis_generated_image_is_accepted_by_confirmation_policy() -> None:
    with tempfile.TemporaryDirectory() as value:
        run_dir = Path(value)
        _contract(run_dir, [{"slide_id": "slide_001"}])
        image = run_dir / "slides" / "slide_001" / "visual_draft.png"
        image.parent.mkdir(parents=True)
        image.write_bytes(b"toapis-image")
        write_visual_provenance(
            run_dir,
            "slide_001",
            image_path=image,
            provider="toapis",
            source_type="api_generation",
            model="gpt-image-2-vip",
            prompt="prompt",
            source_bytes=b"provider-response",
        )

        assert visual_provenance_status(run_dir, "slide_001") == {
            "valid": True,
            "reason": "valid",
            "slide_id": "slide_001",
            "provider": "toapis",
        }


def test_editing_one_slide_does_not_invalidate_other_slides(tmp_path: Path) -> None:
    slides = [
        {"slide_id": "a", "narration": "第一页"},
        {"slide_id": "b", "narration": "第二页"},
    ]
    run_dir, contract_path = _provenance_run(tmp_path, slides)
    assert visual_provenance_status(run_dir, "a")["valid"] is True

    edited = [dict(slides[0]), {"slide_id": "b", "narration": "改过的第二页"}]
    contract_path.write_text(
        json.dumps({"version": "visual_contract_v1", "slides": edited}),
        encoding="utf-8",
    )
    # Only slide b's entry changed; slide a keeps its approved image.
    assert visual_provenance_status(run_dir, "a")["valid"] is True
    status_b = visual_provenance_status(run_dir, "b")
    assert status_b["valid"] is False
    assert status_b["reason"] == "contract_hash_changed"
    with pytest.raises(StageError, match="contract slide entry hash"):
        validate_image_provenance(run_dir / "slides" / "b", {"manual_upload"})
    validate_image_provenance(run_dir / "slides" / "a", {"manual_upload"})


def test_pure_reorder_keeps_v3_provenance_valid(tmp_path: Path) -> None:
    slides = [{"slide_id": "a"}, {"slide_id": "b"}]
    run_dir, contract_path = _provenance_run(tmp_path, slides)
    contract_path.write_text(
        json.dumps({"version": "visual_contract_v1", "slides": [dict(slides[1]), dict(slides[0])]}),
        encoding="utf-8",
    )
    assert visual_provenance_status(run_dir, "a")["valid"] is True
    assert visual_provenance_status(run_dir, "b")["valid"] is True
    assert refresh_provenance_contract_hashes(run_dir, ["b", "a"]) == 2


def test_refresh_cannot_launder_a_real_slide_edit(tmp_path: Path) -> None:
    slides = [{"slide_id": "a", "narration": "原旁白"}, {"slide_id": "b"}]
    run_dir, contract_path = _provenance_run(tmp_path, slides)
    edited = [{"slide_id": "a", "narration": "被改掉的旁白"}, {"slide_id": "b"}]
    contract_path.write_text(
        json.dumps({"version": "visual_contract_v1", "slides": edited}),
        encoding="utf-8",
    )
    # b's entry is untouched and may be refreshed; a's real edit must survive.
    assert refresh_provenance_contract_hashes(run_dir, ["a", "b"]) == 1
    assert visual_provenance_status(run_dir, "a")["valid"] is False
    assert visual_provenance_status(run_dir, "b")["valid"] is True


def test_narration_only_beat_edit_keeps_provenance_valid(tmp_path: Path) -> None:
    """CR-2: 讲稿文本(beat spoken_text)编辑不得使已批准图片失效。

    新写入的 provenance 存视觉投影哈希;投影与失效分类器同一口径。
    """
    slides = [{
        "slide_id": "a",
        "narration_beats": [
            {"beat_id": "b1", "spoken_text": "原始讲稿", "group": "g1"},
        ],
    }]
    run_dir, contract_path = _provenance_run(tmp_path, slides)
    assert visual_provenance_status(run_dir, "a")["valid"] is True

    edited = [{
        "slide_id": "a",
        "narration_beats": [
            {"beat_id": "b1", "spoken_text": "改后的讲稿", "group": "g1"},
        ],
    }]
    contract_path.write_text(
        json.dumps({"version": "visual_contract_v1", "slides": edited}),
        encoding="utf-8",
    )
    status = visual_provenance_status(run_dir, "a")
    assert status["valid"] is True, status


def test_visual_anchor_edit_still_invalidates_provenance(tmp_path: Path) -> None:
    """语块-画面映射(group/anchor)属于视觉输入,变化必须失效 provenance。"""
    slides = [{
        "slide_id": "a",
        "narration_beats": [
            {"beat_id": "b1", "spoken_text": "讲稿", "group": "g1"},
        ],
    }]
    run_dir, contract_path = _provenance_run(tmp_path, slides)
    edited = [{
        "slide_id": "a",
        "narration_beats": [
            {"beat_id": "b1", "spoken_text": "讲稿", "group": "g2"},
        ],
    }]
    contract_path.write_text(
        json.dumps({"version": "visual_contract_v1", "slides": edited}),
        encoding="utf-8",
    )
    status = visual_provenance_status(run_dir, "a")
    assert status["valid"] is False
    assert status["reason"] == "contract_hash_changed"


def test_narration_only_migration_refreshes_legacy_payload(tmp_path: Path) -> None:
    """CR-2 迁移:旧口径(整条目哈希)payload 在 narration-only 编辑后,
    三重证据齐全时迁移到视觉投影,渲染门恢复有效;视觉编辑永远洗不白。"""
    from visual_provenance import refresh_provenance_for_narration_only_changes

    slides = [{
        "slide_id": "a",
        "narration_beats": [{"beat_id": "b1", "spoken_text": "原始讲稿", "group": "g1"}],
    }, {
        "slide_id": "c",
        "narration_beats": [{"beat_id": "b1", "spoken_text": "原稿", "group": "g1"}],
    }]
    run_dir, contract_path = _provenance_run(tmp_path, slides)
    # 把 slide a 的 payload 降级为旧口径整条目哈希,模拟历史项目。
    from visual_provenance import slide_entry_hashes, visual_slide_entry_hashes
    old_hash = slide_entry_hashes(slides)["a"]
    path_a = run_dir / "slides" / "a" / "visual_provenance.json"
    payload_a = json.loads(path_a.read_text(encoding="utf-8"))
    payload_a["contract_slide_sha256"] = old_hash
    path_a.write_text(json.dumps(payload_a, ensure_ascii=False), encoding="utf-8")

    # narration-only 编辑 a;c 保持不变。
    edited = [
        {"slide_id": "a", "narration_beats": [{"beat_id": "b1", "spoken_text": "新讲稿", "group": "g1"}]},
        {"slide_id": "c", "narration_beats": [{"beat_id": "b1", "spoken_text": "原稿", "group": "g1"}]},
    ]
    contract_path.write_text(
        json.dumps({"version": "visual_contract_v1", "slides": edited}),
        encoding="utf-8",
    )
    assert visual_provenance_status(run_dir, "a")["valid"] is False

    migrated = refresh_provenance_for_narration_only_changes(
        run_dir, ["a"], previous_contract={"version": "visual_contract_v1", "slides": slides}
    )
    assert migrated == 1
    assert visual_provenance_status(run_dir, "a")["valid"] is True
    # 幂等:迁移后再次调用,旧哈希证据已不匹配,不再改动。
    assert refresh_provenance_for_narration_only_changes(
        run_dir, ["a"], previous_contract={"version": "visual_contract_v1", "slides": slides}
    ) == 0

    # 视觉编辑(group 变化)洗不白:证据 2(投影相同)失败。
    slides_c = [{"slide_id": "c", "narration_beats": [{"beat_id": "b1", "spoken_text": "原稿", "group": "g1"}]}]
    path_c = run_dir / "slides" / "c" / "visual_provenance.json"
    payload_c = json.loads(path_c.read_text(encoding="utf-8"))
    payload_c["contract_slide_sha256"] = slide_entry_hashes(slides_c)["c"]
    path_c.write_text(json.dumps(payload_c, ensure_ascii=False), encoding="utf-8")
    edited_c = [{"slide_id": "c", "narration_beats": [{"beat_id": "b1", "spoken_text": "原稿", "group": "g9"}]}]
    contract_path.write_text(
        json.dumps({"version": "visual_contract_v1", "slides": [{"slide_id": "a", "narration_beats": [{"beat_id": "b1", "spoken_text": "新讲稿", "group": "g1"}]}] + edited_c}),
        encoding="utf-8",
    )
    assert refresh_provenance_for_narration_only_changes(
        run_dir, ["c"], previous_contract={"version": "visual_contract_v1", "slides": slides_c}
    ) == 0
    assert visual_provenance_status(run_dir, "c")["valid"] is False


def test_legacy_v2_payload_refresh_requires_proven_purity(tmp_path: Path) -> None:
    slides = [{"slide_id": "a"}]
    run_dir, contract_path = _provenance_run(tmp_path, slides)
    path = run_dir / "slides" / "a" / "visual_provenance.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["schema_version"] = LEGACY_CONTRACT_HASH_SCHEMA_VERSION
    payload.pop("contract_slide_sha256")
    path.write_text(json.dumps(payload), encoding="utf-8")
    contract_path.write_text(
        json.dumps(
            {
                "version": "visual_contract_v1",
                # Pure topic backfill: the file changes but the slide entry does not.
                "topic": {"title": "新主题"},
                "slides": [{"slide_id": "a"}],
            }
        ),
        encoding="utf-8",
    )
    # Without the previous contract text the change cannot be proven pure.
    assert refresh_provenance_contract_hashes(run_dir, ["a"]) == 0
    assert visual_provenance_status(run_dir, "a")["valid"] is False
    previous_text = json.dumps({"version": "visual_contract_v1", "slides": [{"slide_id": "a"}]})
    assert (
        refresh_provenance_contract_hashes(run_dir, ["a"], previous_contract_text=previous_text)
        == 1
    )
    assert visual_provenance_status(run_dir, "a")["valid"] is True


def test_new_provenance_uses_per_slide_schema(tmp_path: Path) -> None:
    run_dir, _ = _provenance_run(tmp_path, [{"slide_id": "a", "main_title": "标题"}])
    payload = json.loads(
        (run_dir / "slides" / "a" / "visual_provenance.json").read_text(encoding="utf-8")
    )
    assert payload["schema_version"] == PROVENANCE_SCHEMA_VERSION
    assert payload["contract_sha256"] and payload["contract_slide_sha256"]
