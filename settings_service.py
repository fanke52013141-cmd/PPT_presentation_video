"""Global settings persistence, credential masking, and provider checks."""

from __future__ import annotations

from dataclasses import dataclass
import os
import subprocess
import tempfile
from typing import Any, Callable, Dict, Mapping, Optional

from pydantic import BaseModel


MASKED_SETTINGS_VALUE = "__PPT_STUDIO_MASKED_VALUE__"
SETTINGS_SECRET_KEYS = {
    "llm_api_key",
    "image_api_key",
    "tts_api_key",
    "tts_secret_key",
    "tts_provider_extra",
}


class SettingsUpdate(BaseModel):
    settings: Dict[str, str]


class TestLlmPayload(BaseModel):
    base_url: Optional[str] = None
    api_key: str
    model: str


class TestImagePayload(BaseModel):
    base_url: Optional[str] = None
    api_key: str
    model: str
    size: Optional[str] = None


class TestTtsPayload(BaseModel):
    provider: Optional[str] = "minimax"
    endpoint: Optional[str] = None
    api_key: Optional[str] = None
    secret_key: Optional[str] = None
    region: Optional[str] = None
    model: Optional[str] = None
    voice_id: Optional[str] = None
    clone_voice_id: Optional[str] = None
    provider_extra: Optional[str] = None


@dataclass(frozen=True)
class SettingsDependencies:
    get_all_settings: Callable[[], Dict[str, Any]]
    update_settings: Callable[[Dict[str, str]], Any]
    get_setting: Callable[..., Any]
    get_openai_client: Callable[..., Any]
    generate_image_response: Callable[..., Any]
    response_has_image_data: Callable[[Any], bool]
    normalize_tts_provider: Callable[[Optional[str]], str]
    tts_provider_defaults: Callable[[str], Dict[str, str]]
    configured_tts_api_key: Callable[[str, Optional[str]], str]
    configured_tts_secret_key: Callable[[str, Optional[str]], str]
    first_non_empty: Callable[..., str]
    provider_tts_command: Callable[..., list[str]]
    provider_tts_environment: Callable[[str, str], Dict[str, str]]
    tts_provider_defaults_map: Mapping[str, Dict[str, str]]


_dependencies: SettingsDependencies | None = None


def configure_settings_dependencies(
    dependencies: SettingsDependencies,
) -> None:
    global _dependencies
    _dependencies = dependencies


def _deps() -> SettingsDependencies:
    if _dependencies is None:
        raise RuntimeError("Settings dependencies have not been configured")
    return _dependencies


def mask_settings_secrets_enabled() -> bool:
    value = os.environ.get("PPT_STUDIO_MASK_SETTINGS_SECRETS")
    if value is None:
        return True
    return value.strip().lower() not in {"0", "false", "no", "off"}


def mask_sensitive_settings(
    settings: Dict[str, Any],
    *,
    force: bool = False,
) -> Dict[str, Any]:
    if not force and not mask_settings_secrets_enabled():
        return settings
    masked = dict(settings or {})
    for key in SETTINGS_SECRET_KEYS:
        if masked.get(key) not in (None, ""):
            masked[key] = MASKED_SETTINGS_VALUE
    return masked


def get_settings() -> Dict[str, Any]:
    return mask_sensitive_settings(_deps().get_all_settings())


def preserve_masked_secrets(
    settings: Dict[str, Any],
    current_settings: Dict[str, Any],
) -> Dict[str, Any]:
    preserved = dict(settings)
    for key in SETTINGS_SECRET_KEYS:
        if preserved.get(key) == MASKED_SETTINGS_VALUE:
            preserved[key] = current_settings.get(key, "")
    return preserved


def update_system_settings(payload: SettingsUpdate) -> Dict[str, Any]:
    dependencies = _deps()
    settings = dict(payload.settings or {})
    if mask_settings_secrets_enabled():
        settings = preserve_masked_secrets(
            settings,
            dependencies.get_all_settings(),
        )
    dependencies.update_settings(settings)
    return {"success": True, "message": "设置更新成功"}


def test_llm_connection(payload: TestLlmPayload) -> Dict[str, Any]:
    dependencies = _deps()
    try:
        client = dependencies.get_openai_client(
            api_key=payload.api_key,
            base_url=payload.base_url,
        )
        response = client.chat.completions.create(
            model=payload.model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=5,
            timeout=10,
        )
        content = response.choices[0].message.content
        return {
            "success": True,
            "message": f"连接成功！模型响应: '{content.strip()}'",
        }
    except Exception as exc:
        return {"success": False, "message": f"连接失败: {str(exc)}"}


