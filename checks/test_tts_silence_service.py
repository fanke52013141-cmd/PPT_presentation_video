"""Measured cuts preserve speech, timing, original artifacts and resume behavior."""
import array
import hashlib
import json
import math
from pathlib import Path
import wave

import pytest

import tts_silence_service as silence

ROOT = Path(__file__).resolve().parents[1]


def test_cut_map_keeps_short_gaps_and_translates_each_boundary():
    cuts = silence.silence_cuts(
        "silence_start: 1\nsilence_end: 5\n"
        "silence_start: 6\nsilence_end: 7\n"
        "silence_start: 10", 14, 1000,
    )
    assert cuts == [(2000, 4000), (11000, 13000)]
    seconds = [(start / 1000, end / 1000) for start, end in cuts]
    assert [silence.translate_time(t, seconds) for t in (1, 3, 5, 9, 12, 14)] == [1, 2, 3, 7, 9, 10]


def test_estimated_subtitle_inside_deleted_silence_keeps_text_and_beat():
    segments = [
        {"id": "b1", "text": "前文", "start": 0, "end": 2},
        {"id": "b2", "text": "估算片段", "start": 2, "end": 3},
        {"id": "b3", "text": "后文", "start": 3, "end": 6},
    ]
    silence._retime_segments(segments, [(1, 4)], 3, measured=False)
    assert [s["id"] for s in segments] == ["b1", "b2", "b3"]
    assert segments[1]["text"] == "估算片段"
    assert all(s["end"] > s["start"] >= 0 for s in segments)
    assert all(a["end"] <= b["start"] for a, b in zip(segments, segments[1:]))
    assert segments[-1]["end"] == 3


def test_leading_trailing_and_exact_two_second_silences():
    assert silence.silence_cuts("silence_start: 0\nsilence_end: 3", 6, 1000) == [(1000, 2000)]
    assert silence.silence_cuts("silence_start: 4", 8, 1000) == [(5000, 7000)]
    assert silence.silence_cuts("silence_start: 1\nsilence_end: 3", 5, 1000) == []


