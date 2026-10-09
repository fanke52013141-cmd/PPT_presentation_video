from contextlib import nullcontext
from dataclasses import replace
import base64
import io
from pathlib import Path
from types import SimpleNamespace
import wave

import pytest
from PIL import Image

import model_connection_test_service as probes
from model_connection_service import ResolvedModelConnection, ModelConnectionUnavailableError


@pytest.fixture
def saved(monkeypatch):
    connection = ResolvedModelConnection('saved', 7, 'text', 'openai_compatible',
        'configured-model', 'https://example.test/v1', 'private-ref', {}, 'active')
    monkeypatch.setattr(probes.connections, 'resolve_model_connection', lambda _id: connection)
    monkeypatch.setattr(probes, 'get_credential', lambda ref: {'api_key': 'private-secret'})
    monkeypatch.setattr(probes, 'governed_llm_request', lambda _url: nullcontext())
    return connection


def test_text_calls_saved_model_and_returns_output_and_closes_client(monkeypatch, saved):
    called = {}
    def create(**kwargs):
        called.update(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='收到'))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        close=lambda: called.update(closed=True))
    monkeypatch.setattr(probes.images, 'get_openai_client', lambda **kw: client)
    for _ in range(2):
        result = probes.test_saved_connection(saved.connection_id)
        assert result['success'] and result['text'] == '收到'
        assert result['revision'] == 7
    assert called['model'] == 'configured-model'
    assert called['messages'] == [{'role': 'user', 'content': '两个字回复我'}]
    assert called['closed'] is True


@pytest.mark.parametrize('provider', ['openai_compatible', 'toapis'])
def test_images_use_configured_provider_and_return_decodable_png(monkeypatch, saved, provider):
    connection = replace(saved, kind='image', provider=provider, public_config={'image_size':'512x512', 'quality':'low'})
    monkeypatch.setattr(probes.connections, 'resolve_model_connection', lambda _id: connection)
    calls = {}
    def generate(**kwargs):
        calls.update(kwargs)
        buffer = io.BytesIO()
        Image.new('RGB', (4, 4), 'orange').save(buffer, format='JPEG')
        return {'data':[{'b64_json':base64.b64encode(buffer.getvalue()).decode()}]}
    monkeypatch.setattr(probes.images, 'generate_image_response', generate)
    monkeypatch.setattr(probes.images, 'get_openai_client', lambda **kw: SimpleNamespace(close=lambda: None))
    result = probes.test_saved_connection('saved')
    assert result['success']
    assert calls['provider'] == provider and calls['prompt'] == '生成一只猫咪'
    assert calls['size'] == '512x512' and calls['public_config']['quality'] == 'low'
    assert calls['api_key'] == 'private-secret'
    with Image.open(io.BytesIO(base64.b64decode(result['media_data_url'].split(',',1)[1]))) as image:
        assert image.format == 'PNG' and image.size == (4,4)


@pytest.mark.parametrize('provider', list(probes.tts.TTS_PROVIDER_DEFAULTS))
def test_speech_uses_saved_voice_settings_and_returns_playable_audio(monkeypatch, saved, provider):
    connection = replace(saved, kind='tts', provider=provider,
        public_config={'voice_id':'saved-voice', 'speed':1.2, 'clone_voice_id':'reference.wav'})
    monkeypatch.setattr(probes.connections, 'resolve_model_connection', lambda _id: connection)
    called = {}
    def command(**kwargs):
        called.update(kwargs)
        assert Path(kwargs['text_file']).read_text(encoding='utf-8') == '你好'
        return ['fake']
    def synthesize(*args, **kwargs):
        assert kwargs['env'][probes.tts.TTS_API_KEY_ENV] == 'private-secret'
        with wave.open(called['out_audio'], 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b'\0\0'*1600)
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(probes.tts, 'provider_tts_command', command)
    monkeypatch.setattr(probes, 'run_subprocess_bounded', synthesize)
    monkeypatch.setattr(probes, 'probe_media_duration_sec', lambda *args, **kwargs: 0.1)
    result = probes.test_saved_connection('saved')
    assert result['success'] and result['media_data_url'].startswith('data:audio/wav;base64,')
    assert called['provider'] == provider and called['voice_id'] == 'saved-voice'
    assert called['speed'] == '1.2' and called['model'] == 'configured-model'
    assert not Path(called['out_audio']).exists()  # Test artifacts are temporary.


def test_failure_redacts_keys_and_releases_duplicate_guard(monkeypatch, saved):
    def fail(**kw):
        raise RuntimeError('bad token private-secret')
    monkeypatch.setattr(probes.images, 'get_openai_client', fail)
    result = probes.test_saved_connection('saved')
    assert not result['success'] and 'private-secret' not in result['message']
    assert 'saved' not in probes._running
    with probes._lock:
        probes._running.add('saved')
    try:
        with pytest.raises(ModelConnectionUnavailableError):
            probes.test_saved_connection('saved')
    finally:
        probes._running.discard('saved')


def test_empty_text_is_a_failure(monkeypatch, saved):
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw:
        SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=''))]))), close=lambda: None)
    monkeypatch.setattr(probes.images, 'get_openai_client', lambda **kw: client)
    assert not probes.test_saved_connection('saved')['success']


def test_invalid_image_and_undecodable_audio_are_failures(monkeypatch, saved):
    monkeypatch.setattr(probes.connections, 'resolve_model_connection', lambda _id: replace(saved, kind='image', provider='toapis'))
    monkeypatch.setattr(probes.images, 'generate_image_response', lambda **kw: {'data':[{'b64_json':'aW52YWxpZA=='}]})
    assert not probes.test_saved_connection('saved')['success']
    monkeypatch.setattr(probes.connections, 'resolve_model_connection', lambda _id: replace(saved, kind='tts', provider='minimax'))
    monkeypatch.setattr(probes, 'probe_media_duration_sec', lambda *args, **kw: None)
    def invalid_audio(command, **kwargs):
        Path(command[command.index('--out-audio')+1]).write_bytes(b'invalid')
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(probes, 'run_subprocess_bounded', invalid_audio)
    assert not probes.test_saved_connection('saved')['success']


def test_route_exposes_real_test_result(monkeypatch, saved):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from model_connection_routes import router
    app = FastAPI()
    app.include_router(router)
    monkeypatch.setattr(probes, 'test_saved_connection', lambda key: {'success':True, 'text':'收到', 'connection_id':key})
    with TestClient(app) as client:
        response = client.post('/api/model-connections/saved/test')
    assert response.status_code == 200 and response.json()['text'] == '收到'
