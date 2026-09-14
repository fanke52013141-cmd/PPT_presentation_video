from types import SimpleNamespace

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
