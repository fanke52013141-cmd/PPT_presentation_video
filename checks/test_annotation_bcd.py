import threading
from dataclasses import replace

import pytest

from annotation_build import target_ready_times
from annotation_ink import render_and_write
from checks.test_annotation_ink import _request
from checks.test_annotation_timeline import _item
from scripts.evaluate_annotation_alignment import evaluate


def test_ak_sk_auth_is_signed_and_never_exposes_secret():
    from annotation_ocr_baidu import BaiduOcrEngineConfig, signed_ocr_headers
    config = BaiduOcrEngineConfig(api_key="test-ak", secret_key="private-sk")
    headers = signed_ocr_headers(config, {"Content-Type": "application/x-www-form-urlencoded"},
                                 timestamp="2026-10-06T00:00:00Z")
    assert headers["Authorization"].startswith("bce-auth-v1/test-ak/2026-10-06T00:00:00Z/1800/content-type;host;x-bce-date/")
    assert len(headers["Authorization"].split("/")[-1]) == 64
    assert "private-sk" not in str(headers) + str(config.public_snapshot())
    assert config.public_snapshot()["auth_mode"] == "ak_sk"


def test_arbitrary_tts_rewrite_cannot_claim_original_word_timing():
    from annotation_alignment_worker import normalized_transcript
    text, mapping = normalized_transcript([{"beat_id": "b1", "spoken_text": "增长ABC",
                                           "tts_text": "增长完全不同"}])
    assert "完全不同" in text
    assert all(entry["range"] is None for entry in mapping[2:-1])


def test_unlabelled_benchmark_never_passes():
    result = evaluate([{"sample_id": str(i), "category": "chinese"} for i in range(100)])
    assert not result["passed"] and len(result["unlabelled"]) == 100


def test_independent_truth_rejects_model_and_wrong_audio():
    row = {"sample_id": "1", "category": "chinese", "truth_start_sec": 1,
           "predicted_start_sec": 1.1, "reliable": True, "truth_source": "model"}
    with pytest.raises(ValueError, match="human"):
        evaluate([row])
    with pytest.raises(ValueError, match="hash"):
        evaluate([{**row, "truth_source": "human"}])


def test_benchmark_flags_severe_wrong_reliable_prediction():
    rows = [{"sample_id": str(i), "category": "chinese", "truth_start_sec": 1,
             "predicted_start_sec": 1.05, "reliable": True, "truth_source": "human",
             "audio_sha256": "a", "truth_audio_sha256": "a"} for i in range(100)]
    assert evaluate(rows)["passed"]
    rows[-1]["predicted_start_sec"] = 2
    assert not evaluate(rows)["passed"]


def test_ink_cancel_never_writes_complete_metadata(tmp_path):
    event = threading.Event()
    event.set()
    with pytest.raises(RuntimeError, match="cancelled"):
        render_and_write(_request(texture=False), tmp_path, draw_duration_sec=.6, cancel_event=event)
    assert not (tmp_path / "meta.json").exists()


def test_explicit_group_can_bind_blank_handwritten_region(tmp_path):
    import json
    item = _item()
    item = replace(item, target=replace(item.target, mask_group_ids=("body",)))
    (tmp_path / "scene.json").write_text(json.dumps({"layers": [
        {"id": "body_layer", "target_group_id": "body", "asset": "body.png"},
        {"id": "decoration", "target_group_id": "decor", "asset": "decor.png"}]}))
    (tmp_path / "animation_timeline.json").write_text(json.dumps({"events": [
        {"target": "body_layer", "action": "fade_in", "at": 1, "duration": .4},
        {"target": "decoration", "action": "fade_in", "at": 8, "duration": 1}]}))
    assert target_ready_times(tmp_path, [item], (1920, 1080))[item.annotation_id] == pytest.approx(1.4)
    bad = replace(item, target=replace(item.target, mask_group_ids=("deleted",)))
    assert target_ready_times(tmp_path, [bad], (1920, 1080))[item.annotation_id] is None
