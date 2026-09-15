from pathlib import Path
from types import SimpleNamespace

import comfyui_backend
from scripts import generic_tts


def test_seed_audio_binds_reference_in_references_list(monkeypatch, tmp_path) -> None:
    reference = tmp_path / "reference.mp3"
    reference.write_bytes(b"reference-audio")
    captured = {}

    class FakeResponse:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"audio": "encoded-audio", "duration": 1.0}

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, _url, *, headers, json):
            captured["headers"] = headers
            captured["payload"] = json
            return FakeResponse()

    monkeypatch.setattr(generic_tts.httpx, "Client", lambda **_kwargs: FakeClient())
    monkeypatch.setattr(generic_tts, "probe_audio_duration_sec", lambda _path: 8.5)
    monkeypatch.setattr(generic_tts, "decode_audio_value", lambda *_args, **_kwargs: b"audio")
    monkeypatch.setattr(generic_tts, "write_common_outputs", lambda **kwargs: captured.setdefault("output", kwargs))

    args = SimpleNamespace(
        api_key="secret",
        clone_voice_id=str(reference),
        provider_extra='{"seed_audio_style_instruction":"参考上传的音频作为人物音色。内容如下："}',
        model="seed-audio-1.0",
        audio_format="mp3",
        sample_rate=48000,
        speed=1.0,
        volume=1.0,
        pitch=0,
        timeout=30,
        endpoint="https://openspeech.bytedance.com/api/v3/tts/create",
    )

    generic_tts.synthesize_volcengine_seed_audio(args, "测试旁白", "测试旁白")

    payload = captured["payload"]
    assert "audio_data" not in payload
    assert payload["references"] == [{"audio_data": "cmVmZXJlbmNlLWF1ZGlv"}]
    assert payload["text_prompt"].startswith("@音频1 ")
    assert payload["text_prompt"].count("@音频1") == 1
    assert payload["text_prompt"].endswith("测试旁白")
    assert payload["audio_config"]["format"] == "mp3"
    assert payload["audio_config"]["sample_rate"] == 48000


def test_comfyui_tts_uses_connection_url_and_builtin_workflow(
    monkeypatch,
    tmp_path,
) -> None:
    """A local model connection must drive both the Comfy URL and workflow."""
    reference = tmp_path / "reference.mp3"
    reference.write_bytes(b"reference-audio")
    output = tmp_path / "audio.wav"
    captured = {}

    def fake_run_comfyui_tts(**kwargs):
        captured.update(kwargs)
        Path(kwargs["output_path"]).write_bytes(b"audio")
        return {"prompt_id": "test-prompt"}

    monkeypatch.setenv("PPT_COMFYUI_URL", "http://old-host:8188")
    monkeypatch.setattr(comfyui_backend, "inspect_tts_preflight", lambda _workflow: {"success": True})
    monkeypatch.setattr(comfyui_backend, "run_comfyui_tts", fake_run_comfyui_tts)
    monkeypatch.setattr(generic_tts, "write_common_outputs", lambda **kwargs: captured.setdefault("output", kwargs))

    args = SimpleNamespace(
        endpoint="http://127.0.0.1:8199/",
        clone_voice_id=str(reference),
        out_audio=str(output),
        out_meta=None,
        out_srt=None,
        out_timeline=None,
        slide_id="slide_001",
        timeout=30,
    )

    generic_tts.synthesize_comfyui(args, "测试旁白", "测试旁白")

    assert generic_tts.os.environ["PPT_COMFYUI_URL"] == "http://127.0.0.1:8199"
    assert captured["ref_audio_path"] == reference
    assert captured["workflow_template"]["1"]["class_type"] == "BSAI_IndexTTS2.5Loader"