def test_image_connection(payload: TestImagePayload) -> Dict[str, Any]:
    dependencies = _deps()
    try:
        client = dependencies.get_openai_client(
            api_key=payload.api_key,
            base_url=payload.base_url,
        )
        response = dependencies.generate_image_response(
            client=client,
            model=payload.model,
            prompt="a single dot",
            size=payload.size or "1024x1024",
            base_url=payload.base_url,
            timeout=15,
        )
        if dependencies.response_has_image_data(response):
            return {"success": True, "message": "连接成功！生图接口响应正常。"}
        return {"success": False, "message": "未返回有效图片数据。"}
    except Exception as exc:
        return {"success": False, "message": f"连接失败: {str(exc)}"}


def test_tts_connection(payload: TestTtsPayload) -> Dict[str, Any]:
    dependencies = _deps()
    provider = dependencies.normalize_tts_provider(payload.provider)
    defaults = dependencies.tts_provider_defaults(provider)
    endpoint = dependencies.first_non_empty(
        payload.endpoint,
        dependencies.get_setting("tts_endpoint"),
        defaults.get("endpoint"),
    )
    api_key = dependencies.configured_tts_api_key(
        provider,
        payload.api_key,
    )
    secret_key = dependencies.configured_tts_secret_key(
        provider,
        payload.secret_key,
    )
    model = dependencies.first_non_empty(
        payload.model,
        dependencies.get_setting("tts_model"),
        defaults.get("model"),
    )
    voice_id = dependencies.first_non_empty(
        payload.voice_id,
        dependencies.get_setting("tts_voice_id"),
        defaults.get("voice_id"),
    )
    clone_voice_id = dependencies.first_non_empty(
        payload.clone_voice_id,
        dependencies.get_setting("tts_clone_voice_id"),
    )
    region = dependencies.first_non_empty(
        payload.region,
        dependencies.get_setting("tts_region"),
        defaults.get("region"),
    )
    provider_extra = dependencies.first_non_empty(
        payload.provider_extra,
        dependencies.get_setting("tts_provider_extra"),
    )

    if provider not in dependencies.tts_provider_defaults_map:
        return {
            "success": False,
            "message": f"不支持的 TTS Provider: {payload.provider}",
        }
    # ComfyUI TTS 是本地服务，不需要 API Key
    if provider != "comfyui_tts" and not api_key:
        return {
            "success": False,
            "message": f"缺少 {provider} API Key / SecretId。",
        }
    if provider == "tencent_tts" and not secret_key:
        return {
            "success": False,
            "message": "腾讯云 TTS 还需要 SecretKey。",
        }
    # ComfyUI TTS 不强制要求 voice_id（参考音频可选）
    if provider != "comfyui_tts":
        if not model or not voice_id:
            return {
                "success": False,
                "message": "请填写语音模型和音色 ID。",
            }
    elif not model:
        return {
            "success": False,
            "message": "请填写语音模型名称。",
        }

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            text_file = os.path.join(temp_dir, "tts_test.txt")
            out_audio = os.path.join(temp_dir, "voice.mp3")
            out_meta = os.path.join(temp_dir, "tts_metadata.json")
            out_srt = os.path.join(temp_dir, "tts_narration.srt")
            out_timeline = os.path.join(
                temp_dir,
                "audio_timeline.json",
            )
            with open(text_file, "w", encoding="utf-8") as file:
                file.write("测试语音。\n")
            command = dependencies.provider_tts_command(
                provider=provider,
                text_file=text_file,
                out_audio=out_audio,
                out_meta=out_meta,
                out_srt=out_srt,
                out_timeline=out_timeline,
                slide_id="tts_test",
                endpoint=endpoint,
                region=region,
                model=model,
                voice_id=voice_id,
                clone_voice_id=clone_voice_id,
                provider_extra=provider_extra,
                speed="1.0",
                volume="1.0",
                pitch="0" if provider == "minimax" else "1.0",
            )
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=90,
                env=dependencies.provider_tts_environment(
                    api_key,
                    secret_key,
                ),
            )
            if result.returncode != 0:
                error = (result.stderr or result.stdout)[:600]
                return {
                    "success": False,
                    "message": f"TTS 测试失败: {error}",
                }
            if (
                not os.path.exists(out_audio)
                or os.path.getsize(out_audio) <= 0
            ):
                return {
                    "success": False,
                    "message": "TTS 测试未生成有效音频文件。",
                }
        return {
            "success": True,
            "message": f"连接成功，{provider} TTS 可以正常合成音频。",
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "message": "TTS 测试超时，请检查 endpoint、鉴权和网络。",
        }
    except Exception as exc:
        return {"success": False, "message": f"连接失败: {str(exc)}"}