def _artifacts(tmp_path, *, long_pause=True, channels=1):
    paths = {key: str(tmp_path / name) for key, name in (
        ("audio", "voice.mp3"), ("timeline", "audio_timeline.json"),
        ("srt", "subtitles.srt"), ("metadata", "tts_metadata.json"),
    )}
    rate = 16000
    parts = [(0.4, True), (3.4 if long_pause else 0.7, False), (0.4, True),
             (0.7, False), (0.4, True)]
    samples = array.array("h")
    for duration, speech in parts:
        for index in range(round(rate * duration)):
            value = round(6000 * math.sin(2 * math.pi * 440 * index / rate)) if speech else 0
            samples.extend([value] * channels)
    with wave.open(paths["audio"], "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(samples.tobytes())
    duration = len(samples) / channels / rate
    gap = parts[1][0]
    segments = [
        {"id": "b1", "beat_id": "b1", "text": "第一句", "start": 0, "end": .4},
        {"id": "b2", "beat_id": "b2", "text": "第二句", "start": .4 + gap, "end": .8 + gap},
        {"id": "b3", "beat_id": "b3", "text": "第三句", "start": 1.5 + gap, "end": duration},
    ]
    timeline = {"timing_source": "provider_sentence_timestamps", "duration_sec": duration + .5,
                "audio_content_duration_sec": duration, "audio_start_sec": .5, "segments": segments,
                "provider_timestamps_audio_hash": silence._sha256(Path(paths["audio"])),
                "provider_timestamps": [{"time_begin": round((.4 + gap) * 1000),
                                         "time_end": round((.8 + gap) * 1000),
                                         "timestamped_words": [{"word": "第二句",
                                            "time_begin": round((.4 + gap) * 1000),
                                            "time_end": round((.8 + gap) * 1000)}]}]}
    Path(paths["timeline"]).write_text(json.dumps(timeline), encoding="utf-8")
    Path(paths["metadata"]).write_text(json.dumps({"request": {"voice_id": "keep-me"}}), encoding="utf-8")
    Path(paths["srt"]).write_text(silence._srt(segments), encoding="utf-8")
    return paths


@pytest.fixture
def ffmpeg():
    binary = silence.resolve_media_tool("ffmpeg", ROOT)
    if not binary:
        pytest.skip("FFmpeg unavailable")
    return binary


@pytest.mark.parametrize("channels", [1, 2])
def test_real_audio_cuts_cap_gap_and_preserve_provider_alignment(tmp_path, ffmpeg, channels):
    paths = _artifacts(tmp_path, channels=channels)
    before = {key: Path(path).read_bytes() for key, path in paths.items()}
    report = silence.compress_staged_tts_silence(paths, repo_root=ROOT)
    assert report["removed_sec"] == pytest.approx(1.4, abs=.01)
    timeline = json.loads(Path(paths["timeline"]).read_text(encoding="utf-8"))
    assert timeline["duration_sec"] == pytest.approx(timeline["audio_content_duration_sec"] + .5)
    assert timeline["segments"][1]["start"] == pytest.approx(2.4, abs=.01)
    assert timeline["segments"][2]["start"] - timeline["segments"][1]["end"] == pytest.approx(.7)
    word = timeline["provider_timestamps"][0]["timestamped_words"][0]
    assert word["time_begin"] == pytest.approx(2400, abs=10)
    assert timeline["provider_timestamps_audio_hash"] == hashlib.sha256(Path(paths["audio"]).read_bytes()).hexdigest()
    assert "00:00:02,400" in Path(paths["srt"]).read_text(encoding="utf-8")
    for key, path in paths.items():
        assert (tmp_path / "before_silence_compression" / Path(path).name).read_bytes() == before[key]
    saved = {key: Path(path).read_bytes() for key, path in paths.items()}
    assert silence.compress_staged_tts_silence(paths, repo_root=ROOT) == report
    assert saved == {key: Path(path).read_bytes() for key, path in paths.items()}
    # Check the decoded output waveform, rather than relying only on metadata.
    result = silence._run([ffmpeg, "-hide_banner", "-i", paths["audio"], "-af",
                           "silencedetect=noise=-50dB:d=2.05", "-f", "null", "-"])
    assert "silence_start:" not in result.stderr


def test_short_gaps_are_byte_for_byte_noop(tmp_path, ffmpeg):
    paths = _artifacts(tmp_path, long_pause=False)
    before = {key: Path(path).read_bytes() for key, path in paths.items()}
    assert silence.compress_staged_tts_silence(paths, repo_root=ROOT)["removed_sec"] == 0
    assert before == {key: Path(path).read_bytes() for key, path in paths.items()}
    assert not (tmp_path / "before_silence_compression").exists()


def test_mp3_input_does_not_revalidate_unverified_provider_words(tmp_path, ffmpeg):
    paths = _artifacts(tmp_path)
    mp3 = tmp_path / "provider.mp3"
    silence._run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", paths["audio"],
                  "-c:a", "libmp3lame", str(mp3)])
    Path(paths["audio"]).write_bytes(mp3.read_bytes())
    # Stored provider timestamp hash belongs to different (pre-encode) bytes.
    report = silence.compress_staged_tts_silence(paths, repo_root=ROOT)
    timeline = json.loads(Path(paths["timeline"]).read_text(encoding="utf-8"))
    assert report["removed_sec"] == pytest.approx(1.4, abs=.03)
    assert "provider_timestamps_audio_hash" not in timeline
    assert silence.compressed_timeline_matches_audio(timeline, Path(paths["audio"]))


def test_failed_encoder_does_not_change_staged_artifacts(tmp_path, monkeypatch, ffmpeg):
    paths = _artifacts(tmp_path)
    before = {key: Path(path).read_bytes() for key, path in paths.items()}
    run = silence._run

    def fail_encode(command):
        if "libmp3lame" in command:
            raise RuntimeError("encoder failed")
        return run(command)

    monkeypatch.setattr(silence, "_run", fail_encode)
    with pytest.raises(RuntimeError, match="encoder failed"):
        silence.compress_staged_tts_silence(paths, repo_root=ROOT)
    assert before == {key: Path(path).read_bytes() for key, path in paths.items()}
