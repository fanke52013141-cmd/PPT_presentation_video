"""Provider scripts must persist every field the service audio cache compares.

Regression background: the MiniMax helper wrote ``speed``/``volume``/``pitch``
only into the request payload, never into ``tts_metadata.json``.  The service
cache key contained those fields, so ``_tts_artifact_matches_runtime`` could
never match and every synthesis re-billed the whole project.
"""

import ast
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import generic_tts  # noqa: E402
import tts_service  # noqa: E402

CACHE_KEY_FIELDS = (
    "endpoint",
    "model",
    "voice_id",
    "clone_voice_id",
    "speed",
    "volume",
    "pitch",
)


def _generic_request(args: SimpleNamespace, tmp: Path, extra_request=None) -> dict:
    meta_path = tmp / "tts_metadata.json"
    generic_tts.write_common_outputs(
        args=args,
        provider="unit_test",
        response_json={},
        audio_bytes=b"fake-audio",
        subtitle_text="hello",
        extra_request=extra_request,
    )
    return json.loads(meta_path.read_text(encoding="utf-8"))["request"]


def _fake_args(tmp: Path) -> SimpleNamespace:
    return SimpleNamespace(
        out_audio=str(tmp / "voice.mp3"),
        out_meta=str(tmp / "tts_metadata.json"),
        out_srt=str(tmp / "subtitles.srt"),
        out_timeline=str(tmp / "audio_timeline.json"),
        slide_id="slide_001",
        endpoint="https://tts.example/v1",
        model="model-a",
        voice_id="voice-a",
        clone_voice_id="",
        audio_format="mp3",
        sample_rate=48000,
        speed=1.2,
        volume=1.0,
        pitch="0",
        max_subtitle_chars=18,
        provider_extra='{"appid": "x"}',
        _tts_text="hello",
    )


def test_generic_outputs_persist_every_cache_key_field(tmp_path: Path) -> None:
    args = _fake_args(tmp_path)
    request = _generic_request(args, tmp_path)
    for field in CACHE_KEY_FIELDS:
        assert field in request, f"generic_tts metadata lost {field}"
    assert request["provider_extra"] == args.provider_extra
    assert "reference_audio_signature" in request


def test_comfyui_workflow_hash_reaches_metadata(tmp_path: Path) -> None:
    args = _fake_args(tmp_path)
    request = _generic_request(
        args, tmp_path, extra_request={"workflow_sha256": "abc123"}
    )
    assert request["workflow_sha256"] == "abc123"
    assert tts_service._tts_artifact_matches_runtime(
        {"metadata": str(tmp_path / "tts_metadata.json")},
        {"workflow_sha256": "abc123", "voice_id": "voice-a"},
    )
    assert not tts_service._tts_artifact_matches_runtime(
        {"metadata": str(tmp_path / "tts_metadata.json")},
        {"workflow_sha256": "changed-workflow"},
    )


def test_minimax_metadata_persists_pacing_fields() -> None:
    source = (ROOT / "scripts" / "minimax_tts.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "main":
            continue
        text = ast.get_source_segment(source, node) or ""
        assert '"speed": str(args.speed)' in text
        assert '"volume": str(args.volume)' in text
        assert '"pitch": str(args.pitch)' in text
        break
    else:
        raise AssertionError("minimax_tts.main not found")


def test_service_cache_key_matches_generic_field_names(tmp_path: Path) -> None:
    args = _fake_args(tmp_path)
    request = _generic_request(args, tmp_path)
    base_cache_key = {field: request[field] for field in CACHE_KEY_FIELDS}
    assert tts_service._tts_artifact_matches_runtime(
        {"metadata": str(tmp_path / "tts_metadata.json")}, base_cache_key
    )
    assert not tts_service._tts_artifact_matches_runtime(
        {"metadata": str(tmp_path / "tts_metadata.json")},
        {**base_cache_key, "speed": "1.3"},
    )
