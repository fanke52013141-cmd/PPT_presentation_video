"""TTS provider configuration, secret transport, and retry runtime."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import subprocess
import sys
import time
from typing import Any, Callable, Dict, List, Optional

from runtime_support import run_subprocess_killable


logger = logging.getLogger("PPTStudio.TTSProvider")
TTS_API_KEY_ENV = "PPT_STUDIO_TTS_API_KEY"
TTS_SECRET_KEY_ENV = "PPT_STUDIO_TTS_SECRET_KEY"
# MiniMax 异步合成在服务端排队时，单个任务可能超过数分钟。轮询窗口要
# 明显长于普通请求超时，避免服务端仍在 Processing 时被本地误判为失败。
# 进程额外保留 90 秒，用于上传文本、下载音频和写入时间轴。
STEP7_TTS_TIMEOUT_SEC = 900
STEP7_TTS_PROCESS_TIMEOUT_SEC = STEP7_TTS_TIMEOUT_SEC + 90
STEP7_TTS_RETRY_ATTEMPTS = 3
STEP7_TTS_RETRY_BASE_DELAY_SEC = 4
STEP7_TTS_RATE_LIMIT_BASE_DELAY_SEC = 15
STEP7_TTS_RATE_LIMIT_MAX_DELAY_SEC = 90
_RATE_LIMIT_MARKERS = (
    "429",
    "rate limit",
    "rate_limit",
    "too many requests",
    "quota exceeded",
)

TTS_PROVIDER_ALIASES = {
    "doubao": "volcengine_seed",
    "volcengine": "volcengine_seed",
    "aliyun": "aliyun_cosyvoice",
    "dashscope": "aliyun_cosyvoice",
    "cosyvoice": "aliyun_cosyvoice",
    "tencent": "tencent_tts",
    "comfyui": "comfyui_tts",
    "indextts": "comfyui_tts",
    "index_tts": "comfyui_tts",
    "index_tts_2.5": "comfyui_tts",
    "index tts 2.5": "comfyui_tts",
    "index tts-2.5": "comfyui_tts",
    "indextts2.5": "comfyui_tts",
    "indextts-2.5": "comfyui_tts",
    "index_tts2": "comfyui_tts",
}
TTS_PROVIDER_DEFAULTS = {
    "minimax": {
        "endpoint": "https://api.minimaxi.com/v1/t2a_async_v2",
        "model": "speech-2.8-hd",
        "voice_id": "Chinese (Mandarin)_Soft_Girl",
        "api_key_env": "MINIMAX_API_KEY",
    },
    "aliyun_cosyvoice": {
        "endpoint": "https://dashscope.aliyuncs.com/api/v1",
        "model": "cosyvoice-v3-flash",
        "voice_id": "longxiaochun",
        "api_key_env": "DASHSCOPE_API_KEY",
    },
    "tencent_tts": {
        "endpoint": "https://tts.tencentcloudapi.com",
        "model": "1",
        "voice_id": "101001",
        "api_key_env": "TENCENTCLOUD_SECRET_ID",
        "secret_key_env": "TENCENTCLOUD_SECRET_KEY",
        "region": "ap-guangzhou",
    },
    "volcengine_seed": {
        "endpoint": "https://openspeech.bytedance.com/api/v1/tts",
        "model": "seed-tts-1.1",
        "voice_id": "zh_female_qingxinnvsheng_mars_bigtts",
        "api_key_env": "VOLCENGINE_TTS_TOKEN",
    },
    "comfyui_tts": {
        "endpoint": "",
        "model": "IndexTTS-2",
        "voice_id": "",
        "api_key_env": "",
    },
}


@dataclass(frozen=True)
class TtsProviderDependencies:
    get_setting: Callable[..., Any]
    write_project_log: Callable[..., Any]
    # Keep the process boundary injectable: production uses the killable
    # runner while unit tests can deterministically model retries/timeouts.
    run_subprocess: Callable[..., subprocess.CompletedProcess] = (
        run_subprocess_killable
    )


_dependencies: TtsProviderDependencies | None = None


def configure_tts_provider_dependencies(
    dependencies: TtsProviderDependencies,
) -> None:
    global _dependencies
    _dependencies = dependencies


def _deps() -> TtsProviderDependencies:
    if _dependencies is None:
        raise RuntimeError(
            "TTS provider dependencies have not been configured"
        )
    return _dependencies


def normalize_tts_provider(provider: Optional[str]) -> str:
    value = str(provider or "minimax").strip().lower()
    normalized = TTS_PROVIDER_ALIASES.get(value)
    if normalized:
        return normalized
    # Settings exported by ComfyUI workflows often contain display labels
    # such as "IndexTTS-2.5". Treat harmless spacing/punctuation variants as
    # the same local provider without changing unrelated provider names.
    compact = value.replace(" ", "").replace("-", "_")
    if compact in {"indextts_2.5", "indextts2.5", "indextts_2", "indextts2"}:
        return "comfyui_tts"
    return value or "minimax"


def tts_provider_defaults(provider: str) -> Dict[str, str]:
    return TTS_PROVIDER_DEFAULTS.get(
        provider,
        TTS_PROVIDER_DEFAULTS["minimax"],
    )


def first_non_empty(*values: Optional[str]) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def configured_tts_api_key(
    provider: str,
    explicit: Optional[str] = None,
) -> str:
    defaults = tts_provider_defaults(provider)
    return first_non_empty(
        explicit,
        _deps().get_setting("tts_api_key"),
        os.environ.get(str(defaults.get("api_key_env") or "")),
        (
            os.environ.get("MINIMAX_API_KEY")
            if provider == "minimax"
            else ""
        ),
    )


def configured_tts_secret_key(
    provider: str,
    explicit: Optional[str] = None,
) -> str:
    defaults = tts_provider_defaults(provider)
    return first_non_empty(
        explicit,
        _deps().get_setting("tts_secret_key"),
        os.environ.get(
            str(defaults.get("secret_key_env") or "")
        ),
    )


def provider_tts_command(
    *,
    provider: str,
    text_file: str,
    out_audio: str,
    out_meta: str,
    out_srt: str,
    out_timeline: str,
    slide_id: str,
    endpoint: str,
    region: str,
    model: str,
    voice_id: str,
    clone_voice_id: str,
    provider_extra: str,
    speed: str,
    volume: str,
    pitch: str,
) -> List[str]:
    script = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "scripts",
            "generic_tts.py",
        )
    )
    return [
        sys.executable,
        script,
        "--provider",
        provider,
        "--text-file",
        text_file,
        "--out-audio",
        out_audio,
        "--out-meta",
        out_meta,
        "--out-srt",
        out_srt,
        "--out-timeline",
        out_timeline,
        "--slide-id",
        slide_id,
        "--endpoint",
        endpoint,
        "--region",
        region,
        "--model",
        model,
        "--voice-id",
        voice_id,
        "--clone-voice-id",
        clone_voice_id,
        "--provider-extra",
        provider_extra,
        "--speed",
        speed,
        "--volume",
        volume,
        "--pitch",
        pitch,
        "--timeout",
        str(STEP7_TTS_TIMEOUT_SEC),
    ]


def provider_tts_environment(
    api_key: str,
    secret_key: str,
) -> Dict[str, str]:
    environment = os.environ.copy()
    environment[TTS_API_KEY_ENV] = str(api_key or "")
    environment[TTS_SECRET_KEY_ENV] = str(secret_key or "")
    return environment


def _safe_process_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _is_rate_limited(value: Any) -> bool:
    text = _safe_process_text(value).lower()
    return any(marker in text for marker in _RATE_LIMIT_MARKERS)


def _retry_delay_seconds(attempt: int, output: Any) -> int:
    """Use longer bounded backoff when the provider explicitly rate limits."""
    safe_attempt = max(1, int(attempt))
    if _is_rate_limited(output):
        return min(
            STEP7_TTS_RATE_LIMIT_BASE_DELAY_SEC * (2 ** (safe_attempt - 1)),
            STEP7_TTS_RATE_LIMIT_MAX_DELAY_SEC,
        )
    return STEP7_TTS_RETRY_BASE_DELAY_SEC * safe_attempt


def _redact_tts_process_output(value: Any, tts_env: Dict[str, str]) -> str:
    text = _safe_process_text(value)
    for name in (
        TTS_API_KEY_ENV,
        TTS_SECRET_KEY_ENV,
        "MINIMAX_API_KEY",
        "MINIMAX_TTS_API_KEY",
    ):
        secret = str(tts_env.get(name) or "")
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text


def run_tts_command_with_retries(
    project: Any,
    slide_id: str,
    tts_args: List[str],
    tts_env: Dict[str, str],
) -> Dict[str, Any]:
    last_result: Dict[str, Any] = {
        "ok": False,
        "returncode": None,
        "stdout": "",
        "stderr": "",
        "attempts": 0,
    }
    for attempt in range(1, STEP7_TTS_RETRY_ATTEMPTS + 1):
        last_result["attempts"] = attempt
        try:
            result = _deps().run_subprocess(
                tts_args,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout_sec=STEP7_TTS_PROCESS_TIMEOUT_SEC,
                env=tts_env,
            )
            last_result.update(
                {
                    "returncode": result.returncode,
                    "stdout": result.stdout.strip(),
                    "stderr": result.stderr.strip(),
                }
            )
        except Exception as exc:
            # run_subprocess_killable 内部已处理超时（returncode=124）并真正
            # 杀死进程树；此处仅兜底捕获意料之外的启动异常。
            logger.warning(
                "TTS subprocess launch failed: %s", type(exc).__name__
            )
            last_result.update(
                {
                    "returncode": 1,
                    "stdout": "",
                    "stderr": f"TTS subprocess failed to start: {exc}",
                }
            )

        if last_result["returncode"] == 0:
            last_result["ok"] = True
            return last_result

        # Do not persist process output before masking credentials.  Provider
        # failures are usually safe, but a proxy may echo an authorization
        # value in its diagnostic response.
        last_result["stdout"] = _redact_tts_process_output(
            last_result["stdout"], tts_env
        )
        last_result["stderr"] = _redact_tts_process_output(
            last_result["stderr"], tts_env
        )
        _deps().write_project_log(
            project,
            "step7_slide_tts_attempt_failed",
            slide_id=slide_id,
            attempt=attempt,
            max_attempts=STEP7_TTS_RETRY_ATTEMPTS,
            returncode=last_result["returncode"],
            stdout=last_result["stdout"],
            stderr=last_result["stderr"],
        )
        if attempt < STEP7_TTS_RETRY_ATTEMPTS:
            combined_output = (
                f"{last_result['stderr']}\n{last_result['stdout']}"
            )
            delay = _retry_delay_seconds(attempt, combined_output)
            reason = "rate limit" if _is_rate_limited(combined_output) else "failure"
            logger.warning(
                "TTS %s for %s on attempt %s/%s; "
                "retrying in %ss",
                reason,
                slide_id,
                attempt,
                STEP7_TTS_RETRY_ATTEMPTS,
                delay,
            )
            time.sleep(delay)
    return last_result
