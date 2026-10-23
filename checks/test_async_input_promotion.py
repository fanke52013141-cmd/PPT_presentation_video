"""Old asynchronous media results never replace current source artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from artifact_fingerprint import sha256_file
from digital_human_impact import mark_presenter_audio_stale
import tts_service


def test_staged_tts_result_keeps_old_audio_after_narration_edit(tmp_path: Path, monkeypatch) -> None:
    slide = tmp_path / "slides" / "slide_001"
    slide.mkdir(parents=True)
    text = slide / "tts_text.txt"
    text.write_text("original", encoding="utf-8")
    live = {key: str(slide / name) for key, name in (
        ("audio", "voice.mp3"), ("metadata", "tts_metadata.json"),
        ("srt", "subtitles.srt"), ("timeline", "audio_timeline.json"),
    )}
    stage = tmp_path / "stage"
    stage.mkdir()
    staged = {key: str(stage / Path(path).name) for key, path in live.items()}
    for key in live:
        Path(live[key]).write_text("old", encoding="utf-8")
        Path(staged[key]).write_text("new", encoding="utf-8")
    originals = stage / "before_silence_compression"
    originals.mkdir()
    (originals / "voice.mp3").write_bytes(b"uncut provider audio")
    monkeypatch.setattr(tts_service, "_load_beats_by_slide", lambda *_args: {"slide_001": []})
    monkeypatch.setattr(tts_service, "current_tts_cache_key", lambda _project: {})
    version = tts_service._tts_job_input_version("slide_001", str(text), [], {})
    job = {"slide_id": "slide_001", "paths": {**live, "text": str(text)},
           "stage_paths": staged, "input_version": version}
    text.write_text("edited", encoding="utf-8")
    assert tts_service._promote_staged_tts_outputs(
        job, SimpleNamespace(run_dir=str(tmp_path)), SimpleNamespace(refresh=lambda _p: None),
    ) is False
    assert Path(live["audio"]).read_text(encoding="utf-8") == "old"
    assert not (tmp_path / "recovery").exists()


def test_staged_tts_result_promotes_matching_inputs_and_archives_old_audio(tmp_path: Path, monkeypatch) -> None:
    slide = tmp_path / "slides" / "slide_001"
    slide.mkdir(parents=True)
    text = slide / "tts_text.txt"
    text.write_text("stable", encoding="utf-8")
    live = {key: str(slide / name) for key, name in (
        ("audio", "voice.mp3"), ("metadata", "tts_metadata.json"),
        ("srt", "subtitles.srt"), ("timeline", "audio_timeline.json"),
    )}
    stage = tmp_path / "stage"
    stage.mkdir()
    staged = {key: str(stage / Path(path).name) for key, path in live.items()}
    for key in live:
        Path(live[key]).write_text("old", encoding="utf-8")
        Path(staged[key]).write_text("new", encoding="utf-8")
    originals = stage / "before_silence_compression"
    originals.mkdir()
    (originals / "voice.mp3").write_bytes(b"uncut provider audio")
    monkeypatch.setattr(tts_service, "_load_beats_by_slide", lambda *_args: {"slide_001": []})
    monkeypatch.setattr(tts_service, "current_tts_cache_key", lambda _project: {})
    job = {"slide_id": "slide_001", "paths": {**live, "text": str(text)},
           "stage_paths": staged,
           "input_version": tts_service._tts_job_input_version("slide_001", str(text), [], {})}
    assert tts_service._promote_staged_tts_outputs(
        job, SimpleNamespace(run_dir=str(tmp_path)), SimpleNamespace(refresh=lambda _p: None),
    ) is True
    assert Path(live["audio"]).read_text(encoding="utf-8") == "new"
    backups = list((tmp_path / "recovery" / "audio").glob("slide_001-*/voice.mp3"))
    assert len(backups) == 1 and backups[0].read_text(encoding="utf-8") == "old"
    assert (backups[0].parent / "before_silence_compression" / "voice.mp3").read_bytes() == b"uncut provider audio"


def test_audio_edit_marks_only_dependent_presenter_media_stale(tmp_path: Path) -> None:
    slide = tmp_path / "slides" / "slide_001"
    slide.mkdir(parents=True)
    audio = slide / "voice.mp3"
    audio.write_bytes(b"new audio")
    config_path = tmp_path / "planning" / "digital_human.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps({"slides": {
        "slide_001": {"job_id": "one", "status": "done", "audio_sha256": "old"},
        "slide_002": {"job_id": "two", "status": "done", "audio_sha256": "old"},
        "full": {"job_id": "full", "status": "done", "audio_sha256": "old"},
    }}), encoding="utf-8")
    assert mark_presenter_audio_stale(tmp_path, ("slide_001",)) == ("slide_001", "full")
    saved = json.loads(config_path.read_text(encoding="utf-8"))["slides"]
    assert saved["slide_001"]["status"] == "stale_audio"
    assert saved["slide_002"]["status"] == "done"
    assert saved["full"]["status"] == "stale_audio"
    assert sha256_file(audio) != "old"


def test_multi_page_promotion_does_not_truncate_shared_beats_file(
    tmp_path: Path, monkeypatch,
) -> None:
    """多页 TTS 逐页提升时，第一页的完成校验不得截断共享 beats 文件。

    截断会让第二页在校验时从契约重建原始 beats，与提交时的已处理文本
    不一致而被误判"合成期间旁白已变化"，丢弃已合成音频（2026-10-06 事故）。
    """
    import narration_audio_service as narration_audio

    planning = tmp_path / "planning"
    planning.mkdir(parents=True)
    processed = {
        "slide_001": [{"id": "b1", "tts_text": "已处理旁白一"}],
        "slide_002": [{"id": "b2", "tts_text": "已处理旁白二"}],
    }
    (planning / "narration_beats.json").write_text(json.dumps(
        {"slides": [
            {"slide_id": "slide_001", "beats": processed["slide_001"]},
            {"slide_id": "slide_002", "beats": processed["slide_002"]},
        ]}, ensure_ascii=False), encoding="utf-8")
    (planning / "visual_contract.json").write_text(json.dumps({"slides": [
        {"slide_id": "slide_001",
         "narration_beats": [{"id": "b1", "tts_text": "原始旁白一"}]},
        {"slide_id": "slide_002",
         "narration_beats": [{"id": "b2", "tts_text": "原始旁白二"}]},
    ]}, ensure_ascii=False), encoding="utf-8")

    def _read_json_file(path: str, fallback: object = None) -> object:
        source = Path(path)
        if not source.exists():
            return {} if fallback is None else fallback
        return json.loads(source.read_text(encoding="utf-8"))

    def _read_contract_slide_ids(run_dir: str) -> list:
        contract = _read_json_file(
            str(Path(run_dir) / "planning" / "visual_contract.json"))
        return [slide["slide_id"] for slide in contract.get("slides", [])]

    def _dedupe(beats: object) -> list:
        result, seen = [], set()
        for beat in beats if isinstance(beats, list) else []:
            beat_id = str(beat.get("id") or "").strip()
            if beat_id and beat_id in seen:
                continue
            if beat_id:
                seen.add(beat_id)
            result.append(dict(beat))
        return result

    monkeypatch.setattr(
        narration_audio, "_dependencies",
        narration_audio.NarrationAudioDependencies(
            dedupe_narration_beats=_dedupe,
            probe_media_duration_sec=lambda *_args, **_kwargs: None,
            read_contract_slide_ids=_read_contract_slide_ids,
            read_json_file=_read_json_file,
            write_json_atomic=lambda path, value: Path(path).write_text(
                json.dumps(value, ensure_ascii=False, indent=2),
                encoding="utf-8"),
            repo_root=tmp_path,
        ),
    )
    monkeypatch.setattr(
        tts_service, "sync_narration_beats_to_contract",
        narration_audio.sync_narration_beats_to_contract,
    )
    monkeypatch.setattr(tts_service, "current_tts_cache_key", lambda _project: {})

    project = SimpleNamespace(run_dir=str(tmp_path))
    db = SimpleNamespace(refresh=lambda _p: None)
    beats_by_slide = tts_service._load_beats_by_slide(
        project, ["slide_001", "slide_002"], "test setup")
    jobs = []
    for slide_id in ("slide_001", "slide_002"):
        slide = tmp_path / "slides" / slide_id
        slide.mkdir(parents=True)
        text = slide / "tts_text.txt"
        text.write_text(f"{slide_id} text", encoding="utf-8")
        live = {key: str(slide / name) for key, name in (
            ("audio", "voice.mp3"), ("metadata", "tts_metadata.json"),
            ("srt", "subtitles.srt"), ("timeline", "audio_timeline.json"),
        )}
        stage = tmp_path / "stage" / slide_id
        stage.mkdir(parents=True)
        staged = {key: str(stage / Path(path).name) for key, path in live.items()}
        for key in live:
            Path(live[key]).write_text("old", encoding="utf-8")
            Path(staged[key]).write_text("new", encoding="utf-8")
        jobs.append({
            "slide_id": slide_id,
            "paths": {**live, "text": str(text)},
            "stage_paths": staged,
            "input_version": tts_service._tts_job_input_version(
                slide_id, str(text), beats_by_slide[slide_id], {},
            ),
        })

    assert tts_service._promote_staged_tts_outputs(jobs[0], project, db) is True
    saved = json.loads(
        (planning / "narration_beats.json").read_text(encoding="utf-8"))
    assert [slide["slide_id"] for slide in saved["slides"]] == [
        "slide_001", "slide_002"]
    assert tts_service._promote_staged_tts_outputs(jobs[1], project, db) is True
    assert Path(jobs[1]["paths"]["audio"]).read_text(encoding="utf-8") == "new"
