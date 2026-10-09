"""Real output probes for saved connections, without touching project artifacts."""
from __future__ import annotations

import base64
import io
import tempfile
import threading
import time
from pathlib import Path

import ai_provider_service as images
import model_connection_service as connections
import tts_provider_service as tts
from credential_store import get_credential
from llm_concurrency import governed_llm_request
from reference_audio_paths import resolve_reference_audio_path
from repository_paths import REPO_ROOT
from runtime_support import run_subprocess_bounded
from scripts.media_tools import probe_media_duration_sec


PROBE_INPUTS = {"text": "两个字回复我", "image": "生成一只猫咪", "tts": "你好"}
_lock = threading.Lock()
_running: set[str] = set()
MAX_AUDIO_BYTES = 10 * 1024 * 1024


def _secret(values, *keys):
    return next((str(values[key]) for key in keys if values.get(key)), "")


def _audio(connection, config, secrets):
    provider = tts.normalize_tts_provider(connection.provider)
    if provider not in tts.TTS_PROVIDER_DEFAULTS:
        raise ValueError(f"不支持的语音供应商：{provider}")
    api_key = _secret(secrets, "api_key", "tts_api_key", "secret_id", "access_token", "token", "key")
    if provider != "comfyui_tts" and not api_key:
        raise ValueError("该语音模型未配置可用密钥，请编辑模型设置")
    defaults = tts.tts_provider_defaults(provider)
    with tempfile.TemporaryDirectory(prefix="model-output-test-") as directory:
        root = Path(directory)
        text = root / "input.txt"
        text.write_text(PROBE_INPUTS["tts"], encoding="utf-8")
        audio = root / "voice.mp3"
        command = tts.provider_tts_command(
            provider=provider, text_file=str(text), out_audio=str(audio),
            out_meta=str(root / "meta.json"), out_srt=str(root / "voice.srt"),
            out_timeline=str(root / "timeline.json"), slide_id="model_test",
            endpoint=connection.endpoint or str(config.get("endpoint") or defaults.get("endpoint", "")),
            region=str(config.get("region") or defaults.get("region", "")),
            model=connection.model,
            voice_id=str(config.get("voice_id") or defaults.get("voice_id", "")),
            clone_voice_id=resolve_reference_audio_path(str(config.get("clone_voice_id") or "")),
            provider_extra=str(config.get("provider_extra") or ""),
            speed=str(config.get("speed", 1)), volume=str(config.get("volume", 1)),
            pitch=str(config.get("pitch", 0 if provider == "minimax" else 1)),
        )
        result = run_subprocess_bounded(command, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout_sec=tts.STEP7_TTS_PROCESS_TIMEOUT_SEC,
            env=tts.provider_tts_environment(
                api_key,
                _secret(secrets, "secret_key", "tts_secret_key", "api_secret")))
        if result.returncode == 124:
            raise ValueError("语音测试超时，请检查网络及模型服务状态")
        if result.returncode != 0:
            raise ValueError(result.stderr or result.stdout or "语音合成失败")
        if not audio.is_file() or not 0 < audio.stat().st_size <= MAX_AUDIO_BYTES:
            raise ValueError("未返回有效音频，或音频超过测试大小上限")
        duration = probe_media_duration_sec(audio, repo_root=Path(REPO_ROOT))
        if duration is None or duration <= 0:
            raise ValueError("返回的音频无法解码播放")
        data = audio.read_bytes()
        mime = "audio/wav" if data.startswith(b"RIFF") else "audio/ogg" if data.startswith(b"OggS") else "audio/mpeg"
        return {"media_data_url": f"data:{mime};base64," + base64.b64encode(data).decode(),
                "duration_sec": round(duration, 3)}


def test_saved_connection(connection_id: str) -> dict:
    connection = connections.resolve_model_connection(connection_id)
    if connection.state == "archived":
        raise connections.ModelConnectionUnavailableError("已归档的模型不能测试")
    with _lock:
        if connection_id in _running:
            raise connections.ModelConnectionUnavailableError("该模型正在测试，请等待本次结果")
        _running.add(connection_id)
    started = time.monotonic()
    secrets = {}
    client = None
    result = {"connection_id": connection_id, "revision": connection.revision,
              "kind": connection.kind, "input": PROBE_INPUTS[connection.kind]}
    try:
        secrets = get_credential(connection.credential_ref) if connection.credential_ref else {}
        config = dict(connection.public_config)
        api_key = _secret(secrets, "api_key", "llm_api_key", "image_api_key", "token", "key", "access_token")
        if connection.kind != "tts" and not api_key:
            raise ValueError("该模型未配置可用 API 密钥，请编辑模型设置")
        if connection.kind == "text":
            client = images.get_openai_client(api_key=api_key, base_url=connection.endpoint, timeout=60)
            with governed_llm_request(connection.endpoint):
                response = client.chat.completions.create(model=connection.model,
                    messages=[{"role": "user", "content": result["input"]}], max_tokens=512, timeout=60)
            content = response.choices[0].message.content
            if not isinstance(content, str) or not content.strip():
                raise ValueError("模型未返回有效文本")
            result["text"] = content.strip()
        elif connection.kind == "image":
            if not images.is_toapis_image_provider(connection.provider, connection.endpoint):
                client = images.get_openai_client(api_key=api_key, base_url=connection.endpoint)
            response = images.generate_image_response(client=client, model=connection.model,
                prompt=result["input"], size=str(config.get("image_size") or config.get("size") or "1024x1024"),
                base_url=connection.endpoint, provider=connection.provider, api_key=api_key,
                public_config=config, timeout=600)
            raw = images.extract_image_bytes_from_response(response)
            if len(raw) > images.MAX_IMAGE_UPLOAD_BYTES:
                raise ValueError("返回图片超过测试大小上限")
            with images.open_validated_image(raw) as image:
                buffer = io.BytesIO()
                image.save(buffer, format="PNG")
                result["media_data_url"] = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
        elif connection.kind == "tts":
            result.update(_audio(connection, config, secrets))
        result.update(success=True, message="模型已成功返回，本次输出如下")
    except Exception as exc:
        message = str(exc)
        for value in sorted((str(v) for v in secrets.values() if v), key=len, reverse=True):
            message = message.replace(value, "[已隐藏]")
        result.update(success=False, message=message[:1000] or "模型测试失败")
    finally:
        try:
            if client is not None:
                client.close()
        except Exception:
            pass  # Output validity does not depend on HTTP pool teardown.
        finally:
            with _lock:
                _running.discard(connection_id)
    result["elapsed_sec"] = round(time.monotonic() - started, 2)
    return result
